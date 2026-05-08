from __future__ import annotations

from pathlib import Path

import numpy as np
import opentalking.models
from opentalking.avatars.manifest import parse_manifest
from opentalking.avatars.validator import validate_avatar_dir
from opentalking.models.common.frame_avatar import load_frame_avatar_state
from opentalking.models.musetalk.composer import compose_simple


def test_list_models() -> None:
    assert "wav2lip" in opentalking.models.list_models()
    assert "musetalk" in opentalking.models.list_models()
    assert "flashtalk" in opentalking.models.list_models()
    assert "flashhead" in opentalking.models.list_models()
    assert "quicktalk" in opentalking.models.list_models()


def test_list_available_models_hides_flashtalk_when_off() -> None:
    assert "flashtalk" not in opentalking.models.list_available_models(flashtalk_mode="off")
    assert "flashhead" in opentalking.models.list_available_models(flashtalk_mode="off")
    assert "wav2lip" in opentalking.models.list_available_models(flashtalk_mode="off")
    assert "flashtalk" in opentalking.models.list_available_models(flashtalk_mode="local")


def test_demo_avatar_valid() -> None:
    root = Path(__file__).resolve().parents[2]
    demo = root / "examples" / "avatars" / "demo-avatar"
    errs = validate_avatar_dir(demo)
    assert errs == []


def test_flashhead_demo_avatar_valid() -> None:
    root = Path(__file__).resolve().parents[2]
    demo = root / "examples" / "avatars" / "flashhead-demo"
    errs = validate_avatar_dir(demo)
    assert errs == []


def test_demo_musetalk_avatar_visible_and_fallback_animates() -> None:
    root = Path(__file__).resolve().parents[2]
    demo = root / "examples" / "avatars" / "demo-musetalk"
    errs = validate_avatar_dir(demo)
    assert errs == []

    manifest = parse_manifest(demo / "manifest.json")
    state = load_frame_avatar_state(demo, manifest)
    assert state.frames[0].shape[:2] == (manifest.height, manifest.width)

    first = compose_simple(state, 0, None, timestamp_ms=0).data
    second = compose_simple(state, 1, None, timestamp_ms=40).data
    assert np.count_nonzero(first != second) > 0


def test_parse_demo_manifest() -> None:
    root = Path(__file__).resolve().parents[2]
    m = parse_manifest(root / "examples" / "avatars" / "demo-avatar" / "manifest.json")
    assert m.id == "demo-avatar"
    assert m.model_type == "wav2lip"
