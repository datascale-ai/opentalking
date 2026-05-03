from __future__ import annotations

import json
import os
import re
import subprocess
import wave
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


def flashtalk_recording_video_only_path(session_id: str) -> Path:
    return flashtalk_recording_session_dir(session_id) / "video_only.mp4"


def flashtalk_recording_audio_pcm_path(session_id: str) -> Path:
    return flashtalk_recording_session_dir(session_id) / "audio.pcm"


def flashtalk_recording_audio_wav_path(session_id: str) -> Path:
    return flashtalk_recording_session_dir(session_id) / "audio.wav"


def clear_flashtalk_recording_files(session_id: str) -> None:
    """Remove frames/metadata/exported mp4 for this session so the next capture starts clean."""
    root = flashtalk_recording_session_dir(session_id)
    frames = root / "frames"
    if frames.is_dir():
        for p in frames.iterdir():
            if p.is_file():
                p.unlink(missing_ok=True)
    for name in ("metadata.json", "flashtalk_capture.mp4", "video_only.mp4", "audio.pcm", "audio.wav"):
        p = root / name
        if p.is_file():
            p.unlink(missing_ok=True)


def _metadata_path(session_id: str) -> Path:
    return flashtalk_recording_session_dir(session_id) / "metadata.json"


def _read_metadata(session_id: str) -> dict[str, Any]:
    path = _metadata_path(session_id)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_metadata(session_id: str, meta: dict[str, Any]) -> None:
    path = _metadata_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta), encoding="utf-8")


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
        meta = _read_metadata(session_id)
        meta.update(
            {
                "fps": max(1.0, float(fps)),
                "width": first_shape[0] if first_shape else meta.get("width"),
                "height": first_shape[1] if first_shape else meta.get("height"),
                "frames": idx,
            }
        )
        _write_metadata(session_id, meta)
    return idx


def append_flashtalk_audio(
    session_id: str,
    pcm: Any,
    *,
    sample_rate: int = 16000,
) -> int:
    arr = np.asarray(pcm, dtype=np.int16).reshape(-1)
    if arr.size == 0:
        return 0
    path = flashtalk_recording_audio_pcm_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as f:
        f.write(np.ascontiguousarray(arr).tobytes())

    meta = _read_metadata(session_id)
    n = int(meta.get("audio_samples") or 0) + int(arr.size)
    meta.update({"audio_samples": n, "sample_rate": int(sample_rate)})
    _write_metadata(session_id, meta)
    return int(arr.size)


def append_flashtalk_av_chunk(
    session_id: str,
    frames: Iterable[Any],
    pcm: Any,
    *,
    start_index: int,
    fps: float,
    sample_rate: int = 16000,
) -> int:
    next_index = append_flashtalk_frames(
        session_id,
        frames,
        start_index=start_index,
        fps=fps,
    )
    if next_index > start_index:
        append_flashtalk_audio(session_id, pcm, sample_rate=sample_rate)
    return next_index


def _write_wav_mono_s16le(path: Path, pcm: np.ndarray, sample_rate: int) -> None:
    arr = np.asarray(pcm, dtype=np.int16).reshape(-1)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(np.ascontiguousarray(arr).tobytes())


def _ffmpeg_bin() -> str:
    try:
        from opentalking.core.config import get_settings

        configured = (get_settings().ffmpeg_bin or "").strip()
        if configured:
            return configured
    except Exception:
        pass
    return os.environ.get("OPENTALKING_FFMPEG_BIN", "ffmpeg").strip() or "ffmpeg"


def _mux_audio_video(video_in: Path, audio_in: Path, out_mp4: Path) -> None:
    proc = subprocess.run(
        [
            _ffmpeg_bin(),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_in),
            "-i",
            str(audio_in),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(out_mp4),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or b"").decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"ffmpeg recording mux failed ({proc.returncode}): {msg}")


def _frames_to_mp4(
    frame_paths: list[Path],
    output: Path,
    fps: float,
) -> None:
    import cv2

    first = cv2.imread(str(frame_paths[0]), cv2.IMREAD_COLOR)
    if first is None:
        raise FileNotFoundError("first FlashTalk recording frame is unreadable")
    height, width = first.shape[:2]
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


def _recorded_audio(session_id: str) -> tuple[np.ndarray, int] | None:
    pcm_path = flashtalk_recording_audio_pcm_path(session_id)
    if not pcm_path.is_file() or pcm_path.stat().st_size <= 0:
        return None
    meta = _read_metadata(session_id)
    sample_rate = int(meta.get("sample_rate") or 16000)
    raw = pcm_path.read_bytes()
    if not raw:
        return None
    return np.frombuffer(raw, dtype=np.int16).copy(), sample_rate


def export_flashtalk_recording(session_id: str) -> Path:
    frame_paths = sorted(flashtalk_recording_frame_dir(session_id).glob("frame_*.jpg"))
    if not frame_paths:
        raise FileNotFoundError("no FlashTalk recording frames")

    fps = 25.0
    meta = _read_metadata(session_id)
    if meta:
        try:
            fps = max(1.0, float(meta.get("fps") or fps))
        except Exception:
            fps = 25.0

    audio = _recorded_audio(session_id)
    output = flashtalk_recording_path(session_id)
    if audio is None:
        _frames_to_mp4(frame_paths, output, fps)
        return output

    video_only = flashtalk_recording_video_only_path(session_id)
    _frames_to_mp4(frame_paths, video_only, fps)
    audio_wav = flashtalk_recording_audio_wav_path(session_id)
    pcm, sample_rate = audio
    _write_wav_mono_s16le(audio_wav, pcm, sample_rate)
    _mux_audio_video(video_only, audio_wav, output)
    return output
