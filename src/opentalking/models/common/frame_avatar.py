from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from opentalking.core.interfaces.avatar_asset import AvatarManifest
from opentalking.core.types.frames import AudioChunk, VideoFrameData


def _resize_to_manifest(img: Image.Image, manifest: AvatarManifest) -> Image.Image:
    target = (int(manifest.width), int(manifest.height))
    if img.size == target:
        return img
    return img.resize(target, Image.Resampling.LANCZOS)


def _load_images_from_dir(d: Path, manifest: AvatarManifest) -> list[np.ndarray]:
    paths = sorted(
        p for p in d.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
    )
    frames: list[np.ndarray] = []
    for p in paths:
        img = Image.open(p).convert("RGB")
        img = _resize_to_manifest(img, manifest)
        arr = np.array(img, dtype=np.uint8)
        # OpenCV-style BGR for aiortc/av consistency
        frames.append(arr[:, :, ::-1].copy())
    return frames


def load_preview_frame(
    avatar_path: Path,
    fallback_frame: np.ndarray,
    manifest: AvatarManifest | None = None,
) -> np.ndarray:
    for name in ("preview.png", "preview.jpg", "preview.jpeg", "preview.webp"):
        candidate = avatar_path / name
        if candidate.is_file():
            img = Image.open(candidate).convert("RGB")
            if manifest is not None:
                img = _resize_to_manifest(img, manifest)
            arr = np.array(img, dtype=np.uint8)
            return arr[:, :, ::-1].copy()
    return fallback_frame.copy()


@dataclass
class FrameAvatarState:
    manifest: AvatarManifest
    frames: list[np.ndarray]
    avatar_path: Path
    frame_paths: list[Path] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


def load_frame_avatar_state(avatar_path: Path, manifest: AvatarManifest) -> FrameAvatarState:
    avatar_path = avatar_path.resolve()
    if manifest.model_type == "musetalk":
        candidates = [avatar_path / "full_frames", avatar_path / "full_imgs"]
    else:
        candidates = [avatar_path / "frames"]
    sub = next((p for p in candidates if p.is_dir()), candidates[0])
    if not sub.is_dir():
        raise FileNotFoundError(f"Expected image directory: {sub}")
    frames = _load_images_from_dir(sub, manifest)
    if not frames:
        raise ValueError(f"No images in {sub}")
    paths = sorted(
        p for p in sub.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
    )
    return FrameAvatarState(
        manifest=manifest,
        frames=frames,
        avatar_path=avatar_path,
        frame_paths=paths,
    )


def audio_chunk_to_frame_count(chunk: AudioChunk, fps: int) -> int:
    dur_s = chunk.duration_ms / 1000.0
    return max(1, int(dur_s * fps))


def numpy_bgr_to_videoframe(arr: np.ndarray, ts_ms: float) -> VideoFrameData:
    h, w = arr.shape[:2]
    return VideoFrameData(data=arr, width=w, height=h, timestamp_ms=ts_ms)
