"""FlashTalk 离线导出：上传整段 PCM → 逐块推理生成画面 → 与对齐音频合成 MP4（不经 WebRTC 播放）。"""

from __future__ import annotations

import asyncio
import json
import logging
import wave
import zipfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from opentalking.core.config import get_settings
from opentalking.pipeline.recording.recording import flashtalk_recording_session_dir
from opentalking.pipeline.speak.synthesis_runner import (
    FlashTalkRunner,
    _env_float,
    _fade_head_i16,
    _fade_tail_i16,
)

log = logging.getLogger(__name__)


def _frame_data(frame: Any) -> np.ndarray | None:
    data = getattr(frame, "data", frame)
    arr = np.asarray(data)
    if arr.ndim != 3 or arr.shape[2] < 3:
        return None
    return np.ascontiguousarray(arr[:, :, :3].astype(np.uint8, copy=False))


def _build_aligned_pcm_chunks(
    pcm: np.ndarray,
    *,
    chunk_samples: int,
    sample_rate: int = 16000,
) -> tuple[list[np.ndarray], np.ndarray]:
    """与 ``speak_uploaded_pcm``  producer 一致：淡入淡出、尾静音、按块对齐；返回块列表与完整缓冲（用于 WAV）。"""
    boundary_fade_ms = _env_float("FLASHTALK_TTS_BOUNDARY_FADE_MS", 18.0)
    tail_fade_ms = _env_float("FLASHTALK_TTS_TAIL_FADE_MS", 80.0)
    trailing_silence_ms = _env_float("FLASHTALK_TTS_TRAILING_SILENCE_MS", 320.0)

    pcm_arr = np.asarray(pcm, dtype=np.int16)
    if pcm_arr.size == 0:
        return [], pcm_arr
    faded = _fade_head_i16(pcm_arr, sample_rate, boundary_fade_ms)
    audio_buffer = faded
    if audio_buffer.size > 0:
        audio_buffer = _fade_tail_i16(audio_buffer, sample_rate, tail_fade_ms)
    silence_samples = int(sample_rate * max(0.0, trailing_silence_ms) / 1000.0)
    if silence_samples > 0:
        audio_buffer = np.concatenate(
            [audio_buffer, np.zeros(silence_samples, dtype=np.int16)],
        )
    pad_len = (-len(audio_buffer)) % chunk_samples
    if pad_len:
        audio_buffer = np.concatenate(
            [audio_buffer, np.zeros(pad_len, dtype=np.int16)],
        )
    full_aligned = audio_buffer.copy()
    chunks: list[np.ndarray] = []
    buf = audio_buffer
    while len(buf) >= chunk_samples:
        chunks.append(buf[:chunk_samples].copy())
        buf = buf[chunk_samples:]
    return chunks, full_aligned


def _write_wav_mono_s16le(path: Path, pcm: np.ndarray, sample_rate: int) -> None:
    arr = np.asarray(pcm, dtype=np.int16)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(arr.tobytes())


def _frames_to_mp4(frames_dir: Path, out_mp4: Path, fps: float) -> None:
    frame_paths = sorted(frames_dir.glob("frame_*.jpg"))
    if not frame_paths:
        raise RuntimeError("no frames to encode")
    first = cv2.imread(str(frame_paths[0]), cv2.IMREAD_COLOR)
    if first is None:
        raise RuntimeError("first frame unreadable")
    height, width = first.shape[:2]
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    video_writer_fourcc = getattr(cv2, "VideoWriter_fourcc")
    writer = cv2.VideoWriter(
        str(out_mp4),
        video_writer_fourcc(*"mp4v"),
        max(1.0, float(fps)),
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError(f"cannot open video writer: {out_mp4}")
    try:
        for p in frame_paths:
            frame = cv2.imread(str(p), cv2.IMREAD_COLOR)
            if frame is None:
                continue
            if frame.shape[:2] != (height, width):
                frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
            writer.write(frame)
    finally:
        writer.release()


async def _ffmpeg_mux(
    *,
    ffmpeg_bin: str,
    video_in: Path,
    audio_in: Path,
    out_mp4: Path,
) -> None:
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        ffmpeg_bin,
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
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        msg = (stderr or b"").decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"ffmpeg mux failed ({proc.returncode}): {msg}")


def _write_zip(bundle_mp4: Path, audio_wav: Path, video_only: Path, meta: dict[str, Any], zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if bundle_mp4.is_file():
            zf.write(bundle_mp4, arcname="bundle.mp4")
        if audio_wav.is_file():
            zf.write(audio_wav, arcname="aligned_audio.wav")
        if video_only.is_file():
            zf.write(video_only, arcname="video_only.mp4")
        zf.writestr("metadata.json", json.dumps(meta, ensure_ascii=False, indent=2))


async def run_flashtalk_offline_av_bundle(
    runner: FlashTalkRunner,
    pcm: np.ndarray,
    *,
    session_id: str,
    job_id: str,
) -> dict[str, str]:
    """在已就绪的 FlashTalkRunner 上跑完整段 PCM，输出目录内生成音视频及 zip。"""
    if runner._closed:  # noqa: SLF001
        raise RuntimeError("runner is closed")

    out_root = flashtalk_recording_session_dir(session_id) / "offline" / job_id
    out_root.mkdir(parents=True, exist_ok=True)
    frames_dir = out_root / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    chunk_samples = runner.flashtalk.audio_chunk_samples
    chunks, full_audio = _build_aligned_pcm_chunks(pcm, chunk_samples=chunk_samples)
    fps = float(runner.flashtalk.fps or 25.0)
    sample_rate = 16000

    frame_idx = 0
    async with runner._speak_lock:  # noqa: SLF001
        await runner._await_dynamic_idle_prepare_done()  # noqa: SLF001
        for chunk in chunks:
            frames = await runner._generate_flashtalk_frames(np.asarray(chunk, dtype=np.int16))  # noqa: SLF001
            for fr in frames:
                arr = _frame_data(fr)
                if arr is None:
                    continue
                path = frames_dir / f"frame_{frame_idx:08d}.jpg"
                cv2.imwrite(str(path), arr, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                frame_idx += 1

    if frame_idx == 0:
        raise RuntimeError("FlashTalk produced zero frames for offline export")

    audio_wav = out_root / "aligned_audio.wav"
    _write_wav_mono_s16le(audio_wav, full_audio, sample_rate)

    video_only = out_root / "video_only.mp4"
    _frames_to_mp4(frames_dir, video_only, fps)

    settings = get_settings()
    ffmpeg_bin = (settings.ffmpeg_bin or "ffmpeg").strip() or "ffmpeg"
    bundle_mp4 = out_root / "bundle.mp4"
    await _ffmpeg_mux(ffmpeg_bin=ffmpeg_bin, video_in=video_only, audio_in=audio_wav, out_mp4=bundle_mp4)

    meta = {
        "session_id": session_id,
        "job_id": job_id,
        "fps": fps,
        "frame_count": frame_idx,
        "audio_samples": int(full_audio.size),
        "sample_rate": sample_rate,
        "paths": {
            "bundle_mp4": str(bundle_mp4.resolve()),
            "aligned_audio_wav": str(audio_wav.resolve()),
            "video_only_mp4": str(video_only.resolve()),
        },
    }
    (out_root / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    zip_path = out_root / "offline_bundle.zip"
    _write_zip(bundle_mp4, audio_wav, video_only, meta, zip_path)

    return {
        "work_dir": str(out_root.resolve()),
        "bundle_mp4": str(bundle_mp4.resolve()),
        "aligned_audio_wav": str(audio_wav.resolve()),
        "video_only_mp4": str(video_only.resolve()),
        "zip": str(zip_path.resolve()),
    }
