from __future__ import annotations

import os
from collections.abc import AsyncIterator

import httpx

from opentalking.core.types.frames import AudioChunk
from opentalking.providers.tts.edge.adapter import _stream_decode_audio_to_pcm_chunks


def _settings_value(name: str, default: str = "") -> str:
    try:
        from opentalking.core.config import get_settings

        value = getattr(get_settings(), name, default)
        if value is not None and str(value).strip():
            return str(value).strip()
    except Exception:
        pass
    return default


def _audio_format_from_content_type(content_type: str | None) -> str | None:
    value = (content_type or "").split(";", 1)[0].strip().lower()
    if value in {"audio/wav", "audio/wave", "audio/x-wav"}:
        return "wav"
    if value in {"audio/mpeg", "audio/mp3"}:
        return "mp3"
    return None


class LocalQwen3TTSAdapter:
    """Same-host local Qwen3-TTS service adapter."""

    def __init__(
        self,
        default_voice: str | None = None,
        sample_rate: int = 16000,
        chunk_ms: float = 20.0,
        *,
        model: str | None = None,
    ) -> None:
        self.default_voice = default_voice or "local-default"
        self.sample_rate = sample_rate
        self.chunk_ms = chunk_ms
        self.model = (
            model
            or os.environ.get("OPENTALKING_LOCAL_QWEN3_TTS_MODEL")
            or _settings_value("local_qwen3_tts_model", "")
            or "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
        ).strip()
        self.service_url = (
            os.environ.get("OPENTALKING_LOCAL_QWEN3_TTS_SERVICE_URL", "").strip()
            or _settings_value("local_qwen3_tts_service_url", "")
        )

    async def synthesize_stream(self, text: str, voice: str | None = None) -> AsyncIterator[AudioChunk]:
        if not text.strip():
            return
        if not self.service_url:
            raise RuntimeError(
                "Local Qwen3-TTS requires OPENTALKING_LOCAL_QWEN3_TTS_SERVICE_URL. "
                "Run a local Qwen3-TTS service and point this variable at its synthesize endpoint."
            )
        timeout = httpx.Timeout(connect=30.0, read=180.0, write=30.0, pool=30.0)
        payload = {"text": text, "voice": voice or self.default_voice, "model": self.model}
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", self.service_url, json=payload) as resp:
                resp.raise_for_status()
                input_format = _audio_format_from_content_type(resp.headers.get("content-type"))

                async def _audio_iter() -> AsyncIterator[bytes]:
                    async for data in resp.aiter_bytes():
                        if data:
                            yield data

                async for chunk in _stream_decode_audio_to_pcm_chunks(
                    _audio_iter(),
                    self.sample_rate,
                    self.chunk_ms,
                    input_format=input_format,
                ):
                    yield chunk
