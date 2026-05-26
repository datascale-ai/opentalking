from __future__ import annotations

import argparse
import io
import os
import time
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel


class SynthesizeRequest(BaseModel):
    text: str
    voice: str | None = None
    model: str | None = None
    language: str | None = None
    ref_audio: str | None = None
    ref_text: str | None = None


class Qwen3TTSService:
    def __init__(
        self,
        *,
        model_dir: str,
        device: str,
        dtype: str,
        ref_audio: str,
        ref_text: str,
        language: str,
        max_new_tokens: int,
    ) -> None:
        self.model_dir = model_dir
        self.device = device
        self.dtype = dtype
        self.ref_audio = ref_audio
        self.ref_text = ref_text
        self.language = language
        self.max_new_tokens = max_new_tokens
        self._model: Any | None = None

    def _torch_dtype(self) -> torch.dtype:
        if self.dtype == "float16":
            return torch.float16
        if self.dtype == "float32":
            return torch.float32
        return torch.bfloat16

    def model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from qwen_tts import Qwen3TTSModel
        except ImportError as exc:
            raise RuntimeError(
                "qwen_tts is not installed. Install the local-qwen3-tts-service extra in a separate venv."
            ) from exc
        kwargs: dict[str, Any] = {
            "device_map": self.device,
            "dtype": self._torch_dtype(),
            "attn_implementation": "sdpa",
        }
        t0 = time.perf_counter()
        self._model = Qwen3TTSModel.from_pretrained(self.model_dir, **kwargs)
        print(
            f"loaded qwen3_tts model={self.model_dir} device={self.device} seconds={time.perf_counter() - t0:.3f}",
            flush=True,
        )
        return self._model

    def synthesize_wav(self, req: SynthesizeRequest) -> tuple[bytes, int, float]:
        text = req.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="text is required")
        ref_audio = (req.ref_audio or self.ref_audio).strip()
        ref_text = (req.ref_text or self.ref_text).strip()
        if not ref_audio or not ref_text:
            raise HTTPException(
                status_code=400,
                detail="Qwen3-TTS Base requires reference audio and reference text.",
            )
        t0 = time.perf_counter()
        wavs, sr = self.model().generate_voice_clone(
            text=text,
            language=req.language or self.language,
            ref_audio=ref_audio,
            ref_text=ref_text,
            non_streaming_mode=True,
            max_new_tokens=self.max_new_tokens,
        )
        audio = np.asarray(wavs[0], dtype=np.float32)
        buf = io.BytesIO()
        sf.write(buf, audio, sr, format="WAV")
        elapsed = time.perf_counter() - t0
        return buf.getvalue(), int(sr), elapsed


def create_app(service: Qwen3TTSService) -> FastAPI:
    app = FastAPI(title="OpenTalking Local Qwen3-TTS Service")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "model_dir": service.model_dir,
            "device": service.device,
            "loaded": service._model is not None,
        }

    @app.post("/synthesize")
    def synthesize(req: SynthesizeRequest) -> StreamingResponse:
        try:
            wav_bytes, sr, elapsed = service.synthesize_wav(req)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"qwen3_tts synth failed: {type(exc).__name__}: {exc}",
            ) from exc
        print(f"synth chars={len(req.text.strip())} sr={sr} seconds={elapsed:.3f}", flush=True)
        return StreamingResponse(io.BytesIO(wav_bytes), media_type="audio/wav")

    return app


def build_service_from_env() -> Qwen3TTSService:
    return Qwen3TTSService(
        model_dir=os.environ.get(
            "OPENTALKING_LOCAL_QWEN3_TTS_MODEL_DIR",
            str(Path(os.environ.get("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", "./models/local-audio")).expanduser() / "Qwen__Qwen3-TTS-12Hz-0.6B-Base"),
        ),
        device=os.environ.get("OPENTALKING_LOCAL_QWEN3_TTS_DEVICE", "cuda:0"),
        dtype=os.environ.get("OPENTALKING_LOCAL_QWEN3_TTS_DTYPE", "bfloat16"),
        ref_audio=os.environ.get("OPENTALKING_LOCAL_QWEN3_TTS_REF_AUDIO", ""),
        ref_text=os.environ.get("OPENTALKING_LOCAL_QWEN3_TTS_REF_TEXT", ""),
        language=os.environ.get("OPENTALKING_LOCAL_QWEN3_TTS_LANGUAGE", "Chinese"),
        max_new_tokens=int(os.environ.get("OPENTALKING_LOCAL_QWEN3_TTS_MAX_NEW_TOKENS", "256")),
    )


service = build_service_from_env()
app = create_app(service)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Qwen3-TTS HTTP service.")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "19091")))
    args = parser.parse_args()
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
