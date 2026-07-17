from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

from opentalking.core.config import Settings, get_settings
from opentalking.providers.memory.base import MemoryProvider
from opentalking.providers.memory.mem0_provider import (
    InMemoryMemoryProvider,
    Mem0MemoryProvider,
    Mem0UnavailableError,
)
from opentalking.providers.memory.noop import NoopMemoryProvider
from opentalking.providers.memory.sqlite_provider import SQLiteMemoryProvider

log = logging.getLogger(__name__)


def _strip(value: Any) -> str:
    return str(value or "").strip()


def _base_url_key(provider: str) -> str:
    return "openai_base_url" if provider.lower() == "openai" else "base_url"


def _model_config(*, provider: str, model: str, api_key: str, base_url: str) -> dict[str, Any]:
    cleaned_provider = _strip(provider)
    config: dict[str, Any] = {}
    if _strip(model):
        config["model"] = _strip(model)
    if _strip(api_key):
        config["api_key"] = _strip(api_key)
    if _strip(base_url):
        config[_base_url_key(cleaned_provider)] = _strip(base_url)
    if not cleaned_provider and not config:
        return {}
    return {"provider": cleaned_provider or "openai", "config": config}


def _normalize_vector_store(config: dict[str, Any]) -> dict[str, Any]:
    vector_store = config.get("vector_store")
    if isinstance(vector_store, dict) and str(vector_store.get("provider") or "").lower() == "qdrant":
        store_config = vector_store.get("config")
        if isinstance(store_config, dict) and store_config.get("path") and "on_disk" not in store_config:
            store_config["on_disk"] = True
    return config


def _split_mem0_config(settings: Settings) -> dict[str, Any]:
    config: dict[str, Any] = {}

    llm = _model_config(
        provider=settings.memory_mem0_llm_provider,
        model=settings.memory_mem0_llm_model,
        api_key=settings.memory_mem0_llm_api_key,
        base_url=settings.memory_mem0_llm_base_url,
    )
    if llm:
        config["llm"] = llm

    embedder = _model_config(
        provider=settings.memory_mem0_embedder_provider,
        model=settings.memory_mem0_embedder_model,
        api_key=settings.memory_mem0_embedder_api_key,
        base_url=settings.memory_mem0_embedder_base_url,
    )
    if embedder:
        embedder_config = embedder.setdefault("config", {})
        dims = int(getattr(settings, "memory_mem0_embedder_embedding_dims", 0) or 0)
        if dims > 0:
            embedder_config["embedding_dims"] = dims
        config["embedder"] = embedder

    vector_provider = _strip(settings.memory_mem0_vector_store_provider)
    if vector_provider:
        store_config: dict[str, Any] = {}
        if _strip(settings.memory_mem0_vector_store_collection_name):
            store_config["collection_name"] = _strip(settings.memory_mem0_vector_store_collection_name)
        if _strip(settings.memory_mem0_vector_store_path):
            store_config["path"] = _strip(settings.memory_mem0_vector_store_path)
        if _strip(settings.memory_mem0_vector_store_host):
            store_config["host"] = _strip(settings.memory_mem0_vector_store_host)
        port = int(getattr(settings, "memory_mem0_vector_store_port", 0) or 0)
        if port > 0:
            store_config["port"] = port
        dims = int(getattr(settings, "memory_mem0_vector_store_embedding_model_dims", 0) or 0)
        if dims > 0:
            store_config["embedding_model_dims"] = dims
        config["vector_store"] = {"provider": vector_provider, "config": store_config}

    return _normalize_vector_store(config)


def _mem0_config(settings: Settings) -> dict[str, Any]:
    raw = (settings.memory_mem0_config or "").strip()
    if raw:
        import json

        loaded = json.loads(raw)
        if not isinstance(loaded, dict):
            return {}
        return _normalize_vector_store(loaded)
    return _split_mem0_config(settings)


def _contains_mem0_credential(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in {"api_key", "apikey", "admin_api_key", "workload_identity"} and _strip(child):
                return True
            if _contains_mem0_credential(child):
                return True
    if isinstance(value, list):
        return any(_contains_mem0_credential(item) for item in value)
    return False


def _mem0_credentials_available(config: dict[str, Any]) -> bool:
    if _contains_mem0_credential(config):
        return True
    return bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_ADMIN_KEY"))


def _is_missing_mem0_credentials_error(exc: Exception) -> bool:
    message = str(exc)
    return "Missing credentials" in message or "OPENAI_API_KEY" in message or "OPENAI_ADMIN_KEY" in message


@lru_cache(maxsize=1)
def build_memory_provider() -> MemoryProvider:
    settings = get_settings()
    provider = (settings.memory_provider or "none").strip().lower()
    if provider in {"", "none", "noop", "disabled"}:
        return NoopMemoryProvider()
    if provider in {"sqlite", "local"}:
        return SQLiteMemoryProvider(settings.memory_sqlite_path)
    if provider == "mem0":
        config = _mem0_config(settings)
        if not _mem0_credentials_available(config):
            log.info("mem0 memory provider is not configured; using noop memory provider until API keys are applied")
            return NoopMemoryProvider()
        try:
            return Mem0MemoryProvider(config=config)
        except Mem0UnavailableError:
            return SQLiteMemoryProvider(settings.memory_sqlite_path)
        except Exception as exc:  # noqa: BLE001
            if _is_missing_mem0_credentials_error(exc):
                log.info("mem0 memory provider is missing credentials; using noop memory provider until API keys are applied")
                return NoopMemoryProvider()
            raise
    if provider in {"memory", "inmemory", "in-memory"}:
        return InMemoryMemoryProvider()
    raise ValueError(f"unsupported memory provider: {settings.memory_provider}")


async def close_cached_memory_provider() -> None:
    if build_memory_provider.cache_info().currsize <= 0:
        return
    provider = build_memory_provider()
    try:
        await provider.close()
    except Exception:  # noqa: BLE001
        log.warning("failed to close cached memory provider", exc_info=True)
    finally:
        build_memory_provider.cache_clear()
