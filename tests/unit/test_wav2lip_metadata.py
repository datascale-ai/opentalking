from __future__ import annotations

import json
from pathlib import Path

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
