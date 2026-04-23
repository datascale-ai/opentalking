from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from opentalking.core.interfaces.avatar_asset import AvatarManifest
from opentalking.core.types.frames import AudioChunk, VideoFrameData


def _load_images_from_dir(d: Path) -> list[np.ndarray]:
    paths = sorted(
        p for p in d.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
    )
    frames: list[np.ndarray] = []
    for p in paths:
        img = Image.open(p).convert("RGB")
        arr = np.array(img, dtype=np.uint8)
        # OpenCV-style BGR for aiortc/av consistency
        frames.append(arr[:, :, ::-1].copy())
    return frames


@dataclass
class FrameAvatarState:
    manifest: AvatarManifest
    frames: list[np.ndarray]
    frame_paths: list[Path] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


def load_frame_avatar_state(avatar_path: Path, manifest: AvatarManifest) -> FrameAvatarState:
    avatar_path = avatar_path.resolve()
    if manifest.model_type == "musetalk":
        sub = avatar_path / "full_frames"
    else:
        sub = avatar_path / "frames"
    if not sub.is_dir():
        raise FileNotFoundError(f"Expected image directory: {sub}")
    frames = _load_images_from_dir(sub)
    if not frames:
        raise ValueError(f"No images in {sub}")
    paths = sorted(
        p for p in sub.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
    )
    return FrameAvatarState(manifest=manifest, frames=frames, frame_paths=paths)


def audio_chunk_to_frame_count(chunk: AudioChunk, fps: int) -> int:
    dur_s = chunk.duration_ms / 1000.0
    return max(1, int(dur_s * fps))


def numpy_bgr_to_videoframe(arr: np.ndarray, ts_ms: float) -> VideoFrameData:
    h, w = arr.shape[:2]
    return VideoFrameData(data=arr, width=w, height=h, timestamp_ms=ts_ms)
