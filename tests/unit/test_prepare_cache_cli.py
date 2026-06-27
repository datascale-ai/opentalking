from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from apps.cli.prepare_cache import (
    CacheValidationError,
    _prepare_quicktalk_asset,
    _resolve_quicktalk_template_source,
    _target_video_size,
    _validate_quicktalk_face_cache,
    parse_args,
)


def _write_manifest(avatar_dir: Path, payload: dict) -> dict:
    avatar_dir.mkdir(parents=True, exist_ok=True)
    (avatar_dir / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    return payload


def test_target_video_size_matches_quicktalk_runtime_scaling() -> None:
    manifest = {"width": 830, "height": 1108}

    assert _target_video_size(manifest, max_long_edge=1080) == (808, 1080)
    assert _target_video_size(manifest, max_long_edge=900) == (674, 900)


def test_quicktalk_template_source_prefers_quicktalk_metadata(tmp_path: Path) -> None:
    avatar_dir = tmp_path / "avatars" / "singer"
    preferred = avatar_dir / "quicktalk" / "template_900.mp4"
    fallback = avatar_dir / "idle.mp4"
    preferred.parent.mkdir(parents=True)
    preferred.write_bytes(b"preferred")
    fallback.write_bytes(b"fallback")
    manifest = _write_manifest(
        avatar_dir,
        {
            "id": "singer",
            "model_type": "wav2lip",
            "width": 720,
            "height": 900,
            "metadata": {
                "template_video": "idle.mp4",
                "quicktalk": {"template_video": "quicktalk/template_900.mp4"},
            },
        },
    )

    source = _resolve_quicktalk_template_source(avatar_dir, manifest)

    assert source is not None
    assert source.path == preferred.resolve()
    assert source.mode == "video"


def test_quicktalk_template_source_ignores_paths_outside_avatar(tmp_path: Path) -> None:
    avatar_dir = tmp_path / "avatars" / "anchor"
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    fallback = avatar_dir / "source.mp4"
    fallback.parent.mkdir(parents=True)
    fallback.write_bytes(b"fallback")
    manifest = _write_manifest(
        avatar_dir,
        {
            "id": "anchor",
            "model_type": "flashhead",
            "width": 512,
            "height": 512,
            "metadata": {"quicktalk": {"template_video": "../outside.mp4"}},
        },
    )

    source = _resolve_quicktalk_template_source(avatar_dir, manifest)

    assert source is not None
    assert source.path == fallback.resolve()


def test_validate_quicktalk_face_cache_accepts_expected_schema(tmp_path: Path) -> None:
    cache = tmp_path / "face_cache_v3_900.npz"
    np.savez(
        cache,
        faces=np.zeros((3, 256, 256, 3), dtype=np.uint8),
        boxes=np.zeros((3, 4), dtype=np.int32),
        affines=np.zeros((3, 2, 3), dtype=np.float32),
    )

    info = _validate_quicktalk_face_cache(cache)

    assert info.frames == 3
    assert info.path == cache.resolve()


def test_validate_quicktalk_face_cache_rejects_bad_schema(tmp_path: Path) -> None:
    cache = tmp_path / "face_cache_v3_bad.npz"
    np.savez(
        cache,
        faces=np.zeros((3, 128, 128, 3), dtype=np.uint8),
        boxes=np.zeros((3, 4), dtype=np.int32),
        affines=np.zeros((3, 2, 3), dtype=np.float32),
    )

    with pytest.raises(CacheValidationError, match="faces"):
        _validate_quicktalk_face_cache(cache)


def test_parse_args_rejects_unsupported_model() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--model", "flashhead", "--avatars-root", "examples/avatars"])


def test_parse_args_uses_full_quicktalk_template_by_default() -> None:
    args = parse_args(["--model", "quicktalk", "--avatars-root", "examples/avatars"])

    assert args.max_template_seconds is None

def test_prepare_quicktalk_asset_generates_template_and_cache_from_image(tmp_path: Path) -> None:
    avatar_dir = tmp_path / "avatars" / "anchor"
    source = avatar_dir / "reference.png"
    manifest = _write_manifest(
        avatar_dir,
        {
            "id": "anchor",
            "model_type": "flashhead",
            "width": 512,
            "height": 512,
            "metadata": {"source_image_path": "reference.png"},
        },
    )
    import cv2

    cv2.imwrite(str(source), np.full((32, 32, 3), 127, dtype=np.uint8))

    class FakeRebuild:
        def read_frames(self, template_video: Path, max_seconds: float | None):
            del max_seconds
            assert template_video.is_file()
            return [np.zeros((512, 512, 3), dtype=np.uint8) for _ in range(2)], 25.0

        def face_detect_frames(self, frames):
            return [
                (
                    np.zeros((256, 256, 3), dtype=np.uint8),
                    [1, 2, 3, 4],
                    np.zeros((2, 3), dtype=np.float32),
                )
                for _ in frames
            ]

        def save_face_cache(self, cache_path: Path, results):
            np.savez(
                cache_path,
                faces=np.stack([item[0] for item in results], axis=0),
                boxes=np.asarray([item[1] for item in results], dtype=np.int32),
                affines=np.stack([item[2] for item in results], axis=0),
            )

    result = _prepare_quicktalk_asset(
        avatar_dir=avatar_dir,
        manifest=manifest,
        rebuild=FakeRebuild(),
        max_long_edge=900,
        max_template_seconds=1.0,
        overwrite=False,
        verify=True,
    )

    assert result.status == "generated"
    assert result.source_mode == "image"
    assert result.frames == 2
    assert (avatar_dir / "quicktalk" / "template_512x512.mp4").is_file()
    assert (avatar_dir / "quicktalk" / "face_cache_v3_512x512.npz").is_file()
