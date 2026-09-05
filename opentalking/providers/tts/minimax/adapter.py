from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import numpy as np

from opentalking.core.types.frames import AudioChunk
from opentalking.providers.tts.edge.adapter import _stream_decode_audio_to_pcm_chunks
from opentalking.providers.tts.openai_compatible.adapter import _split_pcm_chunks


def _decode_audio_field(value: Any) -> bytes:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("MiniMax TTS response has no data.audio.")
    raw = value.strip()
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        return bytes.fromhex(raw)
    except ValueError as exc:
        raise RuntimeError("MiniMax TTS response data.audio is not hex audio.") from exc


class MiniMaxTTSAdapter:
    """MiniMax Speech HTTP adapter for the t2a_v2 endpoint."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        default_voice: str,
        audio_format: str = "mp3",
        sample_rate: int = 16000,
        chunk_ms: float = 20.0,
    ) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.model = model.strip()
        self.default_voice = default_voice.strip() or "male-qn-qingse"
        self.audio_format = (audio_format or "mp3").strip().lower()
        self.sample_rate = sample_rate
        self.chunk_ms = chunk_ms

    async def synthesize_stream(self, text: str, voice: str | None = None) -> AsyncIterator[AudioChunk]:
        if not self.api_key:
            raise RuntimeError("MiniMax TTS selected but OPENTALKING_TTS_MINIMAX_API_KEY is empty.")
        if not self.base_url:
            raise RuntimeError("MiniMax TTS selected but OPENTALKING_TTS_MINIMAX_BASE_URL is empty.")
        if not self.model:
            raise RuntimeError("MiniMax TTS selected but OPENTALKING_TTS_MINIMAX_MODEL is empty.")

        effective_voice = (voice or self.default_voice).strip() or self.default_voice
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "text": text,
            "stream": False,
            "output_format": "hex",
            "voice_setting": {"voice_id": effective_voice},
            "audio_setting": {
                "sample_rate": self.sample_rate,
                "bitrate": 128000,
                "format": self.audio_format,
                "channel": 1,
            },
        }
        timeout = httpx.Timeout(connect=30.0, read=180.0, write=30.0, pool=30.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{self.base_url}/t2a_v2", headers=headers, json=payload)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"MiniMax TTS failed ({exc.response.status_code}): {resp.text.strip()}") from exc

        data = self._extract_audio(resp)
        if self.audio_format == "pcm":
            pcm = np.frombuffer(data[: len(data) - (len(data) % 2)], dtype="<i2").copy()
            for chunk in _split_pcm_chunks(pcm, self.sample_rate, self.chunk_ms):
                yield chunk
            return

        async def _single_chunk_iter() -> AsyncIterator[bytes]:
            yield data

        async for chunk in _stream_decode_audio_to_pcm_chunks(
            _single_chunk_iter(),
            self.sample_rate,
            self.chunk_ms,
            input_format=self.audio_format or None,
        ):
            yield chunk

    def _extract_audio(self, resp: httpx.Response) -> bytes:
        try:
            payload = resp.json()
        except ValueError as exc:
            raise RuntimeError("MiniMax TTS response is not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("MiniMax TTS response is not a JSON object.")
        base_resp = payload.get("base_resp")
        if isinstance(base_resp, dict):
            status_code = base_resp.get("status_code")
            if status_code not in (None, 0):
                message = base_resp.get("status_msg") or base_resp.get("status_message") or "request failed"
                raise RuntimeError(f"MiniMax TTS failed ({status_code}): {message}")
        data = payload.get("data")
        audio = data.get("audio") if isinstance(data, dict) else None
        return _decode_audio_field(audio)
