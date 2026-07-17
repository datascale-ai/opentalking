from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import tempfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from PIL import Image

from opentalking.avatar import mouth_metadata
from opentalking.avatar.duo_dialog import duo_dialog_summary_from_metadata
from opentalking.avatar.loader import load_avatar_bundle
from opentalking.avatar.light2d import (
    Light2DContractError,
    Light2DRendererContext,
    load_light2d_renderer,
    open_referenced_asset,
    safe_relative_path,
)
from opentalking.avatar.matting import MattingError, image_has_transparency, remove_avatar_background
from opentalking.avatar.validator import list_avatar_dirs
from opentalking.models.quicktalk.paths import resolve_quicktalk_asset_root
from opentalking.core.model_paths import quicktalk_asset_root
from opentalking.models.registry import get_adapter
from opentalking.providers.synthesis.backends import resolve_model_backend
from opentalking.providers.synthesis.omnirt import auth_headers
from apps.api.schemas.avatar import (
    AvatarPersonModeUpdate,
    AvatarSummary,
    ClientRendererCapability,
    DuoDialogCapability,
    PersonMode,
)
from apps.cli.prepare_cache import (
    PreparedAssetResult,
    _prepare_quicktalk_asset,
    _resolve_quicktalk_template_source,
    _target_video_size,
    _validate_quicktalk_face_cache,
)
from opentalking.avatar.wav2lip_preload import collect_wav2lip_preload_payload_for_avatar

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


def _is_hidden_avatar(manifest_path: Path) -> bool:
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool((raw.get("metadata") or {}).get("hidden"))


def _avatar_matting_status(manifest_path: Path) -> str:
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unknown"
    value = str((raw.get("metadata") or {}).get("matting_status") or "").strip()
    return value if value in {"unknown", "opaque", "transparent_ready"} else "unknown"


def _renderer_context(avatar_dir: Path) -> Light2DRendererContext | None:
    try:
        return load_light2d_renderer(avatar_dir)
    except Light2DContractError:
        return None


def _client_renderer_capability(path: Path) -> ClientRendererCapability | None:
    context = _renderer_context(path)
    if context is None:
        return None
    recommended_for = context.recommended_for
    avatar_id = path.name
    return ClientRendererCapability(
        type="light2d",
        config_url=f"/avatars/{avatar_id}/client-renderer",
        asset_base_url=f"/avatars/{avatar_id}/client-assets/",
        recommended_for=list(recommended_for),
    )


def _normalize_person_mode(raw: object) -> PersonMode | None:
    value = str(raw or "").strip().lower()
    if value == "single":
        return "single"
    if value == "double":
        return "double"
    return None


def _person_mode_from_metadata(metadata: object) -> PersonMode:
    if not isinstance(metadata, dict):
        return "single"
    explicit = _normalize_person_mode(metadata.get("person_mode"))
    if explicit is not None:
        return explicit
    return "double" if duo_dialog_summary_from_metadata(metadata) is not None else "single"


def _apply_person_mode_metadata(metadata: dict[str, Any], person_mode: PersonMode) -> dict[str, Any]:
    out = dict(metadata)
    out["person_mode"] = person_mode
    if person_mode == "double":
        duo_dialog = out.get("duo_dialog")
        if not isinstance(duo_dialog, dict):
            duo_dialog = {}
        speaker_faces = duo_dialog.get("speaker_faces")
        if not isinstance(speaker_faces, dict) or not speaker_faces:
            duo_dialog["speaker_faces"] = {"left": "left", "right": "right"}
        default_voices = duo_dialog.get("default_voices")
        if not isinstance(default_voices, dict):
            duo_dialog["default_voices"] = {}
        out["duo_dialog"] = duo_dialog
    return out


def _avatar_preview_video_path(avatar_dir: Path) -> Path | None:
    manifest_path = avatar_dir / "manifest.json"
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    metadata = raw.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    candidates: list[str] = []
    source_video = metadata.get("source_video")
    if source_video:
        candidates.append(str(source_video))
    for name in ("idle.mp4", "idle.webm", "idle.mov", "idle.avi", "source.mp4"):
        candidates.append(name)

    avatar_root = avatar_dir.resolve()
    for raw_candidate in candidates:
        candidate = (avatar_root / raw_candidate).resolve()
        try:
            candidate.relative_to(avatar_root)
        except ValueError:
            continue
        if candidate.is_file() and candidate.suffix.lower() in {".mp4", ".webm", ".mov", ".avi"}:
            return candidate
    return None


def _video_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".webm":
        return "video/webm"
    if suffix == ".mov":
        return "video/quicktime"
    if suffix == ".avi":
        return "video/x-msvideo"
    return "video/mp4"


def _summary_from_dir(path: Path) -> AvatarSummary:
    b = load_avatar_bundle(path, strict=False)
    m = b.manifest
    duo_dialog = duo_dialog_summary_from_metadata(m.metadata)
    duo_capability = None
    if duo_dialog is not None:
        speaker_faces = duo_dialog.get('speaker_faces')
        default_voices = duo_dialog.get('default_voices')
        if isinstance(speaker_faces, dict) and isinstance(default_voices, dict):
            duo_capability = DuoDialogCapability(
                speaker_faces={str(key): str(value) for key, value in speaker_faces.items()},
                default_voices={str(key): str(value) for key, value in default_voices.items()},
            )
    return AvatarSummary(
        id=m.id,
        name=m.name,
        model_type=m.model_type,
        width=m.width,
        height=m.height,
        person_mode=_person_mode_from_metadata(m.metadata),
        is_custom=_is_custom_avatar(path / 'manifest.json'),
        has_preview_video=_avatar_preview_video_path(path) is not None,
        matting_status=_avatar_matting_status(path / 'manifest.json'),
        duo_dialog=duo_capability,
        client_renderer=_client_renderer_capability(path),
    )


def _sort_avatar_summaries(summaries: list[AvatarSummary]) -> list[AvatarSummary]:
    duo_rows: list[tuple[int, tuple[int, int | str, str, str], AvatarSummary]] = []
    for index, summary in enumerate(summaries):
        if summary.person_mode != "double" or summary.duo_dialog is None:
            continue
        name = (summary.name or "").strip()
        match = re.fullmatch(r"双人对话(\d+)", name)
        sort_key: tuple[int, int | str, str, str]
        if match:
            sort_key = (0, int(match.group(1)), name, summary.id)
        else:
            sort_key = (1, index, name, summary.id)
        duo_rows.append((index, sort_key, summary))

    if len(duo_rows) < 2:
        return summaries

    duo_indices = {index for index, _, _ in duo_rows}
    anchor = min(duo_indices)
    ordered_duo = [summary for _, _, summary in sorted(duo_rows, key=lambda item: item[1])]
    remaining = [summary for index, summary in enumerate(summaries) if index not in duo_indices]
    return remaining[:anchor] + ordered_duo + remaining[anchor:]


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
    return image.convert("RGBA") if "A" in image.getbands() else image.convert("RGB")


async def _read_upload_video(upload: UploadFile) -> tuple[Image.Image, bytes, str]:
    raw = await upload.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty video")
    if len(raw) > 200 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="video too large (max 200MB)")
    suffix = Path(upload.filename or "source.mp4").suffix.lower() or ".mp4"
    if suffix not in {".mp4", ".webm", ".mov", ".avi"}:
        raise HTTPException(status_code=400, detail="unsupported video format")

    import cv2

    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
        tmp.write(raw)
        tmp.flush()
        cap = cv2.VideoCapture(tmp.name)
        try:
            ok, frame = cap.read()
        finally:
            cap.release()
    if not ok or frame is None:
        raise HTTPException(status_code=400, detail="invalid video")
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return Image.fromarray(frame_rgb).convert("RGB"), raw, suffix


def _normalize_custom_avatar_model(model: str | None, fallback: str) -> str:
    value = (model or "").strip().lower()
    if value in {"fasterliveportrait", "flashhead", "flashtalk", "mock", "musetalk", "quicktalk", "wav2lip"}:
        return value
    return fallback


def _write_custom_avatar_manifest(
    base_manifest_path: Path,
    target_manifest_path: Path,
    *,
    avatar_id: str,
    name: str,
    model: str | None = None,
    person_mode: PersonMode = "single",
) -> None:
    raw = json.loads(base_manifest_path.read_text(encoding="utf-8"))
    base_avatar_id = raw.get("id")
    raw["id"] = avatar_id
    raw["name"] = name
    raw["model_type"] = _normalize_custom_avatar_model(model, str(raw.get("model_type") or ""))
    metadata = dict(raw.get("metadata") or {})
    for key in (
        "frame_dir",
        "preprocessed",
        "preprocess_version",
        "quicktalk",
        "source_video",
        "template_video",
        "video",
    ):
        metadata.pop(key, None)
    metadata["custom_avatar"] = True
    metadata["base_avatar_id"] = base_avatar_id
    metadata["idle_mode"] = "static"
    metadata["reference_mode"] = "image"
    metadata["source_image"] = "source/source.png"
    metadata["matting_status"] = "opaque"
    metadata = _apply_person_mode_metadata(metadata, person_mode)
    raw["metadata"] = metadata
    target_manifest_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_manifest(path: Path, raw: dict[str, Any]) -> None:
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def _avatar_image_has_alpha(image: Image.Image) -> bool:
    return image_has_transparency(image)


def _update_manifest_matting_status(manifest_path: Path, image: Image.Image) -> None:
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    metadata = dict(raw.get("metadata") or {})
    metadata["matting_status"] = "transparent_ready" if _avatar_image_has_alpha(image) else "opaque"
    raw["metadata"] = metadata
    manifest_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _update_manifest_matting_source(
    manifest_path: Path,
    *,
    provider_name: str,
    original_source_image: str,
) -> None:
    raw = _read_manifest(manifest_path)
    metadata = dict(raw.get("metadata") or {})
    metadata["matting_provider"] = provider_name
    metadata["matting_source"] = "upload_auto"
    metadata["original_source_image"] = original_source_image
    raw["metadata"] = metadata
    _write_manifest(manifest_path, raw)


def _update_manifest_dimensions(manifest_path: Path, image: Image.Image) -> None:
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["width"] = int(image.width)
    raw["height"] = int(image.height)
    manifest_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _model_type_from_manifest(manifest_path: Path) -> str:
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    return str(raw.get("model_type") or "")


def _write_static_quicktalk_template(image: Image.Image, output_path: Path, *, fps: int) -> None:
    import cv2

    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame_rgb = np.asarray(image.convert("RGB"))
    frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
    height, width = frame_bgr.shape[:2]
    frame_count = max(1, int(max(1, fps)))
    video_writer_fourcc = getattr(cv2, "VideoWriter_fourcc")
    writer = cv2.VideoWriter(
        str(output_path),
        video_writer_fourcc(*"mp4v"),
        float(max(1, fps)),
        (int(width), int(height)),
    )
    if not writer.isOpened():
        raise RuntimeError(f"failed to open video writer: {output_path}")
    try:
        for _ in range(frame_count):
            writer.write(frame_bgr)
    finally:
        writer.release()


def _prepare_quicktalk_custom_assets(manifest_path: Path, image: Image.Image) -> None:
    raw = _read_manifest(manifest_path)
    metadata = dict(raw.get("metadata") or {})
    quicktalk = metadata.get("quicktalk")
    quicktalk_dir = manifest_path.parent / "quicktalk"
    if raw.get("model_type") != "quicktalk" and not isinstance(quicktalk, dict) and not quicktalk_dir.is_dir():
        return

    if quicktalk_dir.exists():
        shutil.rmtree(quicktalk_dir)
    template_rel = "quicktalk/template_900.mp4"
    template_path = manifest_path.parent / template_rel
    _write_static_quicktalk_template(image, template_path, fps=int(raw.get("fps") or 25))
    metadata.pop("quicktalk", None)
    raw["metadata"] = metadata
    _write_manifest(manifest_path, raw)


def _reset_custom_avatar_runtime_assets(target_dir: Path) -> None:
    for name in ("quicktalk", "source", "frames", "wav2lip"):
        path = target_dir / name
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
    for pattern in (
        "idle.mp4",
        "idle.webm",
        "idle.mov",
        "idle.avi",
        "source.mp4",
        "source.webm",
        "source.mov",
        "source.avi",
        ".flashtalk_idle_cache_v*.npz",
    ):
        for path in target_dir.glob(pattern):
            if path.is_file():
                path.unlink(missing_ok=True)


def _endpoint_to_http_url(endpoint: str, path: str) -> str:
    parts = urlsplit(endpoint)
    scheme_map = {"http": "http", "https": "https", "ws": "http", "wss": "https"}
    scheme = scheme_map.get(parts.scheme.lower())
    if scheme is None:
        raise ValueError(f"Unsupported OMNIRT_ENDPOINT scheme: {parts.scheme!r}")
    base_path = parts.path.rstrip("/")
    suffix = path if path.startswith("/") else f"/{path}"
    return urlunsplit((scheme, parts.netloc, base_path + suffix, "", ""))


async def _post_omnirt_json(settings: Any, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    endpoint = (getattr(settings, "omnirt_endpoint", "") or "").strip()
    if not endpoint:
        raise RuntimeError("OMNIRT_ENDPOINT is not configured.")
    url = _endpoint_to_http_url(endpoint, path)
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(url, json=payload, headers=auth_headers(settings))
        response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {"type": "error", "message": "invalid OmniRT response"}


def _settings_quicktalk_model_root(settings: Any) -> Path:
    resolved = resolve_quicktalk_asset_root(settings)
    if resolved is not None:
        return resolved
    return quicktalk_asset_root().expanduser().resolve()


def _settings_int(settings: Any, name: str, env_name: str, default: int) -> int:
    raw = getattr(settings, name, None)
    if raw is None:
        raw = os.environ.get(env_name)
    try:
        return int(str(raw)) if raw not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _settings_float(settings: Any, name: str, env_name: str, default: float) -> float:
    raw = getattr(settings, name, None)
    if raw is None:
        raw = os.environ.get(env_name)
    try:
        return float(str(raw)) if raw not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _settings_optional_float(
    settings: Any, name: str, env_name: str, default: float | None = None
) -> float | None:
    raw = getattr(settings, name, None)
    if raw is None:
        raw = os.environ.get(env_name)
    if raw in (None, ""):
        return default
    try:
        return float(str(raw))
    except (TypeError, ValueError):
        return default


def _quicktalk_rebuild(settings: Any):
    from opentalking.models.quicktalk.adapter import _configured_quicktalk_device
    from opentalking.models.quicktalk.runtime_v2 import QuickTalkRebuild

    return QuickTalkRebuild(
        asset_root=_settings_quicktalk_model_root(settings),
        device=_configured_quicktalk_device(
            getattr(settings, "quicktalk_device", None)
            or os.environ.get("OMNIRT_QUICKTALK_DEVICE"),
            getattr(settings, "torch_device", ""),
            getattr(settings, "device", ""),
        ),
        hubert_device=(
            getattr(settings, "quicktalk_hubert_device", None)
            or os.environ.get("OPENTALKING_QUICKTALK_HUBERT_DEVICE")
            or os.environ.get("OMNIRT_QUICKTALK_HUBERT_DEVICE")
            or None
        ),
        model_backend=str(
            getattr(settings, "quicktalk_model_backend", None)
            or os.environ.get("OPENTALKING_QUICKTALK_MODEL_BACKEND")
            or "pth"
        ),
        video_padding_seconds=0.0,
    )


class _QuickTalkCacheBuilder:
    def __init__(self, settings: Any) -> None:
        import torch
        from opentalking.models.quicktalk.adapter import _configured_quicktalk_device
        from opentalking.models.quicktalk.runtime_v2 import ImageProcessor

        asset_root = _settings_quicktalk_model_root(settings)
        checkpoints = asset_root / "checkpoints"
        aux_min = checkpoints / "auxiliary_min"
        aux_root = aux_min if aux_min.exists() else (checkpoints / "auxiliary")
        device = _configured_quicktalk_device(
            getattr(settings, "quicktalk_face_cache_device", None)
            or getattr(settings, "quicktalk_device", None)
            or os.environ.get("OPENTALKING_QUICKTALK_FACE_CACHE_DEVICE")
            or os.environ.get("OMNIRT_QUICKTALK_DEVICE"),
            getattr(settings, "torch_device", ""),
            getattr(settings, "device", ""),
        )
        torch_device = torch.device(device)
        dtype = torch.float32
        self.image_processor = ImageProcessor(
            aux_root,
            checkpoints / "repair.npy",
            256,
            torch_device,
            dtype,
        )

    def read_frames(self, video_path: Path, max_seconds: float | None = None):
        import cv2

        cap = cv2.VideoCapture(str(video_path))
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        if fps <= 0:
            cap.release()
            raise RuntimeError(f"Invalid FPS from video: {video_path}")
        frames = []
        frame_limit = None if max_seconds is None else int(max_seconds * fps)
        idx = 0
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                frames.append(frame)
                idx += 1
                if frame_limit is not None and idx >= frame_limit:
                    break
        finally:
            cap.release()
        return frames, fps

    def face_detect_frames(self, frames: Any):
        import cv2
        import numpy as np

        results = []
        for frame in frames:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            crop = self.image_processor.affine_transform(rgb)
            face_hwc = crop.face_chw.permute(1, 2, 0).cpu().numpy().astype(np.uint8)
            face_bgr = cv2.cvtColor(face_hwc, cv2.COLOR_RGB2BGR)
            results.append((face_bgr, crop.box, crop.affine_matrix))
        return results

    def save_face_cache(self, cache_path: Path, results: Any) -> None:
        import numpy as np

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        faces = np.stack([item[0] for item in results], axis=0).astype(np.uint8)
        boxes = np.asarray([item[1] for item in results], dtype=np.int32)
        affines = np.stack([item[2] for item in results], axis=0).astype(np.float32)
        tmp_path = cache_path.with_suffix(".tmp.npz")
        np.savez(str(tmp_path), faces=faces, boxes=boxes, affines=affines)
        tmp_path.replace(cache_path)


def _quicktalk_cache_builder(settings: Any) -> _QuickTalkCacheBuilder:
    return _QuickTalkCacheBuilder(settings)


def _quicktalk_cache_hit_result(
    avatar_dir: Path,
    manifest: dict[str, Any],
    *,
    max_long_edge: int,
    verify: bool,
) -> PreparedAssetResult | None:
    width, height = _target_video_size(manifest, max_long_edge=max_long_edge)
    quicktalk_dir = avatar_dir / "quicktalk"
    template_path = quicktalk_dir / f"template_{width}x{height}.mp4"
    cache_path = quicktalk_dir / f"face_cache_v3_{width}x{height}.npz"
    if not template_path.is_file() or not cache_path.is_file():
        return None
    source = _resolve_quicktalk_template_source(avatar_dir, manifest)
    info = _validate_quicktalk_face_cache(cache_path) if verify else None
    return PreparedAssetResult(
        avatar_id=str(manifest.get("id") or avatar_dir.name),
        status="hit",
        source_mode=source.mode if source is not None else "prepared",
        template_path=template_path,
        cache_path=cache_path,
        frames=info.frames if info else None,
    )


def _prepared_cache_response(model: str, cache: PreparedAssetResult) -> dict[str, Any]:
    return {
        "model": model,
        "status": cache.status,
        "source_mode": cache.source_mode,
        "frames": cache.frames,
        "detail": cache.detail,
    }


def _runtime_preload_error_payload(exc: Exception) -> dict[str, str]:
    return {
        "type": "error",
        "code": "preload_failed",
        "message": str(exc),
    }


def _omnirt_audio2video_preload_path(settings: Any, model: str) -> str:
    template = (
        getattr(settings, "omnirt_audio2video_path_template", "")
        or "/v1/audio2video/{model}"
    )
    path = template.format(model=model).rstrip("/")
    return f"{path}/preload"


def _call_adapter_warmup(adapter: Any, avatar_state: Any) -> bool:
    warmup = getattr(adapter, "warmup", None)
    if not callable(warmup):
        return False
    try:
        import inspect

        takes_avatar_state = bool(inspect.signature(warmup).parameters)
    except (TypeError, ValueError):
        takes_avatar_state = False
    if takes_avatar_state:
        warmup(avatar_state)
    else:
        warmup()
    return True


def _local_adapter_device(model: str, settings: Any) -> str:
    model = model.strip().lower()
    if model == "wav2lip":
        return str(
            getattr(settings, "wav2lip_device", "")
            or os.environ.get("OPENTALKING_WAV2LIP_DEVICE")
            or getattr(settings, "device", "")
            or os.environ.get("OPENTALKING_DEVICE")
            or os.environ.get("OPENTALKING_TORCH_DEVICE")
            or os.environ.get("DEVICE")
            or "cuda"
        )
    if model == "quicktalk":
        from opentalking.models.quicktalk.adapter import _configured_quicktalk_device

        return _configured_quicktalk_device(
            getattr(settings, "quicktalk_device", ""),
            os.environ.get("OPENTALKING_DEVICE"),
            os.environ.get("DEVICE"),
            getattr(settings, "torch_device", ""),
            getattr(settings, "device", ""),
        )
    return str(
        getattr(settings, "device", "")
        or os.environ.get("OPENTALKING_DEVICE")
        or os.environ.get("OPENTALKING_TORCH_DEVICE")
        or os.environ.get("DEVICE")
        or "cuda"
    )


def _prewarm_local_adapter(
    model: str,
    avatar_dir: Path,
    settings: Any,
    prepared_cache: PreparedAssetResult | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    import time

    started = time.monotonic()
    adapter = get_adapter(model)
    device = _local_adapter_device(model, settings)
    adapter.load_model(device)
    avatar_state = adapter.load_avatar(str(avatar_dir))
    warmed = _call_adapter_warmup(adapter, avatar_state)
    worker = getattr(avatar_state, "worker", None)
    frames = None
    restore_contexts = getattr(worker, "restore_contexts", None)
    if restore_contexts is not None:
        try:
            frames = len(restore_contexts)
        except TypeError:
            frames = None
    state_extra = getattr(avatar_state, "extra", None)
    preload_result = state_extra.get("preload_result") if isinstance(state_extra, dict) else None
    if isinstance(preload_result, dict) and frames is None:
        frames = preload_result.get("frames")
    runtime = {
        "type": "local_prewarm_result",
        "backend": "local",
        "model": model,
        "warmed": warmed,
        "elapsed_ms": round((time.monotonic() - started) * 1000.0, 3),
    }
    if isinstance(preload_result, dict):
        runtime["preload"] = preload_result
    cache = {
        "model": model,
        "status": "warmed" if warmed else "loaded",
        "source_mode": "local",
        "frames": frames,
        "detail": "local adapter loaded avatar and ran warmup" if warmed else "local adapter loaded avatar",
    }
    if model == "wav2lip":
        cache_dir = avatar_dir / "wav2lip"
        cache_files = sorted(cache_dir.glob("v*.npz")) if cache_dir.is_dir() else []
        manifest_path = avatar_dir / "manifest.json"
        source_mode = "local"
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            metadata = raw.get("metadata") if isinstance(raw, dict) else None
            if isinstance(metadata, dict):
                source_mode = str(metadata.get("reference_mode") or source_mode)
        except Exception:
            source_mode = "local"
        if source_mode == "frames":
            cache["source_mode"] = "frames"
            cache_source = str(preload_result.get("cache_source") or "") if isinstance(preload_result, dict) else ""
            if cache_source == "memory":
                cache["status"] = "memory"
            elif cache_source == "disk":
                cache["status"] = "hit"
            elif cache_source == "built":
                cache["status"] = "built"
            elif cache_files:
                cache["status"] = "built"
            if cache_files or cache_source:
                if frames is None:
                    cache["frames"] = len(cache_files)
                cache["detail"] = "local adapter prepared Wav2Lip frame cache"
            else:
                cache["status"] = "loaded"
                cache["detail"] = "local adapter loaded frames without persistent cache"
    if prepared_cache is not None:
        cache["prepared_status"] = prepared_cache.status
        if frames is None:
            cache["frames"] = prepared_cache.frames
    return cache, runtime


def _prewarm_local_backend(
    model: str,
    avatar_dir: Path,
    manifest: dict[str, Any],
    settings: Any,
    *,
    overwrite: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    prepared_cache: PreparedAssetResult | None = None
    if model == "quicktalk":
        prepared_cache, _runtime_payload = _prepare_quicktalk_prewarm(
            avatar_dir=avatar_dir,
            manifest=manifest,
            settings=settings,
            overwrite=overwrite,
        )
    try:
        return _prewarm_local_adapter(
            model,
            avatar_dir,
            settings,
            prepared_cache=prepared_cache,
        )
    except RuntimeError as exc:
        if model == "quicktalk" and "out of memory" in str(exc).lower():
            cache = {
                "model": model,
                "status": "ready",
                "source_mode": "local",
                "frames": prepared_cache.frames if prepared_cache is not None else None,
                "detail": "local adapter prepared QuickTalk assets but warmup ran out of memory",
                "prepared_status": prepared_cache.status if prepared_cache is not None else None,
            }
            runtime = {
                "type": "local_prewarm_result",
                "backend": "local",
                "model": model,
                "warmed": False,
                "elapsed_ms": 0.0,
                "message": str(exc),
            }
            return cache, runtime
        raise


def _quicktalk_runtime_payload(
    avatar_dir: Path,
    manifest: dict[str, Any],
    cache: PreparedAssetResult | None = None,
) -> dict[str, Any]:
    from opentalking.pipeline.speak.synthesis_runner import FlashTalkRunner

    runner = FlashTalkRunner(
        session_id="prewarm",
        avatar_id=avatar_dir.name,
        avatars_root=avatar_dir.parent,
        redis=None,
        flashtalk_client=object(),
        model_type="quicktalk",
    )
    video_config = runner._quicktalk_video_config() or {}
    payload: dict[str, Any] = dict(video_config)
    if cache is not None and cache.template_path is not None:
        payload["template_mode"] = "video"
        payload["template_video"] = str(cache.template_path)
        if cache.cache_path is not None:
            payload["quicktalk_face_cache"] = str(cache.cache_path)
    else:
        template_mode = runner._quicktalk_template_mode()
        if template_mode:
            payload["template_mode"] = template_mode
        template_video = runner._quicktalk_template_video()
        if template_video is not None:
            payload["template_video"] = str(template_video)
        template_frame_dir = runner._quicktalk_template_frame_dir()
        if template_frame_dir is not None:
            payload["template_frame_dir"] = str(template_frame_dir)
        face_cache = runner._quicktalk_face_cache()
        if face_cache is not None:
            payload["quicktalk_face_cache"] = str(face_cache)
    for key in ("width", "height", "fps"):
        if payload.get(key) is None and manifest.get(key) is not None:
            payload[key] = manifest.get(key)
    return payload


def _wav2lip_prewarm_payload(
    avatars_root: Path,
    avatar_id: str,
    avatar_dir: Path,
    manifest: dict[str, Any],
    settings: Any,
) -> dict[str, Any]:
    postprocess_mode = (
        getattr(settings, "wav2lip_postprocess_mode", "")
        or os.environ.get("OPENTALKING_WAV2LIP_POSTPROCESS_MODE", "")
        or "easy_improved"
    )
    payload = collect_wav2lip_preload_payload_for_avatar(
        avatars_root,
        avatar_id,
        postprocess_mode=str(postprocess_mode),
    )
    if payload is not None:
        payload.setdefault("reference_mode", "frames")
        return payload

    reference_path = None
    for name in ("reference.png", "reference.jpg", "reference.jpeg", "reference.webp", "preview.png"):
        candidate = avatar_dir / name
        if candidate.is_file():
            reference_path = candidate
            break
    if reference_path is None:
        raise HTTPException(
            status_code=400,
            detail=f"wav2lip prewarm requires reference image or preprocessed frames: {avatar_id}",
        )
    raw_metadata = manifest.get("metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
    mouth = {}
    animation = metadata.get("animation")
    if isinstance(animation, dict):
        source_image_hash = metadata.get("source_image_hash")
        mouth = {
            "source_image_hash": source_image_hash,
            "source_image_path": metadata.get("source_image_path"),
            "face_box": metadata.get("face_box"),
            "animation": animation,
        }
    return {
        "avatar_id": avatar_id,
        "ref_image": base64.b64encode(reference_path.read_bytes()).decode("ascii"),
        "width": int(manifest.get("width") or 416),
        "height": int(manifest.get("height") or 704),
        "fps": int(manifest.get("fps") or 25),
        "reference_mode": "image",
        "preprocessed": bool(metadata.get("preprocessed")),
        "wav2lip_postprocess_mode": (
            str(metadata.get("preferred_wav2lip_postprocess_mode") or postprocess_mode)
        ),
        "mouth_metadata": mouth,
    }


def _wav2lip_cache_response(payload: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    source_mode = str(payload.get("reference_mode") or "image")
    if source_mode != "frames":
        return {
            "model": "wav2lip",
            "status": "runtime",
            "source_mode": source_mode,
            "frames": runtime.get("frames"),
            "detail": "image reference mode warms the runtime but does not create a frame npz cache",
        }
    cache_source = str(runtime.get("cache_source") or "")
    if cache_source == "memory":
        status = "memory"
    elif cache_source == "disk":
        status = "hit"
    elif cache_source == "built":
        status = "built"
    else:
        status = cache_source or "unknown"
    return {
        "model": "wav2lip",
        "status": status,
        "source_mode": "frames",
        "frames": runtime.get("frames"),
        "detail": "",
    }


def _prepare_quicktalk_prewarm(
    *,
    avatar_dir: Path,
    manifest: dict[str, Any],
    settings: Any,
    overwrite: bool,
) -> tuple[PreparedAssetResult, dict[str, Any]]:
    max_long_edge = _settings_int(
        settings,
        "quicktalk_max_long_edge",
        "OPENTALKING_QUICKTALK_MAX_LONG_EDGE",
        900,
    )
    cache = None if overwrite else _quicktalk_cache_hit_result(
        avatar_dir,
        manifest,
        max_long_edge=max_long_edge,
        verify=True,
    )
    if cache is None:
        cache = _prepare_quicktalk_asset(
            avatar_dir=avatar_dir,
            manifest=manifest,
            rebuild=_quicktalk_cache_builder(settings),
            max_long_edge=max_long_edge,
            max_template_seconds=_settings_optional_float(
                settings,
                "quicktalk_max_template_seconds",
                "OPENTALKING_QUICKTALK_MAX_TEMPLATE_SECONDS",
                None,
            ),
            overwrite=overwrite,
            verify=True,
        )
    return cache, _quicktalk_runtime_payload(avatar_dir, manifest, cache)


@router.get("", response_model=list[AvatarSummary])
async def list_avatars(request: Request) -> list[AvatarSummary]:
    root = _avatars_root(request)
    out: list[AvatarSummary] = []
    for d in list_avatar_dirs(root):
        if _is_hidden_avatar(d / "manifest.json"):
            continue
        try:
            out.append(_summary_from_dir(d))
        except Exception:  # noqa: BLE001
            continue
    return _sort_avatar_summaries(out)


@router.get("/{avatar_id}/client-renderer")
async def get_client_renderer(avatar_id: str, request: Request) -> dict[str, Any]:
    root = _avatars_root(request)
    avatar_dir = (root / avatar_id).resolve()
    try:
        avatar_dir.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid avatar_id") from exc
    context = _renderer_context(avatar_dir)
    if context is None:
        raise HTTPException(status_code=404, detail="client renderer not found")
    return context.config


@router.get("/{avatar_id}/client-assets/{asset_path:path}")
async def get_client_asset(avatar_id: str, asset_path: str, request: Request) -> Response:
    raw_path = request.scope.get("raw_path", b"")
    if re.search(br"%2f|%5c|%00", raw_path, flags=re.IGNORECASE):
        raise HTTPException(status_code=400, detail="invalid asset path")
    relative = safe_relative_path(asset_path, suffix=".png")
    if relative is None:
        raise HTTPException(status_code=400, detail="invalid asset path")
    root = _avatars_root(request)
    avatar_dir = (root / avatar_id).resolve()
    try:
        avatar_dir.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid avatar_id") from exc
    context = _renderer_context(avatar_dir)
    if context is None:
        raise HTTPException(status_code=404, detail="client renderer not found")
    if relative.as_posix() not in context.referenced_assets:
        raise HTTPException(status_code=404, detail="asset not referenced")
    try:
        with open_referenced_asset(context, relative.as_posix()) as asset:
            content = asset.read()
    except Light2DContractError as exc:
        raise HTTPException(status_code=404, detail="asset not found") from exc
    return Response(content=content, media_type="image/png")


@router.post("/custom", response_model=AvatarSummary)
async def create_custom_avatar(
    request: Request,
    base_avatar_id: str = Form(...),
    name: str = Form(...),
    model: str | None = Form(default=None),
    person_mode: PersonMode = Form(default="single"),
    remove_background: bool = Form(default=False),
    image: UploadFile | None = File(default=None),
    video: UploadFile | None = File(default=None),
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
    if (image is None and video is None) or (image is not None and video is not None):
        raise HTTPException(status_code=400, detail="provide exactly one image or video")
    video_body: bytes | None = None
    video_suffix = ".mp4"
    if video is not None:
        image_rgb, video_body, video_suffix = await _read_upload_video(video)
    elif image is not None:
        image_rgb = await _read_upload_image(image)
    else:  # pragma: no cover - guarded above
        raise HTTPException(status_code=400, detail="provide exactly one image or video")

    try:
        shutil.copytree(
            base_dir,
            target_dir,
            ignore=shutil.ignore_patterns("reference_custom.*"),
        )
        _reset_custom_avatar_runtime_assets(target_dir)
        _write_custom_avatar_manifest(
            base_dir / "manifest.json",
            target_dir / "manifest.json",
            avatar_id=avatar_id,
            name=display_name,
            model=model,
            person_mode=person_mode,
        )
        max_w, max_h = _custom_avatar_max_size()
        fitted_image = _resize_uploaded_avatar_image(image_rgb, max_width=max_w, max_height=max_h)
        source_dir = target_dir / "source"
        source_dir.mkdir(parents=True, exist_ok=True)
        if remove_background and video_body is None:
            original_image = fitted_image.copy()
            try:
                fitted_image, matting_provider = remove_avatar_background(
                    fitted_image,
                    provider_name=str(getattr(request.app.state.settings, "avatar_matting_provider", "rembg")),
                    settings=request.app.state.settings,
                )
            except MattingError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            original_image.save(source_dir / "original.png", format="PNG")
            _update_manifest_matting_source(
                target_dir / "manifest.json",
                provider_name=matting_provider,
                original_source_image="source/original.png",
            )
        _update_manifest_dimensions(target_dir / "manifest.json", fitted_image)
        _update_manifest_matting_status(target_dir / "manifest.json", fitted_image)
        fitted_image.save(target_dir / "preview.png", format="PNG")
        fitted_image.save(target_dir / "reference.png", format="PNG")
        fitted_image.save(source_dir / "source.png", format="PNG")
        if video_body is not None:
            video_name = f"source_video{video_suffix}"
            (source_dir / video_name).write_bytes(video_body)
            raw = _read_manifest(target_dir / "manifest.json")
            metadata = dict(raw.get("metadata") or {})
            metadata["idle_mode"] = "loop"
            metadata["reference_mode"] = "video"
            metadata["source_image"] = "source/source.png"
            metadata["source_video"] = f"source/{video_name}"
            raw["metadata"] = metadata
            _write_manifest(target_dir / "manifest.json", raw)
        mouth_metadata.update_manifest_mouth_metadata(
            target_dir / "manifest.json",
            target_dir / "reference.png",
            force=True,
        )
        if video_body is None:
            _prepare_quicktalk_custom_assets(target_dir / "manifest.json", fitted_image)
        if video_body is None and _model_type_from_manifest(target_dir / "manifest.json") == "wav2lip":
            frames_dir = target_dir / "frames"
            frames_dir.mkdir(parents=True, exist_ok=True)
            frame_path = frames_dir / "frame_00000.png"
            fitted_image.save(frame_path, format="PNG")
            raw = _read_manifest(target_dir / "manifest.json")
            metadata = dict(raw.get("metadata") or {})
            metadata["frame_dir"] = "frames"
            raw["metadata"] = metadata
            _write_manifest(target_dir / "manifest.json", raw)
    except HTTPException:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(target_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"failed to create custom avatar: {exc}") from exc

    return _summary_from_dir(target_dir)


@router.patch("/{avatar_id}/person-mode", response_model=AvatarSummary)
async def update_avatar_person_mode(
    avatar_id: str,
    body: AvatarPersonModeUpdate,
    request: Request,
) -> AvatarSummary:
    root = _avatars_root(request)
    target = (root / avatar_id).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid avatar_id") from exc
    manifest_path = target / "manifest.json"
    if not target.is_dir() or not manifest_path.is_file():
        raise HTTPException(status_code=404, detail="avatar not found")
    raw = _read_manifest(manifest_path)
    metadata = dict(raw.get("metadata") or {})
    raw["metadata"] = _apply_person_mode_metadata(metadata, body.person_mode)
    _write_manifest(manifest_path, raw)
    return _summary_from_dir(target)


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


@router.get("/{avatar_id}/preview-video")
async def get_preview_video(avatar_id: str, request: Request) -> FileResponse:
    root = _avatars_root(request)
    avatar_dir = (root / avatar_id).resolve()
    try:
        avatar_dir.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid avatar_id") from exc
    if not avatar_dir.is_dir():
        raise HTTPException(status_code=404, detail="avatar not found")
    path = _avatar_preview_video_path(avatar_dir)
    if path is None:
        raise HTTPException(status_code=404, detail="preview video not found")
    return FileResponse(path, media_type=_video_media_type(path))


@router.post("/{avatar_id}/prewarm")
async def prewarm_avatar(avatar_id: str, request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        body = {}
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="request body must be an object")
    model = str(body.get("model") or "").strip().lower()
    if not model:
        raise HTTPException(status_code=422, detail="model is required")

    root = _avatars_root(request)
    avatar_dir = (root / avatar_id).resolve()
    try:
        avatar_dir.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid avatar_id") from exc
    manifest_path = avatar_dir / "manifest.json"
    if not avatar_dir.is_dir() or not manifest_path.is_file():
        raise HTTPException(status_code=404, detail="avatar not found")

    manifest = _read_manifest(manifest_path)
    settings = request.app.state.settings
    overwrite = bool(body.get("overwrite") or False)
    cache_response: dict[str, Any] | None = None
    backend = resolve_model_backend(model, settings)
    if backend.backend == "local":
        if model not in {"wav2lip", "quicktalk"}:
            raise HTTPException(status_code=400, detail=f"local prewarm is not supported for model '{model}'")
        try:
            cache_response, runtime = await asyncio.to_thread(
                _prewarm_local_backend,
                model,
                avatar_dir,
                manifest,
                settings,
                overwrite=overwrite,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"failed to prewarm local {model}: {exc}") from exc
        runtime_status = "failed" if not bool(runtime.get("warmed", True)) else "ready"
        return {
            "avatar_id": avatar_id,
            "model": model,
            "status": "ready",
            "runtime_status": runtime_status,
            "cache": cache_response,
            "runtime": runtime,
        }

    try:
        if model == "quicktalk":
            cache, runtime_payload = _prepare_quicktalk_prewarm(
                avatar_dir=avatar_dir,
                manifest=manifest,
                settings=settings,
                overwrite=overwrite,
            )
            cache_response = _prepared_cache_response(model, cache)
        elif model == "wav2lip":
            runtime_payload = _wav2lip_prewarm_payload(root, avatar_id, avatar_dir, manifest, settings)
        else:
            raise HTTPException(status_code=400, detail=f"prewarm is not supported for model '{model}'")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"failed to prepare {model} cache: {exc}") from exc

    if model == "wav2lip" and str(runtime_payload.get("reference_mode") or "image") != "frames":
        runtime = {
            "type": "preload_skipped",
            "reason": "image_reference_mode",
            "message": "image reference mode does not create a frame npz cache",
        }
        return {
            "avatar_id": avatar_id,
            "model": model,
            "status": "ready",
            "runtime_status": "skipped",
            "cache": _wav2lip_cache_response(runtime_payload, runtime),
            "runtime": runtime,
        }

    try:
        runtime = await _post_omnirt_json(
            settings,
            _omnirt_audio2video_preload_path(settings, model),
            runtime_payload,
        )
    except Exception as exc:  # noqa: BLE001
        runtime = _runtime_preload_error_payload(exc)

    runtime_type = str(runtime.get("type") or "")
    runtime_status = "ready" if runtime_type not in {"error", ""} else "failed"
    if model == "wav2lip":
        cache_response = _wav2lip_cache_response(runtime_payload, runtime)
    return {
        "avatar_id": avatar_id,
        "model": model,
        "status": "ready",
        "runtime_status": runtime_status,
        "cache": cache_response,
        "runtime": runtime,
    }


@router.delete("/{avatar_id}")
async def delete_avatar(avatar_id: str, request: Request) -> dict[str, str]:
    """Delete a user-created custom avatar.

    Built-in demo avatars cannot be deleted — they're tracked in git and would
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
