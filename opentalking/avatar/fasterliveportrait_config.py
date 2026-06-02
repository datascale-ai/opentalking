from __future__ import annotations

import math
from typing import Any

FasterLivePortraitConfigValue = bool | float | str

DEFAULT_FASTLIVEPORTRAIT_CONFIG: dict[str, FasterLivePortraitConfigValue] = {
    "head_motion_multiplier": 0.3,
    "pose_motion_multiplier": 0.35,
    "yaw_multiplier": 0.85,
    "pitch_multiplier": 1.0,
    "roll_multiplier": 0.85,
    "expression_multiplier": 1.0,
    "mouth_open_multiplier": 1.25,
    "mouth_corner_multiplier": 0.85,
    "cheek_jaw_multiplier": 0.9,
    "driving_multiplier": 1.0,
    "cfg_scale": 4.0,
    "animation_region": "lip",
    "flag_stitching": True,
    "flag_pasteback": True,
    "flag_relative_motion": True,
    "flag_normalize_lip": True,
    "flag_lip_retargeting": False,
}

FASTLIVEPORTRAIT_RUNTIME_CONFIG_LIMITS: dict[str, tuple[float, float]] = {
    "head_motion_multiplier": (0.0, 4.0),
    "pose_motion_multiplier": (0.0, 4.0),
    "yaw_multiplier": (0.0, 4.0),
    "pitch_multiplier": (0.0, 4.0),
    "roll_multiplier": (0.0, 4.0),
    "expression_multiplier": (0.0, 4.0),
    "mouth_open_multiplier": (0.0, 4.0),
    "mouth_corner_multiplier": (0.0, 4.0),
    "cheek_jaw_multiplier": (0.0, 4.0),
    "driving_multiplier": (0.0, 4.0),
    "cfg_scale": (0.0, 10.0),
}
FASTLIVEPORTRAIT_ANIMATION_REGIONS = {"all", "exp", "pose", "lip", "eyes"}
FASTLIVEPORTRAIT_BOOL_CONFIG_KEYS = {
    "flag_stitching",
    "flag_pasteback",
    "flag_relative_motion",
    "flag_normalize_lip",
    "flag_lip_retargeting",
}

FASTLIVEPORTRAIT_RUNTIME_CONFIG_KEYS = tuple(DEFAULT_FASTLIVEPORTRAIT_CONFIG.keys())


def normalize_fasterliveportrait_runtime_config(raw: Any) -> dict[str, FasterLivePortraitConfigValue]:
    """Return only runtime-safe FasterLivePortrait controls.

    Size, fps, chunking, pasteback, and other structural settings are
    intentionally ignored here because they cannot safely change mid-session.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("fasterliveportrait_config must be an object")

    out: dict[str, FasterLivePortraitConfigValue] = {}
    for key in FASTLIVEPORTRAIT_RUNTIME_CONFIG_KEYS:
        if key not in raw:
            continue
        value = raw.get(key)
        if value is None or value == "":
            continue
        if key == "animation_region":
            region = str(value).strip().lower()
            if region not in FASTLIVEPORTRAIT_ANIMATION_REGIONS:
                allowed = ", ".join(sorted(FASTLIVEPORTRAIT_ANIMATION_REGIONS))
                raise ValueError(f"animation_region must be one of: {allowed}")
            out[key] = region
            continue
        if key in FASTLIVEPORTRAIT_BOOL_CONFIG_KEYS:
            if isinstance(value, bool):
                out[key] = value
                continue
            if isinstance(value, str):
                out[key] = value.strip().lower() in {"1", "true", "yes", "on"}
                continue
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                out[key] = bool(value)
                continue
            raise ValueError(f"{key} must be a boolean")
        if isinstance(value, bool):
            raise ValueError(f"{key} must be a number")
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} must be a number") from exc
        if not math.isfinite(parsed):
            raise ValueError(f"{key} must be finite")
        lo, hi = FASTLIVEPORTRAIT_RUNTIME_CONFIG_LIMITS[key]
        if parsed < lo or parsed > hi:
            raise ValueError(f"{key} must be between {lo:g} and {hi:g}")
        out[key] = parsed
    return out
