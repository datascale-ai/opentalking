from __future__ import annotations

import base64
import io
from typing import Any, AsyncIterator
import wave

import httpx
import numpy as np

from opentalking.core.types.frames import AudioChunk
from opentalking.providers.tts.edge.adapter import _stream_decode_audio_to_pcm_chunks


def _split_pcm_chunks(pcm: np.ndarray, sr: int, chunk_ms: float) -> list[AudioChunk]:
    samples_per_chunk = max(1, int(sr * (chunk_ms / 1000.0)))
    chunks: list[AudioChunk] = []
    for start in range(0, len(pcm), samples_per_chunk):
        part = pcm[start : start + samples_per_chunk]
        if part.size == 0:
            continue
        chunks.append(
            AudioChunk(
                data=part.astype(np.int16),
                sample_rate=sr,
                duration_ms=1000.0 * part.size / sr,
            )
        )
    return chunks


def _resample_if_needed(audio: np.ndarray, in_sr: int, out_sr: int) -> np.ndarray:
    if in_sr == out_sr or audio.size == 0:
        return audio.astype(np.int16, copy=False)
    n_dst = max(1, int(round(audio.size * out_sr / in_sr)))
    x_old = np.linspace(0.0, audio.size - 1.0, num=audio.size)
    x_new = np.linspace(0.0, audio.size - 1.0, num=n_dst)
    return np.interp(x_new, x_old, audio.astype(np.float32)).astype(np.int16)


def _decode_wav_to_pcm16_mono(data: bytes, target_sr: int) -> np.ndarray:
    with wave.open(io.BytesIO(data), "rb") as wf:
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sr = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    if sample_width != 2:
        raise RuntimeError(f"OpenAI-compatible TTS WAV must be 16-bit PCM, got sample width {sample_width}.")
    pcm = np.frombuffer(raw, dtype="<i2").copy()
    if channels > 1 and pcm.size:
        pcm = pcm.reshape(-1, channels).mean(axis=1).astype(np.int16)
    return _resample_if_needed(pcm, sr, target_sr)


class OpenAICompatibleTTSAdapter:
    """OpenAI Audio Speech compatible TTS adapter."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        default_voice: str,
        response_format: str = "wav",
        protocol: str = "audio_speech",
        prompt: str = "",
        sample_rate: int = 16000,
        chunk_ms: float = 20.0,
    ) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.model = model.strip()
        self.default_voice = default_voice.strip() or "default"
        self.response_format = (response_format or "wav").strip().lower()
        self.protocol = (protocol or "audio_speech").strip().lower()
        self.prompt = prompt.strip()
        self.sample_rate = sample_rate
        self.chunk_ms = chunk_ms

    async def synthesize_stream(self, text: str, voice: str | None = None) -> AsyncIterator[AudioChunk]:
        if not self.api_key:
            raise RuntimeError("OpenAI-compatible TTS selected but OPENTALKING_TTS_OPENAI_API_KEY is empty.")
        if not self.base_url:
            raise RuntimeError("OpenAI-compatible TTS selected but OPENTALKING_TTS_OPENAI_BASE_URL is empty.")
        if not self.model:
            raise RuntimeError("OpenAI-compatible TTS selected but OPENTALKING_TTS_OPENAI_MODEL is empty.")

        effective_voice = (voice or self.default_voice).strip() or "default"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(connect=30.0, read=180.0, write=30.0, pool=30.0)

        async with httpx.AsyncClient(timeout=timeout) as client:
            if self.protocol in {"chat_completions", "chat"}:
                payload: dict[str, Any] = {
                    "model": self.model,
                    "messages": [
                        {"role": "user", "content": self.prompt or "请用自然、清晰的中文朗读。"},
                        {"role": "assistant", "content": text},
                    ],
                    "audio": {"format": self.response_format or "wav", "voice": effective_voice},
                }
                resp = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
                try:
                    resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise RuntimeError(
                        f"OpenAI-compatible TTS failed ({exc.response.status_code}): {resp.text.strip()}"
                    ) from exc
                data = self._extract_chat_audio(resp)
            else:
                payload = {
                    "model": self.model,
                    "input": text,
                    "voice": effective_voice,
                    "response_format": self.response_format,
                }
                url = f"{self.base_url}/audio/speech"
                if self.response_format == "pcm":
                    async with client.stream("POST", url, headers=headers, json=payload) as resp:
                        try:
                            resp.raise_for_status()
                        except httpx.HTTPStatusError as exc:
                            detail = await resp.aread()
                            raise RuntimeError(
                                f"OpenAI-compatible TTS failed ({exc.response.status_code}): "
                                f"{detail.decode('utf-8', errors='ignore').strip()}"
                            ) from exc
                        chunk_bytes = max(2, int(self.sample_rate * (self.chunk_ms / 1000.0)) * 2)
                        if chunk_bytes % 2:
                            chunk_bytes += 1
                        buf = bytearray()
                        async for part in resp.aiter_bytes():
                            if not part:
                                continue
                            buf.extend(part)
                            while len(buf) >= chunk_bytes:
                                pcm = np.frombuffer(bytes(buf[:chunk_bytes]), dtype="<i2").copy()
                                del buf[:chunk_bytes]
                                yield AudioChunk(
                                    data=pcm,
                                    sample_rate=self.sample_rate,
                                    duration_ms=1000.0 * pcm.size / self.sample_rate,
                                )
                        if len(buf) % 2:
                            buf = buf[:-1]
                        if buf:
                            pcm = np.frombuffer(bytes(buf), dtype="<i2").copy()
                            yield AudioChunk(
                                data=pcm,
                                sample_rate=self.sample_rate,
                                duration_ms=1000.0 * pcm.size / self.sample_rate,
                            )
                    return

                resp = await client.post(url, headers=headers, json=payload)
                try:
                    resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise RuntimeError(
                        f"OpenAI-compatible TTS failed ({exc.response.status_code}): {resp.text.strip()}"
                    ) from exc
                data = resp.content

        if self.response_format == "wav":
            pcm = _decode_wav_to_pcm16_mono(data, self.sample_rate)
            for chunk in _split_pcm_chunks(pcm, self.sample_rate, self.chunk_ms):
                yield chunk
            return

        async def _single_chunk_iter() -> AsyncIterator[bytes]:
            yield data

        async for chunk in _stream_decode_audio_to_pcm_chunks(
            _single_chunk_iter(),
            self.sample_rate,
            self.chunk_ms,
            input_format=self.response_format or None,
        ):
            yield chunk

# keep method definition close to class for simple import-time behavior
def _extract_chat_audio_from_payload(payload: Any) -> bytes:
    if not isinstance(payload, dict):
        raise RuntimeError("OpenAI-compatible TTS chat response is not a JSON object.")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("OpenAI-compatible TTS chat response has no choices.")
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else None
    audio = message.get("audio") if isinstance(message, dict) else None
    if not isinstance(audio, dict):
        raise RuntimeError("OpenAI-compatible TTS chat response has no message.audio.")
    data = audio.get("data")
    if not isinstance(data, str) or not data.strip():
        raise RuntimeError("OpenAI-compatible TTS chat response has no message.audio.data.")
    raw = data.strip()
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    return base64.b64decode(raw)

def _tts_extract_chat_audio(self: OpenAICompatibleTTSAdapter, resp: httpx.Response) -> bytes:
    try:
        return _extract_chat_audio_from_payload(resp.json())
    except ValueError as exc:
        raise RuntimeError("OpenAI-compatible TTS chat response is not valid JSON.") from exc

OpenAICompatibleTTSAdapter._extract_chat_audio = _tts_extract_chat_audio
