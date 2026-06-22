from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from apps.api.core.config import get_settings
from opentalking.providers.memory.factory import close_cached_memory_provider
from opentalking.providers.stt.factory import (
    clear_stt_adapter_cache,
    normalize_stt_provider,
    stt_enabled_providers,
    stt_provider_config,
)
from opentalking.providers.tts.factory import tts_enabled_providers, tts_provider_config
from opentalking.providers.tts.providers import normalize_tts_provider

router = APIRouter(prefix="/runtime-config", tags=["runtime-config"])

_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
_ENV_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")

_RUNTIME_ENV_KEYS = {
    "DASHSCOPE_API_KEY",
    "OPENTALKING_LLM_PROVIDER",
    "OPENTALKING_LLM_BASE_URL",
    "OPENTALKING_LLM_API_KEY",
    "OPENTALKING_LLM_MODEL",
    "OPENTALKING_STT_DEFAULT_PROVIDER",
    "OPENTALKING_STT_ENABLED_PROVIDERS",
    "OPENTALKING_STT_MODEL",
    "OPENTALKING_STT_API_KEY",
    "OPENTALKING_STT_DASHSCOPE_MODEL",
    "OPENTALKING_STT_DASHSCOPE_API_KEY",
    "OPENTALKING_STT_OPENAI_BASE_URL",
    "OPENTALKING_STT_OPENAI_MODEL",
    "OPENTALKING_STT_OPENAI_API_KEY",
    "OPENTALKING_STT_XIAOMI_BASE_URL",
    "OPENTALKING_STT_XIAOMI_MODEL",
    "OPENTALKING_STT_XIAOMI_API_KEY",
    "OPENTALKING_STT_SENSEVOICE_MODEL",
    "OPENTALKING_STT_FUNASR_MODEL",
    "OPENTALKING_STT_SHERPA_ONNX_MODEL",
    "OPENTALKING_TTS_PROVIDER",
    "OPENTALKING_TTS_DEFAULT_PROVIDER",
    "OPENTALKING_TTS_ENABLED_PROVIDERS",
    "OPENTALKING_TTS_VOICE",
    "OPENTALKING_TTS_EDGE_VOICE",
    "OPENTALKING_TTS_DASHSCOPE_SERVICE_URL",
    "OPENTALKING_TTS_DASHSCOPE_MODEL",
    "OPENTALKING_TTS_DASHSCOPE_VOICE",
    "OPENTALKING_TTS_DASHSCOPE_API_KEY",
    "OPENTALKING_TTS_COSYVOICE_SERVICE_URL",
    "OPENTALKING_TTS_COSYVOICE_MODEL",
    "OPENTALKING_TTS_SAMBERT_MODEL",
    "OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL",
    "OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL",
    "OPENTALKING_TTS_LOCAL_INDEXTTS_SERVICE_URL",
    "OPENTALKING_TTS_LOCAL_INDEXTTS_MODEL",
    "OPENTALKING_TTS_OMNIRT_INDEXTTS_SERVICE_URL",
    "OPENTALKING_TTS_OMNIRT_INDEXTTS_MODEL",
    "OPENTALKING_TTS_OPENAI_BASE_URL",
    "OPENTALKING_TTS_OPENAI_MODEL",
    "OPENTALKING_TTS_OPENAI_VOICE",
    "OPENTALKING_TTS_OPENAI_API_KEY",
    "OPENTALKING_TTS_XIAOMI_BASE_URL",
    "OPENTALKING_TTS_XIAOMI_MODEL",
    "OPENTALKING_TTS_XIAOMI_VOICE",
    "OPENTALKING_TTS_XIAOMI_API_KEY",
    "OPENTALKING_MEMORY_MEM0_LLM_PROVIDER",
    "OPENTALKING_MEMORY_MEM0_LLM_BASE_URL",
    "OPENTALKING_MEMORY_MEM0_LLM_API_KEY",
    "OPENTALKING_MEMORY_MEM0_LLM_MODEL",
    "OPENTALKING_MEMORY_MEM0_EMBEDDER_PROVIDER",
    "OPENTALKING_MEMORY_MEM0_EMBEDDER_BASE_URL",
    "OPENTALKING_MEMORY_MEM0_EMBEDDER_API_KEY",
    "OPENTALKING_MEMORY_MEM0_EMBEDDER_MODEL",
}


class RuntimeConfigPayload(BaseModel):
    llm_base_url: Optional[str] = Field(default=None, max_length=2048)
    llm_model: Optional[str] = Field(default=None, max_length=256)
    llm_api_key: Optional[str] = Field(default=None, max_length=4096)
    stt_provider: Optional[str] = Field(default=None, max_length=64)
    stt_base_url: Optional[str] = Field(default=None, max_length=2048)
    stt_model: Optional[str] = Field(default=None, max_length=256)
    stt_api_key: Optional[str] = Field(default=None, max_length=4096)
    tts_provider: Optional[str] = Field(default=None, max_length=64)
    tts_base_url: Optional[str] = Field(default=None, max_length=2048)
    tts_model: Optional[str] = Field(default=None, max_length=256)
    tts_voice: Optional[str] = Field(default=None, max_length=256)
    tts_api_key: Optional[str] = Field(default=None, max_length=4096)
    mem0_llm_provider: Optional[str] = Field(default=None, max_length=64)
    mem0_llm_base_url: Optional[str] = Field(default=None, max_length=2048)
    mem0_llm_api_key: Optional[str] = Field(default=None, max_length=4096)
    mem0_llm_model: Optional[str] = Field(default=None, max_length=256)
    mem0_embedder_provider: Optional[str] = Field(default=None, max_length=64)
    mem0_embedder_base_url: Optional[str] = Field(default=None, max_length=2048)
    mem0_embedder_api_key: Optional[str] = Field(default=None, max_length=4096)
    mem0_embedder_model: Optional[str] = Field(default=None, max_length=256)
    sync_dashscope_api_key: bool = True


def _strip(value: str | None) -> str:
    return (value or "").strip()


def _unquote_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _quote_env_value(value: str) -> str:
    if not value:
        return ""
    if any(ch.isspace() for ch in value) or any(ch in value for ch in ['"', "'", "#"]):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _read_env_lines(path: Path) -> tuple[list[str], dict[str, str]]:
    if not path.exists():
        return [], {}
    lines = path.read_text(encoding="utf-8").splitlines()
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.removeprefix("export ").strip()
        if key:
            values[key] = _unquote_env_value(value.strip())
    return lines, values


def _env_value(values: dict[str, str], key: str, fallback: str = "") -> str:
    value = os.environ.get(key, "").strip() or values.get(key, "").strip() or fallback
    return _expand_env_refs(str(value), values).strip()


def _expand_env_refs(value: str, values: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1) or match.group(2) or ""
        return os.environ.get(key, "") or values.get(key, "") or match.group(0)

    previous = value
    for _ in range(5):
        expanded = _ENV_REF_RE.sub(replace, previous)
        if expanded == previous:
            return expanded
        previous = expanded
    return previous


def _settings_value(settings: Any, name: str, default: str = "") -> str:
    value = getattr(settings, name, default)
    return str(value or "").strip()


def _enabled_provider_csv(current: list[str], provider: str) -> str:
    providers = [item for item in current if item]
    if provider and provider not in providers:
        providers.append(provider)
    return ",".join(providers)


def _write_env_updates(path: Path, updates: dict[str, str]) -> None:
    lines, _ = _read_env_lines(path)
    if path.exists():
        shutil.copy2(path, path.with_name(f"{path.name}.bak.{int(time.time())}"))

    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(line)
            continue
        raw_key, _ = stripped.split("=", 1)
        key = raw_key.removeprefix("export ").strip()
        if key in updates:
            prefix = "export " if raw_key.strip().startswith("export ") else ""
            out.append(f"{prefix}{key}={_quote_env_value(updates[key])}")
            seen.add(key)
        else:
            out.append(line)

    if updates:
        if out and out[-1].strip():
            out.append("")
        for key in sorted(updates):
            if key not in seen:
                out.append(f"{key}={_quote_env_value(updates[key])}")

    tmp = path.with_suffix(f"{path.suffix}.tmp")
    tmp.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    tmp.replace(path)


def _safe_tts_provider(raw: str) -> str:
    try:
        provider = normalize_tts_provider(raw, default="edge") or "edge"
    except ValueError:
        provider = "edge"
    return "indextts" if provider in {"local_indextts", "omnirt_indextts"} else provider


def _safe_stt_provider(raw: str) -> str:
    try:
        return normalize_stt_provider(raw, default="dashscope") or "dashscope"
    except ValueError:
        return "dashscope"


def _current_stt_payload(provider: str, settings: Any, values: dict[str, str]) -> dict[str, Any]:
    status = stt_provider_config(provider)
    if provider == "openai_compatible":
        base_url = _env_value(values, "OPENTALKING_STT_OPENAI_BASE_URL", _settings_value(settings, "stt_openai_base_url"))
        model = _env_value(values, "OPENTALKING_STT_OPENAI_MODEL", _settings_value(settings, "stt_openai_model", "whisper-1"))
        key = _env_value(values, "OPENTALKING_STT_OPENAI_API_KEY", _settings_value(settings, "stt_openai_api_key"))
    elif provider == "xiaomi_mimo":
        base_url = _env_value(values, "OPENTALKING_STT_XIAOMI_BASE_URL", _settings_value(settings, "stt_xiaomi_base_url"))
        model = _env_value(values, "OPENTALKING_STT_XIAOMI_MODEL", _settings_value(settings, "stt_xiaomi_model", "mimo-v2.5-asr"))
        key = _env_value(values, "OPENTALKING_STT_XIAOMI_API_KEY", _settings_value(settings, "stt_xiaomi_api_key"))
    elif provider == "sensevoice":
        base_url = ""
        model = _env_value(values, "OPENTALKING_STT_SENSEVOICE_MODEL", _settings_value(settings, "stt_sensevoice_model", "iic/SenseVoiceSmall"))
        key = ""
    elif provider == "funasr":
        base_url = ""
        model = _env_value(values, "OPENTALKING_STT_FUNASR_MODEL", _settings_value(settings, "stt_funasr_model", "iic/Fun-ASR-Nano-2512"))
        key = ""
    elif provider == "sherpa_onnx":
        base_url = ""
        model = _env_value(values, "OPENTALKING_STT_SHERPA_ONNX_MODEL", _settings_value(settings, "stt_sherpa_onnx_model"))
        key = ""
    else:
        base_url = ""
        model = _env_value(values, "OPENTALKING_STT_DASHSCOPE_MODEL", _settings_value(settings, "stt_dashscope_model", "paraformer-realtime-v2"))
        key = (
            _env_value(values, "OPENTALKING_STT_DASHSCOPE_API_KEY", _settings_value(settings, "stt_dashscope_api_key"))
            or _env_value(values, "DASHSCOPE_API_KEY")
        )
    return {
        "provider": provider,
        "enabled_providers": stt_enabled_providers(),
        "base_url": base_url.rstrip("/"),
        "model": model or str(status.get("model") or ""),
        "api_key_set": bool(key or status.get("key_set")),
        "service_url_set": bool(base_url or status.get("service_url_set")),
    }


def _current_tts_payload(provider: str, settings: Any, values: dict[str, str]) -> dict[str, Any]:
    status = tts_provider_config(provider)
    if provider == "openai_compatible":
        base_url = _env_value(values, "OPENTALKING_TTS_OPENAI_BASE_URL", _settings_value(settings, "tts_openai_base_url"))
        model = _env_value(values, "OPENTALKING_TTS_OPENAI_MODEL", _settings_value(settings, "tts_openai_model", "gpt-4o-mini-tts"))
        voice = _env_value(values, "OPENTALKING_TTS_OPENAI_VOICE", _settings_value(settings, "tts_openai_voice", "alloy"))
        key = _env_value(values, "OPENTALKING_TTS_OPENAI_API_KEY", _settings_value(settings, "tts_openai_api_key"))
    elif provider == "xiaomi_mimo":
        base_url = _env_value(values, "OPENTALKING_TTS_XIAOMI_BASE_URL", _settings_value(settings, "tts_xiaomi_base_url"))
        model = _env_value(values, "OPENTALKING_TTS_XIAOMI_MODEL", _settings_value(settings, "tts_xiaomi_model", "mimo-v2.5-tts"))
        voice = _env_value(values, "OPENTALKING_TTS_XIAOMI_VOICE", _settings_value(settings, "tts_xiaomi_voice", "mimo_default"))
        key = _env_value(values, "OPENTALKING_TTS_XIAOMI_API_KEY", _settings_value(settings, "tts_xiaomi_api_key"))
    elif provider == "cosyvoice":
        base_url = _env_value(values, "OPENTALKING_TTS_COSYVOICE_SERVICE_URL", _settings_value(settings, "tts_cosyvoice_service_url"))
        model = _env_value(values, "OPENTALKING_TTS_COSYVOICE_MODEL", _settings_value(settings, "tts_cosyvoice_model", "cosyvoice-v3-flash"))
        voice = _env_value(values, "OPENTALKING_TTS_VOICE", _settings_value(settings, "tts_voice"))
        key = _env_value(values, "OPENTALKING_TTS_DASHSCOPE_API_KEY", _settings_value(settings, "tts_dashscope_api_key")) or _env_value(values, "DASHSCOPE_API_KEY")
    elif provider == "sambert":
        base_url = ""
        model = _env_value(values, "OPENTALKING_TTS_SAMBERT_MODEL", _settings_value(settings, "tts_sambert_model", "sambert-zhichu-v1"))
        voice = _env_value(values, "OPENTALKING_TTS_VOICE", _settings_value(settings, "tts_voice"))
        key = _env_value(values, "OPENTALKING_TTS_DASHSCOPE_API_KEY", _settings_value(settings, "tts_dashscope_api_key")) or _env_value(values, "DASHSCOPE_API_KEY")
    elif provider == "local_cosyvoice":
        base_url = _env_value(values, "OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL", _settings_value(settings, "tts_local_cosyvoice_service_url"))
        model = _env_value(values, "OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL", _settings_value(settings, "tts_local_cosyvoice_model", "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"))
        voice = _env_value(values, "OPENTALKING_TTS_VOICE", _settings_value(settings, "tts_voice"))
        key = ""
    elif provider == "indextts":
        base_url = (
            _env_value(values, "OPENTALKING_TTS_LOCAL_INDEXTTS_SERVICE_URL", _settings_value(settings, "tts_local_indextts_service_url"))
            or _env_value(values, "OPENTALKING_TTS_OMNIRT_INDEXTTS_SERVICE_URL", _settings_value(settings, "tts_omnirt_indextts_service_url"))
        )
        model = (
            _env_value(values, "OPENTALKING_TTS_LOCAL_INDEXTTS_MODEL", _settings_value(settings, "tts_local_indextts_model", "IndexTeam/IndexTTS-2"))
            or _env_value(values, "OPENTALKING_TTS_OMNIRT_INDEXTTS_MODEL", _settings_value(settings, "tts_omnirt_indextts_model", "IndexTeam/IndexTTS-2"))
        )
        voice = _env_value(values, "OPENTALKING_TTS_VOICE", _settings_value(settings, "tts_voice"))
        key = ""
    elif provider == "dashscope":
        base_url = _env_value(values, "OPENTALKING_TTS_DASHSCOPE_SERVICE_URL", _settings_value(settings, "tts_dashscope_service_url", "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"))
        model = _env_value(values, "OPENTALKING_TTS_DASHSCOPE_MODEL", _settings_value(settings, "tts_dashscope_model", "qwen3-tts-flash-realtime"))
        voice = _env_value(values, "OPENTALKING_TTS_DASHSCOPE_VOICE", _settings_value(settings, "tts_dashscope_voice", "Cherry"))
        key = _env_value(values, "OPENTALKING_TTS_DASHSCOPE_API_KEY", _settings_value(settings, "tts_dashscope_api_key")) or _env_value(values, "DASHSCOPE_API_KEY")
    else:
        base_url = ""
        model = ""
        voice = _env_value(values, "OPENTALKING_TTS_EDGE_VOICE", _settings_value(settings, "tts_edge_voice", "zh-CN-XiaoxiaoNeural"))
        key = ""
    return {
        "provider": provider,
        "enabled_providers": tts_enabled_providers(),
        "base_url": base_url.rstrip("/"),
        "model": model or str(status.get("model") or ""),
        "voice": voice or str(status.get("voice") or ""),
        "api_key_set": bool(key or status.get("key_set")),
        "service_url_set": bool(base_url or status.get("service_url_set")),
    }


def _current_mem0_model_payload(
    *,
    values: dict[str, str],
    settings: Any,
    prefix: str,
    settings_prefix: str,
    default_model: str,
) -> dict[str, Any]:
    provider = _env_value(
        values,
        f"OPENTALKING_MEMORY_MEM0_{prefix}_PROVIDER",
        _settings_value(settings, f"memory_mem0_{settings_prefix}_provider", "openai"),
    )
    base_url = _env_value(
        values,
        f"OPENTALKING_MEMORY_MEM0_{prefix}_BASE_URL",
        _settings_value(settings, f"memory_mem0_{settings_prefix}_base_url"),
    )
    model = _env_value(
        values,
        f"OPENTALKING_MEMORY_MEM0_{prefix}_MODEL",
        _settings_value(settings, f"memory_mem0_{settings_prefix}_model", default_model),
    )
    key = _env_value(
        values,
        f"OPENTALKING_MEMORY_MEM0_{prefix}_API_KEY",
        _settings_value(settings, f"memory_mem0_{settings_prefix}_api_key"),
    )
    return {
        "provider": provider or "openai",
        "base_url": base_url.rstrip("/"),
        "model": model,
        "api_key_set": bool(key),
    }


def _current_mem0_payload(settings: Any, values: dict[str, str]) -> dict[str, Any]:
    return {
        "llm": _current_mem0_model_payload(
            values=values,
            settings=settings,
            prefix="LLM",
            settings_prefix="llm",
            default_model="qwen-flash",
        ),
        "embedder": _current_mem0_model_payload(
            values=values,
            settings=settings,
            prefix="EMBEDDER",
            settings_prefix="embedder",
            default_model="text-embedding-v4",
        ),
    }


def _current_payload(settings: Any | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    _, values = _read_env_lines(_ENV_PATH)
    tts_provider = _safe_tts_provider(
        _env_value(values, "OPENTALKING_TTS_DEFAULT_PROVIDER")
        or _env_value(values, "OPENTALKING_TTS_PROVIDER")
        or _settings_value(settings, "normalized_tts_default_provider")
        or _settings_value(settings, "normalized_tts_provider")
        or _settings_value(settings, "tts_provider", "edge")
    )
    stt_provider = _safe_stt_provider(
        _env_value(values, "OPENTALKING_STT_DEFAULT_PROVIDER")
        or _settings_value(settings, "normalized_stt_default_provider")
        or _settings_value(settings, "normalized_stt_provider")
        or _settings_value(settings, "stt_provider", "dashscope")
    )
    llm_key = _env_value(values, "OPENTALKING_LLM_API_KEY", _settings_value(settings, "llm_api_key"))
    return {
        "llm": {
            "base_url": _env_value(values, "OPENTALKING_LLM_BASE_URL", _settings_value(settings, "llm_base_url")).rstrip("/"),
            "model": _env_value(values, "OPENTALKING_LLM_MODEL", _settings_value(settings, "llm_model", "qwen-flash")),
            "api_key_set": bool(llm_key),
        },
        "stt": _current_stt_payload(stt_provider, settings, values),
        "tts": _current_tts_payload(tts_provider, settings, values),
        "mem0": _current_mem0_payload(settings, values),
    }


def _build_updates(payload: RuntimeConfigPayload) -> dict[str, str]:
    updates: dict[str, str] = {"OPENTALKING_LLM_PROVIDER": "openai_compatible"}
    sync_key = ""

    if value := _strip(payload.llm_base_url):
        updates["OPENTALKING_LLM_BASE_URL"] = value.rstrip("/")
    if value := _strip(payload.llm_model):
        updates["OPENTALKING_LLM_MODEL"] = value
    if value := _strip(payload.llm_api_key):
        updates["OPENTALKING_LLM_API_KEY"] = value
        sync_key = value

    stt_provider = ""
    if raw := _strip(payload.stt_provider):
        try:
            stt_provider = normalize_stt_provider(raw, default=None) or ""
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if stt_provider:
            updates["OPENTALKING_STT_DEFAULT_PROVIDER"] = stt_provider
            updates["OPENTALKING_STT_ENABLED_PROVIDERS"] = _enabled_provider_csv(stt_enabled_providers(), stt_provider)
    if value := _strip(payload.stt_base_url):
        if stt_provider == "openai_compatible":
            updates["OPENTALKING_STT_OPENAI_BASE_URL"] = value.rstrip("/")
        elif stt_provider == "xiaomi_mimo":
            updates["OPENTALKING_STT_XIAOMI_BASE_URL"] = value.rstrip("/")
    if value := _strip(payload.stt_model):
        updates["OPENTALKING_STT_MODEL"] = value
        if stt_provider == "openai_compatible":
            updates["OPENTALKING_STT_OPENAI_MODEL"] = value
        elif stt_provider == "xiaomi_mimo":
            updates["OPENTALKING_STT_XIAOMI_MODEL"] = value
        elif stt_provider == "sensevoice":
            updates["OPENTALKING_STT_SENSEVOICE_MODEL"] = value
        elif stt_provider == "funasr":
            updates["OPENTALKING_STT_FUNASR_MODEL"] = value
        elif stt_provider == "sherpa_onnx":
            updates["OPENTALKING_STT_SHERPA_ONNX_MODEL"] = value
        else:
            updates["OPENTALKING_STT_DASHSCOPE_MODEL"] = value
    if value := _strip(payload.stt_api_key):
        if stt_provider == "openai_compatible":
            updates["OPENTALKING_STT_OPENAI_API_KEY"] = value
        elif stt_provider == "xiaomi_mimo":
            updates["OPENTALKING_STT_XIAOMI_API_KEY"] = value
        else:
            updates["OPENTALKING_STT_DASHSCOPE_API_KEY"] = value
        sync_key = sync_key or value

    tts_provider = ""
    if raw := _strip(payload.tts_provider):
        try:
            normalized = normalize_tts_provider(raw, default=None) or ""
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        tts_provider = "indextts" if normalized in {"local_indextts", "omnirt_indextts"} else normalized
        if tts_provider:
            updates["OPENTALKING_TTS_PROVIDER"] = tts_provider
            updates["OPENTALKING_TTS_DEFAULT_PROVIDER"] = tts_provider
            updates["OPENTALKING_TTS_ENABLED_PROVIDERS"] = _enabled_provider_csv(tts_enabled_providers(), tts_provider)
    if value := _strip(payload.tts_base_url):
        key = {
            "dashscope": "OPENTALKING_TTS_DASHSCOPE_SERVICE_URL",
            "cosyvoice": "OPENTALKING_TTS_COSYVOICE_SERVICE_URL",
            "local_cosyvoice": "OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL",
            "indextts": "OPENTALKING_TTS_LOCAL_INDEXTTS_SERVICE_URL",
            "openai_compatible": "OPENTALKING_TTS_OPENAI_BASE_URL",
            "xiaomi_mimo": "OPENTALKING_TTS_XIAOMI_BASE_URL",
        }.get(tts_provider)
        if key:
            updates[key] = value.rstrip("/")
    if value := _strip(payload.tts_model):
        key = {
            "dashscope": "OPENTALKING_TTS_DASHSCOPE_MODEL",
            "cosyvoice": "OPENTALKING_TTS_COSYVOICE_MODEL",
            "sambert": "OPENTALKING_TTS_SAMBERT_MODEL",
            "local_cosyvoice": "OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL",
            "indextts": "OPENTALKING_TTS_LOCAL_INDEXTTS_MODEL",
            "openai_compatible": "OPENTALKING_TTS_OPENAI_MODEL",
            "xiaomi_mimo": "OPENTALKING_TTS_XIAOMI_MODEL",
        }.get(tts_provider)
        if key:
            updates[key] = value
    if value := _strip(payload.tts_voice):
        updates["OPENTALKING_TTS_VOICE"] = value
        if tts_provider == "edge":
            updates["OPENTALKING_TTS_EDGE_VOICE"] = value
        elif tts_provider == "dashscope":
            updates["OPENTALKING_TTS_DASHSCOPE_VOICE"] = value
        elif tts_provider == "openai_compatible":
            updates["OPENTALKING_TTS_OPENAI_VOICE"] = value
        elif tts_provider == "xiaomi_mimo":
            updates["OPENTALKING_TTS_XIAOMI_VOICE"] = value
    if value := _strip(payload.tts_api_key):
        if tts_provider == "openai_compatible":
            updates["OPENTALKING_TTS_OPENAI_API_KEY"] = value
        elif tts_provider == "xiaomi_mimo":
            updates["OPENTALKING_TTS_XIAOMI_API_KEY"] = value
        else:
            updates["OPENTALKING_TTS_DASHSCOPE_API_KEY"] = value
        sync_key = sync_key or value

    if value := _strip(payload.mem0_llm_provider):
        updates["OPENTALKING_MEMORY_MEM0_LLM_PROVIDER"] = value
    if value := _strip(payload.mem0_llm_base_url):
        updates["OPENTALKING_MEMORY_MEM0_LLM_BASE_URL"] = value.rstrip("/")
    if value := _strip(payload.mem0_llm_model):
        updates["OPENTALKING_MEMORY_MEM0_LLM_MODEL"] = value
    if value := _strip(payload.mem0_llm_api_key):
        updates["OPENTALKING_MEMORY_MEM0_LLM_API_KEY"] = value
        sync_key = sync_key or value

    if value := _strip(payload.mem0_embedder_provider):
        updates["OPENTALKING_MEMORY_MEM0_EMBEDDER_PROVIDER"] = value
    if value := _strip(payload.mem0_embedder_base_url):
        updates["OPENTALKING_MEMORY_MEM0_EMBEDDER_BASE_URL"] = value.rstrip("/")
    if value := _strip(payload.mem0_embedder_model):
        updates["OPENTALKING_MEMORY_MEM0_EMBEDDER_MODEL"] = value
    if value := _strip(payload.mem0_embedder_api_key):
        updates["OPENTALKING_MEMORY_MEM0_EMBEDDER_API_KEY"] = value
        sync_key = sync_key or value

    if payload.sync_dashscope_api_key and sync_key:
        updates.setdefault("DASHSCOPE_API_KEY", sync_key)
    return updates


async def _refresh_settings(request: Request) -> Any:
    get_settings.cache_clear()
    settings = get_settings()
    request.app.state.settings = settings
    clear_stt_adapter_cache()
    await close_cached_memory_provider()
    if hasattr(request.app.state, "wechat_import_registry"):
        delattr(request.app.state, "wechat_import_registry")
    return settings


def _refresh_live_runners(request: Request, settings: Any) -> int:
    runners = getattr(request.app.state, "session_runners", None)
    if not isinstance(runners, dict):
        return 0
    count = 0
    for runner in list(runners.values()):
        if hasattr(runner, "_llm_base_url"):
            runner._llm_base_url = settings.llm_base_url
            runner._llm_api_key = settings.llm_api_key
            runner._llm_model = settings.llm_model
            runner._llm_client = None
            count += 1
        if hasattr(runner, "llm"):
            from opentalking.providers.llm.openai_compatible.adapter import OpenAICompatibleLLMClient

            runner.llm = OpenAICompatibleLLMClient(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                model=settings.llm_model,
            )
            count += 1
    return count


@router.get("")
async def get_runtime_config(request: Request) -> dict[str, Any]:
    return _current_payload(getattr(request.app.state, "settings", None))


@router.post("/apply")
async def apply_runtime_config(payload: RuntimeConfigPayload, request: Request) -> dict[str, Any]:
    updates = _build_updates(payload)
    unknown = set(updates) - _RUNTIME_ENV_KEYS
    if unknown:
        raise HTTPException(status_code=400, detail=f"unsupported runtime config keys: {', '.join(sorted(unknown))}")
    _write_env_updates(_ENV_PATH, updates)
    _, values = _read_env_lines(_ENV_PATH)
    for key in _RUNTIME_ENV_KEYS:
        if key in values:
            os.environ[key] = values[key]
    settings = await _refresh_settings(request)
    refreshed_runners = _refresh_live_runners(request, settings)
    result = _current_payload(settings)
    result["applied"] = True
    result["requires_new_session"] = refreshed_runners == 0
    result["live_runners_refreshed"] = refreshed_runners
    return result
