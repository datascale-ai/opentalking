from __future__ import annotations

import argparse
import importlib
import io
import os
import sys
import threading
import time
from collections.abc import Iterator
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel



def _soundfile_load_wav(wav: str, target_sr: int):
    import torch

    audio, sr = sf.read(wav, dtype="float32", always_2d=False)
    arr = np.asarray(audio, dtype=np.float32)
    if arr.ndim > 1:
        arr = arr.mean(axis=1)
    tensor = torch.from_numpy(arr).unsqueeze(0)
    if int(sr) == int(target_sr):
        return tensor
    try:
        import torchaudio.functional as AF

        return AF.resample(tensor, int(sr), int(target_sr))
    except Exception:
        import torch.nn.functional as F

        n_dst = max(1, int(round(tensor.shape[-1] * int(target_sr) / int(sr))))
        return F.interpolate(
            tensor.unsqueeze(0),
            size=n_dst,
            mode="linear",
            align_corners=False,
        ).squeeze(0)


def _build_strongly_typed_trt(trt_model: str, trt_kwargs: dict[str, Any], onnx_model: str) -> None:
    import tensorrt as trt

    logger = trt.Logger(trt.Logger.INFO)
    builder = trt.Builder(logger)
    network_flags = 1 << int(trt.NetworkDefinitionCreationFlag.STRONGLY_TYPED)
    network = builder.create_network(network_flags)
    parser = trt.OnnxParser(network, logger)
    config = builder.create_builder_config()
    config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, 1 << 32)
    profile = builder.create_optimization_profile()
    with open(onnx_model, "rb") as f:
        if not parser.parse(f.read()):
            errors = [str(parser.get_error(i)) for i in range(parser.num_errors)]
            raise RuntimeError(f"failed to parse {onnx_model}: {'; '.join(errors)}")
    for i, name in enumerate(trt_kwargs["input_names"]):
        profile.set_shape(name, trt_kwargs["min_shape"][i], trt_kwargs["opt_shape"][i], trt_kwargs["max_shape"][i])
    config.add_optimization_profile(profile)
    engine_bytes = builder.build_serialized_network(network, config)
    if engine_bytes is None:
        raise RuntimeError(f"failed to build TensorRT engine from {onnx_model}")
    with open(trt_model, "wb") as f:
        f.write(engine_bytes)


def _patch_cosyvoice_autocast_fp16_trt() -> None:
    try:
        import cosyvoice.cli.model as cosy_model
    except Exception:
        return
    if getattr(cosy_model, "_opentalking_autocast_fp16_trt_patched", False):
        return

    original_convert = cosy_model.convert_onnx_to_trt
    original_load_trt = cosy_model.CosyVoiceModel.load_trt

    def convert_onnx_to_trt(trt_model, trt_kwargs, onnx_model, fp16):
        onnx_path = Path(str(onnx_model))
        if fp16 and onnx_path.name == "flow.decoder.estimator.autocast_fp16.onnx":
            print(f"building strongly-typed autocast fp16 TensorRT engine: {trt_model}", flush=True)
            return _build_strongly_typed_trt(str(trt_model), trt_kwargs, str(onnx_model))
        return original_convert(trt_model, trt_kwargs, onnx_model, fp16)

    def load_trt(self, flow_decoder_estimator_model, flow_decoder_onnx_model, trt_concurrent, fp16):
        if fp16:
            model_dir = Path(str(flow_decoder_estimator_model)).parent
            autocast_onnx = model_dir / "flow.decoder.estimator.autocast_fp16.onnx"
            if autocast_onnx.exists():
                flow_decoder_estimator_model = str(model_dir / "flow.decoder.estimator.autocast_fp16.mygpu.plan")
                flow_decoder_onnx_model = str(autocast_onnx)
                setattr(self, "_opentalking_trt_autocast_fp16", True)
                setattr(self, "_opentalking_trt_plan", flow_decoder_estimator_model)
                setattr(self, "_opentalking_trt_onnx", flow_decoder_onnx_model)
                print(
                    "using CosyVoice autocast fp16 TensorRT asset "
                    f"onnx={flow_decoder_onnx_model} plan={flow_decoder_estimator_model}",
                    flush=True,
                )
        return original_load_trt(self, flow_decoder_estimator_model, flow_decoder_onnx_model, trt_concurrent, fp16)

    cosy_model.convert_onnx_to_trt = convert_onnx_to_trt
    cosy_model.CosyVoiceModel.load_trt = load_trt
    cosy_model._opentalking_autocast_fp16_trt_patched = True
    print("patched cosyvoice autocast fp16 TensorRT loader", flush=True)


def _patch_cosyvoice_load_wav() -> None:
    patched: list[str] = []
    for module_name in ("cosyvoice.utils.file_utils", "cosyvoice.cli.frontend"):
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        setattr(module, "load_wav", _soundfile_load_wav)
        patched.append(module_name)
    if patched:
        print(f"patched cosyvoice load_wav via soundfile modules={','.join(patched)}", flush=True)


class SynthesizeRequest(BaseModel):
    text: str
    voice: str | None = None
    model: str | None = None
    sample_rate: int | None = None
    prompt_audio: str | None = None
    prompt_text: str | None = None
    mode: str | None = None
    instruction: str | None = None


def _cosyvoice_model(cosyvoice: Any) -> Any:
    return getattr(cosyvoice, "model", cosyvoice)


def _cosyvoice_llm(cosyvoice: Any) -> Any | None:
    model = _cosyvoice_model(cosyvoice)
    return getattr(model, "llm", None)


def _cosyvoice_flow(cosyvoice: Any) -> Any | None:
    model = _cosyvoice_model(cosyvoice)
    return getattr(model, "flow", None)


def current_streaming_tuning(cosyvoice: Any) -> dict[str, Any]:
    model = _cosyvoice_model(cosyvoice)
    return {
        attr: getattr(model, attr)
        for attr in ("token_hop_len", "token_max_hop_len", "stream_scale_factor")
        if hasattr(model, attr)
    }


def apply_streaming_tuning(
    cosyvoice: Any,
    *,
    token_hop_len: int | None = None,
    token_max_hop_len: int | None = None,
    stream_scale_factor: int | None = None,
) -> dict[str, Any]:
    model = _cosyvoice_model(cosyvoice)
    requested = {
        "token_hop_len": token_hop_len,
        "token_max_hop_len": token_max_hop_len,
        "stream_scale_factor": stream_scale_factor,
    }
    applied: dict[str, Any] = {}
    for attr, value in requested.items():
        if value is None:
            continue
        if hasattr(model, attr):
            setattr(model, attr, value)
            applied[attr] = value
        else:
            applied[attr] = "unsupported"
    effective = current_streaming_tuning(cosyvoice)
    setattr(model, "_opentalking_streaming_tuning", effective)
    return {"requested": requested, "applied": applied, "effective": effective}


def ensure_cosyvoice_flow_half(cosyvoice: Any) -> bool:
    model = _cosyvoice_model(cosyvoice)
    flow = getattr(model, "flow", None)
    if flow is None or not hasattr(flow, "half"):
        return False
    flow.half()
    return True


def reset_streaming_tuning(cosyvoice: Any) -> dict[str, Any]:
    model = _cosyvoice_model(cosyvoice)
    baseline = getattr(model, "_opentalking_streaming_tuning", None)
    if baseline is None:
        baseline = current_streaming_tuning(cosyvoice)
        setattr(model, "_opentalking_streaming_tuning", baseline)
    for attr, value in baseline.items():
        if hasattr(model, attr):
            setattr(model, attr, value)
    return current_streaming_tuning(cosyvoice)


def _with_request_streaming_tuning(cosyvoice: Any, model_output: Iterator[Any]) -> Iterator[Any]:
    reset_streaming_tuning(cosyvoice)
    try:
        yield from model_output
    finally:
        reset_streaming_tuning(cosyvoice)


def current_flow_tuning(cosyvoice: Any) -> dict[str, Any]:
    flow = _cosyvoice_flow(cosyvoice)
    if flow is None:
        return {}
    return {"inference_n_timesteps": int(getattr(flow, "inference_n_timesteps", 10))}


def apply_flow_tuning(cosyvoice: Any, *, n_timesteps: int | None = None) -> dict[str, Any]:
    flow = _cosyvoice_flow(cosyvoice)
    requested = {"inference_n_timesteps": n_timesteps}
    if flow is None:
        return {"requested": requested, "applied": "unsupported", "effective": {}}
    applied: dict[str, Any] = {}
    if n_timesteps is not None:
        setattr(flow, "inference_n_timesteps", max(1, int(n_timesteps)))
        applied["inference_n_timesteps"] = getattr(flow, "inference_n_timesteps")
    return {"requested": requested, "applied": applied, "effective": current_flow_tuning(cosyvoice)}


def current_llm_token_ratio_tuning(cosyvoice: Any) -> dict[str, float]:
    llm = _cosyvoice_llm(cosyvoice)
    ratios = getattr(llm, "_opentalking_token_ratios", {}) if llm is not None else {}
    return dict(ratios) if isinstance(ratios, dict) else {}


def apply_llm_token_ratio_patch(
    cosyvoice: Any,
    *,
    max_token_text_ratio: float | None = None,
    min_token_text_ratio: float | None = None,
) -> dict[str, Any]:
    requested = {
        "max_token_text_ratio": max_token_text_ratio,
        "min_token_text_ratio": min_token_text_ratio,
    }
    llm = _cosyvoice_llm(cosyvoice)
    if llm is None or not hasattr(llm, "inference"):
        return {"requested": requested, "applied": "unsupported", "effective": {}}
    if max_token_text_ratio is None and min_token_text_ratio is None:
        return {"requested": requested, "applied": {}, "effective": current_llm_token_ratio_tuning(cosyvoice)}
    original = getattr(llm, "_opentalking_original_inference", None)
    if original is None:
        original = llm.inference
        setattr(llm, "_opentalking_original_inference", original)

    applied = {key: value for key, value in requested.items() if value is not None}

    def inference_with_opentalking_ratios(*args: Any, **kwargs: Any) -> Any:
        if max_token_text_ratio is not None:
            kwargs.setdefault("max_token_text_ratio", max_token_text_ratio)
        if min_token_text_ratio is not None:
            kwargs.setdefault("min_token_text_ratio", min_token_text_ratio)
        return original(*args, **kwargs)

    llm.inference = inference_with_opentalking_ratios
    setattr(llm, "_opentalking_token_ratios", applied)
    return {"requested": requested, "applied": applied, "effective": current_llm_token_ratio_tuning(cosyvoice)}


def current_llm_stop_token_patch(cosyvoice: Any) -> dict[str, Any]:
    llm = _cosyvoice_llm(cosyvoice)
    patch = getattr(llm, "_opentalking_stop_token_patch", {}) if llm is not None else {}
    return dict(patch) if isinstance(patch, dict) else {}


def apply_llm_stop_token_patch(cosyvoice: Any) -> dict[str, Any]:
    llm = _cosyvoice_llm(cosyvoice)
    if llm is None or not hasattr(llm, "sampling_ids"):
        return {"applied": "unsupported", "effective": {}}
    stop_token_ids = list(getattr(llm, "stop_token_ids", []) or [])
    if len(stop_token_ids) <= 1 or not hasattr(llm, "sampling"):
        return {"applied": {}, "effective": current_llm_stop_token_patch(cosyvoice)}
    if getattr(llm, "_opentalking_stop_token_patch_applied", False):
        return {"applied": {}, "effective": current_llm_stop_token_patch(cosyvoice)}

    original = llm.sampling_ids
    setattr(llm, "_opentalking_original_sampling_ids", original)

    def sampling_ids_with_opentalking_stop_mask(
        weighted_scores: Any,
        decoded_tokens: Any,
        sampling: Any,
        ignore_eos: bool = True,
    ) -> Any:
        if ignore_eos is True:
            masked_scores = weighted_scores.clone()
            valid_stop_ids = [idx for idx in stop_token_ids if 0 <= idx < len(masked_scores)]
            if valid_stop_ids:
                masked_scores[valid_stop_ids] = -float("inf")
            return llm.sampling(masked_scores, decoded_tokens, sampling)
        return original(weighted_scores, decoded_tokens, sampling, ignore_eos)

    llm.sampling_ids = sampling_ids_with_opentalking_stop_mask
    setattr(llm, "_opentalking_stop_token_patch_applied", True)
    setattr(llm, "_opentalking_stop_token_patch", {"stop_token_count": len(stop_token_ids)})
    return {"applied": {"stop_token_count": len(stop_token_ids)}, "effective": current_llm_stop_token_patch(cosyvoice)}


def current_runtime_info(cosyvoice: Any) -> dict[str, Any]:
    model = _cosyvoice_model(cosyvoice)
    flow = getattr(model, "flow", None)
    decoder = getattr(flow, "decoder", None)
    estimator = getattr(decoder, "estimator", None)
    estimator_type = estimator.__class__.__name__ if estimator is not None else ""
    return {
        "fp16": bool(getattr(cosyvoice, "fp16", False)),
        "flow_decoder_estimator": estimator_type,
        "flow_decoder_trt": estimator_type == "TrtContextWrapper",
        "trt_autocast_fp16": bool(getattr(model, "_opentalking_trt_autocast_fp16", False)),
        "trt_plan": getattr(model, "_opentalking_trt_plan", ""),
        "trt_onnx": getattr(model, "_opentalking_trt_onnx", ""),
    }


def runtime_package_versions(*packages: str) -> dict[str, str]:
    versions: dict[str, str] = {}
    for package in packages:
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = "not-installed"
    return versions


def _instantiate_automodel(cls: Any, kwargs: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    model_kwargs = dict(kwargs)
    optional_keys = ("load_vllm", "load_jit", "trt_concurrent")
    while True:
        try:
            return cls(**model_kwargs), model_kwargs
        except TypeError as exc:
            text = str(exc)
            unsupported = next((key for key in optional_keys if key in model_kwargs and key in text), None)
            if unsupported is None:
                raise
            model_kwargs.pop(unsupported)


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
        load_jit: bool = False,
        load_trt: bool = False,
        load_vllm: bool = False,
        trt_concurrent: int = 1,
        token_hop_len: int | None = None,
        token_max_hop_len: int | None = None,
        stream_scale_factor: int | None = None,
        flow_n_timesteps: int | None = None,
        max_token_text_ratio: float | None = 6.0,
        min_token_text_ratio: float | None = None,
        mask_stop_tokens: bool = True,
    ) -> None:
        self.model_dir = model_dir
        self.runtime_dir = runtime_dir
        self.device = device
        self.prompt_audio = prompt_audio
        self.prompt_text = prompt_text
        self.mode = mode
        self.instruction = instruction
        self.fp16 = fp16
        self.load_jit = load_jit
        self.load_trt = load_trt
        self.load_vllm = load_vllm
        self.trt_concurrent = max(1, int(trt_concurrent or 1))
        self.token_hop_len = token_hop_len
        self.token_max_hop_len = token_max_hop_len
        self.stream_scale_factor = stream_scale_factor
        self.flow_n_timesteps = flow_n_timesteps
        self.max_token_text_ratio = max_token_text_ratio
        self.min_token_text_ratio = min_token_text_ratio
        self.mask_stop_tokens = mask_stop_tokens
        self._model: Any | None = None
        self._model_lock = threading.Lock()
        self._loaded_model_kwargs: dict[str, Any] = {}
        self._streaming_tuning: dict[str, Any] = {}
        self._flow_tuning: dict[str, Any] = {}
        self._llm_token_ratio_tuning: dict[str, Any] = {}
        self._llm_stop_token_patch: dict[str, Any] = {}

    def model(self) -> Any:
        if self._model is not None:
            return self._model
        runtime = Path(self.runtime_dir).expanduser().resolve()
        matcha = runtime / "third_party" / "Matcha-TTS"
        for path in (runtime, matcha):
            if str(path) not in sys.path:
                sys.path.insert(0, str(path))
        _patch_cosyvoice_load_wav()
        try:
            from cosyvoice.cli.cosyvoice import AutoModel
            _patch_cosyvoice_autocast_fp16_trt()
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
            "load_jit": self.load_jit,
            "load_trt": self.load_trt,
            "load_vllm": self.load_vllm,
            "fp16": self.fp16,
            "trt_concurrent": self.trt_concurrent,
        }
        self._model, self._loaded_model_kwargs = _instantiate_automodel(AutoModel, model_kwargs)
        flow_half_applied = False
        if self.load_trt and self.fp16:
            flow_half_applied = ensure_cosyvoice_flow_half(self._model)
        self._apply_runtime_tuning()
        # Keep the service zero-shot first so it does not require precomputed spk2info.pt.
        print(
            "loaded cosyvoice "
            f"model={self.model_dir} runtime={runtime} device={self.device} "
            f"fp16={self.fp16} load_jit={self.load_jit} load_trt={self.load_trt} "
            f"load_vllm={self.load_vllm} trt_concurrent={self.trt_concurrent} "
            f"flow_half_applied={flow_half_applied} "
            f"seconds={time.perf_counter() - t0:.3f}",
            flush=True,
        )
        return self._model

    def _apply_runtime_tuning(self) -> None:
        if self._model is None:
            return
        self._streaming_tuning = apply_streaming_tuning(
            self._model,
            token_hop_len=self.token_hop_len,
            token_max_hop_len=self.token_max_hop_len,
            stream_scale_factor=self.stream_scale_factor,
        )
        self._flow_tuning = apply_flow_tuning(self._model, n_timesteps=self.flow_n_timesteps)
        self._llm_token_ratio_tuning = apply_llm_token_ratio_patch(
            self._model,
            max_token_text_ratio=self.max_token_text_ratio,
            min_token_text_ratio=self.min_token_text_ratio,
        )
        self._llm_stop_token_patch = (
            apply_llm_stop_token_patch(self._model)
            if self.mask_stop_tokens
            else {"applied": {}, "effective": current_llm_stop_token_patch(self._model)}
        )
        print(
            "cosyvoice tuning "
            f"streaming={self._streaming_tuning} flow={self._flow_tuning} "
            f"llm_token_ratio={self._llm_token_ratio_tuning} "
            f"llm_stop_token_patch={self._llm_stop_token_patch}",
            flush=True,
        )

    def health_payload(self) -> dict[str, Any]:
        model = self._model
        return {
            "status": "ok",
            "model_dir": self.model_dir,
            "runtime_dir": self.runtime_dir,
            "device": self.device,
            "loaded": model is not None,
            "mode": self.mode,
            "runtime_flags": {
                "fp16": self.fp16,
                "load_jit": self.load_jit,
                "load_trt": self.load_trt,
                "load_vllm": self.load_vllm,
                "trt_concurrent": self.trt_concurrent,
                "loaded_model_kwargs": self._loaded_model_kwargs,
            },
            "streaming": current_streaming_tuning(model) if model is not None else self._streaming_tuning,
            "flow": current_flow_tuning(model) if model is not None else self._flow_tuning,
            "llm_token_ratio": current_llm_token_ratio_tuning(model) if model is not None else self._llm_token_ratio_tuning,
            "llm_stop_token_patch": current_llm_stop_token_patch(model) if model is not None else self._llm_stop_token_patch,
            "runtime": current_runtime_info(model) if model is not None else {},
            "runtime_packages": runtime_package_versions(
                "transformers",
                "tokenizers",
                "torch",
                "torchaudio",
                "numpy",
                "onnxruntime-gpu",
                "onnxruntime",
            ),
        }

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
        with self._model_lock:
            for item in _with_request_streaming_tuning(model, iterator):
                speech = item.get("tts_speech") if isinstance(item, dict) else item
                if hasattr(speech, "detach"):
                    speech = speech.detach().cpu().numpy()
                parts.append(np.asarray(speech, dtype=np.float32).reshape(-1))
        if not parts:
            raise HTTPException(status_code=502, detail="CosyVoice returned no audio")
        wav_bytes = self._to_wav_bytes(np.concatenate(parts), sample_rate)
        return wav_bytes, sample_rate, time.perf_counter() - t0

    def _streaming_iterator(self, req: SynthesizeRequest) -> tuple[Iterator[Any], int, int, float, Any]:
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
        return iterator, source_sr, target_sr, t0, model

    def synthesize_pcm_stream(self, req: SynthesizeRequest) -> tuple[Iterator[bytes], int]:
        iterator, source_sr, target_sr, t0, model = self._streaming_iterator(req)

        def generate() -> Iterator[bytes]:
            first = True
            chunks = 0
            samples = 0
            with self._model_lock:
                tuned_iterator = _with_request_streaming_tuning(model, iterator)
                for item in tuned_iterator:
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
        # Exhaust the stream so CosyVoice releases its request state and model lock.
        stream, _sr = self.synthesize_pcm_stream(req)
        for _chunk in stream:
            pass


def create_app(service: CosyVoiceService) -> FastAPI:
    app = FastAPI(title="OpenTalking Local CosyVoice Service")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return service.health_payload()

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


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_optional_int(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    value = int(raw)
    return value if value > 0 else None


def _env_optional_float(name: str, default: float | None = None) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    value = float(raw)
    return value if value > 0 else None


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
        load_jit=_env_bool("OPENTALKING_TTS_LOCAL_COSYVOICE_LOAD_JIT", False),
        load_trt=_env_bool("OPENTALKING_TTS_LOCAL_COSYVOICE_LOAD_TRT", False),
        load_vllm=_env_bool("OPENTALKING_TTS_LOCAL_COSYVOICE_LOAD_VLLM", False),
        trt_concurrent=int(os.environ.get("OPENTALKING_TTS_LOCAL_COSYVOICE_TRT_CONCURRENT", "1") or "1"),
        token_hop_len=_env_optional_int("OPENTALKING_TTS_LOCAL_COSYVOICE_TOKEN_HOP_LEN"),
        token_max_hop_len=_env_optional_int("OPENTALKING_TTS_LOCAL_COSYVOICE_TOKEN_MAX_HOP_LEN"),
        stream_scale_factor=_env_optional_int("OPENTALKING_TTS_LOCAL_COSYVOICE_STREAM_SCALE_FACTOR"),
        flow_n_timesteps=_env_optional_int("OPENTALKING_TTS_LOCAL_COSYVOICE_FLOW_N_TIMESTEPS"),
        max_token_text_ratio=_env_optional_float("OPENTALKING_TTS_LOCAL_COSYVOICE_MAX_TOKEN_TEXT_RATIO", 6.0),
        min_token_text_ratio=_env_optional_float("OPENTALKING_TTS_LOCAL_COSYVOICE_MIN_TOKEN_TEXT_RATIO"),
        mask_stop_tokens=_env_bool("OPENTALKING_TTS_LOCAL_COSYVOICE_MASK_STOP_TOKENS", True),
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
