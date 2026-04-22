from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from typing import AsyncIterator

import numpy as np

from opentalking.core.types.frames import AudioChunk

log = logging.getLogger(__name__)

_MODEL_LOCK = threading.Lock()
_MODEL_CACHE: dict[tuple[str, str], object] = {}
_ASR_LOCK = threading.Lock()
_ASR_CACHE: dict[str, object] = {}


def _ensure_cosyvoice_sys_path(repo_dir: Path) -> None:
    repo_str = str(repo_dir.resolve())
    matcha_str = str((repo_dir / "third_party" / "Matcha-TTS").resolve())
    for entry in (matcha_str, repo_str):
        if entry not in sys.path:
            sys.path.insert(0, entry)


def cosyvoice_runtime_available(repo_dir: Path) -> tuple[bool, Exception | None]:
    try:
        _ensure_cosyvoice_sys_path(repo_dir)
        from cosyvoice.cli.cosyvoice import AutoModel  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return False, exc
    return True, None


def _get_cosyvoice_runtime(model_dir: Path, repo_dir: Path):
    cache_key = (str(model_dir.resolve()), str(repo_dir.resolve()))
    runtime = _MODEL_CACHE.get(cache_key)
    if runtime is not None:
        return runtime

    with _MODEL_LOCK:
        runtime = _MODEL_CACHE.get(cache_key)
        if runtime is not None:
            return runtime
        _ensure_cosyvoice_sys_path(repo_dir)
        try:
            from cosyvoice.cli.cosyvoice import AutoModel
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "CosyVoice runtime is unavailable. Make sure the CosyVoice repo and its "
                "Python dependencies are installed."
            ) from exc

        runtime = AutoModel(
            model_dir=str(model_dir),
            load_trt=False,
            load_vllm=False,
            fp16=False,
        )
        _MODEL_CACHE[cache_key] = runtime
        return runtime


def _get_whisper_runtime(model_path: Path):
    cache_key = str(model_path.resolve())
    runtime = _ASR_CACHE.get(cache_key)
    if runtime is not None:
        return runtime

    with _ASR_LOCK:
        runtime = _ASR_CACHE.get(cache_key)
        if runtime is not None:
            return runtime
        try:
            import whisper
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "ASR prompt extraction requires openai-whisper. Install it or provide "
                "a manual CosyVoice prompt text."
            ) from exc
        if not model_path.is_file():
            raise RuntimeError(f"ASR model not found: {model_path}")
        runtime = whisper.load_model(str(model_path))
        _ASR_CACHE[cache_key] = runtime
        return runtime


def _cache_key_for_file(path: Path, max_seconds: float) -> str:
    stat = path.stat()
    payload = f"{path.resolve()}:{stat.st_mtime_ns}:{stat.st_size}:{max_seconds:.3f}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _resample_audio(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if audio.size == 0 or src_rate == dst_rate:
        return audio.astype(np.float32, copy=False)
    ratio = dst_rate / src_rate
    new_len = max(1, int(round(audio.shape[0] * ratio)))
    x_old = np.linspace(0.0, 1.0, num=audio.shape[0], endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=new_len, endpoint=False)
    return np.interp(x_new, x_old, audio).astype(np.float32, copy=False)


def _split_pcm_chunks(pcm: np.ndarray, sr: int, chunk_ms: float) -> list[AudioChunk]:
    samples_per_chunk = max(1, int(sr * (chunk_ms / 1000.0)))
    out: list[AudioChunk] = []
    for i in range(0, len(pcm), samples_per_chunk):
        part = pcm[i : i + samples_per_chunk]
        if part.size == 0:
            continue
        out.append(
            AudioChunk(
                data=part.astype(np.int16, copy=False),
                sample_rate=sr,
                duration_ms=1000.0 * part.size / sr,
            )
        )
    return out


class CosyVoiceAdapter:
    """Local CosyVoice adapter using zero-shot or instruct2 cloning."""

    _INTERNAL_EOP = "<|endofprompt|>"

    def __init__(
        self,
        *,
        model_dir: Path,
        repo_dir: Path,
        reference_audio: Path,
        mode: str,
        prompt_source: str,
        prompt_prefix: str,
        prompt_text: str,
        prompt_max_seconds: float = 20.0,
        sample_rate: int = 16000,
        chunk_ms: float = 20.0,
        speed: float = 1.0,
        asr_model_path: Path | None = None,
        asr_language: str = "zh",
        cache_dir: Path | None = None,
        ffmpeg_bin: str = "ffmpeg",
    ) -> None:
        self.model_dir = Path(model_dir).expanduser().resolve()
        self.repo_dir = Path(repo_dir).expanduser().resolve()
        self.reference_audio = Path(reference_audio).expanduser().resolve()
        self.mode = mode.strip().lower()
        self.prompt_source = prompt_source.strip().lower()
        self.prompt_prefix = prompt_prefix
        self.prompt_text = prompt_text
        self.prompt_max_seconds = max(1.0, float(prompt_max_seconds))
        self.sample_rate = sample_rate
        self.chunk_ms = chunk_ms
        self.speed = speed
        self.asr_model_path = (
            Path(asr_model_path).expanduser().resolve()
            if asr_model_path is not None
            else None
        )
        self.asr_language = asr_language.strip() or "zh"
        self.cache_dir = (
            Path(cache_dir).expanduser().resolve()
            if cache_dir is not None
            else Path(tempfile.gettempdir()) / "opentalking_tts_cache"
        )
        self.ffmpeg_bin = ffmpeg_bin

        if not self.model_dir.is_dir():
            raise RuntimeError(f"CosyVoice model dir not found: {self.model_dir}")
        if not self.repo_dir.is_dir():
            raise RuntimeError(f"CosyVoice repo dir not found: {self.repo_dir}")
        if not self.reference_audio.is_file():
            raise RuntimeError(f"CosyVoice reference audio not found: {self.reference_audio}")
        if self.mode not in {"zero_shot", "instruct2"}:
            raise RuntimeError(f"Unsupported CosyVoice mode: {self.mode}")
        if self.prompt_source not in {"manual", "asr"}:
            raise RuntimeError(f"Unsupported CosyVoice prompt source: {self.prompt_source}")
        if self.prompt_source == "asr" and self.asr_model_path is None:
            raise RuntimeError("CosyVoice ASR prompt source requires an ASR model path.")

    def _prepared_reference_audio(self, source_audio: Path) -> Path:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.cache_dir / f"cosyvoice_ref_{_cache_key_for_file(source_audio, self.prompt_max_seconds)}.wav"
        if out_path.is_file():
            return out_path
        subprocess.run(
            [
                self.ffmpeg_bin,
                "-y",
                "-i",
                str(source_audio),
                "-t",
                f"{self.prompt_max_seconds:.3f}",
                "-vn",
                "-acodec",
                "pcm_s16le",
                "-ac",
                "1",
                "-ar",
                "16000",
                str(out_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return out_path

    def _prepared_prompt_text(self, prompt_wav: Path) -> str:
        if self.prompt_source == "manual":
            return self.prompt_text

        assert self.asr_model_path is not None
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_key = _cache_key_for_file(prompt_wav, self.prompt_max_seconds)
        transcript_path = self.cache_dir / f"cosyvoice_asr_{cache_key}.json"
        if transcript_path.is_file():
            data = json.loads(transcript_path.read_text(encoding="utf-8"))
            transcript = str(data.get("text", "")).strip()
            if transcript:
                return f"{self.prompt_prefix}{transcript}"

        whisper_model = _get_whisper_runtime(self.asr_model_path)
        result = whisper_model.transcribe(
            str(prompt_wav),
            language=self.asr_language,
            fp16=False,
            verbose=False,
        )
        transcript = str(result.get("text", "")).strip()
        if not transcript:
            raise RuntimeError(
                "ASR did not return transcript text for the CosyVoice prompt audio. "
                f"Model: {self.asr_model_path}"
            )
        transcript_path.write_text(
            json.dumps(
                {
                    "prompt_wav": str(prompt_wav),
                    "asr_model_path": str(self.asr_model_path),
                    "language": self.asr_language,
                    "text": transcript,
                    "segments": result.get("segments", []),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return f"{self.prompt_prefix}{transcript}"

    @staticmethod
    def _runtime_model_name(runtime: object) -> str:
        return type(runtime).__name__

    def _prepare_runtime_inputs(
        self,
        *,
        runtime: object,
        text: str,
        prompt_text: str,
    ) -> tuple[str, str]:
        runtime_prompt_text = prompt_text
        runtime_text = text
        if self._runtime_model_name(runtime) == "CosyVoice3":
            has_eop = (self._INTERNAL_EOP in runtime_prompt_text) or (self._INTERNAL_EOP in runtime_text)
            if not has_eop:
                runtime_text = f"{self._INTERNAL_EOP}{runtime_text}"
        return runtime_text, runtime_prompt_text

    def _synthesize_pcm(self, text: str, reference_audio: Path | None = None) -> tuple[np.ndarray, int]:
        runtime = _get_cosyvoice_runtime(self.model_dir, self.repo_dir)
        prompt_wav = self._prepared_reference_audio(reference_audio or self.reference_audio)
        prompt_text = self._prepared_prompt_text(prompt_wav)
        runtime_text, runtime_prompt_text = self._prepare_runtime_inputs(
            runtime=runtime,
            text=text,
            prompt_text=prompt_text,
        )
        parts: list[np.ndarray] = []
        if self.mode == "zero_shot":
            generator = runtime.inference_zero_shot(
                runtime_text,
                runtime_prompt_text,
                str(prompt_wav),
                stream=False,
                speed=float(self.speed),
                text_frontend=True,
            )
        else:
            generator = runtime.inference_instruct2(
                runtime_text,
                runtime_prompt_text,
                str(prompt_wav),
                stream=False,
                speed=float(self.speed),
                text_frontend=True,
            )
        for item in generator:
            speech = item["tts_speech"].detach().cpu().numpy().reshape(-1).astype(np.float32, copy=False)
            if speech.size:
                parts.append(speech)
        if not parts:
            raise RuntimeError("CosyVoice generated no audio.")
        audio = np.concatenate(parts)
        audio = np.clip(audio, -1.0, 1.0)
        audio = _resample_audio(audio, int(runtime.sample_rate), self.sample_rate)
        pcm = (audio * 32767.0).astype(np.int16)
        return pcm, self.sample_rate

    async def synthesize_stream(
        self,
        text: str,
        voice: str | None = None,
    ) -> AsyncIterator[AudioChunk]:
        if not text.strip():
            return
        reference_audio: Path | None = None
        if voice:
            candidate = Path(voice).expanduser()
            if candidate.is_file():
                reference_audio = candidate.resolve()
        pcm, sample_rate = await asyncio.to_thread(
            self._synthesize_pcm,
            text.strip(),
            reference_audio,
        )
        for chunk in _split_pcm_chunks(pcm, sample_rate, self.chunk_ms):
            yield chunk
