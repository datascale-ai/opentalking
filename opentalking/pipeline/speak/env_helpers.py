"""Environment-variable helpers for the synthesis pipeline.

Extracted from synthesis_runner.py to keep that file focused on orchestration.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)


def default_flashtalk_ws_url() -> str:
    """Resolve a default FlashTalk WS URL.

    Precedence: OMNIRT_ENDPOINT (preferred) → OPENTALKING_FLASHTALK_WS_URL
    (legacy override) → ws://<SERVER_HOST or localhost>:8765 fallback.
    """
    omnirt = (os.environ.get("OMNIRT_ENDPOINT") or "").strip()
    if omnirt:
        from opentalking.providers.synthesis.omnirt import derive_audio2video_ws_url
        path_template = (
            os.environ.get("OPENTALKING_OMNIRT_AUDIO2VIDEO_PATH_TEMPLATE")
            or "/v1/audio2video/{model}"
        )
        return derive_audio2video_ws_url(omnirt, "flashtalk", path_template=path_template)

    legacy = (os.environ.get("OPENTALKING_FLASHTALK_WS_URL") or "").strip()
    if legacy:
        return legacy

    server_host = os.environ.get("SERVER_HOST", "localhost")
    return f"ws://{server_host}:8765"


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None and name.startswith("FLASHTALK_"):
        raw = os.environ.get(f"OPENTALKING_{name}")
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        log.warning("Invalid %s=%r, using %.1f", name, raw, default)
        return default


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None and name.startswith("FLASHTALK_"):
        raw = os.environ.get(f"OPENTALKING_{name}")
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        log.warning("Invalid %s=%r, using %d", name, raw, default)
        return default


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None and name.startswith("FLASHTALK_"):
        raw = os.environ.get(f"OPENTALKING_{name}")
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}
