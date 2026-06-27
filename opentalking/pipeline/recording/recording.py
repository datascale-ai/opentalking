from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

import numpy as np


_SAFE_SESSION_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def _safe_session_id(session_id: str) -> str:
    safe = _SAFE_SESSION_RE.sub("_", session_id.strip())
    return safe[:128] or "session"


def flashtalk_recordings_dir() -> Path:
    raw = (
        os.environ.get("OPENTALKING_FLASHTALK_RECORDINGS_DIR")
        or os.environ.get("FLASHTALK_RECORDINGS_DIR")
    )
    if raw:
        return Path(raw).expanduser().resolve()
    return Path("data/session_recordings").resolve()


def flashtalk_recording_session_dir(session_id: str) -> Path:
    return flashtalk_recordings_dir() / _safe_session_id(session_id)


def flashtalk_recording_frame_dir(session_id: str) -> Path:
    return flashtalk_recording_session_dir(session_id) / "frames"


def flashtalk_recording_path(session_id: str) -> Path:
    return flashtalk_recording_session_dir(session_id) / "flashtalk_capture.mp4"


def clear_flashtalk_recording_files(session_id: str) -> None:
    """Remove frames/metadata/exported mp4 for this session so the next capture starts clean."""
    root = flashtalk_recording_session_dir(session_id)
    frames = root / "frames"
    if frames.is_dir():
        for p in frames.iterdir():
            if p.is_file():
                p.unlink(missing_ok=True)
    for name in ("metadata.json", "flashtalk_capture.mp4"):
        p = root / name
        if p.is_file():
            p.unlink(missing_ok=True)


def _metadata_path(session_id: str) -> Path:
    return flashtalk_recording_session_dir(session_id) / "metadata.json"


def _frame_data(frame: Any) -> np.ndarray | None:
    data = getattr(frame, "data", frame)
    arr = np.asarray(data)
    if arr.ndim != 3 or arr.shape[2] < 3:
        return None
    return np.ascontiguousarray(arr[:, :, :3].astype(np.uint8, copy=False))


def append_flashtalk_frames(
    session_id: str,
    frames: Iterable[Any],
    *,
    start_index: int,
    fps: float,
) -> int:
    import cv2

    frame_dir = flashtalk_recording_frame_dir(session_id)
    frame_dir.mkdir(parents=True, exist_ok=True)
    idx = max(0, int(start_index))
    first_shape: tuple[int, int] | None = None

    for frame in frames:
        arr = _frame_data(frame)
        if arr is None:
            continue
        if first_shape is None:
            first_shape = (int(arr.shape[1]), int(arr.shape[0]))
        path = frame_dir / f"frame_{idx:08d}.jpg"
        cv2.imwrite(str(path), arr, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        idx += 1

    if idx > start_index:
        meta = {
            "fps": max(1.0, float(fps)),
            "width": first_shape[0] if first_shape else None,
            "height": first_shape[1] if first_shape else None,
            "frames": idx,
        }
        _metadata_path(session_id).write_text(json.dumps(meta), encoding="utf-8")
    return idx


def export_flashtalk_recording(session_id: str) -> Path:
    import cv2

    frame_paths = sorted(flashtalk_recording_frame_dir(session_id).glob("frame_*.jpg"))
    if not frame_paths:
        raise FileNotFoundError("no FlashTalk recording frames")

    fps = 25.0
    meta_path = _metadata_path(session_id)
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            fps = max(1.0, float(meta.get("fps") or fps))
        except Exception:
            fps = 25.0

    first = cv2.imread(str(frame_paths[0]), cv2.IMREAD_COLOR)
    if first is None:
        raise FileNotFoundError("first FlashTalk recording frame is unreadable")
    height, width = first.shape[:2]
    output = flashtalk_recording_path(session_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    video_writer_fourcc = getattr(cv2, "VideoWriter_fourcc")

    writer = cv2.VideoWriter(
        str(output),
        video_writer_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError(f"cannot open recording writer: {output}")
    try:
        for path in frame_paths:
            frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if frame is None:
                continue
            if frame.shape[:2] != (height, width):
                frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
            writer.write(frame)
    finally:
        writer.release()
    return output
