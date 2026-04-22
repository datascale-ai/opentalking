from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import subprocess
import sys
import wave
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image


def _bootstrap_local_paths(root: Path) -> None:
    sys.path[:0] = [str(root), str(root / "src")]


ROOT = Path(__file__).resolve().parents[1]
_bootstrap_local_paths(ROOT)

from opentalking.models.flashtalk.ws_client import FlashTalkWSClient
from opentalking.tts.edge.adapter import EdgeTTSAdapter


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _slugify(value: str) -> str:
    slug = []
    for char in value.strip().lower():
        if char.isalnum():
            slug.append(char)
        elif char in {"-", "_"}:
            slug.append(char)
        else:
            slug.append("-")
    compact = "".join(slug).strip("-")
    while "--" in compact:
        compact = compact.replace("--", "-")
    return compact or "run"


def _save_wav(path: Path, pcm: np.ndarray, sample_rate: int) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(np.asarray(pcm, dtype=np.int16).tobytes())


def _load_wav_pcm(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wf:
        frames = wf.readframes(wf.getnframes())
    return np.frombuffer(frames, dtype=np.int16).copy()


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
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(out_path),
        ],
        check=True,
    )


def _concat_audio_files(
    input_paths: list[Path],
    out_path: Path,
    *,
    ffmpeg_bin: str,
) -> None:
    cmd = [ffmpeg_bin]
    for path in input_paths:
        cmd.extend(["-i", str(path)])
    cmd.extend(
        [
            "-y",
            "-filter_complex",
            "".join(f"[{idx}:a]" for idx in range(len(input_paths)))
            + f"concat=n={len(input_paths)}:v=0:a=1[a]",
            "-map",
            "[a]",
            "-acodec",
            "pcm_s16le",
            str(out_path),
        ]
    )
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _concat_videos(
    input_paths: list[Path],
    out_path: Path,
    *,
    ffmpeg_bin: str,
) -> None:
    cmd = [ffmpeg_bin]
    for path in input_paths:
        cmd.extend(["-i", str(path)])
    cmd.extend(
        [
            "-y",
            "-filter_complex",
            "".join(f"[{idx}:v]" for idx in range(len(input_paths)))
            + f"concat=n={len(input_paths)}:v=1:a=0[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(out_path),
        ]
    )
    subprocess.run(cmd, check=True)


def _build_silence_pcm(*, sample_rate: int, duration_seconds: float) -> np.ndarray:
    sample_count = max(0, int(round(sample_rate * max(0.0, duration_seconds))))
    return np.zeros(sample_count, dtype=np.int16)


def _transcode_audio_to_wav(
    input_path: Path,
    out_path: Path,
    *,
    ffmpeg_bin: str,
    sample_rate: int,
) -> None:
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            str(input_path),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
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


def _load_manifest(avatar_path: Path) -> dict[str, Any]:
    manifest_path = avatar_path / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Avatar manifest not found: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _resolve_reference_image(avatar_path: Path) -> Path:
    for name in ("reference.png", "reference.jpg", "reference.jpeg"):
        candidate = avatar_path / name
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        f"No reference image found in {avatar_path}. Expected reference.png or reference.jpg."
    )


def _load_reference_frame(image_path: Path, width: int, height: int) -> np.ndarray:
    with Image.open(image_path).convert("RGB") as img:
        scale = max(width / img.width, height / img.height)
        resized_w = max(1, int(math.ceil(img.width * scale)))
        resized_h = max(1, int(math.ceil(img.height * scale)))
        resized = img.resize((resized_w, resized_h), resample=Image.BILINEAR)
        left = max(0, (resized_w - width) // 2)
        top = max(0, (resized_h - height) // 2)
        cropped = resized.crop((left, top, left + width, top + height))
        rgb = np.asarray(cropped, dtype=np.uint8)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _build_run_dir(output_root: Path, avatar_path: Path, source_label: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder_name = f"{stamp}-{_slugify(avatar_path.name)}-{_slugify(source_label)}"
    run_dir = output_root / folder_name
    _ensure_dir(run_dir)
    return run_dir


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
        raise RuntimeError("TTS produced no audio chunks.")
    return np.concatenate(parts).astype(np.int16, copy=False)


def _build_idle_driver_pcm(*, total_samples: int, level: float) -> np.ndarray:
    if total_samples <= 0:
        return np.zeros(0, dtype=np.int16)

    phase = np.linspace(0.0, 2.0 * np.pi, total_samples, endpoint=False, dtype=np.float32)
    envelope = 0.35 + 0.65 * (0.5 - 0.5 * np.cos(phase))
    harmonic = (
        0.58 * np.sin(phase)
        + 0.27 * np.sin(2.0 * phase + 0.65)
        + 0.15 * np.sin(3.0 * phase + 1.35)
    )
    shimmer = 0.08 * np.sin(5.0 * phase + 0.2)
    signal = envelope * (harmonic + shimmer)

    peak = float(np.max(np.abs(signal))) if signal.size else 1.0
    peak = max(peak, 1e-6)
    pcm = np.clip(signal / peak * level, -32767.0, 32767.0)
    return pcm.astype(np.int16)


def _idle_frame_signature(frame: np.ndarray) -> np.ndarray:
    arr = np.asarray(frame, dtype=np.float32)
    gray = arr[:, :, 0] * 0.114 + arr[:, :, 1] * 0.587 + arr[:, :, 2] * 0.299
    h, w = gray.shape[:2]
    step_y = max(1, h // 24)
    step_x = max(1, w // 24)
    sampled = gray[::step_y, ::step_x]
    return sampled[:24, :24].astype(np.float32, copy=False)


def _blend_frames(left: np.ndarray, right: np.ndarray, alpha: float) -> np.ndarray:
    mixed = np.asarray(left, dtype=np.float32) * (1.0 - alpha)
    mixed += np.asarray(right, dtype=np.float32) * alpha
    return np.clip(mixed, 0.0, 255.0).astype(np.uint8)


def _motion_score(signatures: list[np.ndarray], start: int, end: int) -> float:
    score = 0.0
    steps = 0
    for idx in range(start, min(end, len(signatures) - 1)):
        score += float(np.mean(np.abs(signatures[idx + 1] - signatures[idx])))
        steps += 1
    return score / max(1, steps)


def _optimize_idle_loop(frames: list[np.ndarray], *, crossfade_frames: int) -> list[np.ndarray]:
    if len(frames) < 12:
        return [np.ascontiguousarray(frame) for frame in frames]

    signatures = [_idle_frame_signature(frame) for frame in frames]
    total = len(signatures)
    compare_span = max(3, min(8, crossfade_frames))
    min_loop_frames = max(compare_span * 3, total // 2)
    best_score: float | None = None
    best_start = 0
    best_end = total - 1

    for start in range(max(1, total // 3)):
        min_end = start + min_loop_frames - 1
        if min_end >= total:
            break
        for end in range(min_end, total):
            score = 0.0
            for offset in range(compare_span):
                head = signatures[start + offset]
                tail = signatures[end - compare_span + 1 + offset]
                score += float(np.mean(np.abs(head - tail)))
            edge_motion = _motion_score(signatures, start, start + compare_span)
            edge_motion += _motion_score(
                signatures,
                max(start + 1, end - compare_span),
                end,
            )
            score += edge_motion * 0.35
            if best_score is None or score < best_score:
                best_score = score
                best_start = start
                best_end = end

    segment = [np.ascontiguousarray(frame) for frame in frames[best_start : best_end + 1]]
    overlap = max(2, min(crossfade_frames, len(segment) // 4))
    if len(segment) <= overlap + 2:
        return segment

    smoothed = list(segment[:-overlap])
    tail = segment[-overlap:]
    head = segment[:overlap]
    for idx in range(overlap):
        alpha = (idx + 1) / (overlap + 1)
        smoothed.append(_blend_frames(tail[idx], head[idx], alpha))

    smoothed.append(segment[0])
    return smoothed


def _build_idle_playback_indices(frame_count: int, mode: str) -> list[int]:
    if frame_count <= 1:
        return [0] if frame_count == 1 else []
    if mode == "pingpong":
        return list(range(frame_count)) + list(range(frame_count - 2, 0, -1))
    return list(range(frame_count))


def _build_soft_ellipse_mask(
    height: int,
    width: int,
    *,
    center_x: float,
    center_y: float,
    radius_x: float,
    radius_y: float,
    feather: float = 0.35,
) -> np.ndarray:
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    xx = (xx - center_x) / max(radius_x, 1.0)
    yy = (yy - center_y) / max(radius_y, 1.0)
    dist = np.sqrt(xx * xx + yy * yy)
    outer = 1.0 + max(0.05, feather)
    mask = np.clip((outer - dist) / max(outer - 1.0, 1e-6), 0.0, 1.0)
    return mask.astype(np.float32)


def _stabilize_idle_mouth(
    frames: list[np.ndarray],
    reference_frame: np.ndarray | None,
    *,
    strength: float,
    temporal_strength: float,
) -> list[np.ndarray]:
    if not frames or reference_frame is None or strength <= 0.0:
        return [np.ascontiguousarray(frame) for frame in frames]

    ref = np.asarray(reference_frame, dtype=np.float32)
    h, w = ref.shape[:2]
    mask = _build_soft_ellipse_mask(
        h,
        w,
        center_x=w * 0.5,
        center_y=h * 0.69,
        radius_x=w * 0.16,
        radius_y=h * 0.10,
        feather=0.42,
    )[:, :, None] * min(max(strength, 0.0), 1.0)

    stabilized: list[np.ndarray] = []
    prev_stable: np.ndarray | None = None
    temporal_strength = min(max(temporal_strength, 0.0), 1.0)
    for frame in frames:
        cur = np.asarray(frame, dtype=np.float32)
        blended = cur * (1.0 - mask) + ref * mask
        if prev_stable is not None and temporal_strength > 0.0:
            stable_mix = blended * (1.0 - temporal_strength) + prev_stable * temporal_strength
            blended = blended * (1.0 - mask) + stable_mix * mask
        prev_stable = blended
        stabilized.append(np.clip(blended, 0.0, 255.0).astype(np.uint8))
    return stabilized


def _stabilize_non_face_region(
    frame: np.ndarray,
    reference_frame: np.ndarray | None,
    previous_frame: np.ndarray | None,
    *,
    freeze_strength: float,
    temporal_strength: float,
) -> np.ndarray:
    if reference_frame is None or (freeze_strength <= 0.0 and temporal_strength <= 0.0):
        return np.ascontiguousarray(frame)

    cur = np.asarray(frame, dtype=np.float32)
    ref = np.asarray(reference_frame, dtype=np.float32)
    h, w = cur.shape[:2]
    face_mask = _build_soft_ellipse_mask(
        h,
        w,
        center_x=w * 0.5,
        center_y=h * 0.34,
        radius_x=w * 0.18,
        radius_y=h * 0.22,
        feather=0.28,
    )[:, :, None]
    non_face = 1.0 - face_mask

    out = cur.copy()
    freeze_strength = min(max(freeze_strength, 0.0), 1.0)
    temporal_strength = min(max(temporal_strength, 0.0), 1.0)

    if freeze_strength > 0.0:
        freeze_mask = non_face * freeze_strength
        out = out * (1.0 - freeze_mask) + ref * freeze_mask

    if previous_frame is not None and temporal_strength > 0.0:
        prev = np.asarray(previous_frame, dtype=np.float32)
        temporal_mask = non_face * temporal_strength
        temporal_mix = out * (1.0 - temporal_strength) + prev * temporal_strength
        out = out * (1.0 - temporal_mask) + temporal_mix * temporal_mask

    return np.clip(out, 0.0, 255.0).astype(np.uint8)


async def _build_idle_frames(
    *,
    ws_url: str,
    idle_source_path: Path,
    reference_frame: np.ndarray,
    idle_chunks: int,
    idle_level: float,
    crossfade_frames: int,
    playback_mode: str,
    mouth_lock: float,
    mouth_temporal: float,
    body_freeze_strength: float,
    body_temporal_strength: float,
) -> tuple[list[np.ndarray], dict[str, Any]]:
    temp_client = FlashTalkWSClient(ws_url)
    built: list[np.ndarray] = []
    prev_frame: np.ndarray | None = None
    try:
        await temp_client.init_session(ref_image=idle_source_path)
        chunk_samples = int(temp_client.audio_chunk_samples)
        total_samples = chunk_samples * max(1, idle_chunks)
        driver = _build_idle_driver_pcm(total_samples=total_samples, level=idle_level)

        for chunk_idx in range(max(1, idle_chunks)):
            start = chunk_idx * chunk_samples
            stop = start + chunk_samples
            pcm_chunk = driver[start:stop]
            frames = await temp_client.generate(pcm_chunk)
            for frame in frames:
                stable = _stabilize_non_face_region(
                    frame.data,
                    reference_frame,
                    prev_frame,
                    freeze_strength=body_freeze_strength,
                    temporal_strength=body_temporal_strength,
                )
                prev_frame = stable
                built.append(np.ascontiguousarray(stable))
    finally:
        await temp_client.close()

    optimized = _optimize_idle_loop(built, crossfade_frames=max(2, crossfade_frames))
    optimized = _stabilize_idle_mouth(
        optimized,
        reference_frame,
        strength=mouth_lock,
        temporal_strength=mouth_temporal,
    )
    playback_indices = _build_idle_playback_indices(len(optimized), playback_mode)
    if not playback_indices:
        playback_indices = list(range(len(optimized)))

    return optimized, {
        "idle_chunks": int(idle_chunks),
        "idle_level": float(idle_level),
        "crossfade_frames": int(crossfade_frames),
        "playback_mode": playback_mode,
        "mouth_lock": float(mouth_lock),
        "mouth_temporal": float(mouth_temporal),
        "body_freeze_strength": float(body_freeze_strength),
        "body_temporal_strength": float(body_temporal_strength),
        "playback_indices": playback_indices,
        "driver_samples": int(total_samples),
        "idle_source_image": str(idle_source_path),
        "fps": int(temp_client.fps),
        "width": int(temp_client.width),
        "height": int(temp_client.height),
    }


def _write_idle_video(
    *,
    frames: list[np.ndarray],
    idle_dir: Path,
    fps: int,
    width: int,
    height: int,
    playback_mode: str,
    loop_count: int,
    idle_seconds: float,
) -> tuple[Path, dict[str, Any]]:
    playback_indices = _build_idle_playback_indices(len(frames), playback_mode)
    if not playback_indices:
        playback_indices = list(range(len(frames)))

    if idle_seconds > 0:
        total_frames = max(1, int(round(idle_seconds * fps)))
    else:
        total_frames = max(1, len(playback_indices) * max(1, loop_count))

    silent_path = idle_dir / "idle_loop.mp4"
    writer = _open_writer(silent_path, (width, height), fps)
    try:
        for idx in range(total_frames):
            frame_idx = playback_indices[idx % len(playback_indices)]
            writer.write(frames[frame_idx])
    finally:
        writer.release()

    return silent_path, {
        "idle_video": str(silent_path),
        "frames_written": int(total_frames),
        "loop_count": int(loop_count),
        "idle_seconds": float(idle_seconds),
        "playback_mode": playback_mode,
        "cycle_frames": len(playback_indices),
        "duration_seconds": float(total_frames / float(fps)),
    }


def _build_combined_feedback_video(
    *,
    run_dir: Path,
    idle_video_path: Path,
    idle_duration_seconds: float,
    speech_silent_video: Path,
    speech_audio_wav: Path,
    sample_rate: int,
    ffmpeg_bin: str,
) -> dict[str, str]:
    preview_dir = run_dir / "preview"
    _ensure_dir(preview_dir)
    silence_wav = preview_dir / "idle_silence.wav"
    combined_wav = preview_dir / "combined_audio.wav"
    combined_silent = preview_dir / "combined_silent.mp4"
    combined_muxed = preview_dir / "idle_then_feedback.mp4"

    silence_pcm = _build_silence_pcm(
        sample_rate=sample_rate,
        duration_seconds=idle_duration_seconds,
    )
    _save_wav(silence_wav, silence_pcm, sample_rate)
    _concat_audio_files(
        [silence_wav, speech_audio_wav],
        combined_wav,
        ffmpeg_bin=ffmpeg_bin,
    )
    _concat_videos(
        [idle_video_path, speech_silent_video],
        combined_silent,
        ffmpeg_bin=ffmpeg_bin,
    )
    _mux_audio(combined_silent, combined_wav, combined_muxed, ffmpeg_bin)
    return {
        "preview_dir": str(preview_dir),
        "preview_video": str(combined_muxed),
        "preview_audio": str(combined_wav),
        "preview_silent_video": str(combined_silent),
    }


async def _render_speech_video(
    *,
    client: FlashTalkWSClient,
    pcm: np.ndarray,
    speech_dir: Path,
    reference_frame: np.ndarray,
    ffmpeg_bin: str,
    body_freeze_strength: float,
    body_temporal_strength: float,
) -> dict[str, Any]:
    chunk_samples = int(client.audio_chunk_samples)
    total_chunks = max(1, math.ceil(len(pcm) / max(1, chunk_samples)))
    padded = np.pad(
        np.asarray(pcm, dtype=np.int16),
        (0, total_chunks * chunk_samples - len(pcm)),
        mode="constant",
    )

    silent_path = speech_dir / "rendered_silent.mp4"
    muxed_path = speech_dir / "rendered_with_audio.mp4"
    writer = _open_writer(silent_path, (client.width, client.height), client.fps)
    total_frames = 0
    prev_frame: np.ndarray | None = None
    try:
        for idx in range(total_chunks):
            chunk = padded[idx * chunk_samples : (idx + 1) * chunk_samples]
            frames = await client.generate(chunk)
            for frame in frames:
                stable = _stabilize_non_face_region(
                    frame.data,
                    reference_frame,
                    prev_frame,
                    freeze_strength=body_freeze_strength,
                    temporal_strength=body_temporal_strength,
                )
                prev_frame = stable
                writer.write(stable)
            total_frames += len(frames)
    finally:
        writer.release()

    wav_path = speech_dir / "input.wav"
    _save_wav(wav_path, pcm, client.sample_rate)
    _mux_audio(silent_path, wav_path, muxed_path, ffmpeg_bin)
    return {
        "audio_wav": str(wav_path),
        "silent_video": str(silent_path),
        "muxed_video": str(muxed_path),
        "chunk_samples": chunk_samples,
        "total_chunks": total_chunks,
        "frames_written": total_frames,
    }


async def _run(args: argparse.Namespace) -> Path:
    avatar_path = _resolve_avatar_path(args.avatar)
    manifest = _load_manifest(avatar_path)
    if str(manifest.get("model_type", "")).strip().lower() != "flashtalk":
        raise RuntimeError(
            f"Avatar {avatar_path.name} model_type={manifest.get('model_type')!r}, expected flashtalk."
        )

    sample_rate = int(manifest.get("sample_rate", 16000))
    output_root = Path(args.output_root).expanduser().resolve()
    _ensure_dir(output_root)
    source_label = "audio" if args.audio_path else "tts"
    run_dir = _build_run_dir(output_root, avatar_path, source_label)
    speech_dir = run_dir / "speech"
    idle_dir = run_dir / "idle"
    _ensure_dir(speech_dir)
    _ensure_dir(idle_dir)

    ref_image_path = _resolve_reference_image(avatar_path)
    (run_dir / "avatar_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if args.audio_path:
        src_audio = Path(args.audio_path).expanduser().resolve()
        if not src_audio.is_file():
            raise FileNotFoundError(f"Audio file not found: {src_audio}")
        input_wav = speech_dir / "input.wav"
        _transcode_audio_to_wav(
            src_audio,
            input_wav,
            ffmpeg_bin=args.ffmpeg_bin,
            sample_rate=sample_rate,
        )
        pcm = _load_wav_pcm(input_wav)
        text_value = None
    else:
        text_value = args.text
        if not text_value.strip():
            raise RuntimeError("Text input is empty.")
        pcm = await _synthesize_pcm(
            text_value,
            args.voice,
            sample_rate,
            float(args.chunk_ms),
        )
        (speech_dir / "input.txt").write_text(text_value, encoding="utf-8")

    client = FlashTalkWSClient(args.ws_url)
    try:
        await client.init_session(ref_image=ref_image_path)
        speech_reference_frame = _load_reference_frame(
            ref_image_path,
            int(client.width),
            int(client.height),
        )
        speech_meta = await _render_speech_video(
            client=client,
            pcm=pcm,
            speech_dir=speech_dir,
            reference_frame=speech_reference_frame,
            ffmpeg_bin=args.ffmpeg_bin,
            body_freeze_strength=float(args.body_freeze_strength),
            body_temporal_strength=float(args.body_temporal_strength),
        )
    finally:
        await client.close()

    idle_reference_frame = _load_reference_frame(
        ref_image_path,
        int(client.width or manifest.get("width", 416)),
        int(client.height or manifest.get("height", 704)),
    )
    idle_frames, idle_build_meta = await _build_idle_frames(
        ws_url=args.ws_url,
        idle_source_path=ref_image_path,
        reference_frame=idle_reference_frame,
        idle_chunks=max(1, int(args.idle_chunks)),
        idle_level=float(args.idle_level),
        crossfade_frames=max(2, int(args.idle_crossfade_frames)),
        playback_mode=args.idle_playback,
        mouth_lock=float(args.idle_mouth_lock),
        mouth_temporal=float(args.idle_mouth_temporal),
        body_freeze_strength=float(args.body_freeze_strength),
        body_temporal_strength=float(args.body_temporal_strength),
    )
    if not idle_frames:
        raise RuntimeError("Idle cache generation returned no frames.")
    np.savez_compressed(
        idle_dir / "idle_frames.npz",
        frames=np.stack(idle_frames, axis=0).astype(np.uint8, copy=False),
    )
    idle_video_path, idle_video_meta = _write_idle_video(
        frames=idle_frames,
        idle_dir=idle_dir,
        fps=int(idle_build_meta["fps"]),
        width=int(idle_build_meta["width"]),
        height=int(idle_build_meta["height"]),
        playback_mode=args.idle_playback,
        loop_count=max(1, int(args.idle_loop_count)),
        idle_seconds=float(args.idle_seconds),
    )

    speech_meta.update(
        {
            "avatar": str(avatar_path),
            "reference_image": str(ref_image_path),
            "idle_source_image": str(ref_image_path),
            "voice": args.voice,
            "ws_url": args.ws_url,
            "fps": int(idle_build_meta["fps"]),
            "width": int(idle_build_meta["width"]),
            "height": int(idle_build_meta["height"]),
            "body_freeze_strength": float(args.body_freeze_strength),
            "body_temporal_strength": float(args.body_temporal_strength),
            "text": text_value,
        }
    )
    (speech_dir / "meta.json").write_text(
        json.dumps(speech_meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    idle_meta = {
        "avatar": str(avatar_path),
        "reference_image": str(ref_image_path),
        "ws_url": args.ws_url,
        **idle_build_meta,
        **idle_video_meta,
    }
    (idle_dir / "meta.json").write_text(
        json.dumps(idle_meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    preview_meta = _build_combined_feedback_video(
        run_dir=run_dir,
        idle_video_path=idle_video_path,
        idle_duration_seconds=float(idle_video_meta["duration_seconds"]),
        speech_silent_video=Path(speech_meta["silent_video"]),
        speech_audio_wav=Path(speech_meta["audio_wav"]),
        sample_rate=sample_rate,
        ffmpeg_bin=args.ffmpeg_bin,
    )

    run_meta = {
        "run_dir": str(run_dir),
        "avatar": str(avatar_path),
        "speech_dir": str(speech_dir),
        "idle_dir": str(idle_dir),
        "speech_video": speech_meta["muxed_video"],
        "idle_video": str(idle_video_path),
        **preview_meta,
        "input_mode": source_label,
        "text": text_value,
        "voice": args.voice,
    }
    (run_dir / "meta.json").write_text(
        json.dumps(run_meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline FlashTalk WS render with per-run folders and idle video export."
    )
    parser.add_argument("--avatar", default="flashtalk-demo")
    parser.add_argument(
        "--ws-url",
        default=os.environ.get("OPENTALKING_FLASHTALK_WS_URL", "ws://localhost:8765"),
    )
    parser.add_argument("--audio-path", default=None)
    parser.add_argument(
        "--text",
        default=(
            "大家好，这是 OpenTalking 的 FlashTalk 离线视频测试。"
            "现在我们通过远程 NPU 服务和文本转语音音频，生成一个离线数字人视频示例。"
        ),
    )
    parser.add_argument("--voice", default="zh-CN-XiaoxiaoNeural")
    parser.add_argument("--chunk-ms", type=float, default=20.0)
    parser.add_argument(
        "--output-root",
        default=str(ROOT / "output" / "flashtalk_ws_runs"),
    )
    parser.add_argument("--ffmpeg-bin", default="ffmpeg")
    parser.add_argument("--idle-chunks", type=int, default=int(os.environ.get("FLASHTALK_IDLE_CACHE_CHUNKS", "4")))
    parser.add_argument("--idle-level", type=float, default=float(os.environ.get("FLASHTALK_IDLE_CACHE_LEVEL", "480.0")))
    parser.add_argument(
        "--idle-crossfade-frames",
        type=int,
        default=int(os.environ.get("FLASHTALK_IDLE_CACHE_CROSSFADE_FRAMES", "6")),
    )
    parser.add_argument(
        "--idle-playback",
        default=os.environ.get("FLASHTALK_IDLE_CACHE_PLAYBACK", "pingpong").strip().lower(),
        choices=("pingpong", "loop"),
    )
    parser.add_argument("--idle-mouth-lock", type=float, default=float(os.environ.get("FLASHTALK_IDLE_MOUTH_LOCK", "0.97")))
    parser.add_argument(
        "--idle-mouth-temporal",
        type=float,
        default=float(os.environ.get("FLASHTALK_IDLE_MOUTH_TEMPORAL", "0.85")),
    )
    parser.add_argument("--idle-loop-count", type=int, default=1)
    parser.add_argument("--idle-seconds", type=float, default=0.0)
    parser.add_argument("--body-freeze-strength", type=float, default=0.0)
    parser.add_argument("--body-temporal-strength", type=float, default=0.0)
    args = parser.parse_args()

    run_dir = asyncio.run(_run(args))
    print(run_dir)


if __name__ == "__main__":
    main()
