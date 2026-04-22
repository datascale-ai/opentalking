from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import wave
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np


def _bootstrap_local_paths(root: Path) -> None:
    sys.path[:0] = [str(root), str(root / "src")]


ROOT = Path(__file__).resolve().parents[1]
_bootstrap_local_paths(ROOT)

from opentalking.tts.edge.adapter import EdgeTTSAdapter
from opentalking.worker.pipeline.render_pipeline import (
    render_audio_chunk_sync,
    reset_avatar_speech_state,
)
from opentalking.models.wav2lip.adapter import Wav2LipAdapter
from opentalking.models.wav2lip.official_runtime import (
    ensure_s3fd as ensure_runtime_s3fd,
    resolve_checkpoint_path as resolve_runtime_checkpoint_path,
    run_official_inference as run_runtime_official_inference,
)


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _save_wav(path: Path, pcm: np.ndarray, sample_rate: int) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.astype(np.int16).tobytes())


def _open_writer(path: Path, size: tuple[int, int], fps: int) -> cv2.VideoWriter:
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, float(fps), size)
    if not writer.isOpened():
        raise RuntimeError(f"Failed to open video writer for {path}")
    return writer


def _mux_audio(video_path: Path, wav_path: Path, out_path: Path, ffmpeg_bin: str) -> None:
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(wav_path),
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(out_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _resolve_avatar_path(avatar: str) -> Path:
    avatar_path = Path(avatar).expanduser()
    if avatar_path.is_dir():
        return avatar_path.resolve()
    candidate = ROOT / "examples" / "avatars" / avatar
    if candidate.is_dir():
        return candidate.resolve()
    raise FileNotFoundError(f"Avatar not found: {avatar}")


def _load_manifest(avatar_path: Path) -> dict[str, object]:
    manifest_path = avatar_path / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Avatar manifest not found: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _resolve_face_image(avatar_path: Path, override: str | None) -> Path:
    if override:
        path = Path(override).expanduser()
        if path.is_file():
            return path.resolve()
        raise FileNotFoundError(f"Face image not found: {path}")

    for name in ("preview.png", "preview.jpg", "preview.jpeg"):
        candidate = avatar_path / name
        if candidate.is_file():
            return candidate.resolve()

    frames_dir = avatar_path / "frames"
    if frames_dir.is_dir():
        for pattern in ("*.png", "*.jpg", "*.jpeg"):
            matches = sorted(frames_dir.glob(pattern))
            if matches:
                return matches[0].resolve()

    raise FileNotFoundError(
        f"No preview image found for avatar {avatar_path}. "
        "Expected preview.png or at least one frame image."
    )


def _ensure_support_file(target: Path, sources: list[Path], *, min_bytes: int, label: str) -> Path:
    _ensure_dir(target.parent)
    if target.is_file() and target.stat().st_size >= min_bytes:
        return target.resolve()

    for source in sources:
        if source.is_file() and source.stat().st_size >= min_bytes:
            shutil.copy2(source, target)
            return target.resolve()

    checked = [str(target), *[str(path) for path in sources]]
    raise FileNotFoundError(
        f"Missing usable {label}. Checked: {checked}. "
        f"Please download the file and place it in one of these paths."
    )


def _resolve_checkpoint_path(override: str | None) -> Path:
    return resolve_runtime_checkpoint_path(override)


async def _synthesize_pcm(text: str, voice: str, sample_rate: int, chunk_ms: float) -> np.ndarray:
    tts = EdgeTTSAdapter(
        default_voice=voice,
        sample_rate=sample_rate,
        chunk_ms=chunk_ms,
    )
    parts: list[np.ndarray] = []
    async for chunk in tts.synthesize_stream(text, voice=voice):
        parts.append(np.asarray(chunk.data, dtype=np.int16).reshape(-1).copy())
    if not parts:
        return np.zeros(0, dtype=np.int16)
    return np.concatenate(parts).astype(np.int16, copy=False)


async def _synthesize_chunks(text: str, voice: str, sample_rate: int, chunk_ms: float) -> list[Any]:
    tts = EdgeTTSAdapter(
        default_voice=voice,
        sample_rate=sample_rate,
        chunk_ms=chunk_ms,
    )
    chunks: list[Any] = []
    async for chunk in tts.synthesize_stream(text, voice=voice):
        chunks.append(chunk)
    return chunks


def _pad_pcm_for_idle(pcm: np.ndarray, sample_rate: int, fps: int, lead_frames: int, tail_frames: int) -> np.ndarray:
    lead_samples = max(0, int(round(sample_rate * lead_frames / float(fps))))
    tail_samples = max(0, int(round(sample_rate * tail_frames / float(fps))))
    if lead_samples <= 0 and tail_samples <= 0:
        return pcm
    pad_head = np.zeros(lead_samples, dtype=np.int16)
    pad_tail = np.zeros(tail_samples, dtype=np.int16)
    return np.concatenate([pad_head, pcm, pad_tail]).astype(np.int16, copy=False)


def _run_official_inference(
    *,
    avatar_path: Path,
    checkpoint_path: Path,
    face_image: Path,
    pcm: np.ndarray,
    sample_rate: int,
    out_path: Path,
    fps: int,
    ffmpeg_bin: str,
    pads: tuple[int, int, int, int],
    box: tuple[int, int, int, int] | None,
    resize_factor: int,
    face_det_batch_size: int,
    wav2lip_batch_size: int,
    nosmooth: bool,
) -> None:
    _, _, rendered_path = run_runtime_official_inference(
        avatar_path=avatar_path,
        face_image=face_image,
        pcm=pcm,
        sample_rate=sample_rate,
        fps=fps,
        ffmpeg_bin=ffmpeg_bin,
        checkpoint_path=checkpoint_path,
        pads=pads,
        box=box,
        resize_factor=resize_factor,
        face_det_batch_size=face_det_batch_size,
        wav2lip_batch_size=wav2lip_batch_size,
        nosmooth=nosmooth,
    )
    shutil.copy2(rendered_path, out_path)


async def _run_live_parity(args: argparse.Namespace) -> Path:
    out_dir = ROOT / "debug" / f"wav2lip-offline-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
    _ensure_dir(out_dir)

    os.environ["OPENTALKING_MODELS_DIR"] = str((ROOT / "models").resolve())
    os.environ["OPENTALKING_AVATARS_DIR"] = str((ROOT / "examples/avatars").resolve())
    os.environ["OPENTALKING_TORCH_DEVICE"] = args.device

    avatar_path = _resolve_avatar_path(args.avatar)
    manifest = _load_manifest(avatar_path)
    fps = int(manifest.get("fps", 25))
    sample_rate = int(manifest.get("sample_rate", 16000))
    width = int(manifest.get("width", 768))
    height = int(manifest.get("height", 1024))

    chunks = await _synthesize_chunks(args.text, args.voice, sample_rate, float(args.chunk_ms))
    if not chunks:
        raise RuntimeError("TTS produced no chunks")

    raw_pcm = np.concatenate([np.asarray(chunk.data, dtype=np.int16) for chunk in chunks]).astype(
        np.int16,
        copy=False,
    )
    wav_path = out_dir / "tts.wav"
    silent_path = out_dir / "rendered_silent.mp4"
    muxed_path = out_dir / "rendered_with_audio.mp4"
    meta_path = out_dir / "meta.json"
    frames_check_dir = out_dir / "frames_check"
    _ensure_dir(frames_check_dir)

    padded_pcm = _pad_pcm_for_idle(
        raw_pcm,
        sample_rate=sample_rate,
        fps=fps,
        lead_frames=max(0, int(args.lead_idle_frames)),
        tail_frames=max(0, int(args.tail_idle_frames)),
    )
    _save_wav(wav_path, padded_pcm, sample_rate)

    adapter = Wav2LipAdapter()
    adapter.load_model(args.device)
    avatar_state = adapter.load_avatar(str(avatar_path))
    reset_avatar_speech_state(avatar_state)

    if avatar_state.frames:
        frame_h, frame_w = avatar_state.frames[0].shape[:2]
        width = frame_w
        height = frame_h

    writer = _open_writer(silent_path, (width, height), fps)
    frame_idx = 0
    speech_frame_idx = 0
    exported_frames: list[int] = []
    check_targets = {0, 1, 2, 4, 5}

    for _ in range(max(0, int(args.lead_idle_frames))):
        writer.write(adapter.idle_frame(avatar_state, frame_idx).data)
        frame_idx += 1

    for chunk in chunks:
        start_frame_idx = frame_idx
        frame_idx, frames = render_audio_chunk_sync(
            adapter,
            avatar_state,
            chunk,
            frame_index_start=frame_idx,
            speech_frame_index_start=speech_frame_idx,
        )
        for local_idx, frame in enumerate(frames):
            writer.write(frame.data)
            global_speech_idx = speech_frame_idx + local_idx
            if global_speech_idx in check_targets:
                cv2.imwrite(
                    str(frames_check_dir / f"frame_{global_speech_idx:03d}.png"),
                    frame.data,
                )
                exported_frames.append(global_speech_idx)
        speech_frame_idx += max(0, frame_idx - start_frame_idx)

    for _ in range(max(0, int(args.tail_idle_frames))):
        writer.write(adapter.idle_frame(avatar_state, frame_idx).data)
        frame_idx += 1

    writer.release()
    _mux_audio(silent_path, wav_path, muxed_path, args.ffmpeg_bin)

    meta_path.write_text(
        json.dumps(
            {
                "avatar": str(avatar_path),
                "text": args.text,
                "voice": args.voice,
                "fps": fps,
                "frames": frame_idx,
                "sample_rate": sample_rate,
                "audio_wav": str(wav_path),
                "silent_video": str(silent_path),
                "muxed_video": str(muxed_path),
                "render_mode": "live_parity_pipeline",
                "chunk_ms": float(args.chunk_ms),
                "lead_idle_frames": int(args.lead_idle_frames),
                "tail_idle_frames": int(args.tail_idle_frames),
                "speech_frames": speech_frame_idx,
                "frame_checks": exported_frames,
                "wav2lip_checkpoint_loaded": bool(adapter._torch_bundle),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return out_dir


async def _run_official(args: argparse.Namespace) -> Path:
    out_dir = ROOT / "debug" / f"wav2lip-offline-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
    _ensure_dir(out_dir)

    avatar_path = _resolve_avatar_path(args.avatar)
    manifest = _load_manifest(avatar_path)
    fps = int(manifest.get("fps", 25))
    sample_rate = int(manifest.get("sample_rate", 16000))

    face_image = _resolve_face_image(avatar_path, args.face_image)
    s3fd_path = ensure_runtime_s3fd()
    checkpoint_path = _resolve_checkpoint_path(args.checkpoint_path)

    wav_path = out_dir / "tts.wav"
    muxed_path = out_dir / "rendered_with_audio.mp4"
    meta_path = out_dir / "meta.json"

    pcm = await _synthesize_pcm(args.text, args.voice, sample_rate, float(args.chunk_ms))
    pcm = _pad_pcm_for_idle(
        pcm,
        sample_rate=sample_rate,
        fps=fps,
        lead_frames=max(0, int(args.lead_idle_frames)),
        tail_frames=max(0, int(args.tail_idle_frames)),
    )
    _save_wav(wav_path, pcm, sample_rate)

    box = tuple(args.box) if args.box and any(value >= 0 for value in args.box) else None
    _run_official_inference(
        avatar_path=avatar_path,
        checkpoint_path=checkpoint_path,
        face_image=face_image,
        pcm=pcm,
        sample_rate=sample_rate,
        out_path=muxed_path,
        fps=fps,
        ffmpeg_bin=args.ffmpeg_bin,
        pads=tuple(args.pads),
        box=box,
        resize_factor=max(1, int(args.resize_factor)),
        face_det_batch_size=max(1, int(args.face_det_batch_size)),
        wav2lip_batch_size=max(1, int(args.wav2lip_batch_size)),
        nosmooth=bool(args.nosmooth),
    )

    if not muxed_path.is_file():
        raise RuntimeError(f"Wav2Lip inference did not produce the expected output video: {muxed_path}")

    meta_path.write_text(
        json.dumps(
            {
                "avatar": str(avatar_path),
                "face_image": str(face_image),
                "text": args.text,
                "voice": args.voice,
                "fps": fps,
                "sample_rate": sample_rate,
                "audio_wav": str(wav_path),
                "muxed_video": str(muxed_path),
                "checkpoint_path": str(checkpoint_path),
                "s3fd_path": str(s3fd_path),
                "render_mode": "official_wav2lip_inference",
                "pads": list(args.pads),
                "box": list(args.box),
                "resize_factor": int(args.resize_factor),
                "face_det_batch_size": int(args.face_det_batch_size),
                "wav2lip_batch_size": int(args.wav2lip_batch_size),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return out_dir


async def _run(args: argparse.Namespace) -> Path:
    if args.render_mode == "official":
        return await _run_official(args)
    return await _run_live_parity(args)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline Wav2Lip render with live-parity or official inference modes"
    )
    parser.add_argument("--avatar", default="wav2lip_new")
    parser.add_argument("--face-image", default=None)
    parser.add_argument("--text", default="你好，我们现在正在测试 wav2lip 的离线后端调试链路。")
    parser.add_argument("--voice", default="zh-CN-XiaoxiaoNeural")
    parser.add_argument("--chunk-ms", type=float, default=160.0)
    parser.add_argument("--render-mode", choices=("live-parity", "official"), default="live-parity")
    parser.add_argument("--lead-idle-frames", type=int, default=18)
    parser.add_argument("--tail-idle-frames", type=int, default=24)
    parser.add_argument("--device", default=os.environ.get("OPENTALKING_TORCH_DEVICE", "cuda"))
    parser.add_argument("--checkpoint-path", default=None)
    parser.add_argument("--s3fd-source", action="append", default=[])
    parser.add_argument("--pads", nargs=4, type=int, default=[0, 10, 0, 0])
    parser.add_argument("--box", nargs=4, type=int, default=[-1, -1, -1, -1])
    parser.add_argument("--resize-factor", type=int, default=1)
    parser.add_argument("--face-det-batch-size", type=int, default=8)
    parser.add_argument("--wav2lip-batch-size", type=int, default=64)
    parser.add_argument("--nosmooth", action="store_true")
    parser.add_argument("--ffmpeg-bin", default="ffmpeg")
    args = parser.parse_args()

    out_dir = asyncio.run(_run(args))
    print(out_dir)


if __name__ == "__main__":
    main()
