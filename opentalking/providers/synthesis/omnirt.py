"""OmniRT integration helpers.

OmniRT (https://github.com/datascale-ai/omnirt) is a multimodal inference
runtime that serves multiple synthesis models (FlashTalk / MuseTalk / Wav2Lip)
behind a single endpoint, distinguishing models by URL path.

This module provides the URL derivation OpenTalking uses to talk to OmniRT.
The actual streaming protocol is the existing FlashTalk-compatible WebSocket
binary protocol (`opentalking.providers.synthesis.flashtalk.ws_client`),
which OmniRT speaks for all `audio2video`-class models.
"""
from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

DEFAULT_PATH_TEMPLATE = "/v1/audio2video/{model}"
DEFAULT_VIDEO_CLONE_PATH_TEMPLATE = "/v1/avatar/video-clone/{model}"


def derive_audio2video_ws_url(
    endpoint: str,
    model: str,
    *,
    path_template: str = DEFAULT_PATH_TEMPLATE,
) -> str:
    """Build the model-specific WebSocket URL behind an OmniRT endpoint.

    >>> derive_audio2video_ws_url("http://omnirt:9000", "flashtalk")
    'ws://omnirt:9000/v1/audio2video/flashtalk'
    >>> derive_audio2video_ws_url("https://omnirt.example.com", "musetalk")
    'wss://omnirt.example.com/v1/audio2video/musetalk'
    >>> derive_audio2video_ws_url("ws://omnirt:9000", "wav2lip")
    'ws://omnirt:9000/v1/audio2video/wav2lip'

    Trailing slashes and existing paths on the endpoint are preserved as a
    prefix; the template is appended.
    """
    if not endpoint:
        raise ValueError("OMNIRT_ENDPOINT is empty")

    parts = urlsplit(endpoint)
    scheme_map = {"http": "ws", "https": "wss", "ws": "ws", "wss": "wss"}
    scheme = scheme_map.get(parts.scheme.lower())
    if scheme is None:
        raise ValueError(f"Unsupported OMNIRT_ENDPOINT scheme: {parts.scheme!r}")

    base_path = parts.path.rstrip("/")
    suffix = path_template.format(model=model)
    if not suffix.startswith("/"):
        suffix = "/" + suffix

    return urlunsplit((scheme, parts.netloc, base_path + suffix, "", ""))


def derive_video_clone_ws_url(
    endpoint: str,
    model: str = "fasterliveportrait",
    *,
    path_template: str = DEFAULT_VIDEO_CLONE_PATH_TEMPLATE,
) -> str:
    """Build the independent video-clone WebSocket URL behind OmniRT."""
    return derive_audio2video_ws_url(endpoint, model, path_template=path_template)


def resolve_synthesis_ws_url(model: str, settings) -> str:
    """Resolve the WS URL for a synthesis model, with backward-compat precedence.

    Precedence:
        1. OMNIRT_ENDPOINT  (if set, derive per-model URL from it — recommended)
        2. Model-specific override (settings.flashtalk_ws_url etc.)
        3. localhost default (port 8765 for FlashTalk-protocol services)
    """
    endpoint = (getattr(settings, "omnirt_endpoint", "") or "").strip()
    if endpoint:
        return derive_audio2video_ws_url(
            endpoint,
            model,
            path_template=(
                getattr(settings, "omnirt_audio2video_path_template", DEFAULT_PATH_TEMPLATE)
                or DEFAULT_PATH_TEMPLATE
            ),
        )

    if model == "flashtalk":
        ws = (getattr(settings, "flashtalk_ws_url", "") or "").strip()
        if ws:
            return ws
    if model == "flashhead":
        ws = (getattr(settings, "flashhead_ws_url", "") or "").strip()
        if ws:
            return ws

    return f"ws://localhost:8765{DEFAULT_PATH_TEMPLATE.format(model=model)}"


def auth_headers(settings) -> dict[str, str]:
    """HTTP/WS headers to authenticate against OmniRT (empty if no key set)."""
    api_key = (getattr(settings, "omnirt_api_key", "") or "").strip()
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}"}
