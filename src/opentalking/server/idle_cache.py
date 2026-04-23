from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import torch
from loguru import logger
from PIL import Image

from opentalking.engine import get_audio_embedding, get_base_data, run_pipeline
from opentalking.engine.accelerator import synchronize
from opentalking.server import runtime
from opentalking.server.broadcast import CMD_GENERATE, broadcast_audio_embedding, broadcast_cmd


def _load_reference_frame(image_path: str) -> np.ndarray:
    def _bias(name, default=0.5):
        try:
            return max(0.0, min(1.0, float(os.environ.get(name, default))))
        except (TypeError, ValueError):
            return default

    with Image.open(image_path).convert("RGB") as img:
        scale = max(runtime.WIDTH / img.width, runtime.HEIGHT / img.height)
        resized_w = max(1, int(np.ceil(img.width * scale)))
        resized_h = max(1, int(np.ceil(img.height * scale)))
        resized = img.resize((resized_w, resized_h), resample=Image.BILINEAR)
        v_bias = _bias("FLASHTALK_COND_CROP_VERTICAL_BIAS")
        h_bias = _bias("FLASHTALK_COND_CROP_HORIZONTAL_BIAS")
        margin_h = max(resized_h - runtime.HEIGHT, 0)
        margin_w = max(resized_w - runtime.WIDTH, 0)
        top  = max(0, min(int(round(margin_h * v_bias)), margin_h))
        left = max(0, min(int(round(margin_w * h_bias)), margin_w))
        cropped = resized.crop((left, top, left + runtime.WIDTH, top + runtime.HEIGHT))
        return np.asarray(cropped, dtype=np.uint8)


def _make_idle_cache_key(reference_frame: np.ndarray) -> str:
    payload = {
        "version": runtime.IDLE_CACHE_VERSION,
        "frame_num": runtime.FRAME_NUM,
        "motion_frames_num": runtime.MOTION_FRAMES_NUM,
        "height": runtime.HEIGHT,
        "width": runtime.WIDTH,
        "sample_rate": runtime.SAMPLE_RATE,
        "tgt_fps": runtime.TGT_FPS,
        "idle_cache_chunks": runtime.IDLE_CACHE_CHUNKS,
        "idle_cache_level": runtime.IDLE_CACHE_LEVEL,
        "idle_cache_playback": runtime.IDLE_CACHE_PLAYBACK,
        "idle_cache_crossfade_frames": runtime.IDLE_CACHE_CROSSFADE_FRAMES,
        "idle_enter_chunks": runtime.IDLE_ENTER_CHUNKS,
        "idle_silence_rms": runtime.IDLE_SILENCE_RMS,
        "idle_refresh_interval": runtime.IDLE_REFRESH_INTERVAL,
        "idle_hold_min_chunks": runtime.IDLE_HOLD_MIN_CHUNKS,
        "idle_hold_max_chunks": runtime.IDLE_HOLD_MAX_CHUNKS,
        "idle_mouth_lock": runtime.IDLE_MOUTH_LOCK,
        "idle_mouth_temporal": runtime.IDLE_MOUTH_TEMPORAL,
        "idle_eye_lock": runtime.IDLE_EYE_LOCK,
        "idle_eye_temporal": runtime.IDLE_EYE_TEMPORAL,
        "idle_random_seed": runtime.IDLE_RANDOM_SEED,
        "jpeg_quality": runtime.JPEG_QUALITY,
    }
    digest = hashlib.sha256()
    digest.update(reference_frame.tobytes())
    digest.update(json.dumps(payload, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()


def _build_idle_cache_key(reference_frame: np.ndarray) -> str:
    return _make_idle_cache_key(reference_frame)


def _idle_cache_path(cache_key: str) -> Path:
    return runtime.IDLE_CACHE_DIR / f"{cache_key}.npz"


def _load_idle_cache_frames(cache_key: str) -> list[np.ndarray] | None:
    cached = runtime._IDLE_CACHE_MEMORY.get(cache_key)
    if cached is not None:
        return [chunk.copy() for chunk in cached]

    cache_path = _idle_cache_path(cache_key)
    if not cache_path.exists():
        return None

    try:
        with np.load(cache_path, allow_pickle=False) as data:
            frames = data["frames"]
        if frames.ndim != 5:
            raise ValueError(f"unexpected idle cache shape: {frames.shape}")
        cached_frames = [np.asarray(chunk, dtype=np.uint8) for chunk in frames]
        runtime._IDLE_CACHE_MEMORY[cache_key] = [chunk.copy() for chunk in cached_frames]
        logger.info(
            "[Server] Loaded idle cache from disk: key={} chunks={} path={}",
            cache_key[:12],
            len(cached_frames),
            cache_path,
        )
        return [chunk.copy() for chunk in cached_frames]
    except Exception as exc:
        logger.warning("[Server] Failed to load idle cache {}: {}", cache_path, exc)
        try:
            cache_path.unlink()
        except OSError:
            pass
        return None


def _save_idle_cache_frames(cache_key: str, frames: list[np.ndarray]) -> None:
    if not frames:
        return
    runtime.IDLE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    stacked = np.stack(frames, axis=0).astype(np.uint8, copy=False)
    cache_path = _idle_cache_path(cache_key)
    tmp_path = cache_path.with_suffix(".tmp.npz")
    np.savez_compressed(tmp_path, frames=stacked)
    os.replace(tmp_path, cache_path)
    runtime._IDLE_CACHE_MEMORY[cache_key] = [chunk.copy() for chunk in frames]
    logger.info(
        "[Server] Saved idle cache: key={} chunks={} path={}",
        cache_key[:12],
        len(frames),
        cache_path,
    )


def _build_idle_mouth_mask(frame_height: int, frame_width: int) -> np.ndarray:
    ys = np.linspace(0.0, 1.0, frame_height, dtype=np.float32)[:, None]
    xs = np.linspace(0.0, 1.0, frame_width, dtype=np.float32)[None, :]
    dist = np.sqrt(np.square((xs - 0.50) / 0.14) + np.square((ys - 0.44) / 0.10))
    base_mask = np.clip((1.0 - dist) / 0.28, 0.0, 1.0)
    lower_bias = np.clip((ys - 0.34) / 0.18, 0.0, 1.0)
    mask = np.clip(base_mask * (0.65 + 0.35 * lower_bias), 0.0, 1.0)
    return mask.astype(np.float32)


def _build_idle_eye_mask(frame_height: int, frame_width: int) -> np.ndarray:
    ys = np.linspace(0.0, 1.0, frame_height, dtype=np.float32)[:, None]
    xs = np.linspace(0.0, 1.0, frame_width, dtype=np.float32)[None, :]

    def _eye(center_x: float, center_y: float) -> np.ndarray:
        dist = np.sqrt(np.square((xs - center_x) / 0.095) + np.square((ys - center_y) / 0.050))
        return np.clip((1.0 - dist) / 0.40, 0.0, 1.0)

    lid_bias = np.clip(1.0 - np.abs(ys - 0.28) / 0.12, 0.0, 1.0)
    brow_falloff = np.clip((0.36 - ys) / 0.16, 0.0, 1.0)
    mask = np.maximum(_eye(0.39, 0.28), _eye(0.61, 0.28))
    mask = np.clip(mask * (0.70 + 0.30 * lid_bias) * (0.80 + 0.20 * brow_falloff), 0.0, 1.0)
    return mask.astype(np.float32)


def _prepare_audio_embedding_for_chunk(pipeline, audio_array: np.ndarray) -> torch.Tensor:
    return get_audio_embedding(
        pipeline,
        audio_array,
        runtime.AUDIO_START_IDX,
        runtime.AUDIO_END_IDX,
    )


def _run_pipeline_for_audio_embedding(pipeline, audio_embedding: torch.Tensor) -> torch.Tensor:
    broadcast_cmd(CMD_GENERATE)
    broadcast_audio_embedding(audio_embedding)
    synchronize()
    video = run_pipeline(pipeline, audio_embedding)
    synchronize()
    return video[runtime.MOTION_FRAMES_NUM :]


def _render_video_frames_for_audio_embedding(pipeline, audio_embedding: torch.Tensor) -> np.ndarray:
    video = _run_pipeline_for_audio_embedding(pipeline, audio_embedding)
    return video.cpu().numpy().astype(np.uint8)


def _render_video_frames_for_audio_embedding_local(
    pipeline,
    audio_embedding: torch.Tensor,
) -> np.ndarray:
    video = run_pipeline(pipeline, audio_embedding)
    synchronize()
    return video[runtime.MOTION_FRAMES_NUM :].cpu().numpy().astype(np.uint8)


def _build_idle_audio_chunk(chunk_seed: int) -> np.ndarray:
    rng = np.random.default_rng(chunk_seed)
    t = np.arange(runtime.AUDIO_CHUNK_SAMPLES, dtype=np.float32) / runtime.SAMPLE_RATE
    base = (
        0.55 * np.sin(2 * np.pi * (0.18 + 0.03 * (chunk_seed % 3)) * t + rng.uniform(0, 2 * np.pi))
        + 0.25 * np.sin(2 * np.pi * (0.41 + 0.05 * (chunk_seed % 5)) * t + rng.uniform(0, 2 * np.pi))
    )
    noise = rng.standard_normal(runtime.AUDIO_CHUNK_SAMPLES).astype(np.float32)
    smooth_noise = np.convolve(noise, np.ones(96, dtype=np.float32) / 96.0, mode="same")
    pulse_center = rng.uniform(0.15, 0.85)
    pulse_width = rng.uniform(0.06, 0.12)
    pulse = np.exp(-0.5 * np.square((t / max(t[-1], 1e-6) - pulse_center) / pulse_width))
    envelope = 0.72 + 0.18 * np.sin(2 * np.pi * 0.09 * t + rng.uniform(0, 2 * np.pi))
    chunk = (base + 0.35 * smooth_noise + 0.14 * pulse).astype(np.float32)
    chunk *= envelope.astype(np.float32)
    rms = runtime._chunk_rms(chunk)
    if rms > 1e-6 and runtime.IDLE_CACHE_LEVEL > 0:
        chunk *= runtime.IDLE_CACHE_LEVEL / rms
    else:
        chunk.fill(0.0)
    return np.clip(chunk, -1.0, 1.0)


def _generate_idle_cache_frames(pipeline) -> list[np.ndarray]:
    if runtime.IDLE_CACHE_CHUNKS <= 0:
        return []

    idle_frames: list[np.ndarray] = []
    idle_audio_buffer = np.zeros(runtime.CACHED_AUDIO_SAMPLES, dtype=np.float32)
    idle_write_pos = 0

    logger.info(
        "[Server] Building idle cache: chunks={} level={:.5f} playback={}",
        runtime.IDLE_CACHE_CHUNKS,
        runtime.IDLE_CACHE_LEVEL,
        runtime.IDLE_CACHE_PLAYBACK,
    )

    for idle_idx in range(runtime.IDLE_CACHE_CHUNKS):
        idle_chunk_audio = _build_idle_audio_chunk(runtime.IDLE_RANDOM_SEED + idle_idx * 17)
        idle_write_pos = runtime._append_audio_chunk(
            idle_audio_buffer,
            idle_write_pos,
            idle_chunk_audio,
        )
        idle_audio_array = runtime._linearize_audio_buffer(idle_audio_buffer, idle_write_pos)
        idle_embedding = _prepare_audio_embedding_for_chunk(pipeline, idle_audio_array)
        idle_frames.append(_render_video_frames_for_audio_embedding(pipeline, idle_embedding))

    logger.info("[Server] Idle cache ready with {} chunks.", len(idle_frames))
    return idle_frames


def _generate_idle_cache_frames_local(pipeline) -> list[np.ndarray]:
    if runtime.IDLE_CACHE_CHUNKS <= 0:
        return []

    idle_frames: list[np.ndarray] = []
    idle_audio_buffer = np.zeros(runtime.CACHED_AUDIO_SAMPLES, dtype=np.float32)
    idle_write_pos = 0

    logger.info(
        "[Server] Prebuilding idle cache locally: chunks={} level={:.5f} playback={}",
        runtime.IDLE_CACHE_CHUNKS,
        runtime.IDLE_CACHE_LEVEL,
        runtime.IDLE_CACHE_PLAYBACK,
    )

    for idle_idx in range(runtime.IDLE_CACHE_CHUNKS):
        idle_chunk_audio = _build_idle_audio_chunk(runtime.IDLE_RANDOM_SEED + idle_idx * 17)
        idle_write_pos = runtime._append_audio_chunk(
            idle_audio_buffer,
            idle_write_pos,
            idle_chunk_audio,
        )
        idle_audio_array = runtime._linearize_audio_buffer(idle_audio_buffer, idle_write_pos)
        idle_embedding = _prepare_audio_embedding_for_chunk(pipeline, idle_audio_array)
        idle_frames.append(_render_video_frames_for_audio_embedding_local(pipeline, idle_embedding))

    logger.info("[Server] Local idle cache ready with {} chunks.", len(idle_frames))
    return idle_frames


def _build_idle_refresh_audio_array(
    audio_buffer: np.ndarray,
    write_pos: int,
    refresh_seed: int,
) -> np.ndarray:
    refresh_buffer = audio_buffer.copy()
    refresh_pos = runtime._append_audio_chunk(
        refresh_buffer,
        write_pos,
        _build_idle_audio_chunk(refresh_seed),
    )
    return runtime._linearize_audio_buffer(refresh_buffer, refresh_pos)


def _crossfade_frames(
    previous_frames: np.ndarray | None,
    next_frames: np.ndarray,
    crossfade_frames: int,
) -> np.ndarray:
    if previous_frames is None or crossfade_frames <= 0:
        return next_frames

    blend_frames = min(crossfade_frames, previous_frames.shape[0], next_frames.shape[0])
    if blend_frames <= 0:
        return next_frames

    blended = next_frames.copy()
    alpha = np.linspace(0.0, 1.0, blend_frames + 2, dtype=np.float32)[1:-1][:, None, None, None]
    prev_tail = previous_frames[-blend_frames:].astype(np.float32)
    next_head = next_frames[:blend_frames].astype(np.float32)
    blended[:blend_frames] = np.clip(
        prev_tail * (1.0 - alpha) + next_head * alpha,
        0.0,
        255.0,
    ).astype(np.uint8)
    return blended


def _apply_idle_region_constraints(
    video_frames: np.ndarray,
    reference_frame: np.ndarray | None,
    region_mask: np.ndarray | None,
    previous_idle_frames: np.ndarray | None,
    lock_strength: float,
    temporal_strength: float,
) -> np.ndarray:
    if reference_frame is None or region_mask is None or lock_strength <= 0.0 or video_frames.size == 0:
        return video_frames

    adjusted = video_frames.astype(np.float32)
    ref = reference_frame.astype(np.float32)[None, ...]
    mask = (region_mask * lock_strength)[None, ..., None]
    adjusted = adjusted * (1.0 - mask) + ref * mask

    if previous_idle_frames is not None and temporal_strength > 0.0:
        temporal_mask = (region_mask * temporal_strength)[None, ..., None]
        adjusted = adjusted * (1.0 - temporal_mask) + previous_idle_frames.astype(np.float32) * temporal_mask

    return np.clip(adjusted, 0.0, 255.0).astype(np.uint8)


def _advance_idle_cache_cursor(
    current_index: int,
    current_direction: int,
    cache_size: int,
) -> tuple[int, int]:
    if cache_size <= 1:
        return 0, 1
    if runtime.IDLE_CACHE_PLAYBACK == "loop":
        return (current_index + 1) % cache_size, 1
    if runtime.IDLE_CACHE_PLAYBACK == "random":
        next_index = (current_index + np.random.randint(1, cache_size)) % cache_size
        return next_index, current_direction

    next_index = current_index + current_direction
    next_direction = current_direction
    if next_index >= cache_size:
        next_direction = -1
        next_index = cache_size - 2
    elif next_index < 0:
        next_direction = 1
        next_index = 1
    return next_index, next_direction


def _sample_idle_hold_chunks(idle_rng: np.random.Generator, cache_size: int) -> int:
    if cache_size <= 1:
        return 1
    return int(idle_rng.integers(runtime.IDLE_HOLD_MIN_CHUNKS, runtime.IDLE_HOLD_MAX_CHUNKS + 1))


def _prepare_pipeline_state(
    pipeline,
    image_path: str,
    prompt: str,
    seed: int,
) -> None:
    get_base_data(
        pipeline,
        input_prompt=prompt,
        cond_image=image_path,
        base_seed=seed,
    )
    runtime._reset_audio_embedding_shape_cache()


def _run_startup_warmup(pipeline, image_path: str, prompt: str, seed: int) -> None:
    _prepare_pipeline_state(pipeline, image_path, prompt, seed)
    warmup_buffer = np.zeros(runtime.CACHED_AUDIO_SAMPLES, dtype=np.float32)
    runtime._append_audio_chunk(
        warmup_buffer,
        0,
        np.zeros(runtime.AUDIO_CHUNK_SAMPLES, dtype=np.float32),
    )
    warmup_embedding = _prepare_audio_embedding_for_chunk(pipeline, warmup_buffer)
    run_pipeline(pipeline, warmup_embedding)
    synchronize()
    runtime._reset_audio_embedding_shape_cache()
    logger.info("[Startup] Warmup chunk complete for {}", image_path)


def _run_session_warmup(pipeline) -> None:
    warmup_buffer = np.zeros(runtime.CACHED_AUDIO_SAMPLES, dtype=np.float32)
    runtime._append_audio_chunk(
        warmup_buffer,
        0,
        np.zeros(runtime.AUDIO_CHUNK_SAMPLES, dtype=np.float32),
    )
    warmup_embedding = _prepare_audio_embedding_for_chunk(pipeline, warmup_buffer)
    _run_pipeline_for_audio_embedding(pipeline, warmup_embedding)
    logger.info("Warmup chunk complete")


def _preload_idle_cache_for_ref(
    pipeline,
    image_path: str,
    prompt: str,
    seed: int,
) -> None:
    reference_frame = _load_reference_frame(image_path)
    cache_key = _make_idle_cache_key(reference_frame)
    cached = _load_idle_cache_frames(cache_key)
    if cached is not None:
        logger.info(
            "[Startup] Idle cache already available for {} (key={})",
            image_path,
            cache_key[:12],
        )
        return

    _prepare_pipeline_state(pipeline, image_path, prompt, seed)
    idle_frames = _generate_idle_cache_frames_local(pipeline)
    if runtime.RANK == 0 and idle_frames:
        _save_idle_cache_frames(cache_key, idle_frames)
    _prepare_pipeline_state(pipeline, image_path, prompt, seed)
    logger.info(
        "[Startup] Prebuilt idle cache for {} (key={})",
        image_path,
        cache_key[:12],
    )


__all__ = [
    "_advance_idle_cache_cursor",
    "_apply_idle_region_constraints",
    "_build_idle_audio_chunk",
    "_build_idle_cache_key",
    "_build_idle_eye_mask",
    "_build_idle_mouth_mask",
    "_build_idle_refresh_audio_array",
    "_crossfade_frames",
    "_generate_idle_cache_frames",
    "_generate_idle_cache_frames_local",
    "_idle_cache_path",
    "_load_idle_cache_frames",
    "_load_reference_frame",
    "_make_idle_cache_key",
    "_prepare_audio_embedding_for_chunk",
    "_prepare_pipeline_state",
    "_preload_idle_cache_for_ref",
    "_render_video_frames_for_audio_embedding",
    "_render_video_frames_for_audio_embedding_local",
    "_run_pipeline_for_audio_embedding",
    "_run_session_warmup",
    "_run_startup_warmup",
    "_sample_idle_hold_chunks",
    "_save_idle_cache_frames",
]
