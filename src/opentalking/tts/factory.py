"""根据环境与请求选择 TTS 后端（Edge / 百炼多种 API / ElevenLabs）。"""

from __future__ import annotations

import os
from types import SimpleNamespace

from opentalking.tts.edge.adapter import EdgeTTSAdapter
from opentalking.tts.providers import (
    CORE_TTS_PROVIDERS,
    COSYVOICE_TTS_PROVIDERS,
    QWEN_TTS_PROVIDERS,
    SAMBERT_TTS_PROVIDERS,
)


def _provider() -> str:
    """与 .env 对齐：优先读 pydantic Settings（否则会仅写 .env 却未写入 os.environ 导致永远 edge）。"""
    try:
        from opentalking.core.config import get_settings

        return get_settings().tts_provider.strip().lower()
    except Exception:
        return os.environ.get("OPENTALKING_TTS_PROVIDER", "edge").strip().lower()


def _edge_default_voice() -> str:
    """Edge TTS 音色：Settings.tts_voice / OPENTALKING_TTS_VOICE。"""
    try:
        from opentalking.core.config import get_settings

        v = get_settings().tts_voice.strip()
        if v:
            return v
    except Exception:
        pass
    v = os.environ.get("OPENTALKING_TTS_VOICE", "").strip()
    return v or "zh-CN-XiaoxiaoNeural"


def _tts_voice_for_log_dashscope() -> str:
    try:
        from opentalking.core.config import get_settings

        return (get_settings().tts_voice or "").strip() or "Cherry"
    except Exception:
        return (os.environ.get("OPENTALKING_TTS_VOICE") or "Cherry").strip()


_QWEN_RT = QWEN_TTS_PROVIDERS
_COSY_WS = COSYVOICE_TTS_PROVIDERS
_SAMBERT = SAMBERT_TTS_PROVIDERS
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
        key_ok = bool(os.environ.get("DASHSCOPE_API_KEY", "").strip()) or bool(sk.llm_api_key.strip())
    except Exception:
        key_ok = bool(os.environ.get("DASHSCOPE_API_KEY", "").strip())

    if p in _QWEN_RT:
        voice = (request_voice or "").strip() or _tts_voice_for_log_dashscope()
        model = (
            (tts_model_override or "").strip()
            or (os.environ.get("OPENTALKING_QWEN_TTS_MODEL") or "qwen3-tts-flash-realtime").strip()
        )
        mode = (os.environ.get("OPENTALKING_QWEN_TTS_MODE") or "commit").strip()
        ws = (
            os.environ.get("OPENTALKING_QWEN_TTS_WS_URL") or "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
        ).strip()
        return (
            f"TTS_API=dashscope_qwen | OPENTALKING_TTS_PROVIDER={raw_display} | "
            f"model={model} voice_env={voice!r} mode={mode!r} ws={ws!r} "
            f"dashscope_api_key_set={key_ok} | {req_part}"
        )

    if p in _COSY_WS:
        model = (tts_model_override or "").strip() or "cosyvoice-v3-flash"
        return (
            f"TTS_API=dashscope_cosyvoice_ws | OPENTALKING_TTS_PROVIDER={raw_display} | "
            f"model={model!r} api_route=tts_v2.WebSocket "
            f"dashscope_api_key_set={key_ok} | {req_part}"
        )

    if p in _SAMBERT:
        model = (tts_model_override or "").strip() or "sambert-zhichu-v1"
        return (
            f"TTS_API=dashscope_sambert | OPENTALKING_TTS_PROVIDER={raw_display} | "
            f"model={model!r} dashscope_api_key_set={key_ok} | {req_part}"
        )

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
        from opentalking.tts.dashscope_qwen.adapter import DashScopeQwenTTSAdapter

        return DashScopeQwenTTSAdapter(
            default_voice=default_voice,
            sample_rate=sample_rate,
            chunk_ms=chunk_ms,
            model=tts_model,
        )
    if p in _COSY_WS:
        from opentalking.tts.cosyvoice_ws.adapter import DashScopeCosyVoiceWsAdapter

        dm = (tts_model or "").strip() or "cosyvoice-v3-flash"
        return DashScopeCosyVoiceWsAdapter(
            default_voice=default_voice,
            sample_rate=sample_rate,
            chunk_ms=chunk_ms,
            model=dm,
        )
    if p in _SAMBERT:
        from opentalking.tts.dashscope_sambert.adapter import DashScopeSambertTTSAdapter

        return DashScopeSambertTTSAdapter(
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
    from opentalking.tts.elevenlabs.adapter import ElevenLabsTTSAdapter

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
    provider = (tts_provider or "").strip().lower() or getattr(settings, "normalized_tts_provider", _provider())

    if provider == "elevenlabs":
        return _build_elevenlabs_adapter(
            settings=settings,
            sample_rate=sample_rate,
            chunk_ms=chunk_ms,
            default_voice=default_voice,
            tts_model=tts_model,
        )

    # For dashscope/bailian/etc., delegate to create_tts_adapter
    if provider in _QWEN_RT or provider in _COSY_WS or provider in _SAMBERT:
        return create_tts_adapter(
            sample_rate=sample_rate,
            chunk_ms=chunk_ms,
            default_voice=default_voice or getattr(settings, "tts_voice", None),
            tts_provider=provider,
            tts_model=tts_model,
        )

    if provider in _CORE:
        return EdgeTTSAdapter(
            default_voice=default_voice or getattr(settings, "tts_voice", None) or _edge_default_voice(),
            sample_rate=sample_rate,
            chunk_ms=chunk_ms,
        )

    return _build_edge_adapter(settings=settings, sample_rate=sample_rate, chunk_ms=chunk_ms)
