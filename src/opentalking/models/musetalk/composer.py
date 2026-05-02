from __future__ import annotations

import os
from typing import Any

import numpy as np

from opentalking.core.types.frames import VideoFrameData
from opentalking.models.common.frame_avatar import FrameAvatarState, numpy_bgr_to_videoframe


def resolve_avatar_frame_index(state: FrameAvatarState, frame_idx: int) -> int:
    if not state.frames:
        return 0

    extra = state.extra if isinstance(state.extra, dict) else {}
    if extra.get("rendering_speech") and extra.get("freeze_speaking_to_preview"):
        return int(extra.get("preview_frame_index", 0)) % len(state.frames)
    return frame_idx % len(state.frames)


def _animate_fallback_mouth(base: np.ndarray, frame_idx: int) -> np.ndarray:
    h, w = base.shape[:2]
    if h < 64 or w < 64:
        return base.copy()

    out = base.copy()
    phase = (np.sin(frame_idx * 0.75) + 1.0) / 2.0
    cx = w // 2
    cy = int(h * 0.62)
    rx = max(8, int(w * 0.11))
    ry = max(3, int(h * (0.018 + 0.045 * phase)))

    yy, xx = np.ogrid[:h, :w]
    mask = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1.0
    mouth = np.array([42, 28, 95], dtype=np.uint8)
    out[mask] = (out[mask].astype(np.uint16) * 2 // 5 + mouth.astype(np.uint16) * 3 // 5).astype(
        np.uint8
    )

    if ry > 7:
        tongue_mask = (
            ((xx - cx) / max(4, int(rx * 0.6))) ** 2
            + ((yy - (cy + ry // 3)) / max(3, int(ry * 0.45))) ** 2
            <= 1.0
        )
        tongue = np.array([88, 74, 190], dtype=np.uint8)
        out[tongue_mask & mask] = tongue

    return out


def _boost_visible_mouth_motion(base: np.ndarray, frame_idx: int) -> np.ndarray:
    """Add a clear mouth-open/close cue when neural output is too subtle."""
    h, w = base.shape[:2]
    if h < 64 or w < 64:
        return base.copy()

    out = base.copy()
    phase = (np.sin(frame_idx * 1.35) + 1.0) / 2.0
    cx = w // 2
    cy = int(h * 0.62)
    rx = max(9, int(w * 0.105))
    ry = max(2, int(h * (0.012 + 0.06 * phase)))

    yy, xx = np.ogrid[:h, :w]
    mouth_mask = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1.0
    inner = np.array([20, 12, 45], dtype=np.uint8)
    out[mouth_mask] = (
        out[mouth_mask].astype(np.uint16) * 1 // 4
        + inner.astype(np.uint16) * 3 // 4
    ).astype(np.uint8)

    if ry > 6:
        tooth_mask = (
            (np.abs(xx - cx) < int(rx * 0.72))
            & (np.abs(yy - (cy - ry // 3)) <= max(1, ry // 7))
            & mouth_mask
        )
        out[tooth_mask] = np.array([230, 230, 235], dtype=np.uint8)
    return out


def compose_simple(
    state: FrameAvatarState,
    frame_idx: int,
    prediction: Any,
    *,
    timestamp_ms: float,
) -> VideoFrameData:
    """Compose a video frame from avatar state and optional prediction."""
    avatar_frame_idx = resolve_avatar_frame_index(state, frame_idx)
    extra = state.extra if isinstance(state.extra, dict) else {}
    preview_frame = extra.get("preview_frame")
    if (
        extra.get("rendering_speech")
        and extra.get("freeze_speaking_to_preview")
        and isinstance(preview_frame, np.ndarray)
    ):
        base = preview_frame
    else:
        base = state.frames[avatar_frame_idx]

    if prediction is None:
        return numpy_bgr_to_videoframe(
            _animate_fallback_mouth(base, frame_idx),
            timestamp_ms,
        )

    if isinstance(prediction, np.ndarray) and prediction.ndim == 3:
        crop_infos = state.extra.get("crop_infos")
        prepared_masks = state.extra.get("face_masks")
        prepared_mask_coords = state.extra.get("prepared_mask_coords")

        if crop_infos is not None:
            from opentalking.models.musetalk.face_utils import (
                paste_face_back,
                paste_face_back_with_crop_feather,
                paste_face_back_with_prepared_mask,
            )

            ci = crop_infos[avatar_frame_idx % len(crop_infos)]
            crop_w = ci.x2 - ci.x1
            crop_h = ci.y2 - ci.y1

            if crop_w >= ci.original_w and crop_h >= ci.original_h:
                return numpy_bgr_to_videoframe(prediction, timestamp_ms)

            if prepared_masks is not None and prepared_mask_coords is not None:
                prepared_mode = str(
                    state.extra.get("musetalk_prepared_compose_mode", "")
                ).strip().lower()
                if not prepared_mode:
                    prepared_mode = os.environ.get("OPENTALKING_MUSETALK_PREPARED_COMPOSE", "").strip()
                if not prepared_mode:
                    face_ratio = float(crop_w * crop_h) / float(
                        max(1, state.manifest.width * state.manifest.height)
                    )
                    if state.manifest.height >= int(state.manifest.width * 1.65) and face_ratio <= 0.05:
                        prepared_mode = "raw_crop"
                    else:
                        prepared_mode = "feather_crop"
                if prepared_mode == "raw_crop":
                    out = paste_face_back(base, prediction, ci, None)
                elif prepared_mode == "strict_mask":
                    mask = prepared_masks[avatar_frame_idx % len(prepared_masks)]
                    mask_crop_box = prepared_mask_coords[
                        avatar_frame_idx % len(prepared_mask_coords)
                    ]
                    out = paste_face_back_with_prepared_mask(
                        base,
                        prediction,
                        ci,
                        mask,
                        mask_crop_box,
                    )
                else:
                    out = paste_face_back_with_crop_feather(base, prediction, ci)
                return numpy_bgr_to_videoframe(out, timestamp_ms)

            out = paste_face_back(base, prediction, ci, None)
            return numpy_bgr_to_videoframe(out, timestamp_ms)

        import cv2

        h, w = base.shape[:2]
        resized = cv2.resize(prediction, (w, h), interpolation=cv2.INTER_LINEAR)
        return numpy_bgr_to_videoframe(resized, timestamp_ms)

    return numpy_bgr_to_videoframe(base.copy(), timestamp_ms)
