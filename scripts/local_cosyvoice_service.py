from __future__ import annotations

import argparse
import io
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel


class SynthesizeRequest(BaseModel):
    text: str
    voice: str | None = None
    model: str | None = None
    sample_rate: int | None = None
    prompt_audio: str | None = None
    prompt_text: str | None = None
    mode: str | None = None
    instruction: str | None = None


class CosyVoiceService:
    def __init__(
        self,
        *,
        model_dir: str,
        runtime_dir: str,
        device: str,
        prompt_audio: str,
        prompt_text: str,
        mode: str,
        instruction: str,
        fp16: bool,
    ) -> None:
        self.model_dir = model_dir
        self.runtime_dir = runtime_dir
        self.device = device
        self.prompt_audio = prompt_audio
        self.prompt_text = prompt_text
        self.mode = mode
        self.instruction = instruction
        self.fp16 = fp16
        self._model: Any | None = None

    def model(self) -> Any:
        if self._model is not None:
            return self._model
        runtime = Path(self.runtime_dir).expanduser().resolve()
        matcha = runtime / "third_party" / "Matcha-TTS"
        for path in (runtime, matcha):
            if str(path) not in sys.path:
                sys.path.insert(0, str(path))
        try:
            from cosyvoice.cli.cosyvoice import AutoModel
        except ImportError as exc:
            raise RuntimeError(
                "CosyVoice runtime is not importable. Clone FunAudioLLM/CosyVoice and install its requirements in this service venv."
            ) from exc

        # CUDA_VISIBLE_DEVICES must be set before service startup if GPU masking is needed.
        if self.device.startswith("cuda"):
            try:
                import torch

                torch.cuda.set_device(int(self.device.split(":", 1)[1]))
            except Exception as exc:
                raise RuntimeError(f"Failed to select {self.device}: {exc}") from exc
        t0 = time.perf_counter()
        model_kwargs = {
            "model_dir": self.model_dir,
            "load_trt": False,
            "load_vllm": False,
            "fp16": self.fp16,
        }
        try:
            self._model = AutoModel(**model_kwargs)
        except TypeError as exc:
            if "load_vllm" not in str(exc):
                raise
            model_kwargs.pop("load_vllm")
            self._model = AutoModel(**model_kwargs)
        # Keep the service zero-shot first so it does not require precomputed spk2info.pt.
        print(
            f"loaded cosyvoice model={self.model_dir} runtime={runtime} device={self.device} seconds={time.perf_counter() - t0:.3f}",
            flush=True,
        )
        return self._model

    def _to_wav_bytes(self, speech: Any, sample_rate: int) -> bytes:
        if hasattr(speech, "detach"):
            speech = speech.detach().cpu().numpy()
        audio = np.asarray(speech, dtype=np.float32).reshape(-1)
        buf = io.BytesIO()
        sf.write(buf, audio, sample_rate, format="WAV")
        return buf.getvalue()

    def _audio_to_i16(self, speech: Any) -> np.ndarray:
        if hasattr(speech, "detach"):
            speech = speech.detach().cpu().numpy()
        audio = np.asarray(speech, dtype=np.float32).reshape(-1)
        if audio.size == 0:
            return np.zeros(0, dtype=np.int16)
        if np.max(np.abs(audio)) > 1.5:
            return np.clip(audio, -32768, 32767).astype(np.int16)
        return np.clip(np.round(audio * 32768.0), -32768, 32767).astype(np.int16)

    def _resample_linear(self, pcm: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
        pcm = np.asarray(pcm, dtype=np.int16).reshape(-1)
        if pcm.size == 0 or src_sr == dst_sr:
            return pcm.copy()
        pcm_f = pcm.astype(np.float32) / 32768.0
        n_dst = max(1, int(round(pcm.size * dst_sr / src_sr)))
        xi = np.linspace(0.0, pcm.size - 1.0, num=n_dst)
        out = np.interp(xi, np.arange(pcm.size), pcm_f)
        return np.clip(np.round(out * 32768.0), -32768, 32767).astype(np.int16)

    def _prompt_text_for_zero_shot(self, prompt_text: str) -> str:
        text = prompt_text.strip()
        if "<|endofprompt|>" in text:
            return text
        if text:
            return f"You are a helpful assistant.<|endofprompt|>{text}"
        return "You are a helpful assistant.<|endofprompt|>"

    def synthesize_wav(self, req: SynthesizeRequest) -> tuple[bytes, int, float]:
        text = req.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="text is required")
        prompt_audio = (req.prompt_audio or self.prompt_audio).strip()
        prompt_text = (req.prompt_text or self.prompt_text).strip()
        mode = (req.mode or self.mode).strip().lower()
        model = self.model()
        sample_rate = int(getattr(model, "sample_rate", 24000) or 24000)
        t0 = time.perf_counter()
        if mode == "cross_lingual":
            if not prompt_audio:
                raise HTTPException(status_code=400, detail="prompt_audio is required")
            iterator = model.inference_cross_lingual(text, prompt_audio, stream=False)
        elif mode == "instruct":
            if not prompt_audio:
                raise HTTPException(status_code=400, detail="prompt_audio is required")
            instruction = (req.instruction or self.instruction).strip()
            iterator = model.inference_instruct2(text, instruction, prompt_audio, stream=False)
        else:
            if not prompt_audio or not prompt_text:
                raise HTTPException(
                    status_code=400,
                    detail="zero_shot mode requires prompt_audio and prompt_text",
                )
            iterator = model.inference_zero_shot(
                text,
                self._prompt_text_for_zero_shot(prompt_text),
                prompt_audio,
                stream=False,
            )
        parts: list[np.ndarray] = []
        for item in iterator:
            speech = item.get("tts_speech") if isinstance(item, dict) else item
            if hasattr(speech, "detach"):
                speech = speech.detach().cpu().numpy()
            parts.append(np.asarray(speech, dtype=np.float32).reshape(-1))
        if not parts:
            raise HTTPException(status_code=502, detail="CosyVoice returned no audio")
        wav_bytes = self._to_wav_bytes(np.concatenate(parts), sample_rate)
        return wav_bytes, sample_rate, time.perf_counter() - t0

    def _streaming_iterator(self, req: SynthesizeRequest) -> tuple[Iterator[Any], int, int, float]:
        text = req.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="text is required")
        prompt_audio = (req.prompt_audio or self.prompt_audio).strip()
        prompt_text = (req.prompt_text or self.prompt_text).strip()
        mode = (req.mode or self.mode).strip().lower()
        model = self.model()
        source_sr = int(getattr(model, "sample_rate", 24000) or 24000)
        target_sr = int(req.sample_rate or source_sr)
        t0 = time.perf_counter()
        if mode == "cross_lingual":
            if not prompt_audio:
                raise HTTPException(status_code=400, detail="prompt_audio is required")
            iterator = model.inference_cross_lingual(text, prompt_audio, stream=True)
        elif mode == "instruct":
            if not prompt_audio:
                raise HTTPException(status_code=400, detail="prompt_audio is required")
            instruction = (req.instruction or self.instruction).strip()
            iterator = model.inference_instruct2(text, instruction, prompt_audio, stream=True)
        else:
            if not prompt_audio or not prompt_text:
                raise HTTPException(
                    status_code=400,
                    detail="zero_shot mode requires prompt_audio and prompt_text",
                )
            iterator = model.inference_zero_shot(
                text,
                self._prompt_text_for_zero_shot(prompt_text),
                prompt_audio,
                stream=True,
            )
        return iterator, source_sr, target_sr, t0

    def synthesize_pcm_stream(self, req: SynthesizeRequest) -> tuple[Iterator[bytes], int]:
        iterator, source_sr, target_sr, t0 = self._streaming_iterator(req)

        def generate() -> Iterator[bytes]:
            first = True
            chunks = 0
            samples = 0
            for item in iterator:
                speech = item.get("tts_speech") if isinstance(item, dict) else item
                pcm = self._audio_to_i16(speech)
                pcm = self._resample_linear(pcm, source_sr, target_sr)
                if pcm.size == 0:
                    continue
                if first:
                    print(
                        f"first_pcm chars={len(req.text.strip())} sr={target_sr} seconds={time.perf_counter() - t0:.3f}",
                        flush=True,
                    )
                    first = False
                chunks += 1
                samples += int(pcm.size)
                yield pcm.astype("<i2", copy=False).tobytes()
            if chunks == 0:
                raise RuntimeError("CosyVoice returned no audio")
            print(
                f"synth_stream chars={len(req.text.strip())} sr={target_sr} chunks={chunks} audio_seconds={samples / target_sr:.3f} wall_seconds={time.perf_counter() - t0:.3f}",
                flush=True,
            )

        return generate(), target_sr

    def prewarm(self, *, text: str) -> None:
        warmup_text = text.strip()
        if not warmup_text:
            self.model()
            return
        req = SynthesizeRequest(text=warmup_text)
        stream, _sr = self.synthesize_pcm_stream(req)
        for _chunk in stream:
            break


def create_app(service: CosyVoiceService) -> FastAPI:
    app = FastAPI(title="OpenTalking Local CosyVoice Service")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "model_dir": service.model_dir,
            "runtime_dir": service.runtime_dir,
            "device": service.device,
            "loaded": service._model is not None,
            "mode": service.mode,
        }

    @app.post("/synthesize")
    def synthesize(req: SynthesizeRequest) -> StreamingResponse:
        try:
            stream, sr = service.synthesize_pcm_stream(req)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"cosyvoice synth failed: {type(exc).__name__}: {exc}",
            ) from exc
        return StreamingResponse(
            stream,
            media_type=f"audio/L16; rate={sr}; channels=1",
            headers={"X-Audio-Sample-Rate": str(sr)},
        )

    return app


def _local_audio_root() -> Path:
    return Path(os.environ.get("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", "./models/local-audio")).expanduser()


def build_service_from_env() -> CosyVoiceService:
    device = os.environ.get("OPENTALKING_TTS_LOCAL_COSYVOICE_DEVICE", "cuda:0")
    fp16_raw = os.environ.get("OPENTALKING_TTS_LOCAL_COSYVOICE_FP16", "auto").strip().lower()
    fp16 = device.startswith("cuda") if fp16_raw == "auto" else fp16_raw not in {"0", "false", "no", "off"}
    root = _local_audio_root()
    return CosyVoiceService(
        model_dir=os.environ.get(
            "OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL_DIR",
            str(root / "FunAudioLLM__Fun-CosyVoice3-0.5B-2512"),
        ),
        runtime_dir=os.environ.get(
            "OPENTALKING_TTS_LOCAL_COSYVOICE_RUNTIME_DIR",
            str(root / "runtime" / "CosyVoice"),
        ),
        device=device,
        prompt_audio=os.environ.get("OPENTALKING_TTS_LOCAL_COSYVOICE_PROMPT_AUDIO", ""),
        prompt_text=os.environ.get("OPENTALKING_TTS_LOCAL_COSYVOICE_PROMPT_TEXT", ""),
        mode=os.environ.get("OPENTALKING_TTS_LOCAL_COSYVOICE_MODE", "zero_shot"),
        instruction=os.environ.get(
            "OPENTALKING_TTS_LOCAL_COSYVOICE_INSTRUCTION",
            "You are a helpful assistant.<|endofprompt|>",
        ),
        fp16=fp16,
    )


service = build_service_from_env()
if os.environ.get("OPENTALKING_TTS_LOCAL_COSYVOICE_PRELOAD", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}:
    warmup_text = os.environ.get("OPENTALKING_TTS_LOCAL_COSYVOICE_WARMUP_TEXT", "你好")
    service.prewarm(text=warmup_text)
app = create_app(service)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local CosyVoice HTTP service.")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "19090")))
    args = parser.parse_args()
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
