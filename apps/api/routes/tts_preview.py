from __future__ import annotations

import io
import json
import logging
import tempfile
import wave
from pathlib import Path
from typing import Annotated, Any, Protocol

import numpy as np
from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile as StarletteUploadFile

from opentalking.avatar.duo_dialog import DEFAULT_DUO_DIALOG_GAP_MS, MAX_DUO_DIALOG_GAP_MS
from opentalking.core.config import get_settings
from opentalking.providers.tts.factory import build_tts_adapter
from opentalking.providers.tts.indextts_config import normalize_indextts_config
from opentalking.providers.tts.providers import normalize_tts_provider
from opentalking.providers.tts.qwen_tts_voices import sanitize_qwen_model

router = APIRouter(prefix="/tts", tags=["tts"])
logger = logging.getLogger(__name__)

MAX_PREVIEW_TEXT_CHARS = 1000
LOCAL_COSYVOICE_PREVIEW_SECONDS = 3.0
_INDEXTTS_PROVIDERS = {"indextts", "local_indextts", "omnirt_indextts"}
PreviewUploadFile = UploadFile | StarletteUploadFile


class TTSPreviewSettings(Protocol):
    tts_sample_rate: int


class DuoDialogPreviewLine(BaseModel):
    id: str | None = None
    role: str
    text: Annotated[str, Field(max_length=MAX_PREVIEW_TEXT_CHARS)]


class DuoDialogPreviewSpeaker(BaseModel):
    tts_provider: str | None = None
    provider: str | None = None
    tts_model: str | None = None
    model: str | None = None
    voice: str | None = None
    voice_id: str | None = None
    indextts_config: dict[str, Any] | None = None


class DuoDialogPreviewRequest(BaseModel):
    lines: list[DuoDialogPreviewLine]
    speakers: dict[str, DuoDialogPreviewSpeaker] = Field(default_factory=dict)
    voices: dict[str, str] = Field(default_factory=dict)
    gap_ms: int = DEFAULT_DUO_DIALOG_GAP_MS


class TTSPreviewRequest(BaseModel):
    text: Annotated[str, Field(max_length=MAX_PREVIEW_TEXT_CHARS)]
    voice: str | None = None
    tts_provider: str | None = None
    tts_model: str | None = None
    indextts_config: dict[str, Any] | None = None


def _preview_sample_limit(provider: str | None, sample_rate: int) -> int | None:
    if provider == "local_cosyvoice":
        return max(1, int(sample_rate * LOCAL_COSYVOICE_PREVIEW_SECONDS))
    return None


def _wav_bytes(chunks: list[np.ndarray], sample_rate: int) -> bytes:
    pcm = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)
    pcm = np.asarray(pcm, dtype="<i2").reshape(-1)
    out = io.BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return out.getvalue()


def _coerce_preview_gap_ms(raw: int | None) -> int:
    value = DEFAULT_DUO_DIALOG_GAP_MS if raw is None else int(raw)
    if value < 0 or value > MAX_DUO_DIALOG_GAP_MS:
        raise HTTPException(status_code=422, detail=f"gap_ms must be between 0 and {MAX_DUO_DIALOG_GAP_MS}")
    return value


def _normalize_preview_tts_settings(
    speaker: DuoDialogPreviewSpeaker | None,
    *,
    fallback_voice: str | None = None,
) -> tuple[str | None, str | None, str | None, dict[str, Any] | None]:
    provider_raw = (speaker.tts_provider or speaker.provider) if speaker else None
    try:
        provider = normalize_tts_provider(provider_raw, default=None)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    model_raw = (speaker.tts_model or speaker.model or '').strip() if speaker else ''
    model: str | None = model_raw or None
    if provider in {'dashscope', 'bailian', 'qwen', 'qwen_tts', 'local_cosyvoice', 'local_qwen3_tts'} and model:
        model = sanitize_qwen_model(model)
    voice = (speaker.voice or speaker.voice_id or fallback_voice or '').strip() if speaker else (fallback_voice or '').strip()

    indextts_config: dict[str, Any] | None = None
    if provider in _INDEXTTS_PROVIDERS and speaker and speaker.indextts_config:
        try:
            indextts_config = normalize_indextts_config(dict(speaker.indextts_config)) or None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return voice or None, provider, model, indextts_config


def _normalize_preview_request(
    body: TTSPreviewRequest,
    *,
    indextts_emotion_audio_path: Path | None = None,
) -> tuple[str, str | None, str | None, str | None, dict[str, Any] | None]:
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="text is required")

    try:
        provider = normalize_tts_provider(body.tts_provider, default=None)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    model = body.tts_model.strip() if body.tts_model and body.tts_model.strip() else None
    if provider in {"dashscope", "bailian", "qwen", "qwen_tts", "local_cosyvoice", "local_qwen3_tts"} and model:
        model = sanitize_qwen_model(model)

    voice = body.voice.strip() if body.voice and body.voice.strip() else None
    indextts_config: dict[str, Any] | None = None
    if provider in _INDEXTTS_PROVIDERS and (body.indextts_config or indextts_emotion_audio_path is not None):
        raw_config = dict(body.indextts_config or {})
        if indextts_emotion_audio_path is not None:
            raw_config["emotion_mode"] = "audio"
            raw_config["emo_audio_prompt"] = str(indextts_emotion_audio_path)
        try:
            indextts_config = normalize_indextts_config(raw_config) or None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return text, voice, provider, model, indextts_config


def _is_local_cosyvoice_input_error(exc: Exception) -> bool:
    message = str(exc)
    return isinstance(exc, ValueError) or "HTTP 400" in message or "请求无效" in message or "请先选择本地音色" in message


def _config_from_form_value(raw: object) -> dict[str, Any] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="indextts_config must be valid JSON") from exc
    if not isinstance(decoded, dict):
        raise HTTPException(status_code=422, detail="indextts_config must be a JSON object")
    return decoded


async def _preview_request_from_http(request: Request) -> tuple[TTSPreviewRequest, PreviewUploadFile | None]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type in {"multipart/form-data", "application/x-www-form-urlencoded"}:
        form = await request.form()
        upload = form.get("indextts_emotion_audio_file")
        return (
            TTSPreviewRequest(
                text=str(form.get("text") or ""),
                voice=str(form.get("voice") or "") or None,
                tts_provider=str(form.get("tts_provider") or "") or None,
                tts_model=str(form.get("tts_model") or "") or None,
                indextts_config=_config_from_form_value(form.get("indextts_config")),
            ),
            upload if isinstance(upload, (UploadFile, StarletteUploadFile)) else None,
        )
    try:
        data = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="request body must be valid JSON") from exc
    return TTSPreviewRequest(**data), None


async def _save_preview_emotion_audio(upload: PreviewUploadFile | None) -> Path | None:
    if upload is None:
        return None
    body = await upload.read()
    if not body:
        raise HTTPException(status_code=400, detail="empty IndexTTS emotion audio")
    suffix = Path(upload.filename or "emotion.wav").suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(body)
        return Path(tmp.name)


def _indextts_emotion_mode_for_log(
    *,
    raw_config: dict[str, Any] | None,
    normalized_config: dict[str, Any] | None,
    emotion_audio_path: Path | None,
) -> str:
    if not normalized_config and emotion_audio_path is None:
        return "none"
    if emotion_audio_path is not None or (normalized_config and "emo_audio_prompt" in normalized_config):
        return "audio"

    raw_mode = str((raw_config or {}).get("emotion_mode") or (raw_config or {}).get("mode") or "").strip().lower()
    if raw_mode in {"vector", "manual", "emo_vector", "normalized_vector"}:
        return raw_mode
    if raw_mode in {"text", "emo_text", "emotion_text"}:
        return "text"
    if raw_mode in {"voice", "follow_voice", "none", ""}:
        pass
    elif raw_mode:
        return raw_mode

    if normalized_config and "emo_vector" in normalized_config:
        return "vector"
    if normalized_config and normalized_config.get("use_emo_text"):
        return "text"
    return "voice"


async def _collect_tts_preview_chunks(
    *,
    text: str,
    voice: str | None,
    provider: str | None,
    model: str | None,
    indextts_config: dict[str, Any] | None,
    settings: TTSPreviewSettings,
) -> tuple[list[np.ndarray], int]:
    sample_rate = int(settings.tts_sample_rate)
    tts = build_tts_adapter(
        sample_rate=sample_rate,
        chunk_ms=40.0,
        default_voice=voice,
        tts_provider=provider,
        tts_model=model,
        indextts_config=indextts_config,
    )
    chunks: list[np.ndarray] = []
    effective_sample_rate = sample_rate
    sample_limit = _preview_sample_limit(provider, sample_rate)
    total_samples = 0
    try:
        async for chunk in tts.synthesize_stream(text, voice=voice):
            arr = np.asarray(chunk.data, dtype=np.int16).reshape(-1)
            if arr.size:
                chunks.append(arr.copy())
                total_samples += int(arr.size)
            effective_sample_rate = int(chunk.sample_rate or effective_sample_rate)
            if sample_limit is not None and total_samples >= sample_limit:
                break
    finally:
        close = getattr(tts, "aclose", None)
        if close is not None:
            await close()
    return chunks, effective_sample_rate


def _log_tts_preview_request(
    *,
    provider: str | None,
    voice: str | None,
    model: str | None,
    raw_indextts_config: dict[str, Any] | None,
    indextts_config: dict[str, Any] | None,
    emotion_audio_path: Path | None,
) -> None:
    fields: list[str] = [
        f"provider={provider or 'default'}",
        f"voice_id={voice or 'default'}",
        f"model={model or 'default'}",
    ]
    if provider in _INDEXTTS_PROVIDERS:
        fields.extend(
            [
                "indextts_emotion_mode="
                + _indextts_emotion_mode_for_log(
                    raw_config=raw_indextts_config,
                    normalized_config=indextts_config,
                    emotion_audio_path=emotion_audio_path,
                ),
                f"indextts_emo_alpha={(indextts_config or {}).get('emo_alpha', 'default')}",
                f"indextts_emo_vector={(indextts_config or {}).get('emo_vector', 'default')}",
                f"indextts_use_random={(indextts_config or {}).get('use_random', 'default')}",
                f"indextts_emotion_audio_uploaded={emotion_audio_path is not None}",
            ]
        )
    logger.info("tts preview requested | %s", " ".join(fields))


@router.post("/preview", response_class=Response)
async def preview_tts(request: Request) -> Response:
    body, emotion_audio_upload = await _preview_request_from_http(request)
    emotion_audio_path = await _save_preview_emotion_audio(emotion_audio_upload)
    text, voice, provider, model, indextts_config = _normalize_preview_request(
        body,
        indextts_emotion_audio_path=emotion_audio_path,
    )
    _log_tts_preview_request(
        provider=provider,
        voice=voice,
        model=model,
        raw_indextts_config=body.indextts_config,
        indextts_config=indextts_config,
        emotion_audio_path=emotion_audio_path,
    )
    settings = get_settings()
    sample_rate = int(settings.tts_sample_rate)
    tts = build_tts_adapter(
        sample_rate=sample_rate,
        chunk_ms=40.0,
        default_voice=voice,
        tts_provider=provider,
        tts_model=model,
        indextts_config=indextts_config,
    )
    chunks: list[np.ndarray] = []
    effective_sample_rate = sample_rate
    sample_limit = _preview_sample_limit(provider, sample_rate)
    total_samples = 0
    try:
        async for chunk in tts.synthesize_stream(text, voice=voice):
            arr = np.asarray(chunk.data, dtype=np.int16).reshape(-1)
            if arr.size:
                chunks.append(arr.copy())
                total_samples += int(arr.size)
            effective_sample_rate = int(chunk.sample_rate or effective_sample_rate)
            if sample_limit is not None and total_samples >= sample_limit:
                break
    except Exception as exc:
        logger.exception(
            "tts preview failed | provider=%s voice_id=%s model=%s error=%s",
            provider or "default",
            voice or "default",
            model or "default",
            exc,
        )
        if provider == "local_cosyvoice":
            if _is_local_cosyvoice_input_error(exc):
                raise HTTPException(
                    status_code=400,
                    detail=str(exc),
                ) from exc
            error_text = str(exc)
            if "CosyVoice returned no audio" in error_text or "本地 CosyVoice 返回空音频" in error_text:
                raise HTTPException(
                    status_code=502,
                    detail=f"TTS preview failed: {error_text}",
                ) from exc
            raise HTTPException(
                status_code=502,
                detail=f"TTS preview failed: 本地 CosyVoice 服务不可用（可能已退出/内存不足）；前端可回退 Edge 试听。{exc}",
            ) from exc
        raise HTTPException(status_code=502, detail=f"TTS preview failed: {exc}") from exc
    finally:
        close = getattr(tts, "aclose", None)
        if close is not None:
            await close()
        if emotion_audio_path is not None:
            emotion_audio_path.unlink(missing_ok=True)

    if not chunks:
        raise HTTPException(status_code=502, detail="TTS preview returned no audio")

    return Response(
        content=_wav_bytes(chunks, effective_sample_rate),
        media_type="audio/wav",
        headers={"Cache-Control": "no-store"},
    )

@router.post("/preview-duo-dialog", response_class=Response)
async def preview_duo_dialog_tts(body: DuoDialogPreviewRequest) -> Response:
    if not body.lines:
        raise HTTPException(status_code=422, detail="lines is required")
    gap_ms = _coerce_preview_gap_ms(body.gap_ms)
    settings = get_settings()
    sample_rate = int(settings.tts_sample_rate)
    all_chunks: list[np.ndarray] = []
    for index, line in enumerate(body.lines):
        role = line.role.strip()
        text = line.text.strip()
        if not role:
            raise HTTPException(status_code=422, detail="line role is required")
        if not text:
            raise HTTPException(status_code=422, detail="line text is required")
        speaker = body.speakers.get(role)
        voice, provider, model, indextts_config = _normalize_preview_tts_settings(
            speaker,
            fallback_voice=(body.voices or {}).get(role),
        )
        _log_tts_preview_request(
            provider=provider,
            voice=voice,
            model=model,
            raw_indextts_config=speaker.indextts_config if speaker else None,
            indextts_config=indextts_config,
            emotion_audio_path=None,
        )
        try:
            chunks, effective_sample_rate = await _collect_tts_preview_chunks(
                text=text,
                voice=voice,
                provider=provider,
                model=model,
                indextts_config=indextts_config,
                settings=settings,
            )
        except Exception as exc:
            logger.exception(
                "duo tts preview failed | role=%s provider=%s voice_id=%s model=%s error=%s",
                role,
                provider or "default",
                voice or "default",
                model or "default",
                exc,
            )
            raise HTTPException(status_code=502, detail=f"TTS preview failed: {exc}") from exc
        if not chunks:
            raise HTTPException(status_code=502, detail="TTS preview returned no audio")
        sample_rate = effective_sample_rate
        all_chunks.extend(chunks)
        if index < len(body.lines) - 1 and gap_ms > 0:
            all_chunks.append(np.zeros(int(round(sample_rate * gap_ms / 1000.0)), dtype=np.int16))

    return Response(
        content=_wav_bytes(all_chunks, sample_rate),
        media_type="audio/wav",
        headers={"Cache-Control": "no-store"},
    )
