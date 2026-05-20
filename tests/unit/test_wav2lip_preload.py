from __future__ import annotations

import json
from pathlib import Path

import apps.unified.main as unified_main
import pytest

from opentalking.avatar.wav2lip_preload import (
    collect_wav2lip_preload_payload_for_avatar,
    collect_wav2lip_preload_payloads,
    filter_wav2lip_preload_payloads,
    preload_wav2lip_assets,
    preload_wav2lip_avatar,
)


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

    payloads = collect_wav2lip_preload_payloads(tmp_path, postprocess_mode="opentalking_improved")

    assert payloads == [
        {
            "avatar_id": "good",
            "ref_frame_dir": str(frames.resolve()),
            "ref_frame_metadata_path": str(metadata.resolve()),
            "prepared_cache_dir": str((good / "wav2lip").resolve()),
            "width": 24,
            "height": 32,
            "fps": 30,
            "preprocessed": True,
            "wav2lip_postprocess_mode": "opentalking_improved",
        }
    ]


def test_collect_wav2lip_preload_payload_for_avatar_selects_requested_avatar_only(tmp_path: Path) -> None:
    for avatar_id in ("OWoman", "man"):
        avatar = tmp_path / avatar_id
        frames = avatar / "frames"
        frames.mkdir(parents=True)
        metadata = frames / "mouth_metadata.json"
        metadata.write_text('{"frames": {}}', encoding="utf-8")
        (avatar / "manifest.json").write_text(
            json.dumps(
                {
                    "id": avatar_id,
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

    payload = collect_wav2lip_preload_payload_for_avatar(
        tmp_path,
        "man",
        postprocess_mode="easy_improved",
    )

    assert payload is not None
    assert payload["avatar_id"] == "man"
    assert payload["ref_frame_dir"] == str((tmp_path / "man" / "frames").resolve())
    assert payload["prepared_cache_dir"] == str((tmp_path / "man" / "wav2lip").resolve())


def test_filter_wav2lip_preload_payloads_excludes_already_warmed_avatars() -> None:
    payloads = [
        {"avatar_id": "OWoman"},
        {"avatar_id": "man"},
        {"avatar_id": "singer"},
    ]

    filtered = filter_wav2lip_preload_payloads(
        payloads,
        exclude_avatar_ids={"man", "singer"},
    )

    assert filtered == [{"avatar_id": "OWoman"}]


def test_collect_wav2lip_preload_payloads_prefers_asset_postprocess_mode(tmp_path: Path) -> None:
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
                    "preferred_wav2lip_postprocess_mode": "opentalking-improved",
                },
            }
        ),
        encoding="utf-8",
    )

    payloads = collect_wav2lip_preload_payloads(tmp_path, postprocess_mode="easy_improved")

    assert payloads[0]["wav2lip_postprocess_mode"] == "opentalking_improved"


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
        postprocess_mode="basic",
        post_json=fake_post,
    )

    assert posts[0][0] == "http://127.0.0.1:18765/v1/audio2video/wav2lip/preload"
    assert posts[0][1]["avatar_id"] == "avatar"
    assert posts[0][1]["prepared_cache_dir"] == str((avatar / "wav2lip").resolve())
    assert posts[0][1]["wav2lip_postprocess_mode"] == "basic"


@pytest.mark.asyncio
async def test_preload_wav2lip_avatar_posts_only_requested_avatar(tmp_path: Path) -> None:
    for avatar_id in ("OWoman", "man"):
        avatar = tmp_path / avatar_id
        frames = avatar / "frames"
        frames.mkdir(parents=True)
        metadata = frames / "mouth_metadata.json"
        metadata.write_text('{"frames": {}}', encoding="utf-8")
        (avatar / "manifest.json").write_text(
            json.dumps(
                {
                    "id": avatar_id,
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
        return {"cache_hit": True, "frames": 125}

    await preload_wav2lip_avatar(
        tmp_path,
        "man",
        omnirt_endpoint="http://127.0.0.1:18765",
        postprocess_mode="basic",
        post_json=fake_post,
    )

    assert len(posts) == 1
    assert posts[0][1]["avatar_id"] == "man"


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
        postprocess_mode="opentalking_improved",
        post_json=fake_post,
        attempts=2,
        retry_delay_seconds=0.25,
        sleep=fake_sleep,
    )

    assert attempts == 2
    assert sleeps == [0.25]


def test_unified_does_not_start_all_wav2lip_preload() -> None:
    source = Path(unified_main.__file__).read_text(encoding="utf-8")

    assert "preload_wav2lip_assets(" not in source
    assert "resolve_model_backend(\"wav2lip\", settings).backend" not in source
    assert "_schedule_background_wav2lip_preload" not in source
