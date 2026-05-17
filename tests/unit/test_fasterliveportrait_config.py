from __future__ import annotations

import pytest

from opentalking.avatar.fasterliveportrait_config import (
    DEFAULT_FASTLIVEPORTRAIT_CONFIG,
    normalize_fasterliveportrait_runtime_config,
)


def test_normalize_fasterliveportrait_runtime_config_accepts_supported_controls() -> None:
    config = normalize_fasterliveportrait_runtime_config(
        {
            "head_motion_multiplier": "0.45",
            "pose_motion_multiplier": 0.35,
            "yaw_multiplier": 0.8,
            "pitch_multiplier": 1.0,
            "roll_multiplier": 0.7,
            "expression_multiplier": 1,
            "mouth_open_multiplier": 1.8,
            "mouth_corner_multiplier": 0.9,
            "cheek_jaw_multiplier": 1.2,
            "driving_multiplier": 0.75,
            "cfg_scale": 4,
            "animation_region": "lip",
            "width": 999,
        }
    )

    assert config == {
        "head_motion_multiplier": 0.45,
        "pose_motion_multiplier": 0.35,
        "yaw_multiplier": 0.8,
        "pitch_multiplier": 1.0,
        "roll_multiplier": 0.7,
        "expression_multiplier": 1.0,
        "mouth_open_multiplier": 1.8,
        "mouth_corner_multiplier": 0.9,
        "cheek_jaw_multiplier": 1.2,
        "driving_multiplier": 0.75,
        "cfg_scale": 4.0,
        "animation_region": "lip",
    }


def test_normalize_fasterliveportrait_runtime_config_rejects_out_of_range_values() -> None:
    with pytest.raises(ValueError, match="mouth_open_multiplier"):
        normalize_fasterliveportrait_runtime_config({"mouth_open_multiplier": 9.0})


def test_default_fasterliveportrait_config_matches_realtime_baseline() -> None:
    assert DEFAULT_FASTLIVEPORTRAIT_CONFIG["head_motion_multiplier"] == 0.3
    assert DEFAULT_FASTLIVEPORTRAIT_CONFIG["pose_motion_multiplier"] == 0.35
    assert DEFAULT_FASTLIVEPORTRAIT_CONFIG["yaw_multiplier"] == 0.85
    assert DEFAULT_FASTLIVEPORTRAIT_CONFIG["pitch_multiplier"] == 1.0
    assert DEFAULT_FASTLIVEPORTRAIT_CONFIG["roll_multiplier"] == 0.85
    assert DEFAULT_FASTLIVEPORTRAIT_CONFIG["expression_multiplier"] == 1.0
    assert DEFAULT_FASTLIVEPORTRAIT_CONFIG["mouth_open_multiplier"] == 1.25
    assert DEFAULT_FASTLIVEPORTRAIT_CONFIG["mouth_corner_multiplier"] == 0.85
    assert DEFAULT_FASTLIVEPORTRAIT_CONFIG["cheek_jaw_multiplier"] == 0.9
    assert DEFAULT_FASTLIVEPORTRAIT_CONFIG["driving_multiplier"] == 1.0
    assert DEFAULT_FASTLIVEPORTRAIT_CONFIG["cfg_scale"] == 4.0
    assert DEFAULT_FASTLIVEPORTRAIT_CONFIG["animation_region"] == "lip"


def test_normalize_fasterliveportrait_runtime_config_rejects_bad_animation_region() -> None:
    with pytest.raises(ValueError, match="animation_region"):
        normalize_fasterliveportrait_runtime_config({"animation_region": "mouth"})
