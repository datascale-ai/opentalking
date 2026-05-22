from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from apps.cli.prepare_cache import (
    _normalized_model_crop_from_coords,
    _write_wav2lip_model_crops,
)
from opentalking.models.wav2lip.runtime import Wav2LipRealtimeRuntime, _PreparedFrame
from opentalking.models.wav2lip.realtime import (
    AvatarAudioSpec,
    AvatarVideoSpec,
    RealtimeAvatarService,
    RealtimeAvatarSession,
)


def _write_png(path: Path) -> None:
    Image.new("RGB", (12, 10), (10, 20, 30)).save(path, format="PNG")


def test_local_wav2lip_uses_omnirt_max_long_edge_default(monkeypatch):
    monkeypatch.delenv("OPENTALKING_WAV2LIP_MAX_LONG_EDGE", raising=False)
    monkeypatch.delenv("OMNIRT_WAV2LIP_MAX_LONG_EDGE", raising=False)

    session = RealtimeAvatarService().create_session(
        model="wav2lip",
        backend="local",
        image_bytes=b"fake-image",
        config={"width": 830, "height": 1108},
    )

    assert session.video.width == 830
    assert session.video.height == 1108


def test_local_wav2lip_accepts_omnirt_max_long_edge_env(monkeypatch):
    monkeypatch.delenv("OPENTALKING_WAV2LIP_MAX_LONG_EDGE", raising=False)
    monkeypatch.setenv("OMNIRT_WAV2LIP_MAX_LONG_EDGE", "768")

    session = RealtimeAvatarService().create_session(
        model="wav2lip",
        backend="local",
        image_bytes=b"fake-image",
        config={"width": 830, "height": 1108},
    )

    assert session.video.width == 574
    assert session.video.height == 768


def test_local_wav2lip_accepts_asset_tuned_model_crop():
    crop = Wav2LipRealtimeRuntime._metadata_model_crop(
        {
            "model_crop": [0.25, 0.1, 0.75, 0.6],
            "model_crop_source": "asset_tuned",
        },
        (100, 200),
    )

    assert crop == (10, 60, 50, 150)


def test_local_wav2lip_does_not_use_face_box_as_model_crop():
    crop = Wav2LipRealtimeRuntime._preprocessed_metadata_crop(
        {
            "face_box": [0.25, 0.1, 0.75, 0.6],
        },
        (100, 200),
    )

    assert crop is None


def test_local_wav2lip_face_detection_defaults_to_cpu(monkeypatch):
    monkeypatch.delenv("OPENTALKING_WAV2LIP_FACE_DET_DEVICE", raising=False)
    monkeypatch.delenv("OMNIRT_WAV2LIP_FACE_DET_DEVICE", raising=False)

    assert Wav2LipRealtimeRuntime._resolve_face_detection_device("cuda:6") == "cpu"


def test_local_wav2lip_face_detection_accepts_omnirt_env(monkeypatch):
    monkeypatch.delenv("OPENTALKING_WAV2LIP_FACE_DET_DEVICE", raising=False)
    monkeypatch.setenv("OMNIRT_WAV2LIP_FACE_DET_DEVICE", "cuda:0")

    assert Wav2LipRealtimeRuntime._resolve_face_detection_device("cuda:6") == "cuda:0"


def test_local_wav2lip_cache_key_matches_omnirt_contract(tmp_path):
    frame_dir = tmp_path / "frames"
    frame_dir.mkdir()
    frame_path = frame_dir / "frame_00000.png"
    _write_png(frame_path)
    metadata_path = frame_dir / "mouth_metadata.json"
    metadata_path.write_text(json.dumps({"frames": {"frame_00000.png": {}}}), encoding="utf-8")

    runtime = Wav2LipRealtimeRuntime(device="cpu")
    runtime.checkpoint = (tmp_path / "wav2lip384.pth").resolve()
    runtime.gfpgan_checkpoint = (tmp_path / "GFPGANv1.4.pth").resolve()
    session = RealtimeAvatarSession(
        session_id="local-cache-key-test",
        trace_id="trace",
        model="wav2lip",
        backend="local",
        prompt="",
        reference_mode="frames",
        ref_frame_dir=str(frame_dir),
        ref_frame_metadata_path=str(metadata_path),
        audio=AvatarAudioSpec(sample_rate=16000, chunk_samples=17920),
        video=AvatarVideoSpec(fps=25, width=12, height=10),
        preprocessed=True,
        wav2lip_postprocess_mode="easy_improved",
    )

    key = runtime._frame_sequence_cache_key(session, [frame_path])

    assert "model_crop_only" not in key.split("::")


def test_local_wav2lip_cache_key_ignores_gfpgan_for_easy_improved(tmp_path):
    frame_dir = tmp_path / "frames"
    frame_dir.mkdir()
    frame_path = frame_dir / "frame_00000.png"
    _write_png(frame_path)

    session = RealtimeAvatarSession(
        session_id="local-cache-gfpgan-test",
        trace_id="trace",
        model="wav2lip",
        backend="local",
        prompt="",
        reference_mode="frames",
        ref_frame_dir=str(frame_dir),
        audio=AvatarAudioSpec(sample_rate=16000, chunk_samples=17920),
        video=AvatarVideoSpec(fps=25, width=12, height=10),
        wav2lip_postprocess_mode="easy_improved",
    )
    first = Wav2LipRealtimeRuntime(device="cpu")
    first.checkpoint = (tmp_path / "wav2lip384.pth").resolve()
    first.gfpgan_checkpoint = (tmp_path / "one" / "GFPGANv1.4.pth").resolve()
    second = Wav2LipRealtimeRuntime(device="cpu")
    second.checkpoint = first.checkpoint
    second.gfpgan_checkpoint = (tmp_path / "two" / "GFPGANv1.4.pth").resolve()

    assert first._frame_sequence_cache_key(session, [frame_path]) == second._frame_sequence_cache_key(
        session,
        [frame_path],
    )


def test_local_wav2lip_preload_writes_and_reuses_prepared_cache(tmp_path, monkeypatch):
    frame_dir = tmp_path / "frames"
    frame_dir.mkdir()
    frame_path = frame_dir / "frame_00000.png"
    _write_png(frame_path)
    metadata_path = frame_dir / "mouth_metadata.json"
    metadata_path.write_text(json.dumps({"frames": {"frame_00000.png": {}}}), encoding="utf-8")
    cache_dir = tmp_path / "wav2lip"

    runtime = Wav2LipRealtimeRuntime(device="cpu")
    runtime.checkpoint = tmp_path / "wav2lip384.pth"
    runtime.checkpoint.write_bytes(b"fake")

    calls = {"prepare": 0}

    def fake_prepare_reference_frame(session, frame, *, frame_index, mouth_metadata=None):
        del session, frame, frame_index, mouth_metadata
        calls["prepare"] += 1
        return _PreparedFrame(
            base_frame=np.zeros((10, 12, 3), dtype=np.uint8),
            face_crop=np.zeros((4, 4, 3), dtype=np.uint8),
            coords=(1, 5, 2, 6),
            geometry=None,
        )

    monkeypatch.setattr(runtime, "_prepare_reference_frame", fake_prepare_reference_frame)

    session = RealtimeAvatarSession(
        session_id="local-cache-test",
        trace_id="trace",
        model="wav2lip",
        backend="local",
        prompt="",
        reference_mode="frames",
        ref_frame_dir=str(frame_dir),
        ref_frame_metadata_path=str(metadata_path),
        audio=AvatarAudioSpec(sample_rate=16000, chunk_samples=17920),
        video=AvatarVideoSpec(fps=25, width=12, height=10),
        preprocessed=False,
    )
    session.prepared_cache_dir = str(cache_dir)

    first = runtime.preload_reference(session)
    assert first["cache_source"] == "built"
    assert first["cache_hit"] is False
    cache_files = list(cache_dir.glob("v3-*.npz"))
    assert len(cache_files) == 1
    assert calls["prepare"] == 1

    second_runtime = Wav2LipRealtimeRuntime(device="cpu")
    second_runtime.checkpoint = runtime.checkpoint
    monkeypatch.setattr(second_runtime, "_prepare_reference_frame", fake_prepare_reference_frame)
    second = second_runtime.preload_reference(session)

    assert second["cache_source"] == "disk"
    assert second["cache_hit"] is True
    assert calls["prepare"] == 1


def test_write_wav2lip_model_crops_updates_missing_entries(tmp_path):
    frame_dir = tmp_path / "frames"
    frame_dir.mkdir()
    frame_path = frame_dir / "frame_00000.png"
    _write_png(frame_path)
    metadata_path = frame_dir / "mouth_metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "version": 1,
                "frames": {
                    "frame_00000.png": {
                        "source_frame_hash": "unused",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    result = _write_wav2lip_model_crops(
        metadata_path,
        {"frame_00000.png": [0.25, 0.1, 0.75, 0.6]},
        source="wav2lip_detector",
        overwrite=False,
    )

    assert result["updated"] == 1
    raw = json.loads(metadata_path.read_text(encoding="utf-8"))
    frame = raw["frames"]["frame_00000.png"]
    assert frame["model_crop"] == [0.25, 0.1, 0.75, 0.6]
    assert frame["model_crop_source"] == "wav2lip_detector"


def test_write_wav2lip_model_crops_keeps_existing_entries_without_overwrite(tmp_path):
    frame_dir = tmp_path / "frames"
    frame_dir.mkdir()
    metadata_path = frame_dir / "mouth_metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "version": 1,
                "frames": {
                    "frame_00000.png": {
                        "model_crop": [0.1, 0.1, 0.2, 0.2],
                        "model_crop_source": "asset_tuned",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    result = _write_wav2lip_model_crops(
        metadata_path,
        {"frame_00000.png": [0.25, 0.1, 0.75, 0.6]},
        source="wav2lip_detector",
        overwrite=False,
    )

    assert result["updated"] == 0
    raw = json.loads(metadata_path.read_text(encoding="utf-8"))
    frame = raw["frames"]["frame_00000.png"]
    assert frame["model_crop"] == [0.1, 0.1, 0.2, 0.2]
    assert frame["model_crop_source"] == "asset_tuned"


def test_normalized_model_crop_from_coords_uses_frame_size():
    assert _normalized_model_crop_from_coords((10, 60, 50, 150), width=200, height=100) == [
        0.25,
        0.1,
        0.75,
        0.6,
    ]
