"""Pure helpers for idle-clip generation, looping, and mouth stabilisation.

Extracted from synthesis_runner.py to keep the runner focused on orchestration.
None of these functions touch process-global state.
"""
from __future__ import annotations

import numpy as np


def idle_frame_signature(frame: np.ndarray) -> np.ndarray:
    """Downsample frames for loop-point search."""
    arr = np.asarray(frame, dtype=np.float32)
    if arr.ndim == 3 and arr.shape[2] >= 3:
        gray = arr[:, :, 0] * 0.114 + arr[:, :, 1] * 0.587 + arr[:, :, 2] * 0.299
    else:
        gray = arr

    h, w = gray.shape[:2]
    step_y = max(1, h // 24)
    step_x = max(1, w // 24)
    sampled = gray[::step_y, ::step_x]
    return sampled[:24, :24].astype(np.float32, copy=False)


def blend_frames(left: np.ndarray, right: np.ndarray, alpha: float) -> np.ndarray:
    mixed = np.asarray(left, dtype=np.float32) * (1.0 - alpha)
    mixed += np.asarray(right, dtype=np.float32) * alpha
    return np.clip(mixed, 0.0, 255.0).astype(np.uint8)


def motion_score(signatures: list[np.ndarray], start: int, end: int) -> float:
    score = 0.0
    steps = 0
    for idx in range(start, min(end, len(signatures) - 1)):
        score += float(np.mean(np.abs(signatures[idx + 1] - signatures[idx])))
        steps += 1
    return score / max(1, steps)


def optimize_idle_loop(
    frames: list[np.ndarray],
    *,
    crossfade_frames: int,
) -> list[np.ndarray]:
    """Choose a smoother loop segment and soften the loop boundary."""
    if len(frames) < 12:
        return [np.ascontiguousarray(frame) for frame in frames]

    signatures = [idle_frame_signature(frame) for frame in frames]
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
            edge_motion = motion_score(signatures, start, start + compare_span)
            edge_motion += motion_score(
                signatures,
                max(start + 1, end - compare_span),
                end,
            )
            score += edge_motion * 0.35
            if best_score is None or score < best_score:
                best_score = score
                best_start = start
                best_end = end

    segment = [np.ascontiguousarray(frame) for frame in frames[best_start:best_end + 1]]
    overlap = max(2, min(crossfade_frames, len(segment) // 4))
    if len(segment) <= overlap + 2:
        return segment

    smoothed = list(segment[:-overlap])
    tail = segment[-overlap:]
    head = segment[:overlap]
    for idx in range(overlap):
        alpha = (idx + 1) / (overlap + 1)
        smoothed.append(blend_frames(tail[idx], head[idx], alpha))

    smoothed.append(segment[0])
    return smoothed


def build_idle_playback_indices(frame_count: int, mode: str) -> list[int]:
    if frame_count <= 1:
        return [0] if frame_count == 1 else []
    if mode == "pingpong":
        return list(range(frame_count)) + list(range(frame_count - 2, 0, -1))
    return list(range(frame_count))


def build_soft_ellipse_mask(
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


def stabilize_idle_mouth(
    frames: list[np.ndarray],
    reference_frame: np.ndarray | None,
    *,
    strength: float,
    temporal_strength: float,
) -> list[np.ndarray]:
    if not frames or reference_frame is None or strength <= 0.0:
        return [np.ascontiguousarray(frame) for frame in frames]

    ref_arr = np.asarray(reference_frame)
    sample_h, sample_w = frames[0].shape[:2]
    if ref_arr.shape[:2] != (sample_h, sample_w):
        try:
            import cv2

            ref_arr = cv2.resize(ref_arr, (sample_w, sample_h), interpolation=cv2.INTER_AREA)
        except Exception:
            y_idx = np.linspace(0, ref_arr.shape[0] - 1, sample_h).astype(np.int32)
            x_idx = np.linspace(0, ref_arr.shape[1] - 1, sample_w).astype(np.int32)
            ref_arr = ref_arr[y_idx][:, x_idx]

    ref = np.asarray(ref_arr, dtype=np.float32)
    h, w = ref.shape[:2]
    mask = build_soft_ellipse_mask(
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
