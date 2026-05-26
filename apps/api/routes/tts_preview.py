from __future__ import annotations

import io
import wave
from typing import Annotated

import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from opentalking.core.config import get_settings
from opentalking.providers.tts.factory import build_tts_adapter
from opentalking.providers.tts.providers import normalize_tts_provider
from opentalking.providers.tts.qwen_tts_voices import sanitize_qwen_model

router = APIRouter(prefix="/tts", tags=["tts"])

MAX_PREVIEW_TEXT_CHARS = 240


class TTSPreviewRequest(BaseModel):
    text: Annotated[str, Field(max_length=MAX_PREVIEW_TEXT_CHARS)]
    voice: str | None = None
    tts_provider: str | None = None
    tts_model: str | None = None


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


def _normalize_preview_request(body: TTSPreviewRequest) -> tuple[str, str | None, str | None, str | None]:
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
    return text, voice, provider, model


@router.post("/preview", response_class=Response)
async def preview_tts(body: TTSPreviewRequest) -> Response:
    text, voice, provider, model = _normalize_preview_request(body)
    settings = get_settings()
    sample_rate = int(settings.tts_sample_rate)
    tts = build_tts_adapter(
        sample_rate=sample_rate,
        chunk_ms=40.0,
        default_voice=voice,
        tts_provider=provider,
        tts_model=model,
    )
    chunks: list[np.ndarray] = []
    effective_sample_rate = sample_rate
    try:
        async for chunk in tts.synthesize_stream(text, voice=voice):
            arr = np.asarray(chunk.data, dtype=np.int16).reshape(-1)
            if arr.size:
                chunks.append(arr.copy())
            effective_sample_rate = int(chunk.sample_rate or effective_sample_rate)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"TTS preview failed: {exc}") from exc
    finally:
        close = getattr(tts, "aclose", None)
        if close is not None:
            await close()

    if not chunks:
        raise HTTPException(status_code=502, detail="TTS preview returned no audio")

    return Response(
        content=_wav_bytes(chunks, effective_sample_rate),
        media_type="audio/wav",
        headers={"Cache-Control": "no-store"},
    )
