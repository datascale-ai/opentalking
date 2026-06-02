from __future__ import annotations

from functools import lru_cache
from typing import Any

from opentalking.core.config import Settings, get_settings
from opentalking.providers.memory.base import MemoryProvider
from opentalking.providers.memory.mem0_provider import InMemoryMemoryProvider, Mem0MemoryProvider
from opentalking.providers.memory.noop import NoopMemoryProvider
from opentalking.providers.memory.sqlite_provider import SQLiteMemoryProvider


def _mem0_config(settings: Settings) -> dict[str, Any]:
    raw = (settings.memory_mem0_config or "").strip()
    if not raw:
        return {}
    import json

    loaded = json.loads(raw)
    return loaded if isinstance(loaded, dict) else {}


@lru_cache(maxsize=1)
def build_memory_provider() -> MemoryProvider:
    settings = get_settings()
    provider = (settings.memory_provider or "none").strip().lower()
    if provider in {"", "none", "noop", "disabled"}:
        return NoopMemoryProvider()
    if provider in {"sqlite", "local"}:
        return SQLiteMemoryProvider(settings.memory_sqlite_path)
    if provider == "mem0":
        return Mem0MemoryProvider(config=_mem0_config(settings))
    if provider in {"memory", "inmemory", "in-memory"}:
        return InMemoryMemoryProvider()
    raise ValueError(f"unsupported memory provider: {settings.memory_provider}")
