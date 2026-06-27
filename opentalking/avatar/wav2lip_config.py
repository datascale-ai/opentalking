from __future__ import annotations

import json
from pathlib import Path
from typing import Any

WAV2LIP_POSTPROCESS_MODES = {"basic", "opentalking_improved", "easy_improved", "easy_enhanced"}
DEFAULT_WAV2LIP_POSTPROCESS_MODE = "easy_improved"


def normalize_wav2lip_postprocess_mode(raw: object, *, default: str = DEFAULT_WAV2LIP_POSTPROCESS_MODE) -> str:
    fallback = str(default or DEFAULT_WAV2LIP_POSTPROCESS_MODE).strip().lower().replace("-", "_")
    if fallback not in WAV2LIP_POSTPROCESS_MODES:
        fallback = DEFAULT_WAV2LIP_POSTPROCESS_MODE
    if raw is None:
        return fallback
    mode = str(raw).strip().lower().replace("-", "_")
    return mode if mode in WAV2LIP_POSTPROCESS_MODES else fallback


def optional_wav2lip_postprocess_mode(raw: object) -> str | None:
    if raw is None:
        return None
    mode = str(raw).strip().lower().replace("-", "_")
    if mode in {"", "auto"}:
        return None
    return mode if mode in WAV2LIP_POSTPROCESS_MODES else None


def manifest_preferred_wav2lip_postprocess_mode(manifest: dict[str, Any], *, default: str) -> str:
    metadata = manifest.get("metadata")
    preferred = metadata.get("preferred_wav2lip_postprocess_mode") if isinstance(metadata, dict) else None
    return normalize_wav2lip_postprocess_mode(preferred, default=default)


def read_manifest_preferred_wav2lip_postprocess_mode(manifest_path: Path, *, default: str) -> str:
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return normalize_wav2lip_postprocess_mode(None, default=default)
    if not isinstance(raw, dict):
        return normalize_wav2lip_postprocess_mode(None, default=default)
    return manifest_preferred_wav2lip_postprocess_mode(raw, default=default)
