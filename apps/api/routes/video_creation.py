from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from opentalking.avatar.fasterliveportrait_config import normalize_fasterliveportrait_runtime_config
from opentalking.providers.tts.indextts_config import normalize_indextts_config
from opentalking.providers.tts.providers import normalize_tts_provider
from opentalking.avatar.light2d import Light2DContractError
from opentalking.video_creation import VideoCreationService, preflight_light2d_video_creation

router = APIRouter(prefix="/video-creation", tags=["video-creation"])

_AUDIO_SOURCES = {"upload", "tts_text", "voice_clone", "reference_video", "duo_dialog"}
_INDEXTTS_PROVIDERS = {"indextts", "local_indextts", "omnirt_indextts"}


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


def _parse_fasterliveportrait_config(model: str, raw: str | None) -> dict[str, object] | None:
    if (model or "").strip().lower() != "fasterliveportrait" or not raw:
        return None
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="fasterliveportrait_config must be valid JSON") from exc
    try:
        config = normalize_fasterliveportrait_runtime_config(decoded)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return dict(config) or None


def _parse_indextts_config(tts_provider: str | None, raw: str | None, *, emotion_audio_path: Path | None = None) -> dict[str, object] | None:
    if not raw and emotion_audio_path is None:
        return None
    provider = normalize_tts_provider(tts_provider, default=None)
    if provider not in _INDEXTTS_PROVIDERS:
        return None
    if raw:
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="indextts_config must be valid JSON") from exc
    else:
        decoded = {}
    if not isinstance(decoded, dict):
        raise HTTPException(status_code=400, detail="indextts_config must be a JSON object")
    if emotion_audio_path is not None:
        decoded = {**decoded, "emotion_mode": "audio", "emo_audio_prompt": str(emotion_audio_path)}
    try:
        config = normalize_indextts_config(decoded)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return dict(config) or None


def _parse_video_composition_config(raw: str | None) -> dict[str, object] | None:
    if not raw:
        return None
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="composition_config must be valid JSON") from exc
    if not isinstance(decoded, dict):
        raise HTTPException(status_code=400, detail="composition_config must be a JSON object")
    return decoded


def _parse_duo_dialog(raw: str | None) -> dict[str, object]:
    if not raw:
        raise HTTPException(status_code=400, detail="duo_dialog is required")
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="duo_dialog must be valid JSON") from exc
    if not isinstance(decoded, dict):
        raise HTTPException(status_code=400, detail="duo_dialog must be a JSON object")
    return decoded


async def _save_indextts_emotion_audio(upload: UploadFile | None) -> Path | None:
    if upload is None:
        return None
    body = await upload.read()
    if not body:
        raise HTTPException(status_code=400, detail="empty IndexTTS emotion audio")
    suffix = Path(upload.filename or "emotion.wav").suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(body)
        return Path(tmp.name)


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
    duration_sec: int | None = Form(default=None),
    fasterliveportrait_config: str | None = Form(default=None),
    indextts_config: str | None = Form(default=None),
    composition_config: str | None = Form(default=None),
    duo_dialog: str | None = Form(default=None),
    indextts_emotion_audio_file: UploadFile | None = File(default=None),
) -> dict[str, Any]:
    source = audio_source.strip().lower()
    if source not in _AUDIO_SOURCES:
        raise HTTPException(status_code=400, detail="audio_source must be upload, tts_text, voice_clone, duo_dialog, or reference_video")
    settings = request.app.state.settings
    flp_config = _parse_fasterliveportrait_config(model, fasterliveportrait_config)
    video_composition_config = _parse_video_composition_config(composition_config)
    try:
        light2d_renderer = preflight_light2d_video_creation(
            settings,
            model=model,
            avatar_id=avatar_id,
            source=source,
            text=text,
            composition_config=video_composition_config,
        )
    except (Light2DContractError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    emotion_audio_path = await _save_indextts_emotion_audio(indextts_emotion_audio_file)
    try:
        index_config = _parse_indextts_config(tts_provider, indextts_config, emotion_audio_path=emotion_audio_path)
    except Exception:
        if emotion_audio_path is not None:
            emotion_audio_path.unlink(missing_ok=True)
        raise
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
                    fasterliveportrait_config=flp_config,
                    composition_config=video_composition_config,
                    light2d_renderer=light2d_renderer,
                )
            finally:
                upload_path.unlink(missing_ok=True)
            return _with_download_url(result)

        if source == "reference_video":
            result = await service.create_reference_video(
                model=model,
                avatar_id=avatar_id,
                duration_sec=duration_sec,
                title=title,
                composition_config=video_composition_config,
                light2d_renderer=light2d_renderer,
            )
            return _with_download_url(result)

        if source == "duo_dialog":
            result = await service.create_from_duo_dialog(
                model=model,
                avatar_id=avatar_id,
                title=title,
                duo_dialog=_parse_duo_dialog(duo_dialog),
                tts_provider=tts_provider,
                tts_model=tts_model,
                indextts_config=index_config,
                composition_config=video_composition_config,
            )
            return _with_download_url(result)

        result = await service.create_from_tts_text(
            model=model,
            avatar_id=avatar_id,
            text=text or "",
            title=title,
            tts_provider=tts_provider,
            tts_model=tts_model,
            voice=voice,
            source=source,
            fasterliveportrait_config=flp_config,
            indextts_config=index_config,
            composition_config=video_composition_config,
            light2d_renderer=light2d_renderer,
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
    finally:
        if emotion_audio_path is not None:
            emotion_audio_path.unlink(missing_ok=True)
