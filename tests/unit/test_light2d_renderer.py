from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from opentalking.avatar.light2d import (
    Light2DFrameState,
    Light2DRenderer,
    load_light2d_renderer,
    mouth_state_for_energy,
    normalize_pcm16,
)


FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "light2d_audio_cases.json"


def _write_bundle(
    root: Path,
    *,
    width: int = 2,
    height: int = 2,
    colors: dict[str, tuple[int, int, int, int]] | None = None,
    animation: dict[str, float] | None = None,
) -> Path:
    avatar_dir = root / "synthetic-light2d"
    layer_dir = avatar_dir / "light2d" / "layers"
    layer_dir.mkdir(parents=True)
    palette = {
        "base": (255, 0, 0, 255),
        "blink": (0, 0, 255, 255),
        "closed": (0, 255, 0, 255),
        "small": (255, 255, 0, 255),
        "medium": (255, 0, 255, 255),
        "large": (0, 255, 255, 255),
        **(colors or {}),
    }
    rects = {
        "base": [0, 0, width, height],
        "blink": [0, 0, 1, 1],
        "closed": [0, height - 1, 1, 1],
        "small": [0, height - 1, 1, 1],
        "medium": [0, height - 1, 1, 1],
        "large": [0, height - 1, 1, 1],
    }
    for name, color in palette.items():
        image_width, image_height = rects[name][2:]
        Image.new("RGBA", (image_width, image_height), color).save(layer_dir / f"{name}.png")

    manifest = {
        "id": "synthetic-light2d",
        "name": "Synthetic",
        "model_type": "mock",
        "metadata": {
            "client_renderer": {
                "type": "light2d",
                "config": "light2d/avatar.json",
                "recommended_for": ["mock"],
            }
        },
    }
    config = {
        "version": 1,
        "canvas": {"width": width, "height": height},
        "layers": {
            "base": {"source": "layers/base.png", "rect": rects["base"]},
            "blink": {"source": "layers/blink.png", "rect": rects["blink"]},
            "mouth": {
                name: {"source": f"layers/{name}.png", "rect": rects[name]}
                for name in ("closed", "small", "medium", "large")
            },
        },
        "audio": {
            "silence_gate": 0.025,
            "small_threshold": 0.055,
            "medium_threshold": 0.105,
            "attack_ms": 45,
            "release_ms": 120,
            "crossfade_ms": 80,
        },
        "animation": {
            "breath_period_ms": 1600,
            "breath_scale": 0.006,
            "sway_degrees": 0.7,
            "blink_period_ms": 4800,
            "blink_duration_ms": 130,
            **(animation or {}),
        },
    }
    (avatar_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (avatar_dir / "light2d" / "avatar.json").write_text(json.dumps(config), encoding="utf-8")
    return avatar_dir


def _renderer(tmp_path: Path, **kwargs: object) -> Light2DRenderer:
    return Light2DRenderer(load_light2d_renderer(_write_bundle(tmp_path, **kwargs)))


def test_shared_audio_fixture_matches_int16_normalization_and_mouth_states() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    thresholds = fixture["thresholds"]

    for case in fixture["cases"]:
        normalized = normalize_pcm16(np.asarray(case["int16_samples"], dtype=np.int16))
        assert normalized.tolist() == case["normalized_samples"]
        rms = math.sqrt(float(np.mean(np.square(normalized, dtype=np.float64))))
        assert rms == pytest.approx(case["expected_rms"], abs=1e-12)
        assert mouth_state_for_energy(rms, thresholds) == case["expected_mouth_state"]


def test_renderer_uses_floor_windows_zero_pads_tail_and_ceil_frame_count(tmp_path: Path) -> None:
    renderer = _renderer(tmp_path)
    pcm = np.asarray([32767, 0, 0, 16384], dtype=np.int16)

    frames = list(renderer.iter_frames(pcm, sample_rate=10, fps=3))

    assert len(frames) == 2
    assert frames[0].state.raw_energy == pytest.approx((32767 / 32768) / math.sqrt(3))
    assert frames[1].state.raw_energy == pytest.approx(0.5 / math.sqrt(3))
    assert [frame.state.timestamp_ms for frame in frames] == [0.0, pytest.approx(1000 / 3)]


def test_renderer_uses_fixed_frame_duration_for_energy_smoothing(tmp_path: Path) -> None:
    renderer = _renderer(tmp_path)

    first = next(renderer.iter_frames(np.full(640, 16384, dtype=np.int16)))

    expected = 0.5 * (1 - math.exp(-40 / 45))
    assert first.state.energy == pytest.approx(expected)


def test_empty_pcm_starts_at_zero_ms_closed_with_zero_energy_and_blink_phase_zero(
    tmp_path: Path,
) -> None:
    renderer = _renderer(tmp_path)

    frames = list(renderer.iter_frames(np.asarray([], dtype=np.int16)))

    assert len(frames) == 1
    state = frames[0].state
    assert state.timestamp_ms == 0
    assert state.energy == 0
    assert state.mouth_state == "closed"
    assert state.blinking is True
    assert state.transforms.breath_scale == 0
    assert state.transforms.sway_degrees == 0


def test_initial_frame_draws_closed_mouth_at_full_alpha(tmp_path: Path) -> None:
    renderer = _renderer(
        tmp_path,
        width=1,
        height=1,
        colors={
            "base": (255, 0, 0, 255),
            "blink": (0, 0, 0, 0),
            "closed": (0, 255, 0, 255),
        },
    )

    frame = next(renderer.iter_frames(np.asarray([], dtype=np.int16)))

    assert frame.state.previous_mouth_state == frame.state.mouth_state == "closed"
    assert frame.state.mouth_progress == 0
    assert tuple(frame.rgba[0, 0]) == (0, 255, 0, 255)


def test_breath_and_sway_follow_browser_phase_formula(tmp_path: Path) -> None:
    renderer = _renderer(tmp_path)
    pcm = np.zeros(11 * 640, dtype=np.int16)

    state = list(renderer.iter_frames(pcm))[10].state

    assert state.timestamp_ms == 400
    assert state.transforms.breath_scale == pytest.approx(0.006)
    assert state.transforms.scale_y == pytest.approx(1.006)
    expected_sway = math.sin(3 * math.pi / 8) * 0.7
    assert state.transforms.sway_degrees == pytest.approx(expected_sway)
    assert state.transforms.rotation_degrees == pytest.approx(expected_sway)
    assert state.blinking is False


def test_speaking_weight_adds_browser_scale_and_rotation(tmp_path: Path) -> None:
    renderer = _renderer(tmp_path)

    state = next(renderer.iter_frames(np.full(640, 16384, dtype=np.int16))).state

    assert state.transforms.speaking_weight == 1
    assert state.transforms.breath_scale == 0
    assert state.transforms.sway_degrees == 0
    assert state.transforms.scale_y == pytest.approx(1.003)
    assert state.transforms.rotation_degrees == pytest.approx(0.12)


def test_rgba_source_over_and_mouth_crossfade_match_canvas_order(tmp_path: Path) -> None:
    renderer = _renderer(
        tmp_path,
        width=1,
        height=1,
        colors={
            "base": (255, 0, 0, 128),
            "blink": (0, 0, 0, 0),
            "closed": (0, 255, 0, 128),
            "large": (0, 0, 255, 128),
        },
    )
    state = Light2DFrameState.for_test(
        mouth_state="large",
        previous_mouth_state="closed",
        mouth_progress=0.5,
    )

    pixel = tuple(renderer.render_rgba(state)[0, 0])

    assert pixel == (100, 66, 89, 184)


def test_full_canvas_base_is_copied_without_generic_float_compositor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = _renderer(tmp_path, width=4, height=4)
    calls: list[tuple[tuple[int, ...], np.dtype]] = []

    def record_composite(
        destination: np.ndarray,
        source: np.ndarray,
        alpha: float,
    ) -> np.ndarray:
        calls.append((destination.shape, destination.dtype))
        return destination

    monkeypatch.setattr("opentalking.avatar.light2d._rgba_source_over", record_composite)

    renderer.render_rgba(Light2DFrameState.for_test())

    assert calls
    assert all(shape[:2] != (4, 4) for shape, _dtype in calls)
    assert all(dtype == np.uint8 for _shape, dtype in calls)


def test_transform_preserves_straight_rgb_on_partial_alpha_edges() -> None:
    canvas = np.zeros((4, 4, 4), dtype=np.uint8)
    canvas[1:3, 1:3] = (255, 255, 255, 255)
    transforms = Light2DFrameState.for_test().transforms
    transformed = Light2DRenderer._apply_transform(
        canvas,
        type(transforms)(
            breath_scale=0.0,
            sway_degrees=0.0,
            speaking_weight=0.0,
            scale_y=1.1,
            rotation_degrees=8.0,
        ),
    )

    partial = transformed[(transformed[..., 3] > 0) & (transformed[..., 3] < 255)]

    assert len(partial) > 0
    assert np.all(partial[:, :3] == 255)
    assert np.all(transformed[transformed[..., 3] == 0, :3] == 0)


def test_renderer_preloads_layers_and_repeats_state_sequence_and_frame_hash(
    tmp_path: Path,
) -> None:
    renderer = _renderer(tmp_path)
    pcm = np.concatenate(
        [
            np.full(640, amplitude, dtype=np.int16)
            for amplitude in (0, 1638, 3277, 6554, 0, 0, 0, 0, 0, 0)
        ]
    )
    for path in renderer.context.referenced_assets:
        (renderer.context.renderer_root / path).unlink()

    first = list(renderer.iter_frames(pcm))
    second = list(renderer.iter_frames(pcm))
    states = [frame.state.mouth_state for frame in first]

    assert states == [
        "closed",
        "small",
        "medium",
        "large",
        "large",
        "medium",
        "small",
        "small",
        "small",
        "closed",
    ]
    assert [frame.state.mouth_state for frame in second] == states
    assert hashlib.sha256(first[0].rgba.tobytes()).hexdigest() == (
        "e98b068e1240f1386858add4340fd14d9680c6517249b0797499ec433047ce2a"
    )
    assert hashlib.sha256(second[0].rgba.tobytes()).digest() == hashlib.sha256(
        first[0].rgba.tobytes()
    ).digest()
