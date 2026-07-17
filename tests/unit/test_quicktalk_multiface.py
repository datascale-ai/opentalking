from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
import torch

from apps.cli.quicktalk_multiface import load_multiface_script
from opentalking.models.quicktalk.runtime import (
    FastRestoreContext,
    MultiFaceRealtimeV3Worker,
    MultiFaceSegment,
    assign_face_ids_by_x,
    validate_multiface_script,
)
from opentalking.models.quicktalk.runtime_v2 import FaceDetector


def _fake_face(x0: float, y0: float, x1: float, y1: float) -> SimpleNamespace:
    landmarks = np.zeros((106, 2), dtype=np.float32)
    landmarks[:, 0] = (x0 + x1) / 2.0
    landmarks[:, 1] = (y0 + y1) / 2.0
    return SimpleNamespace(
        bbox=np.asarray([x0, y0, x1, y1], dtype=np.float32),
        landmark_2d_106=landmarks,
    )


def test_face_detector_detect_faces_returns_all_faces_and_keeps_single_face_compat() -> None:
    small = _fake_face(0, 0, 2, 2)
    large = _fake_face(10, 0, 16, 8)
    detector = FaceDetector.__new__(FaceDetector)
    detector.app = SimpleNamespace(get=lambda _image: [small, large])

    detections = detector.detect_faces(np.zeros((20, 20, 3), dtype=np.uint8))

    assert [d.bbox.tolist() for d in detections] == [
        [0.0, 0.0, 2.0, 2.0],
        [10.0, 0.0, 16.0, 8.0],
    ]
    bbox, landmarks = detector(np.zeros((20, 20, 3), dtype=np.uint8))
    assert bbox.tolist() == [10.0, 0.0, 16.0, 8.0]
    assert landmarks.shape == (106, 2)


def test_assign_face_ids_by_x_names_two_anchors_left_and_right() -> None:
    detections = [
        _fake_face(100, 0, 140, 40),
        _fake_face(10, 0, 50, 40),
    ]

    assigned = assign_face_ids_by_x(detections)

    assert [face_id for face_id, _detection in assigned] == ["left", "right"]
    assert assigned[0][1].bbox.tolist() == [10.0, 0.0, 50.0, 40.0]
    assert assigned[1][1].bbox.tolist() == [100.0, 0.0, 140.0, 40.0]


def test_validate_multiface_script_rejects_unknown_speaker_and_overlap() -> None:
    with pytest.raises(ValueError, match="unknown speaker_id: male"):
        validate_multiface_script(
            {
                "speaker_faces": {"female": "left"},
                "segments": [
                    {
                        "speaker_id": "male",
                        "start_ms": 0,
                        "end_ms": 100,
                        "audio": "male.wav",
                    }
                ],
            }
        )

    with pytest.raises(ValueError, match="overlapping segments"):
        validate_multiface_script(
            {
                "speaker_faces": {"female": "left", "male": "right"},
                "segments": [
                    {
                        "speaker_id": "female",
                        "start_ms": 0,
                        "end_ms": 100,
                        "audio": "female.wav",
                    },
                    {
                        "speaker_id": "male",
                        "start_ms": 99,
                        "end_ms": 200,
                        "audio": "male.wav",
                    },
                ],
            }
        )


def _context(frame: np.ndarray, roi: tuple[int, int, int, int]) -> FastRestoreContext:
    x0, y0, x1, y1 = roi
    return FastRestoreContext(
        frame=frame,
        face=np.zeros((2, 2, 3), dtype=np.uint8),
        face_input=np.zeros((7, 2, 2), dtype=np.float32),
        coords=[x0, y0, x1, y1],
        affine=np.eye(2, 3, dtype=np.float32),
        roi=roi,
        inv_affine_roi=torch.zeros((1, 2, 3), dtype=torch.float32),
        frame_roi_t=torch.zeros((3, y1 - y0, x1 - x0), dtype=torch.float32),
        hard_mask_roi_3d=torch.ones((3, y1 - y0, x1 - x0), dtype=torch.float32),
        soft_mask_roi_3d=torch.ones((3, y1 - y0, x1 - x0), dtype=torch.float32),
    )


def test_multiface_worker_only_replaces_target_speaker_roi(monkeypatch: pytest.MonkeyPatch) -> None:
    base = np.zeros((8, 8, 3), dtype=np.uint8)
    worker = MultiFaceRealtimeV3Worker.__new__(MultiFaceRealtimeV3Worker)
    worker.frames = [base]
    worker.fps = 25.0
    worker.restore_contexts_by_face = {
        "left": [_context(base, (0, 0, 4, 4))],
        "right": [_context(base, (4, 0, 8, 4))],
    }
    worker.face_tracks = {}

    class FakeV2:
        device = torch.device("cpu")
        dtype = torch.float32

        def run_model(self, _audio, _face, hn, cn):
            patch = np.zeros((1, 3, 2, 2), dtype=np.float32)
            return patch, hn, cn

        def transform_output_torch(self, patch_t: torch.Tensor) -> torch.Tensor:
            return patch_t

    worker.v2 = FakeV2()

    def fake_restore(_self, context, _patch_t, base_frame=None, paste_weight=None):
        output = (base_frame if base_frame is not None else context.frame).copy()
        x0, y0, x1, y1 = context.roi
        fill = 11 if x0 == 0 else 22
        output[y0:y1, x0:x1] = fill
        return output

    monkeypatch.setattr(worker, "fast_restore_img", fake_restore.__get__(worker))
    state = worker.make_multiface_state()
    reps = [np.zeros((10, 1024), dtype=np.float32)]

    frames = list(
        worker.generate_frames_from_segments(
            [
                MultiFaceSegment(
                    speaker_id="female",
                    start_ms=0,
                    end_ms=40,
                    reps=reps,
                ),
                MultiFaceSegment(
                    speaker_id="male",
                    start_ms=40,
                    end_ms=80,
                    reps=reps,
                ),
            ],
            {"female": "left", "male": "right"},
            state=state,
        )
    )

    assert np.all(frames[0][0:4, 0:4] == 11)
    assert np.all(frames[0][0:4, 4:8] == 0)
    assert np.all(frames[1][0:4, 0:4] == 0)
    assert np.all(frames[1][0:4, 4:8] == 22)


def test_multiface_worker_tail_fade_alpha_reaches_template_on_last_frame() -> None:
    worker = MultiFaceRealtimeV3Worker.__new__(MultiFaceRealtimeV3Worker)
    worker.fps = 25.0
    worker.tail_fade_ms = 120

    alphas = [worker._segment_tail_blend_alpha(idx, 4) for idx in range(4)]

    assert alphas == [1.0, 1.0, 0.5, 0.0]


def test_multiface_worker_keeps_gap_frames_on_current_template_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = np.zeros((8, 8, 3), dtype=np.uint8)
    left_anchor = raw.copy()
    left_anchor[0:4, 0:4] = 5
    right_anchor = raw.copy()
    right_anchor[0:4, 4:8] = 7

    worker = MultiFaceRealtimeV3Worker.__new__(MultiFaceRealtimeV3Worker)
    worker.frames = [raw]
    worker.fps = 25.0
    worker.tail_fade_ms = 0
    worker.idle_anchor_mode = "mouth"
    worker.idle_anchor_start = 0.0
    worker.restore_contexts_by_face = {
        "left": [_context(left_anchor, (0, 0, 4, 4))],
        "right": [_context(right_anchor, (4, 0, 8, 4))],
    }
    worker.face_tracks = {}

    class FakeV2:
        device = torch.device("cpu")
        dtype = torch.float32

        def run_model(self, _audio, _face, hn, cn):
            patch = np.zeros((1, 3, 2, 2), dtype=np.float32)
            return patch, hn, cn

        def transform_output_torch(self, patch_t: torch.Tensor) -> torch.Tensor:
            return patch_t

    worker.v2 = FakeV2()

    def fake_restore(_self, context, _patch_t, base_frame=None, paste_weight=None):
        output = (base_frame if base_frame is not None else context.frame).copy()
        x0, y0, x1, y1 = context.roi
        fill = 11 if x0 == 0 else 22
        output[y0:y1, x0:x1] = fill
        return output

    monkeypatch.setattr(worker, "fast_restore_img", fake_restore.__get__(worker))
    reps = [np.zeros((10, 1024), dtype=np.float32)]
    frames = list(
        worker.generate_frames_from_segments(
            [
                MultiFaceSegment(
                    speaker_id="female",
                    start_ms=0,
                    end_ms=40,
                    reps=reps,
                ),
                MultiFaceSegment(
                    speaker_id="male",
                    start_ms=120,
                    end_ms=160,
                    reps=reps,
                ),
            ],
            {"female": "left", "male": "right"},
        )
    )

    assert np.all(frames[0][0:4, 0:4] == 11)
    assert np.all(frames[0][0:4, 4:8] == 0)
    assert np.all(frames[1][0:4, 0:4] == 0)
    assert np.all(frames[1][0:4, 4:8] == 0)
    assert np.all(frames[3][0:4, 0:4] == 0)
    assert np.all(frames[3][0:4, 4:8] == 22)


def test_multiface_worker_tail_fade_returns_to_current_template_not_idle_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = np.zeros((8, 8, 3), dtype=np.uint8)
    left_anchor = raw.copy()
    left_anchor[0:4, 0:4] = 5

    worker = MultiFaceRealtimeV3Worker.__new__(MultiFaceRealtimeV3Worker)
    worker.frames = [raw]
    worker.fps = 25.0
    worker.tail_fade_ms = 120
    worker.idle_anchor_mode = "mouth"
    worker.idle_anchor_start = 0.0
    worker.restore_contexts_by_face = {
        "left": [_context(left_anchor, (0, 0, 4, 4))],
    }
    worker.face_tracks = {}

    class FakeV2:
        device = torch.device("cpu")
        dtype = torch.float32

        def run_model(self, _audio, _face, hn, cn):
            patch = np.zeros((1, 3, 2, 2), dtype=np.float32)
            return patch, hn, cn

        def transform_output_torch(self, patch_t: torch.Tensor) -> torch.Tensor:
            return patch_t

    worker.v2 = FakeV2()

    def fake_restore(_self, context, _patch_t, base_frame=None, paste_weight=None):
        output = (base_frame if base_frame is not None else context.frame).copy()
        x0, y0, x1, y1 = context.roi
        output[y0:y1, x0:x1] = 11
        return output

    monkeypatch.setattr(worker, "fast_restore_img", fake_restore.__get__(worker))
    reps = [np.zeros((10, 1024), dtype=np.float32) for _ in range(4)]
    frames = list(
        worker.generate_frames_from_segments(
            [
                MultiFaceSegment(
                    speaker_id="female",
                    start_ms=0,
                    end_ms=160,
                    reps=reps,
                ),
            ],
            {"female": "left"},
        )
    )

    assert np.all(frames[-1][0:4, 0:4] == 0)


def test_multiface_worker_tail_fade_reduces_upper_face_paste_before_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = np.zeros((8, 8, 3), dtype=np.uint8)

    worker = MultiFaceRealtimeV3Worker.__new__(MultiFaceRealtimeV3Worker)
    worker.frames = [raw]
    worker.fps = 25.0
    worker.tail_fade_ms = 120
    worker.tail_fade_region = "mouth"
    worker.tail_fade_mouth_start = 0.5
    worker.tail_fade_mouth_ramp = 0.25
    worker.restore_contexts_by_face = {
        "left": [_context(raw, (0, 0, 8, 8))],
    }
    worker.face_tracks = {}

    class FakeV2:
        device = torch.device("cpu")
        dtype = torch.float32

        def run_model(self, _audio, _face, hn, cn):
            patch = np.zeros((1, 3, 2, 2), dtype=np.float32)
            return patch, hn, cn

        def transform_output_torch(self, patch_t: torch.Tensor) -> torch.Tensor:
            return patch_t

    worker.v2 = FakeV2()

    def fake_restore(_self, context, _patch_t, base_frame=None, paste_weight=None):
        output = (base_frame if base_frame is not None else context.frame).copy()
        x0, y0, x1, y1 = context.roi
        if paste_weight is None:
            weight = np.ones((y1 - y0, x1 - x0), dtype=np.float32)
        else:
            weight = paste_weight[0].detach().cpu().numpy().astype(np.float32)
        output[y0:y1, x0:x1] = np.clip(100.0 * weight[..., None], 0, 255).astype(np.uint8)
        return output

    monkeypatch.setattr(worker, "fast_restore_img", fake_restore.__get__(worker))
    reps = [np.zeros((10, 1024), dtype=np.float32) for _ in range(4)]
    frames = list(
        worker.generate_frames_from_segments(
            [
                MultiFaceSegment(
                    speaker_id="female",
                    start_ms=0,
                    end_ms=160,
                    reps=reps,
                ),
            ],
            {"female": "left"},
        )
    )

    fade_frame = frames[2]
    assert int(fade_frame[0, 0, 0]) < int(fade_frame[7, 0, 0])


def test_multiface_worker_paste_strength_reduces_full_speech_patch_opacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = np.zeros((10, 10, 3), dtype=np.uint8)

    worker = MultiFaceRealtimeV3Worker.__new__(MultiFaceRealtimeV3Worker)
    worker.frames = [raw]
    worker.fps = 25.0
    worker.tail_fade_ms = 0
    worker.paste_strength = 0.5
    worker.restore_contexts_by_face = {
        "left": [_context(raw, (0, 0, 10, 10))],
    }
    worker.face_tracks = {}

    class FakeV2:
        device = torch.device("cpu")
        dtype = torch.float32

        def run_model(self, _audio, _face, hn, cn):
            patch = np.zeros((1, 3, 2, 2), dtype=np.float32)
            return patch, hn, cn

        def transform_output_torch(self, patch_t: torch.Tensor) -> torch.Tensor:
            return patch_t

    worker.v2 = FakeV2()

    def fake_restore(_self, context, _patch_t, base_frame=None, paste_weight=None):
        output = (base_frame if base_frame is not None else context.frame).copy()
        x0, y0, x1, y1 = context.roi
        if paste_weight is None:
            weight = np.ones((y1 - y0, x1 - x0), dtype=np.float32)
        else:
            weight = paste_weight[0].detach().cpu().numpy().astype(np.float32)
        output[y0:y1, x0:x1] = np.clip(100.0 * weight[..., None], 0, 255).astype(np.uint8)
        return output

    monkeypatch.setattr(worker, "fast_restore_img", fake_restore.__get__(worker))
    frames = list(
        worker.generate_frames_from_segments(
            [
                MultiFaceSegment(
                    speaker_id="female",
                    start_ms=0,
                    end_ms=40,
                    reps=[np.zeros((10, 1024), dtype=np.float32)],
                ),
            ],
            {"female": "left"},
        )
    )

    frame = frames[0]
    assert int(frame[5, 5, 0]) <= 50
    assert int(frame[9, 5, 0]) <= 50
    assert int(frame[5, 0, 0]) <= 50


def test_multiface_worker_holds_last_mouth_patch_during_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = np.zeros((10, 20, 3), dtype=np.uint8)

    worker = MultiFaceRealtimeV3Worker.__new__(MultiFaceRealtimeV3Worker)
    worker.frames = [raw]
    worker.fps = 25.0
    worker.tail_fade_ms = 0
    worker.mouth_hold_ms = 120
    worker.restore_contexts_by_face = {
        "left": [_context(raw, (0, 0, 10, 10))],
        "right": [_context(raw, (10, 0, 20, 10))],
    }
    worker.face_tracks = {}

    class FakeV2:
        device = torch.device("cpu")
        dtype = torch.float32

        def run_model(self, _audio, _face, hn, cn):
            patch = np.zeros((1, 3, 2, 2), dtype=np.float32)
            return patch, hn, cn

        def transform_output_torch(self, patch_t: torch.Tensor) -> torch.Tensor:
            return patch_t

    worker.v2 = FakeV2()

    def fake_restore(_self, context, _patch_t, base_frame=None, paste_weight=None):
        output = (base_frame if base_frame is not None else context.frame).copy()
        x0, y0, x1, y1 = context.roi
        if paste_weight is None:
            weight = np.ones((y1 - y0, x1 - x0), dtype=np.float32)
        else:
            weight = paste_weight[0].detach().cpu().numpy().astype(np.float32)
        output[y0:y1, x0:x1] = np.clip(100.0 * weight[..., None], 0, 255).astype(np.uint8)
        return output

    monkeypatch.setattr(worker, "fast_restore_img", fake_restore.__get__(worker))
    frames = list(
        worker.generate_frames_from_segments(
            [
                MultiFaceSegment(
                    speaker_id="female",
                    start_ms=0,
                    end_ms=40,
                    reps=[np.zeros((10, 1024), dtype=np.float32)],
                ),
                MultiFaceSegment(
                    speaker_id="male",
                    start_ms=240,
                    end_ms=280,
                    reps=[np.zeros((10, 1024), dtype=np.float32)],
                ),
            ],
            {"female": "left", "male": "right"},
        )
    )

    assert int(frames[1][5, 5, 0]) > 0
    assert int(frames[1][9, 5, 0]) == 0
    assert int(frames[4][5, 5, 0]) == 0


def test_multiface_worker_speech_paste_covers_chin_after_mouth_only_revert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = np.zeros((10, 10, 3), dtype=np.uint8)

    worker = MultiFaceRealtimeV3Worker.__new__(MultiFaceRealtimeV3Worker)
    worker.frames = [raw]
    worker.fps = 25.0
    worker.tail_fade_ms = 0
    worker.paste_strength = 1.0
    worker.restore_contexts_by_face = {
        "left": [_context(raw, (0, 0, 10, 10))],
    }
    worker.face_tracks = {}

    class FakeV2:
        device = torch.device("cpu")
        dtype = torch.float32

        def run_model(self, _audio, _face, hn, cn):
            patch = np.zeros((1, 3, 2, 2), dtype=np.float32)
            return patch, hn, cn

        def transform_output_torch(self, patch_t: torch.Tensor) -> torch.Tensor:
            return patch_t

    worker.v2 = FakeV2()

    def fake_restore(_self, context, _patch_t, base_frame=None, paste_weight=None):
        output = (base_frame if base_frame is not None else context.frame).copy()
        x0, y0, x1, y1 = context.roi
        if paste_weight is None:
            weight = np.ones((y1 - y0, x1 - x0), dtype=np.float32)
        else:
            weight = paste_weight[0].detach().cpu().numpy().astype(np.float32)
        output[y0:y1, x0:x1] = np.clip(100.0 * weight[..., None], 0, 255).astype(np.uint8)
        return output

    monkeypatch.setattr(worker, "fast_restore_img", fake_restore.__get__(worker))
    frames = list(
        worker.generate_frames_from_segments(
            [
                MultiFaceSegment(
                    speaker_id="female",
                    start_ms=0,
                    end_ms=40,
                    reps=[np.zeros((10, 1024), dtype=np.float32)],
                ),
            ],
            {"female": "left"},
        )
    )

    assert int(frames[0][5, 5, 0]) == 100
    assert int(frames[0][9, 5, 0]) == 100


def test_multiface_cli_loads_script_and_resolves_relative_audio(tmp_path) -> None:
    script_path = tmp_path / "script.json"
    (tmp_path / "female.wav").write_bytes(b"wav")
    script_path.write_text(
        """
        {
          "speaker_faces": {"female": "left"},
          "segments": [
            {"speaker_id": "female", "start_ms": 0, "end_ms": 40, "audio": "female.wav"}
          ]
        }
        """,
        encoding="utf-8",
    )

    script = load_multiface_script(script_path)

    assert script["segments"][0]["audio"] == str((tmp_path / "female.wav").resolve())
