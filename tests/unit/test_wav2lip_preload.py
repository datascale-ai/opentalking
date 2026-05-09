from __future__ import annotations

import json
from pathlib import Path

import pytest

from opentalking.avatar.wav2lip_preload import collect_wav2lip_preload_payloads, preload_wav2lip_assets


def test_collect_wav2lip_preload_payloads_selects_only_preprocessed_frame_assets(tmp_path: Path) -> None:
    good = tmp_path / "good"
    frames = good / "frames"
    frames.mkdir(parents=True)
    metadata = frames / "mouth_metadata.json"
    metadata.write_text('{"frames": {}}', encoding="utf-8")
    (good / "manifest.json").write_text(
        json.dumps(
            {
                "id": "good",
                "model_type": "wav2lip",
                "width": 24,
                "height": 32,
                "fps": 30,
                "metadata": {
                    "reference_mode": "frames",
                    "frame_dir": "frames",
                    "frame_metadata": "frames/mouth_metadata.json",
                    "preprocessed": True,
                },
            }
        ),
        encoding="utf-8",
    )
    ignored = tmp_path / "ignored"
    ignored.mkdir()
    (ignored / "manifest.json").write_text(
        json.dumps(
            {
                "id": "ignored",
                "model_type": "wav2lip",
                "metadata": {"reference_mode": "frames"},
            }
        ),
        encoding="utf-8",
    )

    payloads = collect_wav2lip_preload_payloads(tmp_path, enhanced=True)

    assert payloads == [
        {
            "avatar_id": "good",
            "ref_frame_dir": str(frames.resolve()),
            "ref_frame_metadata_path": str(metadata.resolve()),
            "width": 24,
            "height": 32,
            "fps": 30,
            "preprocessed": True,
            "enable_enhanced_postprocessing": True,
        }
    ]


@pytest.mark.asyncio
async def test_preload_wav2lip_assets_posts_payloads(tmp_path: Path) -> None:
    avatar = tmp_path / "avatar"
    frames = avatar / "frames"
    frames.mkdir(parents=True)
    metadata = frames / "mouth_metadata.json"
    metadata.write_text('{"frames": {}}', encoding="utf-8")
    (avatar / "manifest.json").write_text(
        json.dumps(
            {
                "id": "avatar",
                "model_type": "wav2lip",
                "width": 24,
                "height": 32,
                "metadata": {
                    "reference_mode": "frames",
                    "frame_dir": "frames",
                    "frame_metadata": "frames/mouth_metadata.json",
                    "preprocessed": True,
                },
            }
        ),
        encoding="utf-8",
    )
    posts: list[tuple[str, dict]] = []

    async def fake_post(url: str, payload: dict) -> dict:
        posts.append((url, payload))
        return {"cache_hit": False, "frames": 1}

    await preload_wav2lip_assets(
        tmp_path,
        omnirt_endpoint="http://127.0.0.1:18765",
        enhanced=False,
        post_json=fake_post,
    )

    assert posts[0][0] == "http://127.0.0.1:18765/v1/avatar/wav2lip/preload"
    assert posts[0][1]["avatar_id"] == "avatar"
    assert posts[0][1]["enable_enhanced_postprocessing"] is False


@pytest.mark.asyncio
async def test_preload_wav2lip_assets_retries_when_omnirt_is_not_ready(tmp_path: Path) -> None:
    avatar = tmp_path / "avatar"
    frames = avatar / "frames"
    frames.mkdir(parents=True)
    metadata = frames / "mouth_metadata.json"
    metadata.write_text('{"frames": {}}', encoding="utf-8")
    (avatar / "manifest.json").write_text(
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
                    "frame_metadata": "frames/mouth_metadata.json",
                    "preprocessed": True,
                },
            }
        ),
        encoding="utf-8",
    )
    attempts = 0
    sleeps: list[float] = []

    async def fake_post(url: str, payload: dict) -> dict:
        nonlocal attempts
        del url, payload
        attempts += 1
        if attempts == 1:
            raise OSError("connection refused")
        return {"cache_hit": False, "frames": 125}

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    await preload_wav2lip_assets(
        tmp_path,
        omnirt_endpoint="http://127.0.0.1:18765",
        enhanced=True,
        post_json=fake_post,
        attempts=2,
        retry_delay_seconds=0.25,
        sleep=fake_sleep,
    )

    assert attempts == 2
    assert sleeps == [0.25]
