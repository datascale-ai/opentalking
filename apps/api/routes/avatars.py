from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image

from opentalking.avatar import mouth_metadata
from opentalking.avatar.loader import load_avatar_bundle
from opentalking.avatar.validator import list_avatar_dirs
from apps.api.schemas.avatar import AvatarSummary

router = APIRouter(prefix="/avatars", tags=["avatars"])


def _avatars_root(request: Request) -> Path:
    return Path(request.app.state.settings.avatars_dir).resolve()


def _is_custom_avatar(manifest_path: Path) -> bool:
    """Return True only for avatars created via /avatars/custom (deletable)."""
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool((raw.get("metadata") or {}).get("custom_avatar"))


def _summary_from_dir(path: Path) -> AvatarSummary:
    b = load_avatar_bundle(path, strict=False)
    m = b.manifest
    return AvatarSummary(
        id=m.id,
        name=m.name,
        model_type=m.model_type,
        width=m.width,
        height=m.height,
        is_custom=_is_custom_avatar(path / "manifest.json"),
    )


def _slugify_name(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff_-]+", "-", value.strip()).strip("-_")
    return slug[:32] or "avatar"


def _unique_avatar_id(root: Path, display_name: str) -> str:
    base = _slugify_name(display_name)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
    candidate = f"custom-{base}-{stamp}"
    candidate = candidate[:96].rstrip("-_")
    if not (root / candidate).exists():
        return candidate
    suffix = 1
    while (root / f"{candidate}-{suffix}").exists():
        suffix += 1
    return f"{candidate}-{suffix}"


async def _read_upload_image(upload: UploadFile) -> Image.Image:
    raw = await upload.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty image")
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="image too large (max 10MB)")
    try:
        image = Image.open(BytesIO(raw))
        image.load()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="invalid image") from exc
    return image.convert("RGB")


def _write_custom_avatar_manifest(base_manifest_path: Path, target_manifest_path: Path, *, avatar_id: str, name: str) -> None:
    raw = json.loads(base_manifest_path.read_text(encoding="utf-8"))
    raw["id"] = avatar_id
    raw["name"] = name
    metadata = dict(raw.get("metadata") or {})
    metadata["custom_avatar"] = True
    metadata["base_avatar_id"] = json.loads(base_manifest_path.read_text(encoding="utf-8")).get("id")
    raw["metadata"] = metadata
    target_manifest_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _custom_avatar_max_size() -> tuple[int, int]:
    width = int(os.environ.get("OPENTALKING_CUSTOM_AVATAR_MAX_WIDTH", "720"))
    height = int(os.environ.get("OPENTALKING_CUSTOM_AVATAR_MAX_HEIGHT", "1280"))
    return max(1, width), max(1, height)


def _resize_uploaded_avatar_image(image: Image.Image, *, max_width: int, max_height: int) -> Image.Image:
    if image.width <= max_width and image.height <= max_height:
        return image.copy()
    fitted = image.copy()
    fitted.thumbnail((int(max_width), int(max_height)), Image.Resampling.LANCZOS)
    return fitted


def _update_manifest_dimensions(manifest_path: Path, image: Image.Image) -> None:
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["width"] = int(image.width)
    raw["height"] = int(image.height)
    manifest_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _model_type_from_manifest(manifest_path: Path) -> str:
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    return str(raw.get("model_type") or "")


@router.get("", response_model=list[AvatarSummary])
async def list_avatars(request: Request) -> list[AvatarSummary]:
    root = _avatars_root(request)
    out: list[AvatarSummary] = []
    for d in list_avatar_dirs(root):
        try:
            out.append(_summary_from_dir(d))
        except Exception:  # noqa: BLE001
            continue
    return out


@router.post("/custom", response_model=AvatarSummary)
async def create_custom_avatar(
    request: Request,
    base_avatar_id: str = Form(...),
    name: str = Form(...),
    image: UploadFile = File(...),
) -> AvatarSummary:
    display_name = name.strip()
    if not display_name:
        raise HTTPException(status_code=422, detail="name is required")

    root = _avatars_root(request)
    base_dir = (root / base_avatar_id).resolve()
    try:
        base_dir.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid base_avatar_id") from exc
    if not base_dir.is_dir() or not (base_dir / "manifest.json").is_file():
        raise HTTPException(status_code=404, detail="base avatar not found")

    avatar_id = _unique_avatar_id(root, display_name)
    target_dir = root / avatar_id
    image_rgb = await _read_upload_image(image)

    try:
        shutil.copytree(
            base_dir,
            target_dir,
            ignore=shutil.ignore_patterns("reference_custom.*"),
        )
        _write_custom_avatar_manifest(
            base_dir / "manifest.json",
            target_dir / "manifest.json",
            avatar_id=avatar_id,
            name=display_name,
        )
        max_w, max_h = _custom_avatar_max_size()
        fitted_image = _resize_uploaded_avatar_image(image_rgb, max_width=max_w, max_height=max_h)
        _update_manifest_dimensions(target_dir / "manifest.json", fitted_image)
        fitted_image.save(target_dir / "preview.png", format="PNG")
        fitted_image.save(target_dir / "reference.png", format="PNG")
        mouth_metadata.update_manifest_mouth_metadata(
            target_dir / "manifest.json",
            target_dir / "reference.png",
            force=True,
        )
        if _model_type_from_manifest(target_dir / "manifest.json") == "wav2lip":
            frames_dir = target_dir / "frames"
            frames_dir.mkdir(parents=True, exist_ok=True)
            frame_path = frames_dir / "frame_00000.png"
            fitted_image.save(frame_path, format="PNG")
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(target_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"failed to create custom avatar: {exc}") from exc

    return _summary_from_dir(target_dir)


@router.get("/{avatar_id}")
async def get_avatar(avatar_id: str, request: Request) -> AvatarSummary:
    root = _avatars_root(request)
    path = root / avatar_id
    if not path.is_dir():
        raise HTTPException(status_code=404, detail="avatar not found")
    return _summary_from_dir(path)


@router.get("/{avatar_id}/preview")
async def get_preview(avatar_id: str, request: Request) -> FileResponse:
    root = _avatars_root(request)
    path = root / avatar_id / "preview.png"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="preview not found")
    return FileResponse(path, media_type="image/png")


@router.delete("/{avatar_id}")
async def delete_avatar(avatar_id: str, request: Request) -> dict[str, str]:
    """Delete a user-created custom avatar.

    Built-in demo avatars (demo-avatar / demo-musetalk / flashtalk-demo /
    flashhead-demo) cannot be deleted — they're tracked in git and would
    just come back on next deploy. Only avatars with
    `metadata.custom_avatar == true` (created via POST /avatars/custom)
    are removable.
    """
    root = _avatars_root(request)
    target = (root / avatar_id).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid avatar_id") from exc
    if not target.is_dir():
        raise HTTPException(status_code=404, detail="avatar not found")

    manifest = target / "manifest.json"
    if not _is_custom_avatar(manifest):
        raise HTTPException(
            status_code=403,
            detail=(
                f"avatar '{avatar_id}' is built-in and cannot be deleted. "
                f"Only avatars created via the 'New' button are removable."
            ),
        )

    try:
        shutil.rmtree(target)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"failed to delete avatar: {exc}") from exc
    return {"avatar_id": avatar_id, "status": "deleted"}
