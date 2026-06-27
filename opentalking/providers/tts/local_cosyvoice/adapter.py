from __future__ import annotations

import asyncio
import inspect
import importlib
import io
import json
import os
import wave
from collections.abc import AsyncIterator, Iterable
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from opentalking.core.types.frames import AudioChunk
from opentalking.providers.tts.voice_assets import (
    LOCAL_COSYVOICE_PROVIDER,
    local_audio_model_root,
    resolve_voice_asset,
)


def _settings_value(name: str, default: str = "") -> str:
    try:
        from opentalking.core.config import get_settings

        value = getattr(get_settings(), name, default)
        if value is not None and str(value).strip():
            return str(value).strip()
    except Exception:
        pass
    return default


def _model_aliases(model: str | None) -> set[str]:
    value = str(model or "").strip().strip("/").replace("\\", "/")
    if not value:
        return set()
    aliases = {value, value.replace("/", "__")}
    name = Path(value).name
    if name:
        aliases.add(name)
        if "__" in name:
            aliases.add(name.replace("__", "/"))
    return aliases


def _models_match(left: str | None, right: str | None) -> bool:
    return bool(_model_aliases(left) & _model_aliases(right))


def _parse_service_url_map(raw: str) -> dict[str, str]:
    text = raw.strip()
    if not text:
        return {}
    if text.startswith("{"):
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("local CosyVoice service URL map must be a JSON object")
        return {str(k).strip(): str(v).strip() for k, v in parsed.items() if str(k).strip() and str(v).strip()}
    out: dict[str, str] = {}
    for entry in text.replace("\n", ",").replace(";", ",").split(","):
        item = entry.strip()
        if not item:
            continue
        key, sep, value = item.partition("=")
        if not sep:
            raise ValueError(f"invalid local CosyVoice service URL map entry: {item!r}")
        key = key.strip()
        value = value.strip()
        if key and value:
            out[key] = value
    return out


def _service_url_map() -> dict[str, str]:
    raw = (
        os.environ.get("OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URLS", "").strip()
        or _settings_value("tts_local_cosyvoice_service_urls", "")
    )
    return _parse_service_url_map(raw)


def _resolve_service_url_for_model(model: str, default_model: str, default_url: str) -> str:
    urls = _service_url_map()
    if not urls:
        return default_url
    for key, url in urls.items():
        if _models_match(model, key):
            return url
    if default_url and _models_match(model, default_model):
        return default_url
    raise RuntimeError(
        f"No local CosyVoice service URL configured for model {model!r}. "
        "Set OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URLS or omit tts_model to use the default local model."
    )


def _model_root() -> Path:
    return local_audio_model_root()


def _resolve_model_path(model: str) -> str:
    path = Path(model).expanduser()
    if path.exists():
        return str(path)
    return str(_model_root() / model.replace("/", "__"))


def _resolve_local_voice_prompt(voice: str | None) -> dict[str, str] | None:
    voice_id = (voice or "").strip()
    if not voice_id or voice_id == "local-default":
        return None
    if not all(ch.isalnum() or ch in {"_", "-"} for ch in voice_id):
        return None
    asset = resolve_voice_asset(
        voice_id,
        provider=LOCAL_COSYVOICE_PROVIDER,
        sources=("clones", "system"),
        model_root=_model_root(),
        require_prompt_text=True,
    )
    if asset is None or asset.prompt_text is None:
        return None
    result = {"prompt_audio": str(asset.prompt_audio)}
    try:
        text = asset.prompt_text.read_text(encoding="utf-8").strip()
    except OSError:
        text = ""
    if text:
        result["prompt_text"] = text
    for key in ("mode", "instruction"):
        value = str(asset.meta.get(key) or "").strip()
        if value:
            result[key] = value
    if result.get("prompt_text") or result.get("mode") in {"cross_lingual", "instruct"}:
        return result
    return None


class LocalCosyVoiceInputError(ValueError):
    """Invalid local CosyVoice request, usually an unavailable prompt voice."""


def _is_service_default_voice(voice: str | None) -> bool:
    voice_id = (voice or "").strip()
    return not voice_id or voice_id == "local-default"


def _service_default_prompt_configured() -> bool:
    mode = os.environ.get("OPENTALKING_TTS_LOCAL_COSYVOICE_MODE", "zero_shot").strip().lower()
    prompt_audio = os.environ.get("OPENTALKING_TTS_LOCAL_COSYVOICE_PROMPT_AUDIO", "").strip()
    prompt_text = os.environ.get("OPENTALKING_TTS_LOCAL_COSYVOICE_PROMPT_TEXT", "").strip()
    if mode in {"cross_lingual", "instruct"}:
        return bool(prompt_audio)
    return bool(prompt_audio and prompt_text)


def _missing_local_voice_message(voice: str | None) -> str:
    voice_text = (voice or "").strip() or "未选择"
    return f"本地 CosyVoice 音色 {voice_text!r} 没有可用 prompt；请先选择本地音色。"


def _local_cosyvoice_http_400_message(*, voice: str | None, service_url: str, detail: str) -> str:
    suffix = f" sidecar detail: {detail.strip()}" if detail.strip() else ""
    return (
        f"本地 CosyVoice 请求无效：{_missing_local_voice_message(voice)} "
        f"HTTP 400 from {service_url}.{suffix}"
    ).strip()


def _env_device() -> str:
    return (
        os.environ.get("OPENTALKING_TTS_LOCAL_COSYVOICE_DEVICE", "").strip()
        or _settings_value("tts_local_cosyvoice_device", "")
        or os.environ.get("OPENTALKING_LOCAL_TTS_DEVICE", "").strip()
        or os.environ.get("OPENTALKING_LOCAL_AUDIO_DEVICE", "").strip()
        or _settings_value("local_audio_device", "cpu")
        or "cpu"
    )


def _local_cosyvoice_bool(field: str, settings_name: str, default: bool) -> bool:
    raw = os.environ.get(f"OPENTALKING_TTS_LOCAL_COSYVOICE_{field}", "").strip()
    if not raw:
        raw = _settings_value(settings_name, "")
    if not raw:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _local_cosyvoice_int(field: str, settings_name: str, default: int) -> int:
    raw = os.environ.get(f"OPENTALKING_TTS_LOCAL_COSYVOICE_{field}", "").strip()
    if not raw:
        raw = _settings_value(settings_name, "")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _local_cosyvoice_fp16(device: str) -> bool:
    raw = (
        os.environ.get("OPENTALKING_TTS_LOCAL_COSYVOICE_FP16", "").strip()
        or _settings_value("tts_local_cosyvoice_fp16", "")
        or "auto"
    ).lower()
    if raw == "auto":
        return device.startswith("cuda")
    return raw in {"1", "true", "yes", "on"}


def _instantiate_cosyvoice_runtime(cls: Any, model_dir: str, kwargs: dict[str, Any]) -> Any:
    runtime_kwargs = dict(kwargs)
    optional_keys = ("load_vllm", "trt_concurrent", "load_jit", "load_trt", "fp16")
    while True:
        try:
            return cls(model_dir, **runtime_kwargs)
        except TypeError as exc:
            text = str(exc)
            unsupported = next((key for key in optional_keys if key in runtime_kwargs and key in text), None)
            if unsupported is None:
                raise
            runtime_kwargs.pop(unsupported)


def _audio_format_from_content_type(content_type: str | None) -> str | None:
    value = (content_type or "").split(";", 1)[0].strip().lower()
    if value in {"audio/wav", "audio/wave", "audio/x-wav"}:
        return "wav"
    if value in {"audio/l16", "audio/pcm", "application/octet-stream"}:
        return "pcm"
    if value in {"audio/mpeg", "audio/mp3"}:
        return "mp3"
    return None


def _resample_linear(pcm: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    pcm = np.asarray(pcm, dtype=np.int16).reshape(-1)
    if pcm.size == 0 or src_sr == dst_sr:
        return pcm.copy()
    pcm_f = pcm.astype(np.float32) / 32768.0
    n_dst = max(1, int(round(pcm.size * dst_sr / src_sr)))
    xi = np.linspace(0.0, pcm.size - 1.0, num=n_dst)
    out = np.interp(xi, np.arange(pcm.size), pcm_f)
    return np.clip(np.round(out * 32768.0), -32768, 32767).astype(np.int16)


def _float_audio_to_i16(audio: Any) -> np.ndarray:
    arr = np.asarray(audio, dtype=np.float32).reshape(-1)
    if arr.size == 0:
        return np.zeros(0, dtype=np.int16)
    if np.max(np.abs(arr)) > 1.5:
        return np.clip(arr, -32768, 32767).astype(np.int16)
    return np.clip(np.round(arr * 32768.0), -32768, 32767).astype(np.int16)


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


class LocalCosyVoiceTTSAdapter:
    """Local CosyVoice adapter.

    Supports either a same-host local service URL or an in-process CosyVoice
    Python runtime when that package is installed.
    """

    def __init__(
        self,
        default_voice: str | None = None,
        sample_rate: int = 16000,
        chunk_ms: float = 20.0,
        *,
        model: str | None = None,
    ) -> None:
        self.default_voice = default_voice or "local-default"
        self.sample_rate = sample_rate
        self.chunk_ms = chunk_ms
        self.default_model = (
            os.environ.get("OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL")
            or _settings_value("tts_local_cosyvoice_model", "")
            or "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"
        ).strip()
        self.model = (model or self.default_model).strip()
        self.model_dir = (
            os.environ.get("OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL_DIR", "").strip()
            or _settings_value("tts_local_cosyvoice_model_dir", "")
            or _resolve_model_path(self.model)
        )
        self.runtime_dir = (
            os.environ.get("OPENTALKING_TTS_LOCAL_COSYVOICE_RUNTIME_DIR", "").strip()
            or _settings_value("tts_local_cosyvoice_runtime_dir", "")
        )
        default_service_url = (
            os.environ.get("OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL", "").strip()
            or _settings_value("tts_local_cosyvoice_service_url", "")
        )
        self.service_url = _resolve_service_url_for_model(
            self.model,
            self.default_model,
            default_service_url,
        )
        self.device = _env_device()
        self.load_jit = _local_cosyvoice_bool("LOAD_JIT", "tts_local_cosyvoice_load_jit", False)
        self.load_trt = _local_cosyvoice_bool("LOAD_TRT", "tts_local_cosyvoice_load_trt", False)
        self.load_vllm = _local_cosyvoice_bool("LOAD_VLLM", "tts_local_cosyvoice_load_vllm", False)
        self.fp16 = _local_cosyvoice_fp16(self.device)
        self.trt_concurrent = max(
            1,
            _local_cosyvoice_int("TRT_CONCURRENT", "tts_local_cosyvoice_trt_concurrent", 1),
        )
        self._engine: Any | None = None
        self._voice_payload_cache: dict[str, dict[str, str]] = {}

    async def synthesize_stream(self, text: str, voice: str | None = None) -> AsyncIterator[AudioChunk]:
        if not text.strip():
            return
        if self.service_url:
            async for chunk in self._synthesize_via_service(text, voice=voice):
                yield chunk
            return
        chunks = await asyncio.to_thread(self._synthesize_in_process, text, voice or self.default_voice)
        for chunk in chunks:
            yield chunk

    async def _synthesize_via_service(self, text: str, voice: str | None = None) -> AsyncIterator[AudioChunk]:
        timeout = httpx.Timeout(connect=30.0, read=600.0, write=30.0, pool=30.0)
        effective_voice = voice or self.default_voice
        payload = {
            "text": text,
            "voice": effective_voice,
            "model": self.model,
            "sample_rate": self.sample_rate,
        }
        local_prompt = _resolve_local_voice_prompt(effective_voice)
        if local_prompt is not None:
            payload.update(local_prompt)
            payload["zero_shot_spk_id"] = effective_voice
        elif not _is_service_default_voice(effective_voice):
            raise LocalCosyVoiceInputError(_missing_local_voice_message(effective_voice))
        try:
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
                        raw = await resp.aread()
                        with wave.open(io.BytesIO(raw), "rb") as wf:
                            source_sr = int(wf.getframerate())
                            channels = int(wf.getnchannels())
                            sample_width = int(wf.getsampwidth())
                            pcm_bytes = wf.readframes(wf.getnframes())
                        if sample_width != 2:
                            raise RuntimeError(f"Unsupported WAV sample width for local CosyVoice: {sample_width}")
                        pcm = np.frombuffer(pcm_bytes, dtype="<i2").astype(np.int16, copy=False)
                        if channels > 1:
                            frame_count = pcm.size // channels
                            pcm = (
                                pcm[: frame_count * channels]
                                .reshape(frame_count, channels)
                                .mean(axis=1)
                                .astype(np.int16)
                            )
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
        except httpx.HTTPStatusError as exc:
            detail = ""
            try:
                detail = exc.response.text[:500]
            except Exception:
                detail = ""
            if exc.response.status_code == 400:
                raise LocalCosyVoiceInputError(
                    _local_cosyvoice_http_400_message(
                        voice=effective_voice,
                        service_url=self.service_url,
                        detail=detail,
                    )
                ) from exc
            if "CosyVoice returned no audio" in detail:
                raise RuntimeError(
                    "本地 CosyVoice 返回空音频，模型推理状态异常；请重启本地 TTS 服务后重试。"
                    f" HTTP {exc.response.status_code} from {self.service_url}. {detail}".strip()
                ) from exc
            raise RuntimeError(
                "本地 CosyVoice 服务不可用（可能已退出/内存不足）。"
                f" HTTP {exc.response.status_code} from {self.service_url}. {detail}".strip()
            ) from exc
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
            raise RuntimeError(
                "本地 CosyVoice 服务不可用（可能已退出/内存不足）。"
                f" 无法连接或读取 {self.service_url}: {type(exc).__name__}: {exc}"
            ) from exc

    def _load_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        try:
            cosyvoice_module = importlib.import_module("cosyvoice.cli.cosyvoice")
        except ImportError as exc:
            raise RuntimeError(
                "Local CosyVoice requires a local service URL or the CosyVoice Python package. "
                "Set OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL, or install the local-audio runtime."
            ) from exc
        model_dir = self.model_dir or _resolve_model_path(self.model)
        kwargs: dict[str, Any] = {
            "load_jit": self.load_jit,
            "load_trt": self.load_trt,
            "load_vllm": self.load_vllm,
            "fp16": self.fp16,
            "trt_concurrent": self.trt_concurrent,
        }
        model_lower = self.model.lower()
        if "cosyvoice3" in model_lower:
            cls = getattr(cosyvoice_module, "AutoModel")
        elif "cosyvoice2" in model_lower:
            cls = getattr(cosyvoice_module, "CosyVoice2")
        else:
            cls = getattr(cosyvoice_module, "CosyVoice")
        self._engine = _instantiate_cosyvoice_runtime(cls, model_dir, kwargs)
        return self._engine

    def _available_voice(self, engine: Any, requested: str) -> str:
        if requested and requested != "local-default":
            return requested
        list_spks = getattr(engine, "list_available_spks", None)
        if callable(list_spks):
            speakers = list_spks()
            if isinstance(speakers, Iterable):
                for item in speakers:
                    if item:
                        return str(item)
        return requested or "中文女"

    def _callable_supports_keyword(self, fn: Any, keyword: str) -> bool:
        try:
            signature = inspect.signature(fn)
        except (TypeError, ValueError):
            return False
        return keyword in signature.parameters or any(
            param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()
        )

    def _resolved_voice_payload(self, voice: str | None) -> tuple[str | None, dict[str, str] | None]:
        voice_id = (voice or "").strip()
        if not voice_id or voice_id == "local-default":
            return None, None
        cached = self._voice_payload_cache.get(voice_id)
        if cached is not None:
            return voice_id, dict(cached)
        payload = _resolve_local_voice_prompt(voice_id)
        if payload is None:
            return voice_id, None
        self._voice_payload_cache[voice_id] = dict(payload)
        return voice_id, payload

    def _synthesize_in_process(self, text: str, voice: str) -> list[AudioChunk]:
        engine = self._load_engine()
        spk_id = self._available_voice(engine, voice)
        infer = getattr(engine, "inference_sft", None)
        if not callable(infer):
            raise RuntimeError("CosyVoice runtime does not expose inference_sft().")
        sr = int(getattr(engine, "sample_rate", 22050) or 22050)
        pcm_parts: list[np.ndarray] = []
        voice_id, payload = self._resolved_voice_payload(spk_id)
        if payload is not None:
            add_zero_shot_spk = getattr(engine, "add_zero_shot_spk", None)
            if callable(add_zero_shot_spk):
                try:
                    prompt_text = payload.get("prompt_text", "")
                    prompt_audio = payload["prompt_audio"]
                    if self._callable_supports_keyword(add_zero_shot_spk, "zero_shot_spk_id"):
                        add_zero_shot_spk(prompt_text, prompt_audio, zero_shot_spk_id=voice_id)
                    else:
                        add_zero_shot_spk(prompt_text, prompt_audio, voice_id)
                    save_spkinfo = getattr(engine, "save_spkinfo", None)
                    if callable(save_spkinfo):
                        save_spkinfo()
                except Exception:
                    pass
        if payload is not None and self._callable_supports_keyword(infer, "zero_shot_spk_id"):
            iterator = infer(text, "", "", stream=False, zero_shot_spk_id=voice_id)
        elif payload is not None:
            iterator = infer(
                text,
                payload.get("prompt_text", ""),
                payload["prompt_audio"],
                stream=False,
            )
        else:
            iterator = infer(text, spk_id, stream=False)
        for item in iterator:
            speech = item.get("tts_speech") if isinstance(item, dict) else item
            if hasattr(speech, "detach"):
                speech = speech.detach().cpu().numpy()
            pcm_parts.append(_float_audio_to_i16(speech))
        if not pcm_parts:
            return []
        pcm = np.concatenate(pcm_parts).astype(np.int16, copy=False)
        pcm = _resample_linear(pcm, sr, self.sample_rate)
        return _split_pcm_chunks(pcm, self.sample_rate, self.chunk_ms)
