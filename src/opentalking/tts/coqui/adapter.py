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
import soundfile as sf

from opentalking.core.types.frames import AudioChunk

log = logging.getLogger(__name__)

_MODEL_LOCK = threading.Lock()
_MODEL_CACHE: dict[tuple[str, str], object] = {}
_TORCHAUDIO_PATCH_LOCK = threading.Lock()
_TORCHAUDIO_PATCHED = False
_WARMUP_LOCK = threading.Lock()
_WARMED_KEYS: set[str] = set()
_WORKER_CACHE_LOCK = threading.Lock()
_WORKER_CACHE: dict[tuple[str, str, str], "_XTTSSubprocessWorker"] = {}


def _resolve_xtts_source(model_name: str) -> tuple[str, str | None]:
    candidate = Path(model_name).expanduser()
    if candidate.is_dir():
        config_path = candidate / "config.json"
        model_path = candidate / "model.pth"
        if not config_path.is_file() or not model_path.is_file():
            raise RuntimeError(
                "Local XTTS model directory must contain config.json and model.pth: "
                f"{candidate}"
            )
        return str(candidate.resolve()), str(config_path.resolve())
    return model_name, None


def _normalize_device(device: str) -> str:
    raw = device.strip().lower()
    if raw != "auto":
        return raw
    try:
        import torch
    except ImportError:
        return "cpu"
    return "cuda" if torch.cuda.is_available() else "cpu"


def _get_xtts_runtime(model_name: str, device: str):
    model_source, config_path = _resolve_xtts_source(model_name)
    cache_key = (model_source, device)
    runtime = _MODEL_CACHE.get(cache_key)
    if runtime is not None:
        return runtime

    with _MODEL_LOCK:
        runtime = _MODEL_CACHE.get(cache_key)
        if runtime is not None:
            return runtime
        _ensure_xtts_runtime_compat()
        try:
            from TTS.api import TTS
        except ImportError as exc:
            raise RuntimeError(
                "XTTS voice cloning requires the optional package 'coqui-tts'. "
                "Install it with `pip install coqui-tts 'transformers<5,>=4.46'`."
            ) from exc

        gpu = device.startswith("cuda")
        try:
            if config_path is None:
                runtime = TTS(model_name=model_source, progress_bar=False, gpu=gpu)
            else:
                runtime = TTS(
                    model_path=model_source,
                    config_path=config_path,
                    progress_bar=False,
                    gpu=gpu,
                )
        except EOFError as exc:
            raise RuntimeError(
                "XTTS model download requires accepting Coqui's CPML terms. "
                "If you have agreed to the license, rerun with COQUI_TOS_AGREED=1."
            ) from exc
        if hasattr(runtime, "to"):
            moved = runtime.to(device)
            if moved is not None:
                runtime = moved
        _MODEL_CACHE[cache_key] = runtime
        return runtime


def _ensure_xtts_runtime_compat() -> None:
    # XTTS checkpoints in common local installs still rely on the pre-2.6 torch.load behavior.
    os.environ.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")
    _patch_torchaudio_load_if_needed()


def _patch_torchaudio_load_if_needed() -> None:
    global _TORCHAUDIO_PATCHED
    if _TORCHAUDIO_PATCHED:
        return

    with _TORCHAUDIO_PATCH_LOCK:
        if _TORCHAUDIO_PATCHED:
            return
        try:
            import torchaudio
        except Exception as exc:  # noqa: BLE001
            log.debug("torchaudio unavailable for XTTS compatibility patch: %s", exc)
            _TORCHAUDIO_PATCHED = True
            return

        try:
            from torchcodec.decoders import AudioDecoder  # noqa: F401
            _TORCHAUDIO_PATCHED = True
            return
        except Exception:  # noqa: BLE001
            pass

        def _soundfile_load(path, *args, **kwargs):
            import torch

            data, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
            audio = torch.from_numpy(np.asarray(data.T, dtype=np.float32))
            return audio, int(sample_rate)

        torchaudio.load = _soundfile_load
        log.info("patched torchaudio.load with soundfile fallback for XTTS runtime")
        _TORCHAUDIO_PATCHED = True


def xtts_runtime_available() -> tuple[bool, Exception | None]:
    try:
        from TTS.api import TTS  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return False, exc
    return True, None


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


def _cache_key_for_file(path: Path) -> str:
    stat = path.stat()
    payload = f"{path.resolve()}:{stat.st_mtime_ns}:{stat.st_size}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _worker_script_path() -> Path:
    return Path(__file__).resolve().parents[4] / "scripts" / "xtts_worker.py"


class _XTTSSubprocessWorker:
    def __init__(self, *, python_bin: Path, model_name: str, device: str) -> None:
        self.python_bin = python_bin
        self.model_name = model_name
        self.device = device
        self._proc: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._start_lock = asyncio.Lock()
        self._request_lock = asyncio.Lock()

    async def _ensure_started(self) -> None:
        proc = self._proc
        if proc is not None and proc.returncode is None:
            return

        async with self._start_lock:
            proc = self._proc
            if proc is not None and proc.returncode is None:
                return

            script_path = _worker_script_path()
            if not script_path.is_file():
                raise RuntimeError(f"XTTS worker script not found: {script_path}")

            env = os.environ.copy()
            env.setdefault("PYTHONUNBUFFERED", "1")
            lib_dir = str(self.python_bin.parent.parent / "lib")
            current_ld = env.get("LD_LIBRARY_PATH", "")
            env["LD_LIBRARY_PATH"] = (
                f"{lib_dir}:{current_ld}" if current_ld else lib_dir
            )
            self._proc = await asyncio.create_subprocess_exec(
                str(self.python_bin),
                str(script_path),
                "--model-name",
                self.model_name,
                "--device",
                self.device,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            self._stderr_task = asyncio.create_task(self._pump_stderr())

    async def _pump_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            while True:
                line = await proc.stderr.readline()
                if not line:
                    break
                log.info("[xtts-worker] %s", line.decode("utf-8", errors="ignore").rstrip())
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("XTTS worker stderr pump failed", exc_info=True)

    async def request(self, payload: dict[str, object]) -> dict[str, object]:
        await self._ensure_started()
        proc = self._proc
        if proc is None or proc.stdin is None or proc.stdout is None:
            raise RuntimeError("XTTS worker failed to start")

        async with self._request_lock:
            if proc.returncode is not None:
                raise RuntimeError(f"XTTS worker exited with code {proc.returncode}")

            proc.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
            await proc.stdin.drain()

            response: dict[str, object] | None = None
            while response is None:
                raw = await proc.stdout.readline()
                if not raw:
                    raise RuntimeError("XTTS worker closed stdout unexpectedly")
                line = raw.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                try:
                    candidate = json.loads(line)
                except json.JSONDecodeError:
                    log.warning("Ignoring non-JSON XTTS worker stdout: %s", line[:200])
                    continue
                if not isinstance(candidate, dict):
                    log.warning("Ignoring malformed XTTS worker response: %r", candidate)
                    continue
                response = candidate
            if response.get("status") != "ok":
                raise RuntimeError(str(response.get("message", "XTTS worker request failed")))
            return response


def _get_xtts_worker(python_bin: Path, model_name: str, device: str) -> _XTTSSubprocessWorker:
    cache_key = (str(python_bin.resolve()), model_name, device)
    worker = _WORKER_CACHE.get(cache_key)
    if worker is not None:
        return worker
    with _WORKER_CACHE_LOCK:
        worker = _WORKER_CACHE.get(cache_key)
        if worker is not None:
            return worker
        worker = _XTTSSubprocessWorker(
            python_bin=python_bin,
            model_name=model_name,
            device=device,
        )
        _WORKER_CACHE[cache_key] = worker
        return worker


class CoquiXTTSAdapter:
    """Local XTTS adapter with reference-audio voice cloning."""

    def __init__(
        self,
        *,
        model_name: str,
        language: str,
        reference_audio: Path,
        sample_rate: int = 16000,
        chunk_ms: float = 20.0,
        device: str = "auto",
        cache_dir: Path | None = None,
        ffmpeg_bin: str = "ffmpeg",
        python_bin: str = "",
    ) -> None:
        self.model_name = model_name
        self.language = language
        self.reference_audio = Path(reference_audio).expanduser().resolve()
        self.sample_rate = sample_rate
        self.chunk_ms = chunk_ms
        self.python_bin = Path(python_bin).expanduser().resolve() if python_bin.strip() else None
        self.device = device.strip().lower() if self.python_bin is not None else _normalize_device(device)
        self.cache_dir = (
            Path(cache_dir).expanduser().resolve()
            if cache_dir is not None
            else Path(tempfile.gettempdir()) / "opentalking_tts_cache"
        )
        self.ffmpeg_bin = ffmpeg_bin

        if not self.reference_audio.is_file():
            raise RuntimeError(f"Voice clone reference audio not found: {self.reference_audio}")
        if self.python_bin is not None and not self.python_bin.is_file():
            raise RuntimeError(f"XTTS python interpreter not found: {self.python_bin}")

    def _prepared_reference_audio(self) -> Path:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.cache_dir / f"ref_{_cache_key_for_file(self.reference_audio)}.wav"
        if out_path.is_file():
            return out_path
        subprocess.run(
            [
                self.ffmpeg_bin,
                "-y",
                "-i",
                str(self.reference_audio),
                "-vn",
                "-acodec",
                "pcm_s16le",
                "-ac",
                "1",
                "-ar",
                "24000",
                str(out_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return out_path

    def _synthesize_pcm(self, text: str, reference_audio: Path | None = None) -> tuple[np.ndarray, int]:
        runtime = _get_xtts_runtime(self.model_name, self.device)
        prepared_reference_audio = reference_audio or self._prepared_reference_audio()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            out_path = Path(tmp.name)
        try:
            runtime.tts_to_file(
                text=text,
                language=self.language,
                speaker_wav=str(prepared_reference_audio),
                file_path=str(out_path),
                split_sentences=True,
            )
            audio, sample_rate = sf.read(str(out_path), dtype="float32")
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(out_path)

        if isinstance(audio, np.ndarray) and audio.ndim > 1:
            audio = audio.mean(axis=1)
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        audio = np.clip(audio, -1.0, 1.0)
        audio = _resample_audio(audio, int(sample_rate), self.sample_rate)
        pcm = (audio * 32767.0).astype(np.int16)
        return pcm, self.sample_rate

    async def _synthesize_pcm_external(
        self,
        text: str,
        reference_audio: Path | None = None,
    ) -> tuple[np.ndarray, int]:
        if self.python_bin is None:
            raise RuntimeError("XTTS external worker requested without python interpreter")
        prepared_reference_audio = reference_audio or self._prepared_reference_audio()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            out_path = Path(tmp.name)
        try:
            worker = _get_xtts_worker(self.python_bin, self.model_name, self.device)
            await worker.request(
                {
                    "cmd": "synthesize",
                    "text": text,
                    "language": self.language,
                    "reference_audio": str(prepared_reference_audio),
                    "output_path": str(out_path),
                }
            )
            audio, sample_rate = sf.read(str(out_path), dtype="float32")
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(out_path)

        if isinstance(audio, np.ndarray) and audio.ndim > 1:
            audio = audio.mean(axis=1)
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        audio = np.clip(audio, -1.0, 1.0)
        audio = _resample_audio(audio, int(sample_rate), self.sample_rate)
        pcm = (audio * 32767.0).astype(np.int16)
        return pcm, self.sample_rate

    def _warmup_key(self, prepared_reference_audio: Path) -> str:
        return "|".join(
            [
                str(self.python_bin) if self.python_bin is not None else "inproc",
                self.model_name,
                self.device,
                self.language,
                str(self.sample_rate),
                _cache_key_for_file(prepared_reference_audio),
            ]
        )

    def _warmup_sync(self, text: str) -> None:
        prepared_reference_audio = self._prepared_reference_audio()
        key = self._warmup_key(prepared_reference_audio)
        with _WARMUP_LOCK:
            if key in _WARMED_KEYS:
                return
        # Run one tiny synthesis end-to-end so model load, CUDA kernels and
        # reference-audio conditioning are paid during session startup.
        self._synthesize_pcm(text, prepared_reference_audio)
        with _WARMUP_LOCK:
            _WARMED_KEYS.add(key)

    async def warmup(self, text: str = "你好") -> None:
        warmup_text = text.strip() or "你好"
        if self.python_bin is not None:
            prepared_reference_audio = self._prepared_reference_audio()
            key = self._warmup_key(prepared_reference_audio)
            with _WARMUP_LOCK:
                if key in _WARMED_KEYS:
                    return
            worker = _get_xtts_worker(self.python_bin, self.model_name, self.device)
            await worker.request(
                {
                    "cmd": "warmup",
                    "text": warmup_text,
                    "language": self.language,
                    "reference_audio": str(prepared_reference_audio),
                }
            )
            with _WARMUP_LOCK:
                _WARMED_KEYS.add(key)
            return
        await asyncio.to_thread(self._warmup_sync, warmup_text)

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
        if self.python_bin is not None:
            pcm, sample_rate = await self._synthesize_pcm_external(text.strip(), reference_audio)
        else:
            pcm, sample_rate = await asyncio.to_thread(
                self._synthesize_pcm,
                text.strip(),
                reference_audio,
            )
        for chunk in _split_pcm_chunks(pcm, sample_rate, self.chunk_ms):
            yield chunk
