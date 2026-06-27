from __future__ import annotations

import io
import wave
from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx
import numpy as np

from opentalking.core.types.frames import AudioChunk
from opentalking.providers.tts.indextts_config import normalize_indextts_config


def _audio_format_from_content_type(content_type: str | None) -> str | None:
    value = (content_type or "").split(";", 1)[0].strip().lower()
    if value in {"audio/wav", "audio/wave", "audio/x-wav"}:
        return "wav"
    if value in {"audio/l16", "audio/pcm", "application/octet-stream"}:
        return "pcm"
    if value in {"audio/mpeg", "audio/mp3"}:
        return "mp3"
    return None


def _source_sample_rate_from_headers(headers: Any, fallback: int) -> int:
    direct = str(headers.get("x-audio-sample-rate", "") or "").strip()
    if direct.isdigit():
        return int(direct)
    content_type = str(headers.get("content-type", "") or "")
    for part in content_type.split(";")[1:]:
        key, sep, value = part.strip().partition("=")
        if sep and key.strip().lower() == "rate" and value.strip().isdigit():
            return int(value.strip())
    return fallback


def _resample_linear(pcm: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    pcm = np.asarray(pcm, dtype=np.int16).reshape(-1)
    if pcm.size == 0 or src_sr == dst_sr:
        return pcm.copy()
    pcm_f = pcm.astype(np.float32) / 32768.0
    n_dst = max(1, int(round(pcm.size * dst_sr / src_sr)))
    xi = np.linspace(0.0, pcm.size - 1.0, num=n_dst)
    out = np.interp(xi, np.arange(pcm.size), pcm_f)
    return np.clip(np.round(out * 32768.0), -32768, 32767).astype(np.int16)


def _split_pcm_chunks(pcm: np.ndarray, sr: int, chunk_ms: float) -> list[AudioChunk]:
    samples_per_chunk = max(1, int(sr * (chunk_ms / 1000.0)))
    out: list[AudioChunk] = []
    for i in range(0, len(pcm), samples_per_chunk):
        part = pcm[i : i + samples_per_chunk]
        if part.size == 0:
            continue
        out.append(
            AudioChunk(
                data=part.astype(np.int16),
                sample_rate=sr,
                duration_ms=1000.0 * part.size / sr,
            )
        )
    return out


def _read_wav_i16(raw: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(raw), "rb") as wf:
        source_sr = int(wf.getframerate())
        channels = int(wf.getnchannels())
        sample_width = int(wf.getsampwidth())
        pcm_bytes = wf.readframes(wf.getnframes())
    if sample_width != 2:
        raise RuntimeError(f"Unsupported WAV sample width for OmniRT IndexTTS: {sample_width}")
    pcm = np.frombuffer(pcm_bytes, dtype="<i2").astype(np.int16, copy=False)
    if channels > 1:
        frame_count = pcm.size // channels
        pcm = pcm[: frame_count * channels].reshape(frame_count, channels).mean(axis=1).astype(np.int16)
    return pcm, source_sr


class OmniRTIndexTTSAdapter:
    """HTTP stream client for OmniRT IndexTTS text2audio service."""

    def __init__(
        self,
        *,
        service_url: str,
        default_voice: str | None = None,
        sample_rate: int = 16000,
        chunk_ms: float = 20.0,
        model: str | None = None,
        streaming: bool = True,
        streaming_mode: str = "token_window",
        max_text_tokens_per_segment: int = 80,
        quick_streaming_tokens: int = 4,
        interval_silence_ms: int = 0,
        token_window_size: int = 40,
        token_window_hop: int = 96,
        token_window_context: int = 8,
        token_window_overlap_ms: int = 60,
        indextts_config: Mapping[str, object] | None = None,
    ) -> None:
        self.service_url = service_url.rstrip("/") if service_url else ""
        self.default_voice = default_voice or "local-default"
        self.sample_rate = sample_rate
        self.chunk_ms = chunk_ms
        self.model = (model or "IndexTeam/IndexTTS-2").strip()
        self.streaming = bool(streaming)
        self.streaming_mode = (streaming_mode or "token_window").strip()
        self.max_text_tokens_per_segment = int(max_text_tokens_per_segment)
        self.quick_streaming_tokens = int(quick_streaming_tokens)
        self.interval_silence_ms = int(interval_silence_ms)
        self.token_window_size = int(token_window_size)
        self.token_window_hop = int(token_window_hop)
        self.token_window_context = int(token_window_context)
        self.token_window_overlap_ms = int(token_window_overlap_ms)
        self.indextts_config = normalize_indextts_config(indextts_config)

    async def synthesize_stream(self, text: str, voice: str | None = None) -> AsyncIterator[AudioChunk]:
        if not text.strip():
            return
        if not self.service_url:
            raise RuntimeError(
                "OmniRT IndexTTS service URL is not configured. "
                "Set OPENTALKING_TTS_OMNIRT_INDEXTTS_SERVICE_URL."
            )
        timeout = httpx.Timeout(connect=30.0, read=180.0, write=30.0, pool=30.0)
        payload = {
            "text": text,
            "voice": voice or self.default_voice,
            "model": self.model,
            "sample_rate": self.sample_rate,
            "streaming": self.streaming,
            "streaming_mode": self.streaming_mode,
            "max_text_tokens_per_segment": self.max_text_tokens_per_segment,
            "quick_streaming_tokens": self.quick_streaming_tokens,
            "interval_silence_ms": self.interval_silence_ms,
            "token_window_size": self.token_window_size,
            "token_window_hop": self.token_window_hop,
            "token_window_context": self.token_window_context,
            "token_window_overlap_ms": self.token_window_overlap_ms,
        }
        payload.update(self.indextts_config)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", self.service_url, json=payload) as resp:
                resp.raise_for_status()
                input_format = _audio_format_from_content_type(resp.headers.get("content-type"))
                if input_format == "pcm":
                    source_sr = _source_sample_rate_from_headers(resp.headers, self.sample_rate)
                    pending = b""
                    async for data in resp.aiter_bytes():
                        if not data:
                            continue
                        data = pending + data
                        if len(data) % 2:
                            pending = data[-1:]
                            data = data[:-1]
                        else:
                            pending = b""
                        if not data:
                            continue
                        pcm = np.frombuffer(data, dtype="<i2").astype(np.int16, copy=False)
                        pcm = _resample_linear(pcm, source_sr, self.sample_rate)
                        for chunk in _split_pcm_chunks(pcm, self.sample_rate, self.chunk_ms):
                            yield chunk
                    return
                if input_format == "wav":
                    pcm, source_sr = _read_wav_i16(await resp.aread())
                    pcm = _resample_linear(pcm, source_sr, self.sample_rate)
                    for chunk in _split_pcm_chunks(pcm, self.sample_rate, self.chunk_ms):
                        yield chunk
                    return

                from opentalking.providers.tts.edge.adapter import _stream_decode_audio_to_pcm_chunks

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
