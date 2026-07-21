"""根据环境与请求选择 TTS 后端（Edge / 百炼多种 API / ElevenLabs）。"""

from __future__ import annotations

import os
import posixpath
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

from opentalking.core.model_paths import local_audio_model_root, model_repo_root
from opentalking.providers.tts.edge.adapter import EdgeTTSAdapter
from opentalking.providers.tts.providers import (
    CORE_TTS_PROVIDERS,
    COSYVOICE_TTS_PROVIDERS,
    INDEXTTS_TTS_PROVIDERS,
    LOCAL_TTS_PROVIDERS,
    OMNIRT_TTS_PROVIDERS,
    OPENAI_COMPATIBLE_TTS_PROVIDERS,
    QWEN_TTS_PROVIDERS,
    SAMBERT_TTS_PROVIDERS,
    XIAOMI_MIMO_TTS_PROVIDERS,
    normalize_tts_provider,
)


_INDEXTTS_CONCRETE_PROVIDERS = {"local_indextts", "omnirt_indextts"}


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


def _join_config_path(root: str, *parts: str) -> str:
    value = root.strip()
    if "/" in value and "\\" not in value:
        return posixpath.join(value.rstrip("/"), *parts)
    return str(Path(value).expanduser().joinpath(*parts))


def _configured_tts_provider_values() -> tuple[str, ...]:
    return tuple(
        value
        for raw in (
            os.environ.get("OPENTALKING_TTS_DEFAULT_PROVIDER", ""),
            _settings_value("tts_default_provider", ""),
            os.environ.get("OPENTALKING_TTS_PROVIDER", ""),
            _settings_value("tts_provider", ""),
        )
        if (value := str(raw or "").strip())
    )


def _public_tts_provider(provider: str) -> str:
    return "indextts" if provider in _INDEXTTS_CONCRETE_PROVIDERS else provider


def _provider() -> str:
    """Return the default user-facing TTS provider. This is routing only, not fallback."""
    for value in _configured_tts_provider_values():
        provider = normalize_tts_provider(value, default="edge") or "edge"
        return _public_tts_provider(provider)
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


def _local_audio_model_root() -> str:
    return str(local_audio_model_root(_settings_value("local_audio_model_root", "")).resolve())


def _local_cosyvoice_model_dir(model: str) -> str:
    return (
        _provider_env("local_cosyvoice", "MODEL_DIR")
        or _settings_value("tts_local_cosyvoice_model_dir", "")
        or _join_config_path(_local_audio_model_root(), model.replace("/", "__"))
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


def _local_cosyvoice_bool(field: str, settings_name: str, default: bool) -> bool:
    raw = _provider_env("local_cosyvoice", field) or _settings_value(settings_name, "")
    if not raw:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _local_cosyvoice_int(field: str, settings_name: str, default: int) -> int:
    raw = _provider_env("local_cosyvoice", field) or _settings_value(settings_name, "")
    if not raw:
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default


def _local_cosyvoice_float(field: str, settings_name: str, default: float) -> float:
    raw = _provider_env("local_cosyvoice", field) or _settings_value(settings_name, "")
    if not raw:
        return default
    try:
        return float(str(raw).strip())
    except ValueError:
        return default


def _local_cosyvoice_fp16() -> str:
    return (
        _provider_env("local_cosyvoice", "FP16")
        or _settings_value("tts_local_cosyvoice_fp16", "")
        or "auto"
    )


def _local_audio_asset_dir(name: str, required_file: str, *fallback_names: str) -> str:
    root = _local_audio_model_root()
    for candidate_name in (name, *fallback_names):
        candidate_value = _join_config_path(root, candidate_name)
        candidate = Path(candidate_value).expanduser()
        if (candidate / required_file).is_file():
            return candidate_value
    return _join_config_path(root, name)


def _local_audio_asset_file_dir(name: str, relative_file: str, *fallback_names: str) -> str:
    return _local_audio_asset_dir(name, relative_file, *fallback_names)


def _local_f5_tts_model() -> str:
    return _provider_env("local_f5_tts", "MODEL") or _settings_value("tts_local_f5_tts_model", "") or "SWivid/F5-TTS/F5TTS_v1_Base"


def _local_f5_tts_model_dir(model: str) -> str:
    return _provider_env("local_f5_tts", "MODEL_DIR") or _settings_value("tts_local_f5_tts_model_dir", "") or str(Path(_local_audio_model_root()) / model.replace("/", "__"))


def _local_f5_tts_runtime_dir() -> str:
    return (
        _provider_env("local_f5_tts", "RUNTIME_DIR")
        or _settings_value("tts_local_f5_tts_runtime_dir", "")
        or str((model_repo_root() / "F5-TTS").expanduser().resolve())
    )


def _local_f5_tts_service_url() -> str:
    return _provider_env("local_f5_tts", "SERVICE_URL") or _settings_value("tts_local_f5_tts_service_url", "")


def _local_f5_tts_ckpt_file(model_dir: str) -> str:
    return _provider_env("local_f5_tts", "CKPT_FILE") or _settings_value("tts_local_f5_tts_ckpt_file", "") or str(Path(model_dir) / "model_1250000.safetensors")


def _local_f5_tts_vocoder_local_path() -> str:
    return _provider_env("local_f5_tts", "VOCODER_LOCAL_PATH") or _settings_value("tts_local_f5_tts_vocoder_local_path", "")


def _local_f5_tts_prompt_audio() -> str:
    return _provider_env("local_f5_tts", "PROMPT_AUDIO") or _settings_value("tts_local_f5_tts_prompt_audio", "")


def _local_f5_tts_prompt_text() -> str:
    return _provider_env("local_f5_tts", "PROMPT_TEXT") or _settings_value("tts_local_f5_tts_prompt_text", "")


def _local_f5_tts_device() -> str:
    return _provider_env("local_f5_tts", "DEVICE") or _settings_value("tts_local_f5_tts_device", "") or os.environ.get("OPENTALKING_LOCAL_TTS_DEVICE", "").strip() or os.environ.get("OPENTALKING_LOCAL_AUDIO_DEVICE", "").strip() or _settings_value("local_audio_device", "") or "auto"


def _local_indextts_model() -> str:
    return (
        _provider_env("local_indextts", "MODEL")
        or _settings_value("tts_local_indextts_model", "")
        or "IndexTeam/IndexTTS-2"
    )


def _local_indextts_model_dir(model: str) -> str:
    return (
        _provider_env("local_indextts", "MODEL_DIR")
        or _settings_value("tts_local_indextts_model_dir", "")
        or _join_config_path(_local_audio_model_root(), model.replace("/", "__"))
    )


def _local_indextts_cfg_path(model_dir: str) -> str:
    return (
        _provider_env("local_indextts", "CFG_PATH")
        or _settings_value("tts_local_indextts_cfg_path", "")
        or _join_config_path(model_dir, "config.yaml")
    )


def _local_indextts_service_url() -> str:
    return (
        _provider_env("local_indextts", "SERVICE_URL")
        or _settings_value("tts_local_indextts_service_url", "")
    )


def _local_indextts_prompt_audio() -> str:
    return (
        _provider_env("local_indextts", "PROMPT_AUDIO")
        or _settings_value("tts_local_indextts_prompt_audio", "")
    )


def _local_indextts_w2v_bert_dir() -> str:
    return (
        _provider_env("local_indextts", "W2V_BERT_DIR")
        or _settings_value("tts_local_indextts_w2v_bert_dir", "")
        or _join_config_path(_local_audio_model_root(), "facebook__w2v-bert-2.0")
    )


def _local_indextts_maskgct_dir() -> str:
    return (
        _provider_env("local_indextts", "MASKGCT_DIR")
        or _settings_value("tts_local_indextts_maskgct_dir", "")
        or _local_audio_asset_file_dir("amphion__MaskGCT", "semantic_codec/model.safetensors", "amphion__MaskGCT-ms")
    )


def _local_indextts_campplus_dir() -> str:
    return (
        _provider_env("local_indextts", "CAMPPLUS_DIR")
        or _settings_value("tts_local_indextts_campplus_dir", "")
        or _join_config_path(_local_audio_model_root(), "funasr__campplus")
    )


def _local_indextts_bigvgan_dir() -> str:
    return (
        _provider_env("local_indextts", "BIGVGAN_DIR")
        or _settings_value("tts_local_indextts_bigvgan_dir", "")
        or _join_config_path(_local_audio_model_root(), "nvidia__bigvgan_v2_22khz_80band_256x")
    )


def _local_indextts_device() -> str:
    return (
        _provider_env("local_indextts", "DEVICE")
        or _settings_value("tts_local_indextts_device", "")
        or os.environ.get("OPENTALKING_LOCAL_TTS_DEVICE", "").strip()
        or os.environ.get("OPENTALKING_LOCAL_AUDIO_DEVICE", "").strip()
        or _settings_value("local_audio_device", "")
        or "auto"
    )


def _local_indextts_bool(field: str, settings_name: str, default: bool) -> bool:
    raw = _provider_env("local_indextts", field) or _settings_value(settings_name, "")
    if not raw:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _omnirt_indextts_model() -> str:
    return (
        _provider_env("omnirt_indextts", "MODEL")
        or _settings_value("tts_omnirt_indextts_model", "")
        or "IndexTeam/IndexTTS-2"
    )


def _omnirt_indextts_service_url() -> str:
    return (
        _provider_env("omnirt_indextts", "SERVICE_URL")
        or _settings_value("tts_omnirt_indextts_service_url", "")
        or "http://127.0.0.1:9012/v1/text2audio/indextts"
    ).rstrip("/")


def _omnirt_indextts_bool(field: str, settings_name: str, default: bool) -> bool:
    raw = _provider_env("omnirt_indextts", field) or _settings_value(settings_name, "")
    if not raw:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _omnirt_indextts_int(field: str, settings_name: str, default: int) -> int:
    raw = _provider_env("omnirt_indextts", field) or _settings_value(settings_name, "")
    if not raw:
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default


def _omnirt_indextts_streaming_mode() -> str:
    return (
        _provider_env("omnirt_indextts", "STREAMING_MODE")
        or _settings_value("tts_omnirt_indextts_streaming_mode", "")
        or "token_window"
    )



def _indextts_backend() -> str:
    raw = (
        os.environ.get("OPENTALKING_TTS_INDEXTTS_BACKEND", "").strip()
        or _settings_value("tts_indextts_backend", "")
    )
    backend = raw.lower().replace("-", "_")
    if backend in {"omnirt", "omnirt_indextts"}:
        return "omnirt"
    if backend in {"local", "local_indextts", "in_process", "inprocess"}:
        return "local"

    for value in _configured_tts_provider_values():
        try:
            provider = normalize_tts_provider(value, default=None)
        except ValueError:
            continue
        if provider == "omnirt_indextts":
            return "omnirt"
        if provider == "local_indextts":
            return "local"
    return "local"


def _resolve_indextts_provider(provider: str) -> str:
    if provider != "indextts":
        return provider
    return "omnirt_indextts" if _indextts_backend() == "omnirt" else "local_indextts"

def _dashscope_api_key() -> str:
    return (
        _provider_env("dashscope", "API_KEY")
        or _settings_value("tts_dashscope_api_key", "")
    )


def _openai_tts_base_url() -> str:
    return (
        _provider_env("openai", "BASE_URL")
        or os.environ.get("OPENTALKING_TTS_OPENAI_BASE_URL", "").strip()
        or _settings_value("tts_openai_base_url", "")
    ).rstrip("/")


def _openai_tts_api_key() -> str:
    return (
        _provider_env("openai", "API_KEY")
        or os.environ.get("OPENTALKING_TTS_OPENAI_API_KEY", "").strip()
        or _settings_value("tts_openai_api_key", "")
    )


def _openai_tts_model() -> str:
    return (
        _provider_env("openai", "MODEL")
        or os.environ.get("OPENTALKING_TTS_OPENAI_MODEL", "").strip()
        or _settings_value("tts_openai_model", "")
        or "gpt-4o-mini-tts"
    )


def _openai_tts_voice() -> str:
    return (
        _provider_env("openai", "VOICE")
        or os.environ.get("OPENTALKING_TTS_OPENAI_VOICE", "").strip()
        or _settings_value("tts_openai_voice", "")
        or "alloy"
    )


def _openai_tts_response_format() -> str:
    return (
        _provider_env("openai", "RESPONSE_FORMAT")
        or os.environ.get("OPENTALKING_TTS_OPENAI_RESPONSE_FORMAT", "").strip()
        or _settings_value("tts_openai_response_format", "")
        or "wav"
    )


def _openai_tts_protocol() -> str:
    return (
        _provider_env("openai", "PROTOCOL")
        or os.environ.get("OPENTALKING_TTS_OPENAI_PROTOCOL", "").strip()
        or _settings_value("tts_openai_protocol", "")
        or "audio_speech"
    )


def _openai_tts_prompt() -> str:
    return (
        _provider_env("openai", "PROMPT")
        or os.environ.get("OPENTALKING_TTS_OPENAI_PROMPT", "").strip()
        or _settings_value("tts_openai_prompt", "")
    )


def _xiaomi_tts_base_url() -> str:
    return (
        _provider_env("xiaomi", "BASE_URL")
        or _provider_env("xiaomi_mimo", "BASE_URL")
        or os.environ.get("OPENTALKING_TTS_XIAOMI_BASE_URL", "").strip()
        or os.environ.get("OPENTALKING_TTS_XIAOMI_MIMO_BASE_URL", "").strip()
        or _settings_value("tts_xiaomi_base_url", "")
        or _settings_value("tts_xiaomi_mimo_base_url", "")
    ).rstrip("/")


def _xiaomi_tts_api_key() -> str:
    return (
        _provider_env("xiaomi", "API_KEY")
        or _provider_env("xiaomi_mimo", "API_KEY")
        or os.environ.get("OPENTALKING_TTS_XIAOMI_API_KEY", "").strip()
        or os.environ.get("OPENTALKING_TTS_XIAOMI_MIMO_API_KEY", "").strip()
        or _settings_value("tts_xiaomi_api_key", "")
        or _settings_value("tts_xiaomi_mimo_api_key", "")
    )


def _xiaomi_tts_model() -> str:
    return (
        _provider_env("xiaomi", "MODEL")
        or _provider_env("xiaomi_mimo", "MODEL")
        or os.environ.get("OPENTALKING_TTS_XIAOMI_MODEL", "").strip()
        or os.environ.get("OPENTALKING_TTS_XIAOMI_MIMO_MODEL", "").strip()
        or _settings_value("tts_xiaomi_model", "")
        or _settings_value("tts_xiaomi_mimo_model", "")
        or "mimo-v2.5-tts"
    )


def _xiaomi_tts_voice() -> str:
    return (
        _provider_env("xiaomi", "VOICE")
        or _provider_env("xiaomi_mimo", "VOICE")
        or os.environ.get("OPENTALKING_TTS_XIAOMI_VOICE", "").strip()
        or os.environ.get("OPENTALKING_TTS_XIAOMI_MIMO_VOICE", "").strip()
        or _settings_value("tts_xiaomi_voice", "")
        or _settings_value("tts_xiaomi_mimo_voice", "")
        or "mimo_default"
    )


def _xiaomi_tts_response_format() -> str:
    return (
        _provider_env("xiaomi", "RESPONSE_FORMAT")
        or _provider_env("xiaomi_mimo", "RESPONSE_FORMAT")
        or os.environ.get("OPENTALKING_TTS_XIAOMI_RESPONSE_FORMAT", "").strip()
        or os.environ.get("OPENTALKING_TTS_XIAOMI_MIMO_RESPONSE_FORMAT", "").strip()
        or _settings_value("tts_xiaomi_response_format", "")
        or _settings_value("tts_xiaomi_mimo_response_format", "")
        or "wav"
    )


def _xiaomi_tts_protocol() -> str:
    return (
        _provider_env("xiaomi", "PROTOCOL")
        or _provider_env("xiaomi_mimo", "PROTOCOL")
        or os.environ.get("OPENTALKING_TTS_XIAOMI_PROTOCOL", "").strip()
        or os.environ.get("OPENTALKING_TTS_XIAOMI_MIMO_PROTOCOL", "").strip()
        or _settings_value("tts_xiaomi_protocol", "")
        or _settings_value("tts_xiaomi_mimo_protocol", "")
        or "chat_completions"
    )


def _xiaomi_tts_prompt() -> str:
    return (
        _provider_env("xiaomi", "PROMPT")
        or _provider_env("xiaomi_mimo", "PROMPT")
        or os.environ.get("OPENTALKING_TTS_XIAOMI_PROMPT", "").strip()
        or os.environ.get("OPENTALKING_TTS_XIAOMI_MIMO_PROMPT", "").strip()
        or _settings_value("tts_xiaomi_prompt", "")
        or _settings_value("tts_xiaomi_mimo_prompt", "")
        or "自然、清晰、口语化的普通话。"
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
        provider = _public_tts_provider(provider) if provider else None
        if provider and provider not in out:
            out.append(provider)
    return out or [_provider()]


def tts_provider_config(provider: str) -> dict[str, str | bool | int | float]:
    p = normalize_tts_provider(provider, default=None) or _provider()
    if p == "mock":
        return {
            "provider": p,
            "model": "mock",
            "model_dir": "",
            "voice": "mock",
            "device": "",
            "key_set": False,
            "service_url_set": True,
        }
    if p == "indextts":
        resolved = _resolve_indextts_provider(p)
        config = dict(tts_provider_config(resolved))
        config["provider"] = "indextts"
        config["backend"] = _indextts_backend()
        config["resolved_provider"] = resolved
        return config
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
        token_hop_len = _local_cosyvoice_int(
            "TOKEN_HOP_LEN",
            "tts_local_cosyvoice_token_hop_len",
            0,
        )
        token_max_hop_len = _local_cosyvoice_int(
            "TOKEN_MAX_HOP_LEN",
            "tts_local_cosyvoice_token_max_hop_len",
            0,
        )
        stream_scale_factor = _local_cosyvoice_int(
            "STREAM_SCALE_FACTOR",
            "tts_local_cosyvoice_stream_scale_factor",
            0,
        )
        flow_n_timesteps = _local_cosyvoice_int(
            "FLOW_N_TIMESTEPS",
            "tts_local_cosyvoice_flow_n_timesteps",
            0,
        )
        return {
            "provider": p,
            "model": model,
            "model_dir": _local_cosyvoice_model_dir(model),
            "voice": "local-default",
            "device": _local_cosyvoice_device(),
            "key_set": False,
            "service_url": service_url,
            "service_url_set": bool(service_url),
            "fp16": _local_cosyvoice_fp16(),
            "load_jit": _local_cosyvoice_bool("LOAD_JIT", "tts_local_cosyvoice_load_jit", False),
            "load_trt": _local_cosyvoice_bool("LOAD_TRT", "tts_local_cosyvoice_load_trt", False),
            "load_vllm": _local_cosyvoice_bool("LOAD_VLLM", "tts_local_cosyvoice_load_vllm", False),
            "trt_concurrent": _local_cosyvoice_int(
                "TRT_CONCURRENT",
                "tts_local_cosyvoice_trt_concurrent",
                1,
            ),
            "token_hop_len": token_hop_len,
            "token_max_hop_len": token_max_hop_len,
            "stream_scale_factor": stream_scale_factor,
            "flow_n_timesteps": flow_n_timesteps,
            "max_token_text_ratio": _local_cosyvoice_float(
                "MAX_TOKEN_TEXT_RATIO",
                "tts_local_cosyvoice_max_token_text_ratio",
                6.0,
            ),
            "min_token_text_ratio": _local_cosyvoice_float(
                "MIN_TOKEN_TEXT_RATIO",
                "tts_local_cosyvoice_min_token_text_ratio",
                0.0,
            ),
            "mask_stop_tokens": _local_cosyvoice_bool(
                "MASK_STOP_TOKENS",
                "tts_local_cosyvoice_mask_stop_tokens",
                True,
            ),
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
    if p == "local_f5_tts":
        model = _local_f5_tts_model()
        model_dir = _local_f5_tts_model_dir(model)
        service_url = _local_f5_tts_service_url()
        return {"provider": p, "model": model, "model_dir": model_dir, "voice": "local-default", "device": _local_f5_tts_device(), "key_set": False, "service_url": service_url, "service_url_set": bool(service_url), "runtime_dir": _local_f5_tts_runtime_dir(), "ckpt_file": _local_f5_tts_ckpt_file(model_dir), "vocoder_local_path": _local_f5_tts_vocoder_local_path(), "prompt_audio_set": bool(_local_f5_tts_prompt_audio())}
    if p == "local_indextts":
        model = _local_indextts_model()
        model_dir = _local_indextts_model_dir(model)
        service_url = _local_indextts_service_url()
        return {
            "provider": p,
            "model": model,
            "model_dir": model_dir,
            "voice": "local-default",
            "device": _local_indextts_device(),
            "key_set": False,
            "service_url": service_url,
            "service_url_set": bool(service_url),
            "cfg_path": _local_indextts_cfg_path(model_dir),
            "prompt_audio_set": bool(_local_indextts_prompt_audio()),
            "w2v_bert_dir": _local_indextts_w2v_bert_dir(),
            "maskgct_dir": _local_indextts_maskgct_dir(),
            "campplus_dir": _local_indextts_campplus_dir(),
            "bigvgan_dir": _local_indextts_bigvgan_dir(),
        }
    if p == "omnirt_indextts":
        service_url = _omnirt_indextts_service_url()
        return {
            "provider": p,
            "model": _omnirt_indextts_model(),
            "model_dir": "",
            "voice": "local-default",
            "device": "",
            "key_set": False,
            "service_url": service_url,
            "service_url_set": bool(service_url),
            "streaming": _omnirt_indextts_bool("STREAMING", "tts_omnirt_indextts_streaming", True),
            "streaming_mode": _omnirt_indextts_streaming_mode(),
            "max_text_tokens_per_segment": _omnirt_indextts_int(
                "MAX_TEXT_TOKENS_PER_SEGMENT",
                "tts_omnirt_indextts_max_text_tokens_per_segment",
                80,
            ),
            "quick_streaming_tokens": _omnirt_indextts_int(
                "QUICK_STREAMING_TOKENS",
                "tts_omnirt_indextts_quick_streaming_tokens",
                4,
            ),
            "interval_silence_ms": _omnirt_indextts_int(
                "INTERVAL_SILENCE_MS",
                "tts_omnirt_indextts_interval_silence_ms",
                0,
            ),
            "token_window_size": _omnirt_indextts_int(
                "TOKEN_WINDOW_SIZE",
                "tts_omnirt_indextts_token_window_size",
                40,
            ),
            "token_window_hop": _omnirt_indextts_int(
                "TOKEN_WINDOW_HOP",
                "tts_omnirt_indextts_token_window_hop",
                96,
            ),
            "token_window_context": _omnirt_indextts_int(
                "TOKEN_WINDOW_CONTEXT",
                "tts_omnirt_indextts_token_window_context",
                8,
            ),
            "token_window_overlap_ms": _omnirt_indextts_int(
                "TOKEN_WINDOW_OVERLAP_MS",
                "tts_omnirt_indextts_token_window_overlap_ms",
                60,
            ),
        }
    if p in _OPENAI_COMPATIBLE:
        return {
            "provider": p,
            "model": _openai_tts_model(),
            "model_dir": "",
            "voice": _openai_tts_voice(),
            "device": "",
            "key_set": bool(_openai_tts_api_key()),
            "service_url_set": bool(_openai_tts_base_url()),
        }
    if p in _XIAOMI_MIMO:
        return {
            "provider": p,
            "profile": "xiaomi_mimo",
            "model": _xiaomi_tts_model(),
            "model_dir": "",
            "voice": _xiaomi_tts_voice(),
            "device": "",
            "key_set": bool(_xiaomi_tts_api_key()),
            "service_url_set": bool(_xiaomi_tts_base_url()),
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


def tts_status(provider: str | None = None) -> dict[str, str | bool | int | float]:
    return tts_provider_config(provider or _provider())


_QWEN_RT = QWEN_TTS_PROVIDERS
_COSY_WS = COSYVOICE_TTS_PROVIDERS
_SAMBERT = SAMBERT_TTS_PROVIDERS
_LOCAL = LOCAL_TTS_PROVIDERS
_OMNIRT = OMNIRT_TTS_PROVIDERS
_INDEXTTS = INDEXTTS_TTS_PROVIDERS
_OPENAI_COMPATIBLE = OPENAI_COMPATIBLE_TTS_PROVIDERS
_XIAOMI_MIMO = XIAOMI_MIMO_TTS_PROVIDERS
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
    if p in _OPENAI_COMPATIBLE:
        return "openai_compatible"
    if p in _XIAOMI_MIMO:
        return "xiaomi_mimo"
    if p in _INDEXTTS:
        return _resolve_indextts_provider(p)
    if p in _LOCAL or p in _OMNIRT:
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
    p = normalize_tts_provider(tts_provider_override, default=None) or _provider()
    if p in _INDEXTTS:
        p = _resolve_indextts_provider(p)
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

    if p == "local_f5_tts":
        model = (tts_model_override or "").strip() or _local_f5_tts_model()
        return f"TTS_API=local_f5_tts | model={model!r} device={_local_f5_tts_device()!r} prompt_audio_set={bool(_local_f5_tts_prompt_audio())} | {req_part}"

    if p == "local_indextts":
        model = (tts_model_override or "").strip() or _local_indextts_model()
        return (
            f"TTS_API=local_indextts | model={model!r} "
            f"device={_local_indextts_device()!r} prompt_audio_set={bool(_local_indextts_prompt_audio())} | {req_part}"
        )

    if p == "omnirt_indextts":
        model = (tts_model_override or "").strip() or _omnirt_indextts_model()
        return (
            f"TTS_API=omnirt_indextts | model={model!r} "
            f"service_url_set={bool(_omnirt_indextts_service_url())} "
            f"streaming_mode={_omnirt_indextts_streaming_mode()!r} | {req_part}"
        )

    if p in _OPENAI_COMPATIBLE:
        model = (tts_model_override or "").strip() or _openai_tts_model()
        voice = req or _openai_tts_voice()
        return (
            f"TTS_API=openai_compatible | OPENTALKING_TTS_PROVIDER={raw_display} | "
            f"model={model!r} voice_effective={voice!r} base_url_set={bool(_openai_tts_base_url())} "
            f"api_key_set={bool(_openai_tts_api_key())} format={_openai_tts_response_format()!r} | {req_part}"
        )

    if p in _XIAOMI_MIMO:
        model = (tts_model_override or "").strip() or _xiaomi_tts_model()
        voice = req or _xiaomi_tts_voice()
        voice_display = "data:audio/*;base64,..." if voice.startswith("data:audio/") else voice
        return (
            f"TTS_API=xiaomi_mimo | OPENTALKING_TTS_PROVIDER={raw_display} | "
            f"model={model!r} voice_effective={voice_display!r} base_url_set={bool(_xiaomi_tts_base_url())} "
            f"api_key_set={bool(_xiaomi_tts_api_key())} format={_xiaomi_tts_response_format()!r} | {req_part}"
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
    indextts_config: Mapping[str, object] | None = None,
    reuse_ws: bool | None = None,
):
    """返回与 EdgeTTSAdapter 相同接口的 TTS 适配器实例。"""
    p = normalize_tts_provider(tts_provider, default=None) or _provider()
    if p in _INDEXTTS:
        p = _resolve_indextts_provider(p)
    if p in _QWEN_RT:
        from opentalking.providers.tts.dashscope_qwen.adapter import DashScopeQwenTTSAdapter

        return DashScopeQwenTTSAdapter(
            default_voice=default_voice or _dashscope_voice(),
            sample_rate=sample_rate,
            chunk_ms=chunk_ms,
            model=(tts_model or "").strip() or _dashscope_model(),
            service_url=_dashscope_service_url(),
            reuse_ws=reuse_ws,
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

        model = (
            (tts_model or "").strip()
            or os.environ.get("OPENTALKING_TTS_LOCAL_QWEN3_TTS_MODEL", "").strip()
            or os.environ.get("OPENTALKING_LOCAL_QWEN3_TTS_MODEL", "").strip()
            or _settings_value("local_qwen3_tts_model", "")
            or "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
        )
        service_url = (
            os.environ.get("OPENTALKING_TTS_LOCAL_QWEN3_TTS_SERVICE_URL", "").strip()
            or os.environ.get("OPENTALKING_LOCAL_QWEN3_TTS_SERVICE_URL", "").strip()
            or _settings_value("local_qwen3_tts_service_url", "")
        )
        return LocalQwen3TTSAdapter(
            default_voice=default_voice,
            sample_rate=sample_rate,
            chunk_ms=chunk_ms,
            model=model,
            service_url=service_url,
        )
    if p == "local_f5_tts":
        from opentalking.providers.tts.local_f5_tts.adapter import LocalF5TTSAdapter
        model = (tts_model or "").strip() or _local_f5_tts_model()
        model_dir = _local_f5_tts_model_dir(model)
        return LocalF5TTSAdapter(default_voice=default_voice, sample_rate=sample_rate, chunk_ms=chunk_ms, model=model, model_dir=model_dir, runtime_dir=_local_f5_tts_runtime_dir(), ckpt_file=_local_f5_tts_ckpt_file(model_dir), vocoder_local_path=_local_f5_tts_vocoder_local_path(), service_url=_local_f5_tts_service_url(), prompt_audio=_local_f5_tts_prompt_audio(), prompt_text=_local_f5_tts_prompt_text(), device=_local_f5_tts_device())
    if p == "local_indextts":
        from opentalking.providers.tts.local_indextts.adapter import LocalIndexTTSAdapter

        model = (tts_model or "").strip() or _local_indextts_model()
        model_dir = _local_indextts_model_dir(model)
        return LocalIndexTTSAdapter(
            default_voice=default_voice,
            sample_rate=sample_rate,
            chunk_ms=chunk_ms,
            model=model,
            model_dir=model_dir,
            cfg_path=_local_indextts_cfg_path(model_dir),
            service_url=_local_indextts_service_url(),
            prompt_audio=_local_indextts_prompt_audio(),
            w2v_bert_dir=_local_indextts_w2v_bert_dir(),
            maskgct_dir=_local_indextts_maskgct_dir(),
            campplus_dir=_local_indextts_campplus_dir(),
            bigvgan_dir=_local_indextts_bigvgan_dir(),
            device=_local_indextts_device(),
            use_fp16=_local_indextts_bool(
                "USE_FP16",
                "tts_local_indextts_use_fp16",
                _local_indextts_device().startswith("cuda"),
            ),
            use_cuda_kernel=_local_indextts_bool(
                "USE_CUDA_KERNEL",
                "tts_local_indextts_use_cuda_kernel",
                False,
            ),
            use_deepspeed=_local_indextts_bool(
                "USE_DEEPSPEED",
                "tts_local_indextts_use_deepspeed",
                False,
            ),
            indextts_config=indextts_config,
        )
    if p == "omnirt_indextts":
        from opentalking.providers.tts.omnirt_indextts.adapter import OmniRTIndexTTSAdapter

        return OmniRTIndexTTSAdapter(
            service_url=_omnirt_indextts_service_url(),
            default_voice=default_voice,
            sample_rate=sample_rate,
            chunk_ms=chunk_ms,
            model=(tts_model or "").strip() or _omnirt_indextts_model(),
            streaming=_omnirt_indextts_bool("STREAMING", "tts_omnirt_indextts_streaming", True),
            streaming_mode=_omnirt_indextts_streaming_mode(),
            max_text_tokens_per_segment=_omnirt_indextts_int(
                "MAX_TEXT_TOKENS_PER_SEGMENT",
                "tts_omnirt_indextts_max_text_tokens_per_segment",
                80,
            ),
            quick_streaming_tokens=_omnirt_indextts_int(
                "QUICK_STREAMING_TOKENS",
                "tts_omnirt_indextts_quick_streaming_tokens",
                4,
            ),
            interval_silence_ms=_omnirt_indextts_int(
                "INTERVAL_SILENCE_MS",
                "tts_omnirt_indextts_interval_silence_ms",
                0,
            ),
            token_window_size=_omnirt_indextts_int(
                "TOKEN_WINDOW_SIZE",
                "tts_omnirt_indextts_token_window_size",
                40,
            ),
            token_window_hop=_omnirt_indextts_int(
                "TOKEN_WINDOW_HOP",
                "tts_omnirt_indextts_token_window_hop",
                96,
            ),
            token_window_context=_omnirt_indextts_int(
                "TOKEN_WINDOW_CONTEXT",
                "tts_omnirt_indextts_token_window_context",
                8,
            ),
            token_window_overlap_ms=_omnirt_indextts_int(
                "TOKEN_WINDOW_OVERLAP_MS",
                "tts_omnirt_indextts_token_window_overlap_ms",
                60,
            ),
            indextts_config=indextts_config,
        )
    if p in _OPENAI_COMPATIBLE or p in _XIAOMI_MIMO:
        from opentalking.providers.tts.openai_compatible.adapter import OpenAICompatibleTTSAdapter

        if p in _XIAOMI_MIMO:
            return OpenAICompatibleTTSAdapter(
                api_key=_xiaomi_tts_api_key(),
                base_url=_xiaomi_tts_base_url(),
                model=(tts_model or "").strip() or _xiaomi_tts_model(),
                default_voice=(default_voice or "").strip() or _xiaomi_tts_voice(),
                response_format=_xiaomi_tts_response_format(),
                protocol=_xiaomi_tts_protocol(),
                prompt=_xiaomi_tts_prompt(),
                sample_rate=sample_rate,
                chunk_ms=chunk_ms,
            )

        return OpenAICompatibleTTSAdapter(
            api_key=_openai_tts_api_key(),
            base_url=_openai_tts_base_url(),
            model=(tts_model or "").strip() or _openai_tts_model(),
            default_voice=(default_voice or "").strip() or _openai_tts_voice(),
            response_format=_openai_tts_response_format(),
            protocol=_openai_tts_protocol(),
            prompt=_openai_tts_prompt(),
            sample_rate=sample_rate,
            chunk_ms=chunk_ms,
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
    indextts_config: Mapping[str, object] | None = None,
    reuse_ws: bool | None = None,
):
    """Settings-based entry point with optional per-request TTS overrides."""
    from opentalking.core.config import get_settings

    settings = settings or get_settings()
    explicit_provider = normalize_tts_provider(tts_provider, default=None)
    env_provider = normalize_tts_provider(
        os.environ.get("OPENTALKING_TTS_DEFAULT_PROVIDER", "")
        or os.environ.get("OPENTALKING_TTS_PROVIDER", ""),
        default=None,
    )
    provider = (
        explicit_provider
        or getattr(settings, "normalized_tts_default_provider", None)
        or getattr(settings, "normalized_tts_provider", None)
        or env_provider
        or _provider()
    )
    request_tts_model = (tts_model or "").strip() or None
    effective_tts_model = request_tts_model or getattr(settings, "tts_model", "").strip() or None

    if provider in _OPENAI_COMPATIBLE or provider in _XIAOMI_MIMO:
        return create_tts_adapter(
            sample_rate=sample_rate,
            chunk_ms=chunk_ms,
            default_voice=default_voice,
            tts_provider=provider,
            tts_model=request_tts_model,
        )

    if provider == "elevenlabs":
        return _build_elevenlabs_adapter(
            settings=settings,
            sample_rate=sample_rate,
            chunk_ms=chunk_ms,
            default_voice=default_voice,
            tts_model=effective_tts_model,
        )

    if provider == "mock":
        from opentalking.providers.tts.mock.adapter import MockTTSAdapter

        return MockTTSAdapter(
            default_voice=default_voice or "mock",
            sample_rate=sample_rate,
            chunk_ms=chunk_ms,
        )

    # For dashscope/bailian/etc., delegate to create_tts_adapter
    if provider in _QWEN_RT or provider in _COSY_WS or provider in _SAMBERT or provider in _LOCAL or provider in _OMNIRT or provider in _INDEXTTS:
        return create_tts_adapter(
            sample_rate=sample_rate,
            chunk_ms=chunk_ms,
            default_voice=default_voice or getattr(settings, "tts_voice", None),
            tts_provider=provider,
            tts_model=effective_tts_model,
            indextts_config=indextts_config,
            reuse_ws=reuse_ws,
        )

    if provider in _CORE:
        if provider == "mock":
            from opentalking.providers.tts.mock.adapter import MockTTSAdapter

            return MockTTSAdapter(
                default_voice=default_voice or getattr(settings, "tts_voice", None) or "mock",
                sample_rate=sample_rate,
                chunk_ms=chunk_ms,
            )
        return EdgeTTSAdapter(
            default_voice=default_voice or getattr(settings, "tts_voice", None) or _edge_default_voice(),
            sample_rate=sample_rate,
            chunk_ms=chunk_ms,
        )

    return _build_edge_adapter(settings=settings, sample_rate=sample_rate, chunk_ms=chunk_ms)
