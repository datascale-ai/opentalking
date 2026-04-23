from __future__ import annotations

from typing import Any

import numpy as np

from opentalking.core.types.frames import VideoFrameData
from opentalking.models.common.frame_avatar import FrameAvatarState, numpy_bgr_to_videoframe


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
    mouth = np.array([42, 28, 95], dtype=np.uint8)  # BGR dark red
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


def compose_simple(
    state: FrameAvatarState,
    frame_idx: int,
    prediction: Any,
    *,
    timestamp_ms: float,
) -> VideoFrameData:
    """Compose a video frame from avatar state and optional prediction.

    When prediction is None (fallback mode), returns the base avatar frame.
    When prediction is a BGR numpy array (v1.5 inferred face region),
    pastes it back onto the base frame using cached crop info.
    """
    base = state.frames[frame_idx % len(state.frames)]

    if prediction is None:
        return numpy_bgr_to_videoframe(
            _animate_fallback_mouth(base, frame_idx),
            timestamp_ms,
        )

    if isinstance(prediction, np.ndarray) and prediction.ndim == 3:
        # prediction is a generated face region (256, 256, 3) BGR
        crop_infos = state.extra.get("crop_infos")
        masks = state.extra.get("face_masks")

        if crop_infos is not None:
            from opentalking.models.musetalk.face_utils import paste_face_back

            ci = crop_infos[frame_idx % len(crop_infos)]
            mask = masks[frame_idx % len(masks)] if masks else None
            out = paste_face_back(base, prediction, ci, mask)
            return numpy_bgr_to_videoframe(out, timestamp_ms)

        # No crop info cached -- return prediction resized to base frame size
        # This shouldn't happen in normal flow but handles edge cases
        return numpy_bgr_to_videoframe(base.copy(), timestamp_ms)

    # Unknown prediction type -- fallback to base frame
    return numpy_bgr_to_videoframe(base.copy(), timestamp_ms)
