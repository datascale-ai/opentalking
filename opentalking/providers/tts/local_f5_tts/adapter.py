from __future__ import annotations

import io
import os
import re
import wave
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from opentalking.core.types.frames import AudioChunk
from opentalking.providers.tts.voice_assets import LOCAL_F5_TTS_PROVIDER, resolve_voice_asset


def _settings_value(name: str, default: str = "") -> str:
    try:
        from opentalking.core.config import get_settings
        value = getattr(get_settings(), name, default)
        if value is not None and str(value).strip():
            return str(value).strip()
    except Exception:
        pass
    return default


def _local_audio_model_root() -> Path:
    raw = os.environ.get("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", "").strip()
    try:
        from opentalking.core.config import get_settings
        raw = raw or (get_settings().local_audio_model_root or "").strip()
    except Exception:
        pass
    return Path(raw or "./models/local-audio").expanduser().resolve()


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
        out.append(AudioChunk(data=part.astype(np.int16), sample_rate=sr, duration_ms=1000.0 * part.size / sr))
    return out


def _read_wav_bytes_i16(raw: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(raw), "rb") as wf:
        source_sr = int(wf.getframerate())
        channels = int(wf.getnchannels())
        sample_width = int(wf.getsampwidth())
        pcm_bytes = wf.readframes(wf.getnframes())
    if sample_width != 2:
        raise RuntimeError(f"Unsupported WAV sample width for local F5-TTS: {sample_width}")
    pcm = np.frombuffer(pcm_bytes, dtype="<i2").astype(np.int16, copy=False)
    if channels > 1:
        frame_count = pcm.size // channels
        pcm = pcm[: frame_count * channels].reshape(frame_count, channels).mean(axis=1).astype(np.int16)
    return pcm, source_sr


@dataclass(frozen=True)
class F5VoicePrompt:
    prompt_audio: Path
    prompt_text: str


class LocalF5TTSAdapter:
    def __init__(self, default_voice: str | None = None, sample_rate: int = 16000, chunk_ms: float = 20.0, *, model: str | None = None, model_dir: str | None = None, runtime_dir: str | None = None, ckpt_file: str | None = None, vocoder_local_path: str | None = None, service_url: str | None = None, prompt_audio: str | None = None, prompt_text: str | None = None, device: str = "auto") -> None:
        self.default_voice = default_voice or "local-default"
        self.sample_rate = sample_rate
        self.chunk_ms = chunk_ms
        self.model = (model or "SWivid/F5-TTS/F5TTS_v1_Base").strip()
        self.model_dir = str(Path(model_dir or _local_audio_model_root() / self.model.replace("/", "__")).expanduser())
        self.runtime_dir = str(Path(runtime_dir or _local_audio_model_root() / "runtime" / "F5-TTS").expanduser())
        self.ckpt_file = str(Path(ckpt_file or Path(self.model_dir) / "model_1250000.safetensors").expanduser())
        self.vocoder_local_path = str(Path(vocoder_local_path).expanduser()) if vocoder_local_path else ""
        self.service_url = (service_url or os.environ.get("OPENTALKING_TTS_LOCAL_F5_TTS_SERVICE_URL", "").strip() or _settings_value("tts_local_f5_tts_service_url", "")).strip()
        self.prompt_audio = str(Path(prompt_audio).expanduser()) if prompt_audio else ""
        self.prompt_text = (prompt_text or "").strip()
        self.device = device or "auto"

    async def synthesize_stream(self, text: str, voice: str | None = None) -> AsyncIterator[AudioChunk]:
        if not text.strip():
            return
        if not self.service_url:
            raise RuntimeError("Local F5-TTS requires OPENTALKING_TTS_LOCAL_F5_TTS_SERVICE_URL. Run scripts/quickstart/start_local_f5_tts.sh first.")
        async for chunk in self._synthesize_via_service(text, voice=voice):
            yield chunk

    def _resolve_voice_prompt(self, voice: str | None) -> F5VoicePrompt | None:
        voice_id = (voice or "").strip()
        if voice_id and voice_id != "local-default" and re.fullmatch(r"[A-Za-z0-9_-]{3,80}", voice_id):
            asset = resolve_voice_asset(voice_id, provider=LOCAL_F5_TTS_PROVIDER, sources=("clones", "system"), model_root=_local_audio_model_root(), require_prompt_text=False)
            if asset is not None:
                text = asset.prompt_text.read_text(encoding="utf-8").strip() if asset.prompt_text else ""
                return F5VoicePrompt(prompt_audio=asset.prompt_audio, prompt_text=text)
        if self.prompt_audio:
            return F5VoicePrompt(prompt_audio=Path(self.prompt_audio), prompt_text=self.prompt_text)
        return None

    async def _synthesize_via_service(self, text: str, voice: str | None = None) -> AsyncIterator[AudioChunk]:
        timeout = httpx.Timeout(connect=30.0, read=180.0, write=30.0, pool=30.0)
        payload: dict[str, Any] = {"text": text, "voice": voice or self.default_voice, "model": self.model, "sample_rate": self.sample_rate}
        prompt = self._resolve_voice_prompt(voice or self.default_voice)
        if prompt is not None:
            payload["prompt_audio"] = str(prompt.prompt_audio)
            payload["prompt_text"] = prompt.prompt_text
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
                    pcm, source_sr = _read_wav_bytes_i16(await resp.aread())
                    pcm = _resample_linear(pcm, source_sr, self.sample_rate)
                    for chunk in _split_pcm_chunks(pcm, self.sample_rate, self.chunk_ms):
                        yield chunk
                    return
                from opentalking.providers.tts.edge.adapter import _stream_decode_audio_to_pcm_chunks
                async def _audio_iter() -> AsyncIterator[bytes]:
                    async for data in resp.aiter_bytes():
                        if data:
                            yield data
                async for chunk in _stream_decode_audio_to_pcm_chunks(_audio_iter(), self.sample_rate, self.chunk_ms, input_format=input_format):
                    yield chunk
