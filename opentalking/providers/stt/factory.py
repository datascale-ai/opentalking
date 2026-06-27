"""Speech-to-text provider selection for DashScope and local STT runtimes."""

from __future__ import annotations

import os
import queue
import re
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np

STT_PROVIDERS = frozenset({"dashscope", "openai_compatible", "xiaomi_mimo", "funasr", "sensevoice", "sherpa_onnx"})
LOCAL_STT_PROVIDERS = frozenset({"funasr", "sensevoice", "sherpa_onnx"})
_SENSEVOICE_TAG_RE = re.compile(r"<\|[^|<>]+\|>")


def _clean_text(text: str) -> str:
    return _SENSEVOICE_TAG_RE.sub("", text).strip()


_ADAPTER_CACHE: dict[tuple[str, str, str, str, str], object] = {}
_ADAPTER_CACHE_LOCK = threading.Lock()


def normalize_stt_provider(value: str | None, *, default: str | None = None) -> str | None:
    provider = (value or "").strip().lower()
    if not provider:
        return default
    if provider not in STT_PROVIDERS:
        raise ValueError(f"unsupported stt provider: {value}")
    return provider


def _settings_value(name: str, default: str = "") -> str:
    try:
        from opentalking.core.config import get_settings

        value = getattr(get_settings(), name, default)
        if value is not None and str(value).strip():
            return str(value).strip()
    except Exception:
        pass
    return default


def _provider_env(provider: str, field: str) -> str:
    key_provider = provider.upper().replace("-", "_")
    return os.environ.get(f"OPENTALKING_STT_{key_provider}_{field}", "").strip()


def _provider() -> str:
    for raw in (
        os.environ.get("OPENTALKING_STT_DEFAULT_PROVIDER", ""),
        _settings_value("stt_default_provider", ""),
        os.environ.get("OPENTALKING_STT_PROVIDER", ""),
        _settings_value("stt_provider", ""),
    ):
        value = str(raw or "").strip()
        if value:
            return normalize_stt_provider(value, default="dashscope") or "dashscope"
    return "dashscope"


def _model_root() -> Path:
    raw = (
        os.environ.get("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", "").strip()
        or _settings_value("local_audio_model_root", "")
        or "./models/local-audio"
    )
    return Path(raw).expanduser()


def _device() -> str:
    return _device_for_provider(_provider())


def _device_for_provider(provider: str) -> str:
    for value in (
        _provider_env(provider, "DEVICE"),
        _settings_value(f"stt_{provider}_device", ""),
        os.environ.get("OPENTALKING_STT_DEVICE", ""),
        os.environ.get("OPENTALKING_LOCAL_AUDIO_DEVICE", ""),
        _settings_value("stt_device", ""),
        _settings_value("local_audio_device", ""),
    ):
        device = str(value or "").strip()
        if device and device != "auto":
            return device
    return "auto"


def _openai_stt_base_url() -> str:
    return (
        _provider_env("openai", "BASE_URL")
        or os.environ.get("OPENTALKING_STT_OPENAI_BASE_URL", "").strip()
        or _settings_value("stt_openai_base_url", "")
    ).rstrip("/")


def _openai_stt_api_key() -> str:
    return (
        _provider_env("openai", "API_KEY")
        or os.environ.get("OPENTALKING_STT_OPENAI_API_KEY", "").strip()
        or _settings_value("stt_openai_api_key", "")
    )


def _openai_stt_language() -> str:
    return (
        _provider_env("openai", "LANGUAGE")
        or os.environ.get("OPENTALKING_STT_OPENAI_LANGUAGE", "").strip()
        or _settings_value("stt_openai_language", "")
    )


def _openai_stt_response_format() -> str:
    return (
        _provider_env("openai", "RESPONSE_FORMAT")
        or os.environ.get("OPENTALKING_STT_OPENAI_RESPONSE_FORMAT", "").strip()
        or _settings_value("stt_openai_response_format", "")
        or "json"
    )


def _openai_stt_protocol() -> str:
    return (
        _provider_env("openai", "PROTOCOL")
        or os.environ.get("OPENTALKING_STT_OPENAI_PROTOCOL", "").strip()
        or _settings_value("stt_openai_protocol", "")
        or "audio_transcriptions"
    )


def _openai_stt_audio_format() -> str:
    return (
        _provider_env("openai", "AUDIO_FORMAT")
        or os.environ.get("OPENTALKING_STT_OPENAI_AUDIO_FORMAT", "").strip()
        or _settings_value("stt_openai_audio_format", "")
        or "wav"
    )


def _xiaomi_stt_base_url() -> str:
    return (
        _provider_env("xiaomi", "BASE_URL")
        or _provider_env("xiaomi_mimo", "BASE_URL")
        or os.environ.get("OPENTALKING_STT_XIAOMI_BASE_URL", "").strip()
        or os.environ.get("OPENTALKING_STT_XIAOMI_MIMO_BASE_URL", "").strip()
        or _settings_value("stt_xiaomi_base_url", "")
        or _settings_value("stt_xiaomi_mimo_base_url", "")
    ).rstrip("/")


def _xiaomi_stt_api_key() -> str:
    return (
        _provider_env("xiaomi", "API_KEY")
        or _provider_env("xiaomi_mimo", "API_KEY")
        or os.environ.get("OPENTALKING_STT_XIAOMI_API_KEY", "").strip()
        or os.environ.get("OPENTALKING_STT_XIAOMI_MIMO_API_KEY", "").strip()
        or _settings_value("stt_xiaomi_api_key", "")
        or _settings_value("stt_xiaomi_mimo_api_key", "")
    )


def _xiaomi_stt_language() -> str:
    return (
        _provider_env("xiaomi", "LANGUAGE")
        or _provider_env("xiaomi_mimo", "LANGUAGE")
        or os.environ.get("OPENTALKING_STT_XIAOMI_LANGUAGE", "").strip()
        or os.environ.get("OPENTALKING_STT_XIAOMI_MIMO_LANGUAGE", "").strip()
        or _settings_value("stt_xiaomi_language", "")
        or _settings_value("stt_xiaomi_mimo_language", "")
    )


def _xiaomi_stt_response_format() -> str:
    return (
        _provider_env("xiaomi", "RESPONSE_FORMAT")
        or _provider_env("xiaomi_mimo", "RESPONSE_FORMAT")
        or os.environ.get("OPENTALKING_STT_XIAOMI_RESPONSE_FORMAT", "").strip()
        or os.environ.get("OPENTALKING_STT_XIAOMI_MIMO_RESPONSE_FORMAT", "").strip()
        or _settings_value("stt_xiaomi_response_format", "")
        or _settings_value("stt_xiaomi_mimo_response_format", "")
        or "json"
    )


def _xiaomi_stt_protocol() -> str:
    return (
        _provider_env("xiaomi", "PROTOCOL")
        or _provider_env("xiaomi_mimo", "PROTOCOL")
        or os.environ.get("OPENTALKING_STT_XIAOMI_PROTOCOL", "").strip()
        or os.environ.get("OPENTALKING_STT_XIAOMI_MIMO_PROTOCOL", "").strip()
        or _settings_value("stt_xiaomi_protocol", "")
        or _settings_value("stt_xiaomi_mimo_protocol", "")
        or "chat_completions"
    )


def _xiaomi_stt_audio_format() -> str:
    return (
        _provider_env("xiaomi", "AUDIO_FORMAT")
        or _provider_env("xiaomi_mimo", "AUDIO_FORMAT")
        or os.environ.get("OPENTALKING_STT_XIAOMI_AUDIO_FORMAT", "").strip()
        or os.environ.get("OPENTALKING_STT_XIAOMI_MIMO_AUDIO_FORMAT", "").strip()
        or _settings_value("stt_xiaomi_audio_format", "")
        or _settings_value("stt_xiaomi_mimo_audio_format", "")
        or "wav"
    )


def _stt_model(provider: str) -> str:
    provider = normalize_stt_provider(provider, default="dashscope") or "dashscope"
    if provider == "funasr":
        return (
            _provider_env("funasr", "MODEL")
            or _settings_value("stt_funasr_model", "")
            or os.environ.get("OPENTALKING_STT_MODEL", "").strip()
            or _settings_value("stt_model", "")
            or "iic/Fun-ASR-Nano-2512"
        )
    if provider == "sensevoice":
        return (
            _provider_env("sensevoice", "MODEL")
            or _settings_value("stt_sensevoice_model", "")
            or "iic/SenseVoiceSmall"
        )
    if provider == "openai_compatible":
        return (
            _provider_env("openai", "MODEL")
            or os.environ.get("OPENTALKING_STT_OPENAI_MODEL", "").strip()
            or _settings_value("stt_openai_model", "")
            or "whisper-1"
        )
    if provider == "xiaomi_mimo":
        return (
            _provider_env("xiaomi", "MODEL")
            or _provider_env("xiaomi_mimo", "MODEL")
            or os.environ.get("OPENTALKING_STT_XIAOMI_MODEL", "").strip()
            or os.environ.get("OPENTALKING_STT_XIAOMI_MIMO_MODEL", "").strip()
            or _settings_value("stt_xiaomi_model", "")
            or _settings_value("stt_xiaomi_mimo_model", "")
            or "mimo-v2.5-asr"
        )
    if provider == "sherpa_onnx":
        return (
            _provider_env("sherpa_onnx", "MODEL")
            or _settings_value("stt_sherpa_onnx_model", "")
            or os.environ.get("OPENTALKING_STT_MODEL", "").strip()
            or _settings_value("stt_model", "")
        )
    return (
        _provider_env("dashscope", "MODEL")
        or _settings_value("stt_dashscope_model", "")
        or os.environ.get("OPENTALKING_STT_MODEL", "").strip()
        or _settings_value("stt_model", "")
        or "paraformer-realtime-v2"
    )


def _stt_model_dir(provider: str, model: str | None = None) -> str:
    provider = normalize_stt_provider(provider, default="dashscope") or "dashscope"
    direct = _provider_env(provider, "MODEL_DIR") or _settings_value(f"stt_{provider}_model_dir", "")
    if direct:
        return str(Path(direct).expanduser().resolve())
    if provider in LOCAL_STT_PROVIDERS:
        return str(_local_path_for_model((model or _stt_model(provider)).strip()))
    return ""


def _local_path_for_model(model: str) -> Path:
    path = Path(model).expanduser()
    if path.is_absolute():
        return path.resolve()
    root = _model_root().expanduser()
    if path.exists():
        return path.resolve()
    if "/" in model:
        return (root / model.replace("/", "__")).resolve()
    return (root / model).resolve()


def _write_pcm_queue_to_wav(
    chunk_queue: "queue.Queue[bytes | None]",
    wav_path: Path,
    *,
    sample_rate: int = 16000,
) -> None:
    chunks: list[bytes] = []
    while True:
        chunk = chunk_queue.get()
        if chunk is None:
            break
        if chunk:
            chunks.append(bytes(chunk))
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"".join(chunks))


def _extract_text(result: Any) -> str:
    if isinstance(result, str):
        return _clean_text(result)
    if isinstance(result, dict):
        text = result.get("text") or result.get("sentence")
        if isinstance(text, str):
            return _clean_text(text)
    if isinstance(result, list):
        return "".join(filter(None, (_extract_text(item) for item in result))).strip()
    return ""


class LocalFunASRSTTAdapter:
    """FunASR/SenseVoice local adapter loaded lazily on first transcription."""

    def __init__(
        self,
        *,
        provider: str,
        model: str | None = None,
        model_dir: str | None = None,
        device: str | None = None,
    ) -> None:
        self.provider = provider
        self.model = (model or _stt_model(provider)).strip()
        self.model_dir = (model_dir or _stt_model_dir(provider, self.model)).strip()
        self.device = (device or _device_for_provider(provider)).strip() or "auto"
        self.model_root = _model_root()
        self._runtime: Any | None = None

    def _runtime_model_name(self) -> str:
        if self.model_dir:
            return str(Path(self.model_dir).expanduser().resolve())
        local_path = _local_path_for_model(self.model)
        return str(local_path)

    def _load_runtime(self) -> Any:
        if self._runtime is not None:
            return self._runtime
        try:
            from funasr import AutoModel
        except ImportError as exc:
            raise RuntimeError(
                "FunASR local STT requires the local-audio extra: "
                "uv sync --extra dev --extra models --extra local-audio"
            ) from exc

        kwargs: dict[str, Any] = {}
        if self.device and self.device != "auto":
            kwargs["device"] = self.device
        kwargs["disable_update"] = True
        self._runtime = AutoModel(model=self._runtime_model_name(), **kwargs)
        return self._runtime

    def transcribe_wav(self, wav_path: str | Path) -> tuple[str, float]:
        model = self._load_runtime()
        t0 = time.perf_counter()
        result = model.generate(input=str(wav_path), language="auto", use_itn=True)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return _extract_text(result), elapsed_ms

    def transcribe_pcm_queue(
        self,
        chunk_queue: "queue.Queue[bytes | None]",
        *,
        sample_rate: int = 16000,
    ) -> tuple[str, float]:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = Path(tmp.name)
        try:
            _write_pcm_queue_to_wav(chunk_queue, wav_path, sample_rate=sample_rate)
            return self.transcribe_wav(wav_path)
        finally:
            try:
                wav_path.unlink(missing_ok=True)
            except OSError:
                pass


class SherpaOnnxSTTAdapter:
    def __init__(self, *, model: str | None = None) -> None:
        self.model = (model or _stt_model("sherpa_onnx")).strip()

    def transcribe_wav(self, wav_path: str | Path) -> tuple[str, float]:
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError("sherpa-onnx local STT requires the local-audio extra.") from exc
        if not self.model:
            raise RuntimeError("OPENTALKING_STT_MODEL must point to a sherpa-onnx model path.")
        t0 = time.perf_counter()
        recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=self.model,
            tokens="",
            num_threads=2,
        )
        stream = recognizer.create_stream()
        samples = _read_wav_float32_mono(Path(wav_path))
        stream.accept_waveform(16000, samples)
        recognizer.decode_stream(stream)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return str(stream.result.text).strip(), elapsed_ms

    def transcribe_pcm_queue(
        self,
        chunk_queue: "queue.Queue[bytes | None]",
        *,
        sample_rate: int = 16000,
    ) -> tuple[str, float]:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = Path(tmp.name)
        try:
            _write_pcm_queue_to_wav(chunk_queue, wav_path, sample_rate=sample_rate)
            return self.transcribe_wav(wav_path)
        finally:
            try:
                wav_path.unlink(missing_ok=True)
            except OSError:
                pass


def _read_wav_float32_mono(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        channels = wf.getnchannels()
        raw = wf.readframes(wf.getnframes())
    pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1)
    if sr != 16000 and pcm.size:
        n_dst = max(1, int(round(pcm.size * 16000 / sr)))
        x_old = np.linspace(0.0, pcm.size - 1.0, num=pcm.size)
        x_new = np.linspace(0.0, pcm.size - 1.0, num=n_dst)
        pcm = np.interp(x_new, x_old, pcm).astype(np.float32)
    return pcm


def create_stt_adapter(provider: str | None = None):
    selected = normalize_stt_provider(provider, default=None) or _provider()
    model = _stt_model(selected)
    model_dir = _stt_model_dir(selected, model)
    device = _device_for_provider(selected)
    cache_key = (selected, model, model_dir, device, str(_model_root()))
    with _ADAPTER_CACHE_LOCK:
        cached = _ADAPTER_CACHE.get(cache_key)
        if cached is not None:
            return cached
    if selected in {"openai_compatible", "xiaomi_mimo"}:
        from opentalking.providers.stt.openai_compatible.adapter import OpenAICompatibleSTTAdapter

        if selected == "xiaomi_mimo":
            adapter = OpenAICompatibleSTTAdapter(
                api_key=_xiaomi_stt_api_key(),
                base_url=_xiaomi_stt_base_url(),
                model=model,
                language=_xiaomi_stt_language(),
                response_format=_xiaomi_stt_response_format(),
                protocol=_xiaomi_stt_protocol(),
                audio_format=_xiaomi_stt_audio_format(),
            )
        else:
            adapter = OpenAICompatibleSTTAdapter(
                api_key=_openai_stt_api_key(),
                base_url=_openai_stt_base_url(),
                model=model,
                language=_openai_stt_language(),
                response_format=_openai_stt_response_format(),
                protocol=_openai_stt_protocol(),
                audio_format=_openai_stt_audio_format(),
            )
    elif selected in {"funasr", "sensevoice"}:
        adapter = LocalFunASRSTTAdapter(provider=selected, model=model, model_dir=model_dir, device=device)
    elif selected == "sherpa_onnx":
        adapter = SherpaOnnxSTTAdapter(model=model)
    else:
        return None
    with _ADAPTER_CACHE_LOCK:
        return _ADAPTER_CACHE.setdefault(cache_key, adapter)


def prewarm_stt_adapter(provider: str | None = None) -> bool:
    selected = normalize_stt_provider(provider, default=None) or _provider()
    if selected not in LOCAL_STT_PROVIDERS:
        return False

    adapter = create_stt_adapter(selected)
    if adapter is None:
        return False
    load_runtime = getattr(adapter, "_load_runtime", None)
    if callable(load_runtime):
        load_runtime()
    return True


def clear_stt_adapter_cache() -> None:
    with _ADAPTER_CACHE_LOCK:
        _ADAPTER_CACHE.clear()


def transcribe_wav_path_sync(wav_path: str | Path, *, provider: str | None = None) -> tuple[str, float]:
    selected = normalize_stt_provider(provider, default=None) or _provider()
    if selected == "dashscope":
        from opentalking.providers.stt.dashscope.adapter import _recognize_wav_sync

        return _recognize_wav_sync(Path(wav_path))

    adapter = create_stt_adapter(selected)
    if adapter is None:
        raise RuntimeError(f"unsupported local STT provider: {selected}")
    return adapter.transcribe_wav(wav_path)


def transcribe_pcm_chunk_queue_sync(
    chunk_queue: "queue.Queue[bytes | None]",
    *,
    sample_rate: int = 16000,
    provider: str | None = None,
) -> tuple[str, float]:
    selected = normalize_stt_provider(provider, default=None) or _provider()
    if selected == "dashscope":
        from opentalking.providers.stt.dashscope.adapter import (
            transcribe_pcm_chunk_queue_sync as dashscope_transcribe_pcm_chunk_queue_sync,
        )

        return dashscope_transcribe_pcm_chunk_queue_sync(chunk_queue)

    adapter = create_stt_adapter(selected)
    if adapter is None:
        raise RuntimeError(f"unsupported local STT provider: {selected}")
    return adapter.transcribe_pcm_queue(chunk_queue, sample_rate=sample_rate)


def stt_status(provider: str | None = None) -> dict[str, str | bool]:
    return stt_provider_config(provider or _provider())


def stt_enabled_providers() -> list[str]:
    raw = os.environ.get("OPENTALKING_STT_ENABLED_PROVIDERS", "").strip() or _settings_value(
        "stt_enabled_providers",
        "",
    )
    if not raw:
        return [_provider()]
    out: list[str] = []
    for item in raw.replace(";", ",").split(","):
        provider = normalize_stt_provider(item, default=None)
        if provider and provider not in out:
            out.append(provider)
    return out or [_provider()]


def stt_provider_config(provider: str) -> dict[str, str | bool]:
    selected = _provider()
    selected = normalize_stt_provider(provider, default=None) or selected
    model = _stt_model(selected)
    model_dir = _stt_model_dir(selected, model)
    key = ""
    service_url = ""
    if selected == "dashscope":
        key = (
            _provider_env("dashscope", "API_KEY")
            or _settings_value("stt_dashscope_api_key", "")
            or os.environ.get("OPENTALKING_STT_API_KEY", "").strip()
            or _settings_value("stt_api_key", "")
        )
    elif selected == "openai_compatible":
        key = _openai_stt_api_key()
        service_url = _openai_stt_base_url()
    elif selected == "xiaomi_mimo":
        key = _xiaomi_stt_api_key()
        service_url = _xiaomi_stt_base_url()
    config: dict[str, str | bool] = {
        "provider": selected,
        "model": model,
        "model_dir": model_dir,
        "device": _device_for_provider(selected),
        "key_set": bool(key),
        "service_url_set": bool(service_url),
    }
    if selected == "xiaomi_mimo":
        config["profile"] = "xiaomi_mimo"
    return config
