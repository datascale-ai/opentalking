from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import httpx

from opentalking.models.registry import get_adapter
from opentalking.providers.synthesis import SYNTHESIS_PROVIDERS
from opentalking.providers.synthesis.backends import resolve_model_backend
from opentalking.providers.synthesis.omnirt import auth_headers


@dataclass(frozen=True)
class ModelStatus:
    id: str
    backend: str
    connected: bool
    reason: str

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "id": self.id,
            "backend": self.backend,
            "connected": self.connected,
            "reason": self.reason,
        }


def _endpoint_to_http_url(endpoint: str, path: str) -> str:
    parts = urlsplit(endpoint)
    scheme_map = {"http": "http", "https": "https", "ws": "http", "wss": "https"}
    scheme = scheme_map.get(parts.scheme.lower())
    if scheme is None:
        raise ValueError(f"Unsupported OMNIRT_ENDPOINT scheme: {parts.scheme!r}")
    base_path = parts.path.rstrip("/")
    suffix = path if path.startswith("/") else f"/{path}"
    return urlunsplit((scheme, parts.netloc, base_path + suffix, "", ""))


async def _fetch_omnirt_models_at_path(settings, endpoint: str, status_path: str) -> set[str]:
    url = _endpoint_to_http_url(endpoint, status_path)
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            response = await client.get(url, headers=auth_headers(settings))
            response.raise_for_status()
    except Exception:
        return set()
    payload = response.json()
    if not isinstance(payload, dict):
        return set()
    connected = payload.get("models")
    if isinstance(connected, list):
        return {str(item).strip().lower() for item in connected if str(item).strip()}
    statuses = payload.get("statuses")
    if isinstance(statuses, list):
        result: set[str] = set()
        for item in statuses:
            if not isinstance(item, dict) or not item.get("connected"):
                continue
            model_id = str(item.get("id") or "").strip().lower()
            if model_id:
                result.add(model_id)
        return result
    return set()


async def _fetch_omnirt_audio2video_models(settings) -> set[str]:
    endpoint = (getattr(settings, "omnirt_endpoint", "") or "").strip()
    if not endpoint:
        return set()
    status_path = (
        getattr(settings, "omnirt_audio2video_models_path", "")
        or "/v1/audio2video/models"
    )
    models = await _fetch_omnirt_models_at_path(settings, endpoint, status_path)
    if models or status_path != "/v1/audio2video/models":
        return models
    legacy_path = getattr(settings, "omnirt_avatar_models_path", "") or "/v1/avatar/models"
    return await _fetch_omnirt_models_at_path(settings, endpoint, legacy_path)


def _explicit_env_enabled(name: str) -> bool:
    raw = os.environ.get(name)
    return raw is not None and raw.strip().lower() in {"1", "true", "yes", "on"}


def _local_adapter_available(model: str) -> bool:
    try:
        adapter = get_adapter(model)
    except Exception:
        return False
    runtime_available = getattr(adapter, "runtime_available", None)
    if callable(runtime_available):
        try:
            return bool(runtime_available())
        except Exception:
            return False
    return True


async def _is_direct_ws_reachable(url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme.lower() not in {"ws", "wss"} or not parts.hostname:
        return False
    port = parts.port or (443 if parts.scheme.lower() == "wss" else 80)
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            response = await client.get(_endpoint_to_http_url(url, "/"))
            return response.status_code < 500
    except Exception:
        try:
            with socket.create_connection((parts.hostname, port), timeout=1.0):
                return True
        except OSError:
            return False


async def resolve_model_statuses(settings) -> list[ModelStatus]:
    omnirt_models = await _fetch_omnirt_audio2video_models(settings)
    has_omnirt = bool((getattr(settings, "omnirt_endpoint", "") or "").strip())

    statuses: list[ModelStatus] = []
    for model in SYNTHESIS_PROVIDERS:
        resolved = resolve_model_backend(model, settings)
        connected = False
        reason = "not_configured"
        if resolved.backend == "mock":
            connected = True
            reason = "local_self_test"
        elif resolved.backend == "local":
            connected = _local_adapter_available(model)
            reason = "local_runtime" if connected else "local_adapter_missing"
        elif resolved.backend == "omnirt":
            if has_omnirt:
                connected = model in omnirt_models
                reason = "omnirt" if connected else "omnirt_unavailable"
            elif model == "flashtalk" and resolved.backend == "omnirt":
                connected = bool(getattr(settings, "flashtalk_ws_url", ""))
                reason = "legacy_ws" if connected else "not_configured"
            else:
                reason = "not_configured"
        elif resolved.backend == "direct_ws":
            if resolved.ws_url:
                connected = await _is_direct_ws_reachable(resolved.ws_url)
                reason = "direct_ws" if connected else "direct_ws_unavailable"
            else:
                reason = "not_configured"
            if model == "flashhead" and _explicit_env_enabled("OPENTALKING_FLASHHEAD_ENABLED"):
                connected = True
                reason = "explicit_enabled"
        statuses.append(
            ModelStatus(
                id=model,
                backend=resolved.backend,
                connected=connected,
                reason=reason,
            )
        )
    return statuses


async def connected_model_ids(settings) -> list[str]:
    return [status.id for status in await resolve_model_statuses(settings) if status.connected]
