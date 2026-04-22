from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

import opentalking.models
from opentalking.avatars.manifest import parse_manifest
from opentalking.avatars.validator import validate_avatar_dir
from opentalking.models.common.frame_avatar import FrameAvatarState, load_frame_avatar_state
from opentalking.models.musetalk.composer import compose_simple, resolve_avatar_frame_index
from opentalking.models.musetalk.adapter import MuseTalkAdapter
from opentalking.models.musetalk.prepared_assets import resolve_prepared_musetalk_assets
from opentalking.models.wav2lip.adapter import (
    Wav2LipAdapter,
    _AvatarLandmarks,
    _NeuralFaceState,
    _apply_synthetic_mouth,
    _rescale_box,
)


def test_list_models() -> None:
    assert "wav2lip" in opentalking.models.list_models()
    assert "musetalk" in opentalking.models.list_models()
    assert "flashtalk" in opentalking.models.list_models()


def test_list_available_models_hides_flashtalk_when_off() -> None:
    assert "flashtalk" not in opentalking.models.list_available_models(flashtalk_mode="off")
    assert "wav2lip" in opentalking.models.list_available_models(flashtalk_mode="off")
    assert "flashtalk" in opentalking.models.list_available_models(flashtalk_mode="local")


def test_wav2lip_new_avatar_valid() -> None:
    root = Path(__file__).resolve().parents[2]
    avatar_dir = root / "examples" / "avatars" / "wav2lip_new"
    errs = validate_avatar_dir(avatar_dir)
    assert errs == []


def test_musetalk_new_avatar_visible_and_fallback_animates() -> None:
    root = Path(__file__).resolve().parents[2]
    avatar_dir = root / "examples" / "avatars" / "musetalk_new"
    errs = validate_avatar_dir(avatar_dir)
    assert errs == []

    manifest = parse_manifest(avatar_dir / "manifest.json")
    state = load_frame_avatar_state(avatar_dir, manifest)
    assert state.frames[0].shape[:2] == (manifest.height, manifest.width)
    assert len(state.frames) >= 1

    first = compose_simple(state, 0, None, timestamp_ms=0).data
    assert first.shape[:2] == (manifest.height, manifest.width)


def test_parse_wav2lip_new_manifest() -> None:
    root = Path(__file__).resolve().parents[2]
    m = parse_manifest(root / "examples" / "avatars" / "wav2lip_new" / "manifest.json")
    assert m.id == "wav2lip_new"
    assert m.model_type == "wav2lip"


def test_musetalk_new_idle_frame_uses_full_frame_sequence() -> None:
    root = Path(__file__).resolve().parents[2]
    avatar_dir = root / "examples" / "avatars" / "musetalk_new"

    adapter = MuseTalkAdapter()
    state = adapter.load_avatar(str(avatar_dir))

    assert np.array_equal(adapter.idle_frame(state, 0).data, state.frames[0])
    assert np.array_equal(adapter.idle_frame(state, 1).data, state.frames[1])


def test_wav2lip_new_idle_frame_uses_full_frame_sequence() -> None:
    root = Path(__file__).resolve().parents[2]
    avatar_dir = root / "examples" / "avatars" / "wav2lip_new"

    adapter = Wav2LipAdapter()
    state = adapter.load_avatar(str(avatar_dir))

    assert state.extra["wav2lip_static_avatar"] is False
    assert np.array_equal(adapter.idle_frame(state, 0).data, state.frames[0])
    assert np.array_equal(adapter.idle_frame(state, 1).data, state.frames[1])


def test_wav2lip_new_can_enable_neural_while_preserving_idle_loop() -> None:
    root = Path(__file__).resolve().parents[2]
    avatar_dir = root / "examples" / "avatars" / "wav2lip_new"

    adapter = Wav2LipAdapter()
    adapter._torch_bundle = {"enabled": True}
    adapter._prepare_neural_face_state = lambda frame: _NeuralFaceState(  # type: ignore[method-assign]
        base_frame=frame.copy(),
        coords=(0, frame.shape[0], 0, frame.shape[1]),
        face_input=np.zeros((96, 96, 6), dtype=np.float32),
    )

    state = adapter.load_avatar(str(avatar_dir))

    assert state.extra["wav2lip_static_avatar"] is False
    assert state.extra["freeze_speaking_to_preview"] is True
    assert state.extra["wav2lip_neural_enabled"] is True
    assert np.array_equal(adapter.idle_frame(state, 0).data, state.frames[0])
    assert np.array_equal(adapter.idle_frame(state, 1).data, state.frames[1])


def test_wav2lip_rescale_box_shrinks_and_biases_down() -> None:
    scaled = _rescale_box((10, 20, 110, 220), frame_shape=(400, 200), scale=0.8, center_y_bias=0.05)
    assert scaled == (20, 50, 100, 210)


def test_wav2lip_synthetic_mouth_can_render_teeth_for_large_open_amount() -> None:
    frame = np.full((96, 96, 3), 90, dtype=np.uint8)
    landmarks = _AvatarLandmarks(mouth_center=(48, 58), mouth_rx=16, mouth_ry=8)

    out = _apply_synthetic_mouth(frame, landmarks, 0.72)

    bright = out[:, :, 0] >= 190
    assert int(bright.sum()) > 0


def test_musetalk_speaking_can_freeze_to_preview_frame() -> None:
    preview = np.full((8, 8, 3), 180, dtype=np.uint8)
    state = FrameAvatarState(
        manifest=SimpleNamespace(fps=25, width=8, height=8),
        frames=[
            np.zeros((8, 8, 3), dtype=np.uint8),
            np.full((8, 8, 3), 255, dtype=np.uint8),
        ],
        avatar_path=Path("/tmp/avatar"),
        extra={
            "preview_frame": preview,
            "preview_frame_index": 0,
            "freeze_speaking_to_preview": True,
            "rendering_speech": True,
        },
    )

    assert resolve_avatar_frame_index(state, 7) == 0
    frame = compose_simple(state, 7, "keep-preview", timestamp_ms=0.0)
    assert np.array_equal(frame.data, preview)


def test_wav2lip_speaking_can_freeze_to_preview_frame() -> None:
    adapter = Wav2LipAdapter()
    preview = np.full((8, 8, 3), 120, dtype=np.uint8)
    state = FrameAvatarState(
        manifest=SimpleNamespace(fps=25, width=8, height=8),
        frames=[
            np.zeros((8, 8, 3), dtype=np.uint8),
            np.full((8, 8, 3), 255, dtype=np.uint8),
        ],
        avatar_path=Path("/tmp/avatar"),
        extra={
            "preview_frame": preview,
            "freeze_speaking_to_preview": True,
            "rendering_speech": True,
            "wav2lip_static_avatar": False,
            "wav2lip_landmarks": None,
            "wav2lip_test_frame_order": [0, 1],
        },
    )

    frame = adapter.compose_frame(state, 0, 0.0)
    assert np.array_equal(frame.data, preview)


def test_musetalk_new_has_prepared_assets_and_compose_override() -> None:
    root = Path(__file__).resolve().parents[2]
    avatar_dir = root / "examples" / "avatars" / "musetalk_new"

    assets = resolve_prepared_musetalk_assets(avatar_dir)
    assert assets is not None
    assert len(assets.coords) > 0
    assert len(assets.latents) > 0

    adapter = MuseTalkAdapter()
    state = adapter.load_avatar(str(avatar_dir))
    assert state.extra["musetalk_prepared_compose_mode"] == "strict_mask"
