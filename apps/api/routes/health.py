from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Request

from opentalking.core.queue_status import get_flashtalk_queue_status
from opentalking.models.quicktalk.paths import resolve_quicktalk_asset_root
from opentalking.providers.stt.factory import stt_enabled_providers, stt_provider_config, stt_status
from opentalking.providers.tts.factory import tts_enabled_providers, tts_provider_config, tts_status

router = APIRouter(tags=["health"])

_IGNORED_LEGACY_ENV = (
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_MODEL",
    "LLM_SYSTEM_PROMPT",
    "OPENTALKING_QWEN_TTS_MODEL",
    "OPENTALKING_QWEN_TTS_WS_URL",
    "OPENTALKING_COSYVOICE_WS_URL",
    "OPENTALKING_STT_PROVIDER",
    "OPENTALKING_STT_MODEL",
    "OPENTALKING_STT_API_KEY",
    "OPENTALKING_TTS_PROVIDER",
    "OPENTALKING_TTS_MODEL",
    "OPENTALKING_TTS_API_KEY",
)


def _runtime_status_payload(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    stt = stt_status()
    stt_provider = str(stt.get("provider", ""))
    stt_model = str(stt.get("model", ""))
    stt_device = str(stt.get("device", ""))
    stt_provider_list = stt_enabled_providers()
    if stt_provider not in stt_provider_list:
        stt_provider_list = [stt_provider, *stt_provider_list]
    stt_status_providers = [*stt_provider_list]
    for provider in ("sensevoice", "dashscope", "xiaomi_mimo", "openai_compatible"):
        if provider not in stt_status_providers:
            stt_status_providers.append(provider)
    stt_provider_map = {provider: stt_provider_config(provider) for provider in stt_status_providers}
    stt_effective = stt_provider_map.get(stt_provider, stt)
    tts = tts_status()
    tts_provider = str(tts.get("provider", ""))
    tts_provider_list = tts_enabled_providers()
    if tts_provider not in tts_provider_list:
        tts_provider_list = [tts_provider, *tts_provider_list]
    tts_status_providers = [*tts_provider_list]
    for provider in (
        "local_cosyvoice",
        "indextts",
        "dashscope",
        "xiaomi_mimo",
        "openai_compatible",
        "edge",
        "cosyvoice",
        "sambert",
    ):
        if provider not in tts_status_providers:
            tts_status_providers.append(provider)
    tts_provider_map = {provider: tts_provider_config(provider) for provider in tts_status_providers}
    tts_effective = tts_provider_map.get(tts_provider, tts)
    llm_key = os.environ.get("OPENTALKING_LLM_API_KEY", "").strip() or str(
        getattr(settings, "llm_api_key", "") or ""
    ).strip()
    ignored_legacy_env = [name for name in _IGNORED_LEGACY_ENV if os.environ.get(name)]
    quicktalk_backend = os.environ.get("OPENTALKING_QUICKTALK_BACKEND", "").strip() or str(
        getattr(settings, "quicktalk_backend", "") or ""
    ).strip()
    quicktalk_device = os.environ.get("OPENTALKING_QUICKTALK_DEVICE", "").strip() or str(
        getattr(settings, "quicktalk_device", "") or ""
    ).strip()
    quicktalk_asset_root_path = resolve_quicktalk_asset_root(settings)
    quicktalk_asset_root = str(quicktalk_asset_root_path) if quicktalk_asset_root_path else ""
    return {
        "status": "ok",
        "llm_provider": os.environ.get("OPENTALKING_LLM_PROVIDER", "").strip()
        or str(getattr(settings, "llm_provider", "openai_compatible") or "openai_compatible"),
        "llm_model": os.environ.get("OPENTALKING_LLM_MODEL", "").strip()
        or str(getattr(settings, "llm_model", "") or ""),
        "llm_key_set": bool(llm_key),
        "tts_provider": tts_provider,
        "tts_default_provider": tts_provider,
        "tts_enabled_providers": tts_provider_list,
        "tts_providers": tts_provider_map,
        "tts_model": tts_effective.get("model", ""),
        "tts_key_set": bool(tts_effective.get("key_set")),
        "tts_service_url_set": bool(tts_effective.get("service_url_set")),
        "tts_voice": tts_effective.get("voice", ""),
        "tts_model_dir": tts_effective.get("model_dir", ""),
        "tts_mode": os.environ.get("OPENTALKING_TTS_MODE", "").strip().lower()
        or str(tts_effective.get("backend") or ("local" if tts_provider.startswith("local_") else "omnirt" if tts_provider.startswith("omnirt_") else "api")),
        "stt_provider": stt_provider,
        "stt_default_provider": stt_provider,
        "stt_enabled_providers": stt_provider_list,
        "stt_providers": stt_provider_map,
        "stt_model": stt_model,
        "stt_model_dir": stt_effective.get("model_dir", ""),
        "stt_key_set": bool(stt_effective.get("key_set")),
        "stt_device": stt_device,
        "default_model": str(getattr(settings, "default_model", "") or ""),
        "quicktalk_backend": quicktalk_backend,
        "quicktalk_device": quicktalk_device,
        "quicktalk_asset_root": quicktalk_asset_root,
        "ignored_legacy_env": ignored_legacy_env,
    }


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    return _runtime_status_payload(request)


@router.get("/runtime/status")
async def runtime_status(request: Request) -> dict[str, Any]:
    return _runtime_status_payload(request)


@router.get("/queue/status")
async def queue_status(request: Request) -> dict[str, bool | int]:
    try:
        return await get_flashtalk_queue_status(request.app.state.redis)
    except Exception:
        return {"slot_occupied": False, "queue_size": 0}
