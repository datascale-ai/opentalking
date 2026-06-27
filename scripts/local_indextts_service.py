from __future__ import annotations

import argparse
import io
import importlib
import os
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel


class SynthesizeRequest(BaseModel):
    text: str
    voice: str | None = None
    model: str | None = None
    sample_rate: int | None = None
    prompt_audio: str | None = None
    emo_alpha: float | None = None
    emo_audio_prompt: str | None = None
    emo_vector: list[float] | None = None
    use_emo_text: bool | None = None
    emo_text: str | None = None
    use_random: bool | None = None
    interval_silence_ms: int | None = None
    max_text_tokens_per_segment: int | None = None
    quick_streaming_tokens: int | None = None


def _audio_to_i16(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wf:
        sr = int(wf.getframerate())
        channels = int(wf.getnchannels())
        sample_width = int(wf.getsampwidth())
        pcm_bytes = wf.readframes(wf.getnframes())
    if sample_width != 2:
        raise RuntimeError(f"Unsupported WAV sample width for local IndexTTS: {sample_width}")
    pcm = np.frombuffer(pcm_bytes, dtype="<i2").astype(np.int16, copy=False)
    if channels > 1:
        frame_count = pcm.size // channels
        pcm = pcm[: frame_count * channels].reshape(frame_count, channels).mean(axis=1).astype(np.int16)
    return pcm, sr


def _resample_linear(pcm: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    pcm = np.asarray(pcm, dtype=np.int16).reshape(-1)
    if pcm.size == 0 or src_sr == dst_sr:
        return pcm.copy()
    pcm_f = pcm.astype(np.float32) / 32768.0
    n_dst = max(1, int(round(pcm.size * dst_sr / src_sr)))
    xi = np.linspace(0.0, pcm.size - 1.0, num=n_dst)
    out = np.interp(xi, np.arange(pcm.size), pcm_f)
    return np.clip(np.round(out * 32768.0), -32768, 32767).astype(np.int16)


def _to_wav_bytes(pcm: np.ndarray, sr: int) -> bytes:
    buf = io.BytesIO()
    _write_wav_i16(buf, np.asarray(pcm, dtype=np.int16), sr)
    return buf.getvalue()


def _write_wav_i16(path_or_file: str | Path | io.BytesIO, data: np.ndarray, sample_rate: int) -> None:
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
    with wave.open(path_or_file if hasattr(path_or_file, "write") else str(path_or_file), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(pcm.reshape(-1).tobytes())


class LocalIndexTTSService:
    def __init__(
        self,
        *,
        model_dir: str,
        cfg_path: str,
        prompt_audio: str,
        device: str,
        w2v_bert_dir: str,
        maskgct_dir: str,
        campplus_dir: str,
        bigvgan_dir: str,
        use_fp16: bool,
        use_cuda_kernel: bool,
        use_deepspeed: bool,
    ) -> None:
        self.model_dir = model_dir
        self.cfg_path = cfg_path
        self.prompt_audio = prompt_audio
        self.device = device
        self.use_fp16 = use_fp16
        self.w2v_bert_dir = w2v_bert_dir
        self.maskgct_dir = maskgct_dir
        self.campplus_dir = campplus_dir
        self.bigvgan_dir = bigvgan_dir
        self.use_cuda_kernel = use_cuda_kernel
        self.use_deepspeed = use_deepspeed
        self._engine: Any | None = None
        self._lock = threading.Lock()

    def model(self) -> Any:
        if self._engine is not None:
            return self._engine
        try:
            module = importlib.import_module("indextts.infer_v2")
        except ImportError as exc:
            raise RuntimeError(
                "index-tts is not installed. Install it in the local IndexTTS service venv, not in the OpenTalking venv."
            ) from exc
        self._patch_local_runtime_assets(module)
        cls = getattr(module, "IndexTTS2", None)
        if cls is None:
            raise RuntimeError("index-tts runtime does not expose indextts.infer_v2.IndexTTS2.")
        t0 = time.perf_counter()
        self._engine = cls(
            cfg_path=self.cfg_path,
            model_dir=self.model_dir,
            use_fp16=self.use_fp16,
            device=None if self.device == "auto" else self.device,
            use_cuda_kernel=self.use_cuda_kernel,
            use_deepspeed=self.use_deepspeed,
        )
        print(
            f"loaded indextts model_dir={self.model_dir} cfg={self.cfg_path} device={self.device} seconds={time.perf_counter() - t0:.3f}",
            flush=True,
        )
        return self._engine

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
                data = np.asarray(data)
                if data.ndim == 2 and data.shape[0] == 1:
                    data = data[0]
                elif data.ndim == 2:
                    data = data.T
                _write_wav_i16(path, data, sample_rate)
                return None

        torchaudio.save = save

    @staticmethod
    def _existing_dir(value: str, required_file: str) -> Path | None:
        if not value:
            return None
        path = Path(value).expanduser()
        if path.is_dir() and (path / required_file).is_file():
            return path
        return None

    @staticmethod
    def _existing_file(value: str, relative_file: str) -> Path | None:
        if not value:
            return None
        path = Path(value).expanduser() / relative_file
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

    def _infer_kwargs(self, req: SynthesizeRequest) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if req.emo_alpha is not None:
            kwargs["emo_alpha"] = float(req.emo_alpha)
        if req.emo_audio_prompt:
            kwargs["emo_audio_prompt"] = req.emo_audio_prompt
        if req.emo_vector is not None:
            kwargs["emo_vector"] = list(req.emo_vector)
        if req.use_emo_text is not None:
            kwargs["use_emo_text"] = bool(req.use_emo_text)
        if req.emo_text:
            kwargs["emo_text"] = req.emo_text
        if req.use_random is not None:
            kwargs["use_random"] = bool(req.use_random)
        if req.interval_silence_ms is not None:
            kwargs["interval_silence"] = int(req.interval_silence_ms)
        if req.max_text_tokens_per_segment is not None:
            kwargs["max_text_tokens_per_segment"] = int(req.max_text_tokens_per_segment)
        if req.quick_streaming_tokens is not None:
            kwargs["more_segment_before"] = int(req.quick_streaming_tokens)
        return kwargs

    def synthesize_pcm(self, req: SynthesizeRequest) -> tuple[bytes, int, float]:
        text = req.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="text is required")
        prompt_audio = (req.prompt_audio or self.prompt_audio).strip()
        if not prompt_audio:
            raise HTTPException(status_code=400, detail="prompt_audio is required")
        if not Path(prompt_audio).is_file():
            raise HTTPException(status_code=400, detail=f"prompt_audio does not exist: {prompt_audio}")
        target_sr = int(req.sample_rate or 16000)
        t0 = time.perf_counter()
        fd, tmp_name = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        tmp_path = Path(tmp_name)
        try:
            with self._lock:
                self.model().infer(prompt_audio, text, tmp_name, **self._infer_kwargs(req))
            pcm, sr = _audio_to_i16(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)
        pcm = _resample_linear(pcm, sr, target_sr)
        elapsed = time.perf_counter() - t0
        print(
            f"synth chars={len(text)} sr={target_sr} audio_seconds={pcm.size / target_sr:.3f} wall_seconds={elapsed:.3f}",
            flush=True,
        )
        return pcm.astype("<i2", copy=False).tobytes(), target_sr, elapsed

    def prewarm(self, *, text: str) -> None:
        warmup_text = text.strip()
        if not warmup_text:
            self.model()
            return
        self.synthesize_pcm(SynthesizeRequest(text=warmup_text))


def create_app(service: LocalIndexTTSService) -> FastAPI:
    app = FastAPI(title="OpenTalking Local IndexTTS Service")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "model_dir": service.model_dir,
            "cfg_path": service.cfg_path,
            "device": service.device,
            "loaded": service._engine is not None,
            "w2v_bert_dir": service.w2v_bert_dir,
            "maskgct_dir": service.maskgct_dir,
            "campplus_dir": service.campplus_dir,
            "bigvgan_dir": service.bigvgan_dir,
        }

    @app.post("/synthesize")
    def synthesize(req: SynthesizeRequest) -> StreamingResponse:
        try:
            pcm_bytes, sr, _elapsed = service.synthesize_pcm(req)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"indextts synth failed: {type(exc).__name__}: {exc}",
            ) from exc
        return StreamingResponse(
            io.BytesIO(pcm_bytes),
            media_type=f"audio/L16; rate={sr}; channels=1",
            headers={"X-Audio-Sample-Rate": str(sr)},
        )

    return app


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _local_audio_root() -> Path:
    return Path(os.environ.get("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", "./models/local-audio")).expanduser()


def _existing_dir(value: str, required_file: str) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if path.is_dir() and (path / required_file).is_file():
        return path
    return None


def _existing_file(value: str, relative_file: str) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser() / relative_file
    if path.is_file():
        return path
    return None


def _first_existing_asset_dir(candidates: list[Path], required_file: str) -> Path:
    for candidate in candidates:
        if _existing_dir(str(candidate), required_file) is not None:
            return candidate
    return candidates[0]


def _first_existing_asset_file_dir(candidates: list[Path], relative_file: str) -> Path:
    for candidate in candidates:
        if _existing_file(str(candidate), relative_file) is not None:
            return candidate
    return candidates[0]


def build_service_from_env() -> LocalIndexTTSService:
    root = _local_audio_root()
    model_dir = os.environ.get(
        "OPENTALKING_TTS_LOCAL_INDEXTTS_MODEL_DIR",
        str(root / "IndexTeam__IndexTTS-2"),
    )
    maskgct_dir = os.environ.get(
        "OPENTALKING_TTS_LOCAL_INDEXTTS_MASKGCT_DIR",
        str(_first_existing_asset_file_dir([root / "amphion__MaskGCT", root / "amphion__MaskGCT-ms"], "semantic_codec/model.safetensors")),
    )
    device = os.environ.get("OPENTALKING_TTS_LOCAL_INDEXTTS_DEVICE", "auto")
    return LocalIndexTTSService(
        model_dir=model_dir,
        cfg_path=os.environ.get("OPENTALKING_TTS_LOCAL_INDEXTTS_CFG_PATH", str(Path(model_dir) / "config.yaml")),
        prompt_audio=os.environ.get("OPENTALKING_TTS_LOCAL_INDEXTTS_PROMPT_AUDIO", ""),
        device=device,
        w2v_bert_dir=os.environ.get("OPENTALKING_TTS_LOCAL_INDEXTTS_W2V_BERT_DIR", str(root / "facebook__w2v-bert-2.0")),
        maskgct_dir=maskgct_dir,
        campplus_dir=os.environ.get("OPENTALKING_TTS_LOCAL_INDEXTTS_CAMPPLUS_DIR", str(root / "funasr__campplus")),
        bigvgan_dir=os.environ.get("OPENTALKING_TTS_LOCAL_INDEXTTS_BIGVGAN_DIR", str(root / "nvidia__bigvgan_v2_22khz_80band_256x")),
        use_fp16=_env_bool("OPENTALKING_TTS_LOCAL_INDEXTTS_USE_FP16", device.startswith("cuda")),
        use_cuda_kernel=_env_bool("OPENTALKING_TTS_LOCAL_INDEXTTS_USE_CUDA_KERNEL", False),
        use_deepspeed=_env_bool("OPENTALKING_TTS_LOCAL_INDEXTTS_USE_DEEPSPEED", False),
    )


service = build_service_from_env()
if os.environ.get("OPENTALKING_TTS_LOCAL_INDEXTTS_PRELOAD", "0").strip().lower() in {"1", "true", "yes", "on"}:
    service.prewarm(text=os.environ.get("OPENTALKING_TTS_LOCAL_INDEXTTS_WARMUP_TEXT", "你好"))
app = create_app(service)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local IndexTTS HTTP service.")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "19092")))
    args = parser.parse_args()
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
