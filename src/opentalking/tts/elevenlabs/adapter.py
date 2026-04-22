from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import httpx

from opentalking.core.types.frames import AudioChunk
from opentalking.tts.edge.adapter import _stream_decode_mp3_to_pcm_chunks

log = logging.getLogger(__name__)


class ElevenLabsTTSAdapter:
    """ElevenLabs low-latency TTS using Flash v2.5 streaming."""

    def __init__(
        self,
        *,
        api_key: str,
        default_voice: str,
        base_url: str = "https://api.elevenlabs.io",
        model_id: str = "eleven_flash_v2_5",
        output_format: str = "mp3_22050_32",
        sample_rate: int = 16000,
        chunk_ms: float = 20.0,
    ) -> None:
        self.api_key = api_key.strip()
        self.default_voice = default_voice.strip()
        self.base_url = base_url.rstrip("/")
        self.model_id = model_id.strip()
        self.output_format = output_format.strip()
        self.sample_rate = sample_rate
        self.chunk_ms = chunk_ms

    async def synthesize_stream(
        self,
        text: str,
        voice: str | None = None,
    ) -> AsyncIterator[AudioChunk]:
        voice_id = (voice or self.default_voice).strip()
        if not self.api_key:
            raise RuntimeError("ElevenLabs API key is empty.")
        if not voice_id:
            raise RuntimeError("ElevenLabs voice id is empty.")

        timeout = httpx.Timeout(connect=30.0, read=120.0, write=30.0, pool=30.0)
        url = f"{self.base_url}/v1/text-to-speech/{voice_id}/stream"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "text": text,
            "model_id": self.model_id,
        }
        params = {"output_format": self.output_format}

        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                url,
                headers=headers,
                params=params,
                json=payload,
            ) as resp:
                try:
                    resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    detail = await resp.aread()
                    message = detail.decode("utf-8", errors="ignore").strip()
                    if message:
                        raise RuntimeError(
                            f"ElevenLabs TTS failed ({exc.response.status_code}): {message}"
                        ) from exc
                    raise

                async def _audio_iter() -> AsyncIterator[bytes]:
                    async for chunk in resp.aiter_bytes():
                        if chunk:
                            yield chunk

                async for chunk in _stream_decode_mp3_to_pcm_chunks(
                    _audio_iter(),
                    self.sample_rate,
                    self.chunk_ms,
                ):
                    yield chunk


async def list_elevenlabs_voices(
    *,
    api_key: str,
    base_url: str = "https://api.elevenlabs.io",
) -> list[dict[str, Any]]:
    api_key = api_key.strip()
    if not api_key:
        return []

    timeout = httpx.Timeout(connect=15.0, read=30.0, write=15.0, pool=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(
            f"{base_url.rstrip('/')}/v2/voices",
            headers={"xi-api-key": api_key},
        )
        resp.raise_for_status()
        data = resp.json()

    voices = data.get("voices", [])
    if not isinstance(voices, list):
        log.warning("Unexpected ElevenLabs voices payload: %s", json.dumps(data)[:300])
        return []

    out: list[dict[str, Any]] = []
    for item in voices:
        if not isinstance(item, dict):
            continue
        voice_id = str(item.get("voice_id", "")).strip()
        name = str(item.get("name", "")).strip() or voice_id
        if not voice_id:
            continue
        labels = item.get("labels") or {}
        category = str(item.get("category", "")).strip()
        parts: list[str] = []
        if category:
            parts.append(category)
        if isinstance(labels, dict):
            for key in ("gender", "age", "accent", "use_case"):
                value = str(labels.get(key, "")).strip()
                if value:
                    parts.append(value)
        out.append(
            {
                "voice_id": voice_id,
                "name": name,
                "description": " / ".join(parts) or "ElevenLabs 在线声线",
            }
        )
    return out
