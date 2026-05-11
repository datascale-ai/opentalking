from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import cv2
import numpy as np

from opentalking.core.types.frames import AudioChunk
from opentalking.models.quicktalk.adapter import QuickTalkAdapter, QuickTalkState
from opentalking.models.quicktalk.runtime_v2 import ensure_ffmpeg, maybe_mkdir


def _read_wav_i16(path: Path) -> AudioChunk:
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        sample_rate = wf.getframerate()
        sampwidth = wf.getsampwidth()
        frames = wf.getnframes()
        raw = wf.readframes(frames)
    if sampwidth != 2:
        raise ValueError(f"Only 16-bit wav is supported for the bench CLI, got sampwidth={sampwidth}")
    pcm = np.frombuffer(raw, dtype="<i2")
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1).astype(np.int16)
    duration_ms = float(pcm.shape[0]) / float(sample_rate) * 1000.0
    return AudioChunk(data=pcm.astype(np.int16, copy=False), sample_rate=sample_rate, duration_ms=duration_ms)


def _open_ffmpeg_writer(fps: float, width: int, height: int, audio: Path, output: Path) -> subprocess.Popen:
    maybe_mkdir(output.parent)
    ffmpeg = ensure_ffmpeg()
    cmd = [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-s",
        f"{width}x{height}",
        "-r",
        f"{fps:g}",
        "-i",
        "pipe:0",
        "-i",
        str(audio),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-tune",
        "zerolatency",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(output),
    ]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)


def _finish_ffmpeg_writer(proc: subprocess.Popen) -> None:
    assert proc.stdin is not None
    proc.stdin.close()
    stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr is not None else ""
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"ffmpeg failed with code {rc}: {stderr.strip()}")


def _write_video_with_audio(frames: list[np.ndarray], fps: float, audio: Path, output: Path) -> None:
    if not frames:
        raise ValueError("No frames to write")
    h, w = frames[0].shape[:2]
    proc = _open_ffmpeg_writer(fps, w, h, audio, output)
    assert proc.stdin is not None
    for frame in frames:
        proc.stdin.write(np.ascontiguousarray(frame).tobytes())
    _finish_ffmpeg_writer(proc)


def _make_temp_avatar(asset_root: Path, template_video: Path) -> Path:
    root = Path(tempfile.mkdtemp(prefix="opentalking-quicktalk-avatar-"))
    cap = cv2.VideoCapture(str(template_video))
    ok, frame = cap.read()
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    cap.release()
    if not ok:
        raise RuntimeError(f"Failed to read template video: {template_video}")
    h, w = frame.shape[:2]
    cv2.imwrite(str(root / "preview.png"), frame)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "id": "quicktalk-temp",
                "model_type": "quicktalk",
                "fps": int(round(fps)) or 25,
                "sample_rate": 16000,
                "width": w,
                "height": h,
                "version": "1.0",
                "metadata": {
                    "asset_root": str(asset_root),
                    "template_video": str(template_video),
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return root


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark QuickTalk inside OpenTalking.")
    parser.add_argument("--asset-root", required=True)
    parser.add_argument("--template-video", required=True)
    parser.add_argument("--audio", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--device", default="cuda:0")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asset_root = Path(args.asset_root).expanduser().resolve()
    template_video = Path(args.template_video).expanduser().resolve()
    audio = Path(args.audio).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()

    avatar_dir = _make_temp_avatar(asset_root, template_video)
    adapter = QuickTalkAdapter()
    adapter.load_model(args.device)

    t0 = time.perf_counter()
    state = adapter.load_avatar(str(avatar_dir))
    init_seconds = time.perf_counter() - t0
    assert isinstance(state, QuickTalkState)

    chunk = _read_wav_i16(audio)
    features = adapter.extract_features_for_stream(chunk, state)

    h, w = state.worker.frames[0].shape[:2]
    proc = _open_ffmpeg_writer(state.fps, w, h, audio, output)
    assert proc.stdin is not None
    frames = 0
    first_frame_seconds = None
    t1 = time.perf_counter()
    try:
        for frame in state.worker.generate_frames_from_reps(features.reps):
            if frames == 0:
                first_frame_seconds = time.perf_counter() - t1
            proc.stdin.write(np.ascontiguousarray(frame).tobytes())
            frames += 1
    except Exception:
        proc.kill()
        proc.wait()
        raise
    render_seconds = time.perf_counter() - t1
    mux_t0 = time.perf_counter()
    _finish_ffmpeg_writer(proc)
    mux_seconds = time.perf_counter() - mux_t0

    metrics = {
        "output": str(output),
        "frames": frames,
        "fps": state.fps,
        "audio_duration_ms": chunk.duration_ms,
        "init_seconds": init_seconds,
        "audio_feature_seconds": features.audio_feature_seconds,
        "first_frame_seconds": first_frame_seconds,
        "render_seconds": render_seconds,
        "render_fps": frames / render_seconds if render_seconds > 0 else 0.0,
        "mux_seconds": mux_seconds,
    }
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
