from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import httpx

from opentalking.providers.synthesis import SYNTHESIS_PROVIDERS
from opentalking.providers.synthesis.omnirt import auth_headers


@dataclass(frozen=True)
class ModelStatus:
    id: str
    connected: bool
    reason: str

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "id": self.id,
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


async def resolve_model_statuses(settings) -> list[ModelStatus]:
    omnirt_models = await _fetch_omnirt_audio2video_models(settings)
    has_omnirt = bool((getattr(settings, "omnirt_endpoint", "") or "").strip())
    has_flashtalk = bool((getattr(settings, "flashtalk_ws_url", "") or "").strip())

    statuses: list[ModelStatus] = []
    for model in SYNTHESIS_PROVIDERS:
        connected = False
        reason = "not_configured"
        if model == "mock":
            connected = True
            reason = "local_self_test"
        elif model == "flashtalk":
            if has_omnirt:
                connected = model in omnirt_models
                reason = "omnirt" if connected else "omnirt_unavailable"
            else:
                connected = has_flashtalk
                reason = "legacy_ws" if connected else "not_configured"
        elif model in {"wav2lip", "musetalk"}:
            connected = has_omnirt and model in omnirt_models
            reason = "omnirt" if connected else "omnirt_unavailable"
        elif model == "flashhead":
            connected = _explicit_env_enabled("OPENTALKING_FLASHHEAD_ENABLED")
            reason = "explicit_enabled" if connected else "not_configured"
        elif model == "quicktalk":
            connected = True
            reason = "local_runtime"
        statuses.append(ModelStatus(id=model, connected=connected, reason=reason))
    return statuses


async def connected_model_ids(settings) -> list[str]:
    return [status.id for status in await resolve_model_statuses(settings) if status.connected]
