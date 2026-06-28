from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel


DEFAULT_MODEL = "SWivid/F5-TTS/F5TTS_v1_Base"
DEFAULT_SERVICE_SAMPLE_RATE = 24000


def _local_audio_model_root() -> Path:
    return Path(os.environ.get("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", "./models/local-audio")).expanduser().resolve()


def _default_model_dir(root: Path) -> Path:
    return root / "SWivid__F5-TTS__F5TTS_v1_Base"


def _default_runtime_dir(root: Path) -> Path:
    return root / "runtime" / "F5-TTS"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _select_device(value: str) -> str | None:
    value = value.strip()
    if value and value != "auto":
        return value
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return None


def _pcm_bytes(wav: Any) -> bytes:
    arr = np.asarray(wav)
    if arr.ndim > 1:
        arr = arr.mean(axis=1)
    if np.issubdtype(arr.dtype, np.floating):
        arr = np.clip(arr, -1.0, 1.0)
        arr = np.round(arr * 32767.0).astype("<i2")
    else:
        arr = np.clip(arr, -32768, 32767).astype("<i2")
    return arr.reshape(-1).tobytes()


def _soundfile_torchaudio_load(path: str | Path, *args: Any, **kwargs: Any):
    import soundfile as sf
    import torch

    audio, sr = sf.read(str(path), dtype="float32", always_2d=True)
    tensor = torch.from_numpy(audio.T.copy())
    normalize = kwargs.get("normalize", True)
    if not normalize:
        tensor = (tensor.clamp(-1.0, 1.0) * 32767.0).to(torch.int16)
    frame_offset = int(kwargs.get("frame_offset", 0) or 0)
    num_frames = int(kwargs.get("num_frames", -1) or -1)
    if frame_offset > 0 or num_frames >= 0:
        end = None if num_frames < 0 else frame_offset + num_frames
        tensor = tensor[:, frame_offset:end]
    return tensor, int(sr)


def _patch_torchaudio_load() -> None:
    try:
        import torchaudio
    except Exception:
        return
    if getattr(torchaudio, "_opentalking_soundfile_load_patched", False):
        return
    torchaudio.load = _soundfile_torchaudio_load
    torchaudio._opentalking_soundfile_load_patched = True


class SynthesizeRequest(BaseModel):
    text: str
    voice: str | None = None
    model: str | None = None
    sample_rate: int | None = None
    prompt_audio: str | None = None
    prompt_text: str | None = None
    speed: float | None = None
    nfe_step: int | None = None


class F5TTSService:
    def __init__(
        self,
        *,
        model: str | None = None,
        model_dir: str | Path | None = None,
        runtime_dir: str | Path | None = None,
        ckpt_file: str | Path | None = None,
        vocoder_local_path: str | Path | None = None,
        prompt_audio: str | Path | None = None,
        prompt_text: str | None = None,
        device: str | None = None,
        preload: bool = True,
    ) -> None:
        root = _local_audio_model_root()
        self.model = (model or os.environ.get("OPENTALKING_TTS_LOCAL_F5_TTS_MODEL") or DEFAULT_MODEL).strip()
        self.model_dir = Path(
            model_dir or os.environ.get("OPENTALKING_TTS_LOCAL_F5_TTS_MODEL_DIR") or _default_model_dir(root)
        ).expanduser()
        self.runtime_dir = Path(
            runtime_dir or os.environ.get("OPENTALKING_TTS_LOCAL_F5_TTS_RUNTIME_DIR") or _default_runtime_dir(root)
        ).expanduser()
        self.ckpt_file = Path(
            ckpt_file
            or os.environ.get("OPENTALKING_TTS_LOCAL_F5_TTS_CKPT_FILE")
            or self.model_dir / "model_1250000.safetensors"
        ).expanduser()
        vocoder = vocoder_local_path or os.environ.get("OPENTALKING_TTS_LOCAL_F5_TTS_VOCODER_LOCAL_PATH") or ""
        self.vocoder_local_path = Path(vocoder).expanduser() if str(vocoder).strip() else None
        prompt = prompt_audio or os.environ.get("OPENTALKING_TTS_LOCAL_F5_TTS_PROMPT_AUDIO") or ""
        self.prompt_audio = Path(prompt).expanduser() if str(prompt).strip() else None
        self.prompt_text = (prompt_text or os.environ.get("OPENTALKING_TTS_LOCAL_F5_TTS_PROMPT_TEXT") or "").strip()
        self.device = device or os.environ.get("OPENTALKING_TTS_LOCAL_F5_TTS_DEVICE") or "auto"
        self._engine: Any | None = None
        self._lock = threading.Lock()
        if preload:
            self.engine()

    def engine(self) -> Any:
        with self._lock:
            if self._engine is not None:
                return self._engine
            if not self.ckpt_file.exists():
                raise RuntimeError(f"Missing F5-TTS checkpoint: {self.ckpt_file}")
            src_dir = self.runtime_dir / "src"
            for candidate in (src_dir, self.runtime_dir):
                if candidate.exists() and str(candidate) not in sys.path:
                    sys.path.insert(0, str(candidate))
            _patch_torchaudio_load()
            from f5_tts.api import F5TTS

            kwargs: dict[str, Any] = {"model": "F5TTS_v1_Base", "ckpt_file": str(self.ckpt_file)}
            if self.vocoder_local_path is not None:
                kwargs["vocoder_local_path"] = str(self.vocoder_local_path)
            selected_device = _select_device(self.device)
            if selected_device:
                kwargs["device"] = selected_device
            self._engine = F5TTS(**kwargs)
            return self._engine

    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "provider": "local_f5_tts",
            "model": self.model,
            "model_dir": str(self.model_dir),
            "runtime_dir": str(self.runtime_dir),
            "ckpt_file": str(self.ckpt_file),
            "ckpt_exists": self.ckpt_file.exists(),
            "loaded": self._engine is not None,
            "device": self.device,
        }

    def prewarm(self, text: str = "你好。") -> None:
        if self.prompt_audio is None or not self.prompt_audio.exists():
            self.engine()
            return
        list(self.synthesize(text=text, prompt_audio=self.prompt_audio, prompt_text=self.prompt_text))

    def synthesize(
        self,
        *,
        text: str,
        prompt_audio: str | Path | None = None,
        prompt_text: str | None = None,
        speed: float | None = None,
        nfe_step: int | None = None,
    ) -> Iterator[bytes]:
        text = text.strip()
        if not text:
            return
        ref_audio = Path(prompt_audio).expanduser() if prompt_audio else self.prompt_audio
        if ref_audio is None or not ref_audio.exists():
            raise RuntimeError("Local F5-TTS requires prompt_audio for voice cloning.")
        ref_text = (prompt_text if prompt_text is not None else self.prompt_text).strip()
        infer_kwargs: dict[str, Any] = {
            "ref_file": str(ref_audio),
            "ref_text": ref_text,
            "gen_text": text,
            "show_info": lambda *_args, **_kwargs: None,
            "progress": None,
        }
        if speed is not None:
            infer_kwargs["speed"] = float(speed)
        if nfe_step is not None:
            infer_kwargs["nfe_step"] = int(nfe_step)
        wav, _sr, _spec = self.engine().infer(**infer_kwargs)
        yield _pcm_bytes(wav)


def create_app(service: F5TTSService | None = None) -> FastAPI:
    service = service or F5TTSService(preload=_env_bool("OPENTALKING_TTS_LOCAL_F5_TTS_PRELOAD", True))
    app = FastAPI(title="OpenTalking Local F5-TTS Service")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return service.health()

    @app.post("/synthesize")
    def synthesize(request: SynthesizeRequest) -> StreamingResponse:
        try:
            started = time.perf_counter()
            audio = list(
                service.synthesize(
                    text=request.text,
                    prompt_audio=request.prompt_audio,
                    prompt_text=request.prompt_text,
                    speed=request.speed,
                    nfe_step=request.nfe_step,
                )
            )
            elapsed = max(time.perf_counter() - started, 0.001)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        headers = {
            "X-Audio-Sample-Rate": str(DEFAULT_SERVICE_SAMPLE_RATE),
            "X-OpenTalking-Elapsed": f"{elapsed:.3f}",
        }
        return StreamingResponse(
            iter(audio),
            media_type=f"audio/L16; rate={DEFAULT_SERVICE_SAMPLE_RATE}; channels=1",
            headers=headers,
        )

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the OpenTalking local F5-TTS sidecar.")
    parser.add_argument("--host", default=os.environ.get("OPENTALKING_TTS_LOCAL_F5_TTS_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("OPENTALKING_TTS_LOCAL_F5_TTS_PORT", "19095")))
    parser.add_argument("--no-preload", action="store_true")
    args = parser.parse_args()

    import uvicorn

    app = create_app(F5TTSService(preload=not args.no_preload and _env_bool("OPENTALKING_TTS_LOCAL_F5_TTS_PRELOAD", True)))
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
