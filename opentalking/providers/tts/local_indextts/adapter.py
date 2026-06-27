from __future__ import annotations

import asyncio
import io
import importlib
import os
import re
import tempfile
import threading
import wave
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any

import numpy as np
import httpx

from opentalking.core.types.frames import AudioChunk
from opentalking.providers.tts.indextts_config import indextts_infer_kwargs, normalize_indextts_config
from opentalking.providers.tts.voice_assets import INDEXTTS_PROVIDER, resolve_voice_asset


_ENGINE_CACHE_LOCK = threading.Lock()
_ENGINE_CACHE: dict[tuple[object, ...], tuple[Any, threading.Lock]] = {}


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


def _local_audio_model_root() -> Path:
    raw = os.environ.get("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", "").strip()
    try:
        from opentalking.core.config import get_settings

        raw = raw or (get_settings().local_audio_model_root or "").strip()
    except Exception:
        pass
    return Path(raw or "./models/local-audio").expanduser().resolve()


def _bundled_system_voice_root() -> Path:
    return Path(__file__).resolve().parents[3] / "assets" / "voices" / "system"


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


def _read_wav_handle_i16(wf: wave.Wave_read) -> tuple[np.ndarray, int]:
    source_sr = int(wf.getframerate())
    channels = int(wf.getnchannels())
    sample_width = int(wf.getsampwidth())
    pcm_bytes = wf.readframes(wf.getnframes())
    if sample_width != 2:
        raise RuntimeError(f"Unsupported WAV sample width for local IndexTTS: {sample_width}")
    pcm = np.frombuffer(pcm_bytes, dtype="<i2").astype(np.int16, copy=False)
    if channels > 1:
        frame_count = pcm.size // channels
        pcm = pcm[: frame_count * channels].reshape(frame_count, channels).mean(axis=1).astype(np.int16)
    return pcm, source_sr


def _read_wav_i16(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wf:
        return _read_wav_handle_i16(wf)


def _read_wav_bytes_i16(raw: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(raw), "rb") as wf:
        return _read_wav_handle_i16(wf)


def _write_wav_i16(path: str | Path, data: np.ndarray, sample_rate: int) -> None:
    pcm = np.asarray(data)
    if pcm.ndim == 2 and pcm.shape[0] == 1:
        pcm = pcm[0]
    elif pcm.ndim == 2:
        pcm = pcm.T.reshape(-1)
    if np.issubdtype(pcm.dtype, np.floating):
        pcm = np.clip(pcm, -1.0, 1.0)
        pcm = np.round(pcm * 32767.0).astype("<i2")
    else:
        pcm = np.clip(pcm, -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(pcm.reshape(-1).tobytes())


class LocalIndexTTSAdapter:
    """In-process IndexTTS2 adapter for OpenTalking local TTS mode."""

    def __init__(
        self,
        default_voice: str | None = None,
        sample_rate: int = 16000,
        chunk_ms: float = 20.0,
        *,
        model: str | None = None,
        model_dir: str | None = None,
        cfg_path: str | None = None,
        service_url: str | None = None,
        prompt_audio: str | None = None,
        w2v_bert_dir: str | None = None,
        maskgct_dir: str | None = None,
        campplus_dir: str | None = None,
        bigvgan_dir: str | None = None,
        device: str = "auto",
        use_fp16: bool | None = None,
        use_cuda_kernel: bool = False,
        use_deepspeed: bool = False,
        indextts_config: Mapping[str, object] | None = None,
    ) -> None:
        self.default_voice = default_voice or "local-default"
        self.sample_rate = sample_rate
        self.chunk_ms = chunk_ms
        self.model = (model or "IndexTeam/IndexTTS-2").strip()
        self.model_dir = str(Path(model_dir or f"./models/local-audio/{self.model.replace('/', '__')}").expanduser())
        self.cfg_path = str(Path(cfg_path or Path(self.model_dir) / "config.yaml").expanduser())
        self.service_url = (service_url or "").strip().rstrip("/")
        self.prompt_audio = str(Path(prompt_audio).expanduser()) if prompt_audio else ""
        self.w2v_bert_dir = str(Path(w2v_bert_dir).expanduser()) if w2v_bert_dir else ""
        self.maskgct_dir = str(Path(maskgct_dir).expanduser()) if maskgct_dir else ""
        self.campplus_dir = str(Path(campplus_dir).expanduser()) if campplus_dir else ""
        self.bigvgan_dir = str(Path(bigvgan_dir).expanduser()) if bigvgan_dir else ""
        self.device = device or "auto"
        self.use_fp16 = bool(self.device.startswith("cuda")) if use_fp16 is None else bool(use_fp16)
        self.use_cuda_kernel = bool(use_cuda_kernel)
        self.use_deepspeed = bool(use_deepspeed)
        self.indextts_config = normalize_indextts_config(indextts_config)

    async def synthesize_stream(self, text: str, voice: str | None = None) -> AsyncIterator[AudioChunk]:
        if not text.strip():
            return
        if self.service_url:
            async for chunk in self._synthesize_via_service(text, voice=voice):
                yield chunk
            return
        chunks = await asyncio.to_thread(self._synthesize_in_process, text, voice)
        for chunk in chunks:
            yield chunk

    async def _synthesize_via_service(self, text: str, voice: str | None = None) -> AsyncIterator[AudioChunk]:
        timeout = httpx.Timeout(connect=30.0, read=180.0, write=30.0, pool=30.0)
        payload: dict[str, Any] = {
            "text": text,
            "voice": voice or self.default_voice,
            "model": self.model,
            "sample_rate": self.sample_rate,
        }
        payload.update(self.indextts_config)
        prompt = self._resolve_voice_prompt(voice or self.default_voice)
        if prompt is not None:
            payload["prompt_audio"] = str(prompt)
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

                async for chunk in _stream_decode_audio_to_pcm_chunks(
                    _audio_iter(),
                    self.sample_rate,
                    self.chunk_ms,
                    input_format=input_format,
                ):
                    yield chunk

    def _resolve_voice_prompt(self, voice: str | None) -> Path | None:
        voice_id = (voice or "").strip()
        if voice_id and re.fullmatch(r"[A-Za-z0-9_-]{3,80}", voice_id):
            asset = resolve_voice_asset(
                voice_id,
                provider=INDEXTTS_PROVIDER,
                sources=("clones", "system"),
                model_root=_local_audio_model_root(),
            )
            if asset is not None:
                return asset.prompt_audio
        if self.prompt_audio:
            return Path(self.prompt_audio)
        return None

    def _engine_cache_key(self) -> tuple[object, ...]:
        return (
            str(Path(self.model_dir).expanduser().resolve()),
            str(Path(self.cfg_path).expanduser().resolve()),
            self.device,
            self.use_fp16,
            self.use_cuda_kernel,
            self.use_deepspeed,
            str(Path(self.w2v_bert_dir).expanduser().resolve()) if self.w2v_bert_dir else "",
            str(Path(self.maskgct_dir).expanduser().resolve()) if self.maskgct_dir else "",
            str(Path(self.campplus_dir).expanduser().resolve()) if self.campplus_dir else "",
            str(Path(self.bigvgan_dir).expanduser().resolve()) if self.bigvgan_dir else "",
        )

    def _create_engine(self) -> Any:
        try:
            module = importlib.import_module("indextts.infer_v2")
        except ImportError as exc:
            if exc.name and not exc.name.startswith("indextts"):
                raise RuntimeError(f"Local IndexTTS runtime dependency is missing: {exc.name}") from exc
            raise RuntimeError(
                "Local IndexTTS requires the index-tts Python package. "
                "Run the documented local IndexTTS sidecar and set OPENTALKING_TTS_LOCAL_INDEXTTS_SERVICE_URL, or install index-tts only in an isolated runtime environment."
            ) from exc
        cls = getattr(module, "IndexTTS2", None)
        if cls is None:
            raise RuntimeError("index-tts runtime does not expose indextts.infer_v2.IndexTTS2.")
        self._patch_local_runtime_assets(module)
        return cls(
            cfg_path=self.cfg_path,
            model_dir=self.model_dir,
            use_fp16=self.use_fp16,
            device=None if self.device == "auto" else self.device,
            use_cuda_kernel=self.use_cuda_kernel,
            use_deepspeed=self.use_deepspeed,
        )

    def _load_engine_entry(self) -> tuple[Any, threading.Lock]:
        key = self._engine_cache_key()
        with _ENGINE_CACHE_LOCK:
            entry = _ENGINE_CACHE.get(key)
            if entry is None:
                entry = (self._create_engine(), threading.Lock())
                _ENGINE_CACHE[key] = entry
            return entry

    def _load_engine(self) -> Any:
        return self._load_engine_entry()[0]

    def _patch_local_runtime_assets(self, module: Any) -> None:
        self._patch_w2v_bert_runtime(module)
        self._patch_hf_hub_download(module)
        self._patch_bigvgan_runtime()
        self._patch_torchaudio_save(module)

    def _patch_w2v_bert_runtime(self, module: Any) -> None:
        local_dir = self._existing_dir(self.w2v_bert_dir, "preprocessor_config.json")
        if local_dir is None:
            return
        self._patch_from_pretrained(module, "SeamlessM4TFeatureExtractor", local_dir)
        try:
            maskgct_utils = importlib.import_module("indextts.utils.maskgct_utils")
        except ImportError:
            return
        self._patch_from_pretrained(maskgct_utils, "Wav2Vec2BertModel", local_dir)

    def _patch_hf_hub_download(self, module: Any) -> None:
        original = getattr(module, "hf_hub_download", None)
        if not callable(original):
            return
        asset_map = self._local_hub_asset_map()
        if not asset_map:
            return

        def hf_hub_download(repo_id: str, filename: str, *args: Any, **kwargs: Any) -> str:
            path = asset_map.get((repo_id, filename))
            if path is not None:
                return str(path)
            return original(repo_id, filename, *args, **kwargs)

        module.hf_hub_download = hf_hub_download

    def _local_hub_asset_map(self) -> dict[tuple[str, str], Path]:
        out: dict[tuple[str, str], Path] = {}
        maskgct = self._existing_file(self.maskgct_dir, "semantic_codec/model.safetensors")
        if maskgct is not None:
            out[("amphion/MaskGCT", "semantic_codec/model.safetensors")] = maskgct
        campplus = self._existing_file(self.campplus_dir, "campplus_cn_common.bin")
        if campplus is not None:
            out[("funasr/campplus", "campplus_cn_common.bin")] = campplus
        return out

    def _patch_bigvgan_runtime(self) -> None:
        local_dir = self._existing_dir(self.bigvgan_dir, "config.json")
        if local_dir is None or not (local_dir / "bigvgan_generator.pt").is_file():
            return
        for module_name in (
            "indextts.BigVGAN.bigvgan",
            "indextts.s2mel.modules.bigvgan.bigvgan",
        ):
            try:
                bigvgan = importlib.import_module(module_name)
            except ImportError:
                continue
            self._patch_bigvgan_from_pretrained(bigvgan, local_dir)

    @staticmethod
    def _patch_bigvgan_from_pretrained(module: Any, local_dir: Path) -> None:
        cls = getattr(module, "BigVGAN", None)
        original = getattr(cls, "from_pretrained", None)
        if cls is None or not callable(original):
            return

        def from_pretrained(value: str, *args: Any, **kwargs: Any) -> Any:
            if value == "nvidia/bigvgan_v2_22khz_80band_256x":
                return original(str(local_dir), *args, **kwargs)
            return original(value, *args, **kwargs)

        cls.from_pretrained = from_pretrained

    @staticmethod
    def _patch_torchaudio_save(module: Any) -> None:
        torchaudio = getattr(module, "torchaudio", None)
        original = getattr(torchaudio, "save", None)
        if torchaudio is None or not callable(original):
            return

        def save(path: str, tensor: Any, sample_rate: int, *args: Any, **kwargs: Any) -> Any:
            try:
                return original(path, tensor, sample_rate, *args, **kwargs)
            except (ImportError, RuntimeError) as exc:
                text = str(exc)
                if "TorchCodec is required" not in text and "libtorchcodec" not in text:
                    raise
                data = tensor.detach().cpu().numpy() if hasattr(tensor, "detach") else np.asarray(tensor)
                _write_wav_i16(path, data, sample_rate)
                return None

        torchaudio.save = save

    @staticmethod
    def _existing_dir(value: str, required_file: str) -> Path | None:
        if not value:
            return None
        path = Path(value)
        if path.is_dir() and (path / required_file).is_file():
            return path
        return None

    @staticmethod
    def _existing_file(value: str, relative_file: str) -> Path | None:
        if not value:
            return None
        path = Path(value) / relative_file
        if path.is_file():
            return path
        return None

    @staticmethod
    def _patch_from_pretrained(module: Any, attr_name: str, local_dir: Path) -> None:
        target = getattr(module, attr_name, None)
        original = getattr(target, "from_pretrained", None)
        if target is None or not callable(original):
            return

        def from_pretrained(value: str, *args: Any, **kwargs: Any) -> Any:
            if value == "facebook/w2v-bert-2.0":
                return original(str(local_dir), *args, **kwargs)
            return original(value, *args, **kwargs)

        target.from_pretrained = from_pretrained

    def _synthesize_in_process(self, text: str, voice: str | None = None) -> list[AudioChunk]:
        prompt = self._resolve_voice_prompt(voice)
        if prompt is None:
            raise RuntimeError(
                "Local IndexTTS requires OPENTALKING_TTS_LOCAL_INDEXTTS_PROMPT_AUDIO. "
                "Point it at a short reference WAV for the local voice."
            )
        if not prompt.is_file():
            raise RuntimeError(f"Local IndexTTS prompt audio does not exist: {prompt}")
        cfg = Path(self.cfg_path)
        if not cfg.is_file():
            raise RuntimeError(f"Local IndexTTS config does not exist: {cfg}")
        model_dir = Path(self.model_dir)
        if not model_dir.is_dir():
            raise RuntimeError(f"Local IndexTTS model directory does not exist: {model_dir}")

        engine, engine_lock = self._load_engine_entry()
        infer = getattr(engine, "infer", None)
        if not callable(infer):
            raise RuntimeError("IndexTTS2 runtime does not expose infer().")

        fd, tmp_name = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        tmp_path = Path(tmp_name)
        try:
            with engine_lock:
                infer(str(prompt), text, tmp_name, **indextts_infer_kwargs(self.indextts_config))
                pcm, source_sr = _read_wav_i16(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

        pcm = _resample_linear(pcm, source_sr, self.sample_rate)
        return _split_pcm_chunks(pcm, self.sample_rate, self.chunk_ms)
