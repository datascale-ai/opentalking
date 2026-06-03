from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from opentalking.video_creation import VideoCreationService

router = APIRouter(prefix="/video-creation", tags=["video-creation"])

_AUDIO_SOURCES = {"upload", "tts_text"}


def _audio_max_bytes(settings: object) -> int:
    try:
        return int(getattr(settings, "video_creation_audio_max_bytes", 50 * 1024 * 1024))
    except (TypeError, ValueError):
        return 50 * 1024 * 1024


def _with_download_url(payload: dict[str, Any]) -> dict[str, Any]:
    item = payload.get("export_video")
    if isinstance(item, dict) and item.get("id") and not item.get("download_url"):
        item["download_url"] = f"/exports/videos/{item['id']}/download"
    return payload


@router.post("/jobs", response_model=None)
async def create_video_creation_job(
    request: Request,
    model: str = Form(...),
    avatar_id: str = Form(...),
    audio_source: str = Form(...),
    title: str = Form(""),
    audio_file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
    tts_provider: str | None = Form(default=None),
    tts_model: str | None = Form(default=None),
    voice: str | None = Form(default=None),
) -> dict[str, Any]:
    source = audio_source.strip().lower()
    if source not in _AUDIO_SOURCES:
        raise HTTPException(status_code=400, detail="audio_source must be upload or tts_text")
    settings = request.app.state.settings
    service = VideoCreationService(settings)
    try:
        if source == "upload":
            if audio_file is None:
                raise HTTPException(status_code=400, detail="audio_file is required")
            body = await audio_file.read()
            max_bytes = _audio_max_bytes(settings)
            if len(body) > max_bytes:
                raise HTTPException(status_code=413, detail=f"audio too large (max {max_bytes} bytes)")
            if not body:
                raise HTTPException(status_code=400, detail="empty audio")
            suffix = Path(audio_file.filename or "speech.wav").suffix or ".wav"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(body)
                upload_path = Path(tmp.name)
            try:
                result = await service.create_from_audio_file(
                    model=model,
                    avatar_id=avatar_id,
                    upload_path=upload_path,
                    title=title,
                    mime_type=audio_file.content_type,
                )
            finally:
                upload_path.unlink(missing_ok=True)
            return _with_download_url(result)

        result = await service.create_from_tts_text(
            model=model,
            avatar_id=avatar_id,
            text=text or "",
            title=title,
            tts_provider=tts_provider,
            tts_model=tts_model,
            voice=voice,
        )
        return _with_download_url(result)
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"video creation failed: {exc}") from exc
