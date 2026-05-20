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


def test_wav2lip_mouth_metadata_includes_asset_tuned_model_crop(tmp_path: Path) -> None:
    avatar_dir = tmp_path / "avatar"
    avatar_dir.mkdir()
    reference = avatar_dir / "reference.png"
    _write_png(reference, (255, 255, 255))
    image_hash = image_file_sha256(reference)
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "avatar",
                "model_type": "wav2lip",
                "metadata": {
                    "source_image_hash": image_hash,
                    "model_crop": [0.27, 0.075, 0.75, 0.555],
                    "model_crop_source": "asset_tuned",
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

    metadata = runner._wav2lip_mouth_metadata()

    assert metadata is not None
    assert metadata["model_crop"] == [0.27, 0.075, 0.75, 0.555]
    assert metadata["model_crop_source"] == "asset_tuned"


def test_wav2lip_postprocess_mode_prefers_avatar_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    avatar_dir = tmp_path / "avatar"
    avatar_dir.mkdir()
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "avatar",
                "model_type": "wav2lip",
                "metadata": {
                    "preferred_wav2lip_postprocess_mode": "opentalking-improved",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENTALKING_WAV2LIP_POSTPROCESS_MODE", "easy_improved")

    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "wav2lip"
    runner.avatar_id = "avatar"
    runner.avatars_root = tmp_path

    assert runner._wav2lip_postprocess_mode() == "opentalking_improved"


def test_wav2lip_postprocess_mode_manual_override_wins_over_avatar_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    avatar_dir = tmp_path / "avatar"
    avatar_dir.mkdir()
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "avatar",
                "model_type": "wav2lip",
                "metadata": {
                    "preferred_wav2lip_postprocess_mode": "opentalking_improved",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENTALKING_WAV2LIP_POSTPROCESS_MODE", "easy_improved")

    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "wav2lip"
    runner.avatar_id = "avatar"
    runner.avatars_root = tmp_path
    runner._wav2lip_postprocess_mode_override = "basic"

    assert runner._wav2lip_postprocess_mode() == "basic"


def test_wav2lip_postprocess_mode_auto_override_keeps_avatar_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    avatar_dir = tmp_path / "avatar"
    avatar_dir.mkdir()
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "avatar",
                "model_type": "wav2lip",
                "metadata": {
                    "preferred_wav2lip_postprocess_mode": "opentalking_improved",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENTALKING_WAV2LIP_POSTPROCESS_MODE", "easy_improved")

    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "wav2lip"
    runner.avatar_id = "avatar"
    runner.avatars_root = tmp_path
    runner._wav2lip_postprocess_mode_override = None

    assert runner._wav2lip_postprocess_mode() == "opentalking_improved"


def test_wav2lip_postprocess_mode_uses_selected_driver_not_avatar_manifest_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    avatar_dir = tmp_path / "avatar"
    avatar_dir.mkdir()
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "avatar",
                "model_type": "flashhead",
                "metadata": {
                    "preferred_wav2lip_postprocess_mode": "opentalking_improved",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENTALKING_WAV2LIP_POSTPROCESS_MODE", "easy_improved")

    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "wav2lip"
    runner.avatar_id = "avatar"
    runner.avatars_root = tmp_path

    assert runner._wav2lip_postprocess_mode() == "opentalking_improved"


def test_wav2lip_postprocess_mode_falls_back_to_global_when_manifest_value_is_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    avatar_dir = tmp_path / "avatar"
    avatar_dir.mkdir()
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "avatar",
                "model_type": "wav2lip",
                "metadata": {
                    "preferred_wav2lip_postprocess_mode": "not-a-mode",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENTALKING_WAV2LIP_POSTPROCESS_MODE", "basic")

    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "wav2lip"
    runner.avatar_id = "avatar"
    runner.avatars_root = tmp_path

    assert runner._wav2lip_postprocess_mode() == "basic"


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
    assert fake.kwargs["prepared_cache_dir"] == (avatar_dir / "wav2lip").resolve()
    assert fake.kwargs["preprocessed"] is True


def test_quicktalk_template_video_comes_from_manifest_metadata(tmp_path: Path) -> None:
    avatar_dir = tmp_path / "avatar"
    avatar_dir.mkdir()
    template = avatar_dir / "idle.mp4"
    template.write_bytes(b"video")
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "avatar",
                "model_type": "wav2lip",
                "metadata": {
                    "source_video": "idle.mp4",
                },
            }
        ),
        encoding="utf-8",
    )

    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "quicktalk"
    runner.avatar_id = "avatar"
    runner.avatars_root = tmp_path

    assert runner._quicktalk_template_mode() == "video"
    assert runner._quicktalk_template_video() == template.resolve()
    assert runner._quicktalk_template_frame_dir() is None


def test_quicktalk_template_frames_come_from_manifest_metadata(tmp_path: Path) -> None:
    avatar_dir = tmp_path / "avatar"
    frames_dir = avatar_dir / "frames"
    frames_dir.mkdir(parents=True)
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
    runner.model_type = "quicktalk"
    runner.avatar_id = "avatar"
    runner.avatars_root = tmp_path

    assert runner._quicktalk_template_mode() == "frames"
    assert runner._quicktalk_template_frame_dir() == frames_dir.resolve()
    assert runner._quicktalk_template_video() is None


def test_quicktalk_template_defaults_to_image_for_static_avatar(tmp_path: Path) -> None:
    avatar_dir = tmp_path / "avatar"
    avatar_dir.mkdir()
    (avatar_dir / "manifest.json").write_text(
        json.dumps({"id": "avatar", "model_type": "wav2lip", "metadata": {}}),
        encoding="utf-8",
    )

    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "quicktalk"
    runner.avatar_id = "avatar"
    runner.avatars_root = tmp_path

    assert runner._quicktalk_template_mode() == "image"
    assert runner._quicktalk_template_video() is None
    assert runner._quicktalk_template_frame_dir() is None


@pytest.mark.asyncio
async def test_quicktalk_init_session_sends_template_args(tmp_path: Path) -> None:
    avatar_dir = tmp_path / "avatar"
    avatar_dir.mkdir()
    reference = avatar_dir / "reference.png"
    _write_png(reference, (255, 255, 255))
    template = avatar_dir / "idle.mp4"
    template.write_bytes(b"video")
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "avatar",
                "model_type": "quicktalk",
                "width": 512,
                "height": 768,
                "fps": 30,
                "metadata": {"source_video": "idle.mp4"},
            }
        ),
        encoding="utf-8",
    )

    class FakeFlashTalk:
        def __init__(self) -> None:
            self.kwargs = None

        async def init_session(self, ref_image, **kwargs) -> None:
            self.kwargs = kwargs

    fake = FakeFlashTalk()
    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "quicktalk"
    runner.avatar_id = "avatar"
    runner.avatars_root = tmp_path
    runner.flashtalk = fake

    await runner._init_flashtalk_session(reference)

    assert fake.kwargs["template_mode"] == "video"
    assert fake.kwargs["template_video"] == template.resolve()
    assert fake.kwargs["template_frame_dir"] is None
    assert fake.kwargs["video_config"] == {"width": 512, "height": 768, "fps": 25}


@pytest.mark.asyncio
async def test_quicktalk_init_session_sends_asset_face_cache(tmp_path: Path) -> None:
    avatar_dir = tmp_path / "avatar"
    avatar_dir.mkdir()
    reference = avatar_dir / "reference.png"
    _write_png(reference, (255, 255, 255))
    quicktalk_dir = avatar_dir / "quicktalk"
    quicktalk_dir.mkdir()
    cache = quicktalk_dir / "face_cache_v3_900.npz"
    cache.write_bytes(b"cache")
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "avatar",
                "model_type": "quicktalk",
                "width": 512,
                "height": 768,
                "fps": 25,
                "metadata": {"quicktalk": {"face_cache": "quicktalk/face_cache_v3_900.npz"}},
            }
        ),
        encoding="utf-8",
    )

    class FakeFlashTalk:
        def __init__(self) -> None:
            self.kwargs = None

        async def init_session(self, ref_image, **kwargs) -> None:
            self.kwargs = kwargs

    fake = FakeFlashTalk()
    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "quicktalk"
    runner.avatar_id = "avatar"
    runner.avatars_root = tmp_path
    runner.flashtalk = fake

    await runner._init_flashtalk_session(reference)

    assert fake.kwargs["quicktalk_face_cache"] == cache.resolve()


@pytest.mark.asyncio
async def test_quicktalk_init_session_derives_face_cache_from_asset_quicktalk_dir(tmp_path: Path) -> None:
    avatar_dir = tmp_path / "avatar"
    avatar_dir.mkdir()
    reference = avatar_dir / "reference.png"
    _write_png(reference, (255, 255, 255))
    source_dir = avatar_dir / "source"
    source_dir.mkdir()
    (source_dir / "avatar.mp4").write_bytes(b"video")
    quicktalk_dir = avatar_dir / "quicktalk"
    quicktalk_dir.mkdir()
    cache = quicktalk_dir / "face_cache_v3_674x900.npz"
    cache.write_bytes(b"cache")
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "avatar",
                "model_type": "wav2lip",
                "width": 830,
                "height": 1108,
                "fps": 30,
                "metadata": {
                    "reference_mode": "frames",
                    "frame_dir": "frames",
                    "source_video": "source/avatar.mp4",
                },
            }
        ),
        encoding="utf-8",
    )

    class FakeFlashTalk:
        def __init__(self) -> None:
            self.kwargs = None

        async def init_session(self, ref_image, **kwargs) -> None:
            self.kwargs = kwargs

    fake = FakeFlashTalk()
    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "quicktalk"
    runner.avatar_id = "avatar"
    runner.avatars_root = tmp_path
    runner.flashtalk = fake

    await runner._init_flashtalk_session(reference)

    assert fake.kwargs["template_mode"] == "video"
    assert fake.kwargs["quicktalk_face_cache"] == cache.resolve()


def test_quicktalk_video_avatar_does_not_use_mismatched_generic_face_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENTALKING_QUICKTALK_MAX_LONG_EDGE", "1080")
    avatar_dir = tmp_path / "avatar"
    avatar_dir.mkdir()
    source_dir = avatar_dir / "source"
    source_dir.mkdir()
    (source_dir / "avatar.mp4").write_bytes(b"video")
    quicktalk_dir = avatar_dir / "quicktalk"
    quicktalk_dir.mkdir()
    (quicktalk_dir / "face_cache_v3_900.npz").write_bytes(b"stale-cache")
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "avatar",
                "model_type": "wav2lip",
                "width": 830,
                "height": 1108,
                "fps": 30,
                "metadata": {"source_video": "source/avatar.mp4"},
            }
        ),
        encoding="utf-8",
    )

    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "quicktalk"
    runner.avatar_id = "avatar"
    runner.avatars_root = tmp_path

    assert runner._quicktalk_cache_video_size() == (808, 1080)
    assert runner._quicktalk_face_cache() is None


def test_quicktalk_image_avatar_keeps_generic_face_cache_compatibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENTALKING_QUICKTALK_MAX_LONG_EDGE", "1080")
    avatar_dir = tmp_path / "avatar"
    avatar_dir.mkdir()
    quicktalk_dir = avatar_dir / "quicktalk"
    quicktalk_dir.mkdir()
    cache = quicktalk_dir / "face_cache_v3_900.npz"
    cache.write_bytes(b"cache")
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "avatar",
                "model_type": "wav2lip",
                "width": 720,
                "height": 900,
                "fps": 30,
                "metadata": {"reference_mode": "image"},
            }
        ),
        encoding="utf-8",
    )

    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "quicktalk"
    runner.avatar_id = "avatar"
    runner.avatars_root = tmp_path

    assert runner._quicktalk_face_cache() == cache.resolve()



def test_quicktalk_template_video_can_come_from_quicktalk_metadata(tmp_path: Path) -> None:
    avatar_dir = tmp_path / "avatar"
    avatar_dir.mkdir()
    quicktalk_dir = avatar_dir / "quicktalk"
    quicktalk_dir.mkdir()
    template = quicktalk_dir / "template_900.mp4"
    template.write_bytes(b"video")
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "avatar",
                "model_type": "wav2lip",
                "metadata": {
                    "quicktalk": {"template_video": "quicktalk/template_900.mp4"},
                },
            }
        ),
        encoding="utf-8",
    )

    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "quicktalk"
    runner.avatar_id = "avatar"
    runner.avatars_root = tmp_path

    assert runner._quicktalk_template_mode() == "video"
    assert runner._quicktalk_template_video() == template.resolve()
