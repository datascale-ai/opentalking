"""根据环境与请求选择 TTS 后端（Edge / 百炼多种 API / ElevenLabs）。"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from opentalking.providers.tts.edge.adapter import EdgeTTSAdapter
from opentalking.providers.tts.providers import (
    CORE_TTS_PROVIDERS,
    COSYVOICE_TTS_PROVIDERS,
    LOCAL_TTS_PROVIDERS,
    QWEN_TTS_PROVIDERS,
    SAMBERT_TTS_PROVIDERS,
    normalize_tts_provider,
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


def _provider_env(provider: str, field: str) -> str:
    key_provider = provider.upper().replace("-", "_")
    return os.environ.get(f"OPENTALKING_TTS_{key_provider}_{field}", "").strip()


def _provider() -> str:
    """Return the default TTS provider. This is routing only, not fallback."""
    for raw in (
        os.environ.get("OPENTALKING_TTS_DEFAULT_PROVIDER", ""),
        _settings_value("tts_default_provider", ""),
        os.environ.get("OPENTALKING_TTS_PROVIDER", ""),
        _settings_value("tts_provider", ""),
    ):
        value = str(raw or "").strip()
        if value:
            return normalize_tts_provider(value, default="edge") or "edge"
    return "edge"


def _edge_default_voice() -> str:
    """Edge TTS 音色：Settings.tts_voice / OPENTALKING_TTS_VOICE。"""
    v = os.environ.get("OPENTALKING_TTS_EDGE_VOICE", "").strip() or _settings_value("tts_edge_voice", "")
    if not v:
        v = _settings_value("tts_voice", "") or os.environ.get("OPENTALKING_TTS_VOICE", "").strip()
    return v or "zh-CN-XiaoxiaoNeural"


def _tts_voice_for_log_dashscope() -> str:
    return (
        os.environ.get("OPENTALKING_TTS_DASHSCOPE_VOICE", "").strip()
        or _settings_value("tts_dashscope_voice", "")
        or "Cherry"
    )


def _dashscope_model() -> str:
    return (
        _provider_env("dashscope", "MODEL")
        or _settings_value("tts_dashscope_model", "")
        or "qwen3-tts-flash-realtime"
    )


def _dashscope_service_url() -> str:
    return (
        _provider_env("dashscope", "SERVICE_URL")
        or _settings_value("tts_dashscope_service_url", "")
        or "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
    )


def _dashscope_voice() -> str:
    return _tts_voice_for_log_dashscope()


def _local_cosyvoice_model() -> str:
    return (
        _provider_env("local_cosyvoice", "MODEL")
        or _settings_value("tts_local_cosyvoice_model", "")
        or "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"
    )


def _local_cosyvoice_service_url() -> str:
    return (
        _provider_env("local_cosyvoice", "SERVICE_URL")
        or _settings_value("tts_local_cosyvoice_service_url", "")
    )


def _local_audio_model_root() -> Path:
    raw = (
        os.environ.get("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", "").strip()
        or _settings_value("local_audio_model_root", "")
        or "./models/local-audio"
    )
    return Path(raw).expanduser()


def _local_cosyvoice_model_dir(model: str) -> str:
    return (
        _provider_env("local_cosyvoice", "MODEL_DIR")
        or _settings_value("tts_local_cosyvoice_model_dir", "")
        or str(_local_audio_model_root() / model.replace("/", "__"))
    )


def _local_cosyvoice_device() -> str:
    return (
        _provider_env("local_cosyvoice", "DEVICE")
        or _settings_value("tts_local_cosyvoice_device", "")
        or os.environ.get("OPENTALKING_LOCAL_TTS_DEVICE", "").strip()
        or os.environ.get("OPENTALKING_LOCAL_AUDIO_DEVICE", "").strip()
        or _settings_value("local_audio_device", "")
        or "auto"
    )


def _dashscope_api_key() -> str:
    return (
        _provider_env("dashscope", "API_KEY")
        or _settings_value("tts_dashscope_api_key", "")
    )


def tts_enabled_providers() -> list[str]:
    raw = os.environ.get("OPENTALKING_TTS_ENABLED_PROVIDERS", "").strip() or _settings_value(
        "tts_enabled_providers",
        "",
    )
    if not raw:
        return [_provider()]
    out: list[str] = []
    for item in raw.replace(";", ",").split(","):
        provider = normalize_tts_provider(item, default=None)
        if provider and provider not in out:
            out.append(provider)
    return out or [_provider()]


def tts_provider_config(provider: str) -> dict[str, str | bool]:
    p = normalize_tts_provider(provider, default=None) or _provider()
    if p in _QWEN_RT:
        service_url = _dashscope_service_url()
        return {
            "provider": p,
            "model": _dashscope_model(),
            "model_dir": "",
            "voice": _dashscope_voice(),
            "device": "",
            "key_set": bool(_dashscope_api_key()),
            "service_url_set": bool(service_url),
        }
    if p in _COSY_WS:
        model = (
            os.environ.get("OPENTALKING_TTS_COSYVOICE_MODEL", "").strip()
            or _settings_value("tts_cosyvoice_model", "")
            or "cosyvoice-v3-flash"
        )
        service_url = (
            os.environ.get("OPENTALKING_TTS_COSYVOICE_SERVICE_URL", "").strip()
            or _settings_value("tts_cosyvoice_service_url", "")
        )
        return {
            "provider": p,
            "model": model,
            "model_dir": "",
            "voice": "",
            "device": "",
            "key_set": bool(_dashscope_api_key()),
            "service_url_set": bool(service_url),
        }
    if p in _SAMBERT:
        model = (
            os.environ.get("OPENTALKING_TTS_SAMBERT_MODEL", "").strip()
            or _settings_value("tts_sambert_model", "")
            or "sambert-zhichu-v1"
        )
        return {
            "provider": p,
            "model": model,
            "model_dir": "",
            "voice": "",
            "device": "",
            "key_set": bool(_dashscope_api_key()),
            "service_url_set": False,
        }
    if p == "local_cosyvoice":
        model = _local_cosyvoice_model()
        service_url = _local_cosyvoice_service_url()
        return {
            "provider": p,
            "model": model,
            "model_dir": _local_cosyvoice_model_dir(model),
            "voice": "local-default",
            "device": _local_cosyvoice_device(),
            "key_set": False,
            "service_url_set": bool(service_url),
        }
    if p == "local_qwen3_tts":
        model = (
            os.environ.get("OPENTALKING_TTS_LOCAL_QWEN3_TTS_MODEL", "").strip()
            or os.environ.get("OPENTALKING_LOCAL_QWEN3_TTS_MODEL", "").strip()
            or _settings_value("local_qwen3_tts_model", "")
            or "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
        )
        service_url = (
            os.environ.get("OPENTALKING_TTS_LOCAL_QWEN3_TTS_SERVICE_URL", "").strip()
            or os.environ.get("OPENTALKING_LOCAL_QWEN3_TTS_SERVICE_URL", "").strip()
            or _settings_value("local_qwen3_tts_service_url", "")
        )
        return {
            "provider": p,
            "model": model,
            "model_dir": "",
            "voice": "",
            "device": "",
            "key_set": False,
            "service_url_set": bool(service_url),
        }
    return {
        "provider": p,
        "model": "",
        "model_dir": "",
        "voice": _edge_default_voice(),
        "device": "",
        "key_set": False,
        "service_url_set": False,
    }


def tts_status(provider: str | None = None) -> dict[str, str | bool]:
    return tts_provider_config(provider or _provider())


_QWEN_RT = QWEN_TTS_PROVIDERS
_COSY_WS = COSYVOICE_TTS_PROVIDERS
_SAMBERT = SAMBERT_TTS_PROVIDERS
_LOCAL = LOCAL_TTS_PROVIDERS
_CORE = CORE_TTS_PROVIDERS


def tts_provider_log_label() -> str:
    """简短标签，用于日志里对比各 TTS 路径耗时。"""
    p = _provider()
    if p in _QWEN_RT:
        return "dashscope_qwen"
    if p in _COSY_WS:
        return "dashscope_cosyvoice_ws"
    if p in _SAMBERT:
        return "dashscope_sambert"
    if p == "elevenlabs":
        return "elevenlabs"
    if p in _LOCAL:
        return p
    return "edge"


def tts_log_profile(
    *,
    request_voice: str | None = None,
    tts_provider_override: str | None = None,
    tts_model_override: str | None = None,
) -> str:
    """供运行日志使用：显式区分 TTS API 路由与关键参数。"""
    try:
        from opentalking.core.config import get_settings

        raw_cfg = get_settings().tts_provider
    except Exception:
        raw_cfg = os.environ.get("OPENTALKING_TTS_PROVIDER", "")
    raw_display = repr(raw_cfg.strip()) if str(raw_cfg).strip() else "(unset → code default edge)"
    p = (tts_provider_override or "").strip().lower() or _provider()
    req = (request_voice or "").strip()
    req_part = f"speak_voice_arg={req!r}" if req else "speak_voice_arg=(none)"

    try:
        from opentalking.core.config import get_settings

        sk = get_settings()
        key_ok = bool(
            os.environ.get("OPENTALKING_TTS_DASHSCOPE_API_KEY", "").strip()
            or getattr(sk, "tts_dashscope_api_key", "").strip()
        )
    except Exception:
        key_ok = bool(os.environ.get("OPENTALKING_TTS_DASHSCOPE_API_KEY", "").strip())

    if p in _QWEN_RT:
        voice = (request_voice or "").strip() or _tts_voice_for_log_dashscope()
        model = (
            (tts_model_override or "").strip()
            or _dashscope_model()
        )
        mode = (os.environ.get("OPENTALKING_QWEN_TTS_MODE") or "commit").strip()
        ws = (
            _dashscope_service_url()
        ).strip()
        return (
            f"TTS_API=dashscope_qwen | OPENTALKING_TTS_PROVIDER={raw_display} | "
            f"model={model} voice_env={voice!r} mode={mode!r} ws={ws!r} "
            f"dashscope_api_key_set={key_ok} | {req_part}"
        )

    if p in _COSY_WS:
        model = (
            (tts_model_override or "").strip()
            or os.environ.get("OPENTALKING_TTS_COSYVOICE_MODEL", "").strip()
            or _settings_value("tts_cosyvoice_model", "")
            or "cosyvoice-v3-flash"
        )
        return (
            f"TTS_API=dashscope_cosyvoice_ws | OPENTALKING_TTS_PROVIDER={raw_display} | "
            f"model={model!r} api_route=tts_v2.WebSocket "
            f"dashscope_api_key_set={key_ok} | {req_part}"
        )

    if p in _SAMBERT:
        model = (
            (tts_model_override or "").strip()
            or os.environ.get("OPENTALKING_TTS_SAMBERT_MODEL", "").strip()
            or _settings_value("tts_sambert_model", "")
            or "sambert-zhichu-v1"
        )
        return (
            f"TTS_API=dashscope_sambert | OPENTALKING_TTS_PROVIDER={raw_display} | "
            f"model={model!r} dashscope_api_key_set={key_ok} | {req_part}"
        )

    if p == "local_cosyvoice":
        model = (
            (tts_model_override or "").strip()
            or _local_cosyvoice_model()
        )
        device = (
            _provider_env("local_cosyvoice", "DEVICE")
            or _settings_value("tts_local_cosyvoice_device", "")
            or os.environ.get("OPENTALKING_LOCAL_TTS_DEVICE", os.environ.get("OPENTALKING_LOCAL_AUDIO_DEVICE", "auto"))
        )
        return f"TTS_API=local_cosyvoice | model={model!r} device={device!r} | {req_part}"

    if p == "local_qwen3_tts":
        model = (
            (tts_model_override or "").strip()
            or os.environ.get(
                "OPENTALKING_LOCAL_QWEN3_TTS_MODEL",
                "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
            ).strip()
        )
        service = os.environ.get("OPENTALKING_LOCAL_QWEN3_TTS_SERVICE_URL", "").strip() or "(unset)"
        return f"TTS_API=local_qwen3_tts | model={model!r} service={service!r} | {req_part}"

    if p == "elevenlabs":
        try:
            from opentalking.core.config import get_settings

            sk = get_settings()
            key_set = bool(sk.tts_elevenlabs_api_key.strip())
            model = (tts_model_override or "").strip() or sk.tts_elevenlabs_model_id
            voice = req or sk.tts_elevenlabs_voice_id
        except Exception:
            key_set = bool(os.environ.get("OPENTALKING_TTS_ELEVENLABS_API_KEY", "").strip())
            model = (
                (tts_model_override or "").strip()
                or os.environ.get("OPENTALKING_TTS_ELEVENLABS_MODEL_ID", "eleven_flash_v2_5").strip()
            )
            voice = req or os.environ.get("OPENTALKING_TTS_ELEVENLABS_VOICE_ID", "").strip()
        return (
            f"TTS_API=elevenlabs | OPENTALKING_TTS_PROVIDER={raw_display} | "
            f"model={model!r} voice_effective={voice!r} elevenlabs_api_key_set={key_set} | {req_part}"
        )

    v_eff = req or _edge_default_voice()
    return (
        f"TTS_API=edge_tts | OPENTALKING_TTS_PROVIDER={raw_display} | "
        f"voice_effective={v_eff!r} | {req_part}"
    )


def create_tts_adapter(
    *,
    sample_rate: int,
    chunk_ms: float,
    default_voice: str | None = None,
    tts_provider: str | None = None,
    tts_model: str | None = None,
):
    """返回与 EdgeTTSAdapter 相同接口的 TTS 适配器实例。"""
    p = (tts_provider or "").strip().lower() or _provider()
    if p in _QWEN_RT:
        from opentalking.providers.tts.dashscope_qwen.adapter import DashScopeQwenTTSAdapter

        return DashScopeQwenTTSAdapter(
            default_voice=default_voice or _dashscope_voice(),
            sample_rate=sample_rate,
            chunk_ms=chunk_ms,
            model=(tts_model or "").strip() or _dashscope_model(),
            service_url=_dashscope_service_url(),
        )
    if p in _COSY_WS:
        from opentalking.providers.tts.cosyvoice_ws.adapter import DashScopeCosyVoiceWsAdapter

        dm = (
            (tts_model or "").strip()
            or os.environ.get("OPENTALKING_TTS_COSYVOICE_MODEL", "").strip()
            or _settings_value("tts_cosyvoice_model", "")
            or "cosyvoice-v3-flash"
        )
        service = os.environ.get("OPENTALKING_TTS_COSYVOICE_SERVICE_URL", "").strip() or _settings_value(
            "tts_cosyvoice_service_url",
            "",
        )
        return DashScopeCosyVoiceWsAdapter(
            default_voice=default_voice,
            sample_rate=sample_rate,
            chunk_ms=chunk_ms,
            model=dm,
            service_url=service,
        )
    if p in _SAMBERT:
        from opentalking.providers.tts.dashscope_sambert.adapter import DashScopeSambertTTSAdapter

        return DashScopeSambertTTSAdapter(
            default_voice=default_voice,
            sample_rate=sample_rate,
            chunk_ms=chunk_ms,
            model=(tts_model or "").strip()
            or os.environ.get("OPENTALKING_TTS_SAMBERT_MODEL", "").strip()
            or _settings_value("tts_sambert_model", "")
            or None,
        )
    if p == "local_cosyvoice":
        from opentalking.providers.tts.local_cosyvoice.adapter import LocalCosyVoiceTTSAdapter

        return LocalCosyVoiceTTSAdapter(
            default_voice=default_voice,
            sample_rate=sample_rate,
            chunk_ms=chunk_ms,
            model=(tts_model or "").strip() or _local_cosyvoice_model(),
        )
    if p == "local_qwen3_tts":
        from opentalking.providers.tts.local_qwen3_tts.adapter import LocalQwen3TTSAdapter

        return LocalQwen3TTSAdapter(
            default_voice=default_voice,
            sample_rate=sample_rate,
            chunk_ms=chunk_ms,
            model=tts_model,
        )
    if p == "elevenlabs":
        try:
            from opentalking.core.config import get_settings

            settings = get_settings()
        except Exception:
            settings = SimpleNamespace()
        return _build_elevenlabs_adapter(
            settings=settings,
            sample_rate=sample_rate,
            chunk_ms=chunk_ms,
            default_voice=default_voice,
            tts_model=tts_model,
        )
    return EdgeTTSAdapter(
        default_voice=default_voice or _edge_default_voice(),
        sample_rate=sample_rate,
        chunk_ms=chunk_ms,
    )


# ---------------------------------------------------------------------------
# Upstream-compatible entry point (Settings-based, supports ElevenLabs)
# ---------------------------------------------------------------------------

def _build_edge_adapter(*, settings, sample_rate: int, chunk_ms: float) -> EdgeTTSAdapter:
    return EdgeTTSAdapter(
        default_voice=settings.tts_voice,
        sample_rate=sample_rate,
        chunk_ms=chunk_ms,
    )


def _build_elevenlabs_adapter(
    *,
    settings,
    sample_rate: int,
    chunk_ms: float,
    default_voice: str | None = None,
    tts_model: str | None = None,
):
    from opentalking.providers.tts.elevenlabs.adapter import ElevenLabsTTSAdapter

    api_key = (
        getattr(settings, "tts_elevenlabs_api_key", "").strip()
        or os.environ.get("OPENTALKING_TTS_ELEVENLABS_API_KEY", "").strip()
    )
    voice_id = (
        (default_voice or "").strip()
        or getattr(settings, "tts_elevenlabs_voice_id", "").strip()
        or os.environ.get("OPENTALKING_TTS_ELEVENLABS_VOICE_ID", "").strip()
    )
    model_id = (
        (tts_model or "").strip()
        or getattr(settings, "tts_elevenlabs_model_id", "").strip()
        or os.environ.get("OPENTALKING_TTS_ELEVENLABS_MODEL_ID", "eleven_flash_v2_5").strip()
    )
    base_url = (
        getattr(settings, "tts_elevenlabs_base_url", "").strip()
        or os.environ.get("OPENTALKING_TTS_ELEVENLABS_BASE_URL", "https://api.elevenlabs.io").strip()
    )
    output_format = (
        getattr(settings, "tts_elevenlabs_output_format", "").strip()
        or os.environ.get("OPENTALKING_TTS_ELEVENLABS_OUTPUT_FORMAT", "mp3_22050_32").strip()
    )

    if not api_key:
        raise RuntimeError("ElevenLabs provider selected but OPENTALKING_TTS_ELEVENLABS_API_KEY is empty.")
    if not voice_id:
        raise RuntimeError("ElevenLabs provider selected but OPENTALKING_TTS_ELEVENLABS_VOICE_ID is empty.")
    return ElevenLabsTTSAdapter(
        api_key=api_key,
        default_voice=voice_id,
        base_url=base_url,
        model_id=model_id,
        output_format=output_format,
        sample_rate=sample_rate,
        chunk_ms=chunk_ms,
    )


def build_tts_adapter(
    *,
    sample_rate: int,
    chunk_ms: float,
    settings=None,
    default_voice: str | None = None,
    tts_provider: str | None = None,
    tts_model: str | None = None,
):
    """Settings-based entry point with optional per-request TTS overrides."""
    from opentalking.core.config import get_settings

    settings = settings or get_settings()
    explicit_provider = (tts_provider or "").strip().lower()
    provider = (
        explicit_provider
        or getattr(settings, "normalized_tts_default_provider", None)
        or getattr(settings, "normalized_tts_provider", None)
        or _provider()
    )
    effective_tts_model = (tts_model or "").strip() or getattr(settings, "tts_model", "").strip()
    effective_tts_model = effective_tts_model or None

    if provider == "elevenlabs":
        return _build_elevenlabs_adapter(
            settings=settings,
            sample_rate=sample_rate,
            chunk_ms=chunk_ms,
            default_voice=default_voice,
            tts_model=effective_tts_model,
        )

    # For dashscope/bailian/etc., delegate to create_tts_adapter
    if provider in _QWEN_RT or provider in _COSY_WS or provider in _SAMBERT or provider in _LOCAL:
        return create_tts_adapter(
            sample_rate=sample_rate,
            chunk_ms=chunk_ms,
            default_voice=default_voice or getattr(settings, "tts_voice", None),
            tts_provider=provider,
            tts_model=effective_tts_model,
        )

    if provider in _CORE:
        return EdgeTTSAdapter(
            default_voice=default_voice or getattr(settings, "tts_voice", None) or _edge_default_voice(),
            sample_rate=sample_rate,
            chunk_ms=chunk_ms,
        )

    return _build_edge_adapter(settings=settings, sample_rate=sample_rate, chunk_ms=chunk_ms)
