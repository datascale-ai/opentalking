from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from opentalking.avatars.loader import load_avatar_bundle
from opentalking.avatars.validator import list_avatar_dirs
from apps.api.schemas.avatar import AvatarSummary

router = APIRouter(prefix="/avatars", tags=["avatars"])


def _avatars_root(request: Request) -> Path:
    return Path(request.app.state.settings.avatars_dir).resolve()


@router.get("", response_model=list[AvatarSummary])
async def list_avatars(request: Request) -> list[AvatarSummary]:
    root = _avatars_root(request)
    out: list[AvatarSummary] = []
    for d in list_avatar_dirs(root):
        try:
            b = load_avatar_bundle(d, strict=False)
        except Exception:  # noqa: BLE001
            continue
        m = b.manifest
        out.append(
            AvatarSummary(
                id=d.name,
                name=m.name,
                manifest_id=m.id,
                model_type=m.model_type,
                width=m.width,
                height=m.height,
            )
        )
    return out


@router.get("/{avatar_id}")
async def get_avatar(avatar_id: str, request: Request) -> AvatarSummary:
    root = _avatars_root(request)
    path = root / avatar_id
    if not path.is_dir():
        raise HTTPException(status_code=404, detail="avatar not found")
    b = load_avatar_bundle(path, strict=False)
    m = b.manifest
    return AvatarSummary(
        id=path.name,
        name=m.name,
        manifest_id=m.id,
        model_type=m.model_type,
        width=m.width,
        height=m.height,
    )


@router.get("/{avatar_id}/preview")
async def get_preview(avatar_id: str, request: Request) -> FileResponse:
    root = _avatars_root(request)
    path = root / avatar_id / "preview.png"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="preview not found")
    return FileResponse(path, media_type="image/png")
