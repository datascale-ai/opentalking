from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from opentalking.avatar.mouth_metadata import image_file_sha256
from opentalking.pipeline.speak.synthesis_runner import FlashTalkRunner


def _write_png(path: Path, color: tuple[int, int, int]) -> None:
    Image.new("RGB", (8, 8), color).save(path, format="PNG")


def test_wav2lip_mouth_metadata_is_ignored_when_hash_mismatches_reference(tmp_path: Path) -> None:
    avatar_dir = tmp_path / "avatar"
    avatar_dir.mkdir()
    reference = avatar_dir / "reference.png"
    stale = avatar_dir / "old-reference.png"
    _write_png(reference, (255, 255, 255))
    _write_png(stale, (0, 0, 0))
    stale_hash = image_file_sha256(stale)
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "avatar",
                "model_type": "wav2lip",
                "metadata": {
                    "source_image_hash": stale_hash,
                    "animation": {
                        "mouth_center": [0.5, 0.56],
                        "mouth_rx": 0.06,
                        "mouth_ry": 0.02,
                        "outer_lip": [[0.45, 0.55], [0.5, 0.53], [0.55, 0.55]],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "wav2lip"
    runner.avatar_id = "avatar"
    runner.avatars_root = tmp_path
    runner._custom_ref_image_path = ""
    runner._ref_image_path = reference

    assert runner._wav2lip_mouth_metadata() is None


def test_wav2lip_frame_reference_dir_comes_from_manifest_metadata(tmp_path: Path) -> None:
    avatar_dir = tmp_path / "avatar"
    frames_dir = avatar_dir / "frames"
    frames_dir.mkdir(parents=True)
    (frames_dir / "frame_00000.png").write_bytes(b"frame")
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "avatar",
                "model_type": "wav2lip",
                "metadata": {
                    "reference_mode": "frames",
                    "frame_dir": "frames",
                },
            }
        ),
        encoding="utf-8",
    )

    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "wav2lip"
    runner.avatar_id = "avatar"
    runner.avatars_root = tmp_path

    assert runner._wav2lip_reference_mode() == "frames"
    assert runner._wav2lip_reference_frame_dir() == frames_dir.resolve()


def test_wav2lip_frame_metadata_path_comes_from_manifest_metadata(tmp_path: Path) -> None:
    avatar_dir = tmp_path / "avatar"
    frames_dir = avatar_dir / "frames"
    frames_dir.mkdir(parents=True)
    metadata_path = frames_dir / "mouth_metadata.json"
    metadata_path.write_text("{}", encoding="utf-8")
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "avatar",
                "model_type": "wav2lip",
                "metadata": {
                    "reference_mode": "frames",
                    "frame_metadata": "frames/mouth_metadata.json",
                },
            }
        ),
        encoding="utf-8",
    )

    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "wav2lip"
    runner.avatar_id = "avatar"
    runner.avatars_root = tmp_path

    assert runner._wav2lip_reference_frame_metadata_path() == metadata_path.resolve()


def test_wav2lip_frame_reference_frames_are_loaded_for_idle_playback(tmp_path: Path) -> None:
    avatar_dir = tmp_path / "avatar"
    frames_dir = avatar_dir / "frames"
    frames_dir.mkdir(parents=True)
    _write_png(frames_dir / "frame_00000.png", (255, 0, 0))
    _write_png(frames_dir / "frame_00001.png", (0, 255, 0))
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "avatar",
                "model_type": "wav2lip",
                "width": 4,
                "height": 4,
                "metadata": {
                    "reference_mode": "frames",
                    "frame_dir": "frames",
                },
            }
        ),
        encoding="utf-8",
    )

    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "wav2lip"
    runner.avatar_id = "avatar"
    runner.avatars_root = tmp_path
    runner.flashtalk = type("FakeFlashTalk", (), {"width": 4, "height": 4})()

    frames = runner._load_wav2lip_reference_idle_frames()

    assert frames is not None
    assert len(frames) == 2
    assert frames[0].shape == (4, 4, 3)
    assert frames[0][0, 0].tolist() == [0, 0, 255]
    assert frames[1][0, 0].tolist() == [0, 255, 0]


def test_wav2lip_preprocessed_flag_comes_from_manifest_metadata(tmp_path: Path) -> None:
    avatar_dir = tmp_path / "avatar"
    avatar_dir.mkdir()
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "avatar",
                "model_type": "wav2lip",
                "metadata": {
                    "reference_mode": "frames",
                    "preprocessed": True,
                },
            }
        ),
        encoding="utf-8",
    )

    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "wav2lip"
    runner.avatar_id = "avatar"
    runner.avatars_root = tmp_path

    assert runner._wav2lip_preprocessed() is True


@pytest.mark.asyncio
async def test_wav2lip_reset_session_preserves_frame_reference_args(tmp_path: Path) -> None:
    avatar_dir = tmp_path / "avatar"
    frames_dir = avatar_dir / "frames"
    frames_dir.mkdir(parents=True)
    metadata_path = frames_dir / "mouth_metadata.json"
    metadata_path.write_text("{}", encoding="utf-8")
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "avatar",
                "model_type": "wav2lip",
                "metadata": {
                    "reference_mode": "frames",
                    "frame_dir": "frames",
                    "frame_metadata": "frames/mouth_metadata.json",
                    "preprocessed": True,
                    "animation": {"mouth_center": [0.5, 0.5]},
                },
            }
        ),
        encoding="utf-8",
    )
    reference = avatar_dir / "reference.png"
    _write_png(reference, (255, 255, 255))

    class FakeFlashTalk:
        def __init__(self) -> None:
            self.kwargs = None

        async def close(self) -> None:
            pass

        async def connect(self) -> None:
            pass

        async def init_session(self, ref_image, **kwargs) -> None:
            self.kwargs = kwargs

    fake = FakeFlashTalk()
    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "wav2lip"
    runner.avatar_id = "avatar"
    runner.avatars_root = tmp_path
    runner.flashtalk = fake
    runner._custom_ref_image_path = ""
    runner._ref_image_path = reference

    await runner._reset_flashtalk_session(reference)

    assert fake.kwargs["reference_mode"] == "frames"
    assert fake.kwargs["ref_frame_dir"] == frames_dir.resolve()
    assert fake.kwargs["ref_frame_metadata_path"] == metadata_path.resolve()
    assert fake.kwargs["preprocessed"] is True
