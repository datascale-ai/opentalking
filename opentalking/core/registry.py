"""Capability registry — single source of truth for provider lookup.

Usage:
    from opentalking.core.registry import register, resolve

    @register("synthesis", "flashtalk")
    class FlashTalkAdapter: ...

    cls = resolve("synthesis", "flashtalk")
"""
from __future__ import annotations

from typing import Any, Callable


class RegistryError(KeyError):
    pass


_REGISTRY: dict[str, dict[str, Any]] = {}


def register(capability: str, key: str) -> Callable[[Any], Any]:
    def decorator(cls_or_factory):
        bucket = _REGISTRY.setdefault(capability, {})
        if key in bucket:
            raise RegistryError(f"{capability}/{key} already registered")
        bucket[key] = cls_or_factory
        return cls_or_factory

    return decorator


def resolve(capability: str, key: str) -> Any:
    if capability not in _REGISTRY:
        raise RegistryError(f"unknown capability: {capability}")
    if key not in _REGISTRY[capability]:
        raise RegistryError(f"unknown {capability} provider: {key}")
    return _REGISTRY[capability][key]


def list_keys(capability: str) -> list[str]:
    return sorted(_REGISTRY.get(capability, {}).keys())


def list_capabilities() -> list[str]:
    return sorted(_REGISTRY.keys())


def _reset_for_tests() -> None:
    _REGISTRY.clear()
