from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

FACE_SIZE = 256
_FACE_CASCADE: Any | None = None
_EYE_CASCADE: Any | None = None


@dataclass
class CropInfo:
    """Stores face crop coordinates for paste-back."""

    x1: int
    y1: int
    x2: int
    y2: int
    original_h: int
    original_w: int


def _get_face_cascade() -> Any:
    global _FACE_CASCADE
    if _FACE_CASCADE is None:
        import cv2

        _FACE_CASCADE = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
    return _FACE_CASCADE


def _get_eye_cascade() -> Any:
    global _EYE_CASCADE
    if _EYE_CASCADE is None:
        import cv2

        path = cv2.data.haarcascades + "haarcascade_eye_tree_eyeglasses.xml"
        cascade = cv2.CascadeClassifier(path)
        if cascade.empty():
            cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")
        _EYE_CASCADE = cascade
    return _EYE_CASCADE


def _clip_box(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    x1 = max(0, min(width - 2, int(round(x1))))
    y1 = max(0, min(height - 2, int(round(y1))))
    x2 = max(x1 + 1, min(width, int(round(x2))))
    y2 = max(y1 + 1, min(height, int(round(y2))))
    return x1, y1, x2, y2


def _make_square_crop(
    *,
    center_x: float,
    center_y: float,
    size: float,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    size = max(8.0, float(size))
    x1 = center_x - size * 0.5
    y1 = center_y - size * 0.5
    x2 = x1 + size
    y2 = y1 + size

    if x1 < 0:
        x2 -= x1
        x1 = 0
    if y1 < 0:
        y2 -= y1
        y1 = 0
    if x2 > width:
        shift = x2 - width
        x1 -= shift
        x2 = width
    if y2 > height:
        shift = y2 - height
        y1 -= shift
        y2 = height

    x1 = max(0.0, x1)
    y1 = max(0.0, y1)
    return _clip_box(x1, y1, x2, y2, width=width, height=height)


def detect_face_box(frame: np.ndarray) -> tuple[int, int, int, int] | None:
    """Detect face bounding box using Haar cascade with heuristic fallback."""
    try:
        import cv2

        h, w = frame.shape[:2]
        cascade = _get_face_cascade()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, 1.1, 4, minSize=(30, 30))

        if len(faces) > 0:
            areas = [fw * fh for (_, _, fw, fh) in faces]
            idx = int(np.argmax(areas))
            fx, fy, fw, fh = faces[idx]
            return (int(fx), int(fy), int(fx + fw), int(fy + fh))

        face_h = int(h * 0.6)
        face_w = int(face_h * 0.85)
        cx, cy = w // 2, int(h * 0.35)
        x1 = max(0, cx - face_w // 2)
        y1 = max(0, cy - face_h // 2)
        x2 = min(w, x1 + face_w)
        y2 = min(h, y1 + face_h)
        return (x1, y1, x2, y2)
    except ImportError:
        h, w = frame.shape[:2]
        size = min(h, w)
        cx, cy = w // 2, h // 2
        half = size // 2
        return (cx - half, cy - half, cx + half, cy + half)


def detect_eye_centers(
    frame: np.ndarray,
    face_box: tuple[int, int, int, int],
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Detect approximate left/right eye centers inside a face box."""
    try:
        import cv2

        x1, y1, x2, y2 = face_box
        face = frame[y1:y2, x1:x2]
        if face.size == 0:
            return None

        h, w = face.shape[:2]
        upper = face[: max(1, int(h * 0.62)), :]
        gray = cv2.cvtColor(upper, cv2.COLOR_BGR2GRAY)
        eyes = _get_eye_cascade().detectMultiScale(gray, 1.1, 4, minSize=(12, 12))
        if len(eyes) < 2:
            return None

        areas = [ew * eh for (_, _, ew, eh) in eyes]
        order = np.argsort(areas)[::-1]
        selected = []
        for idx in order:
            ex, ey, ew, eh = eyes[int(idx)]
            cx = x1 + ex + ew * 0.5
            cy = y1 + ey + eh * 0.5
            selected.append((cx, cy))
            if len(selected) == 2:
                break
        if len(selected) < 2:
            return None
        selected.sort(key=lambda item: item[0])
        return selected[0], selected[1]
    except Exception:
        return None


def estimate_face_crop_box(
    frame: np.ndarray,
    bbox: tuple[int, int, int, int] | None = None,
) -> tuple[int, int, int, int]:
    """Estimate a stable crop box closer to face alignment than simple expansion."""
    h, w = frame.shape[:2]
    if bbox is None:
        bbox = detect_face_box(frame)
    if bbox is None:
        return (0, 0, w, h)

    x1, y1, x2, y2 = bbox
    bw, bh = x2 - x1, y2 - y1
    use_eye_align = os.environ.get("OPENTALKING_MUSETALK_EYE_ALIGN", "0") == "1"
    eye_centers = detect_eye_centers(frame, bbox) if use_eye_align else None

    if eye_centers is not None:
        left_eye, right_eye = eye_centers
        eye_mid_x = (left_eye[0] + right_eye[0]) * 0.5
        eye_mid_y = (left_eye[1] + right_eye[1]) * 0.5
        eye_dist = max(1.0, float(abs(right_eye[0] - left_eye[0])))
        crop_size = max(bw * 1.35, bh * 1.45, eye_dist * 3.15)
        center_x = eye_mid_x
        center_y = eye_mid_y + crop_size * 0.16
        return _make_square_crop(
            center_x=center_x,
            center_y=center_y,
            size=crop_size,
            width=w,
            height=h,
        )

    # Full-body portrait avatars often produce overly loose Haar detections
    # that include hair, neck and shoulders. Tighten the crop so MuseTalk
    # receives a head-dominant region instead of a semi-body patch.
    if h >= int(w * 1.65):
        center_x = x1 + bw * 0.5
        center_y = y1 + bh * 0.38
        crop_size = max(
            bw * 0.98,
            bh * 0.84,
            w * 0.18,
        )
        crop_size = min(crop_size, w * 0.30)
        return _make_square_crop(
            center_x=center_x,
            center_y=center_y,
            size=crop_size,
            width=w,
            height=h,
        )

    if h <= 512 and w <= 512:
        pad_x = bw * 0.12
        pad_top = bh * 0.18
        pad_bottom = bh * 0.28
    else:
        pad_x = bw * 0.18
        pad_top = bh * 0.22
        pad_bottom = bh * 0.34

    return _clip_box(
        x1 - pad_x,
        y1 - pad_top,
        x2 + pad_x,
        y2 + pad_bottom,
        width=w,
        height=h,
    )


def estimate_infer_face_crop_box(
    frame: np.ndarray,
    bbox: tuple[int, int, int, int] | None = None,
) -> tuple[int, int, int, int]:
    """Estimate a tighter head crop for inference while preserving a larger paste box."""
    h, w = frame.shape[:2]
    if bbox is None:
        bbox = detect_face_box(frame)
    if bbox is None:
        return estimate_face_crop_box(frame, bbox)

    x1, y1, x2, y2 = bbox
    bw, bh = x2 - x1, y2 - y1
    portrait_fullbody = h >= int(w * 1.65)

    if portrait_fullbody:
        center_x = x1 + bw * 0.5
        center_y = y1 + bh * 0.48
        crop_size = max(
            bw * 0.86,
            bh * 0.88,
            w * 0.145,
        )
        crop_size = min(crop_size, w * 0.245)
        return _make_square_crop(
            center_x=center_x,
            center_y=center_y,
            size=crop_size,
            width=w,
            height=h,
        )

    return estimate_face_crop_box(frame, bbox)


def smooth_crop_boxes(
    crop_boxes: list[tuple[int, int, int, int]],
    momentum: float = 0.72,
) -> list[tuple[int, int, int, int]]:
    """Smooth a sequence of crop boxes to reduce avatar-frame jitter."""
    if not crop_boxes:
        return []

    boxes = np.asarray(crop_boxes, dtype=np.float32)
    fwd = boxes.copy()
    for i in range(1, len(fwd)):
        fwd[i] = momentum * fwd[i - 1] + (1.0 - momentum) * fwd[i]

    bwd = boxes.copy()
    for i in range(len(bwd) - 2, -1, -1):
        bwd[i] = momentum * bwd[i + 1] + (1.0 - momentum) * bwd[i]

    smoothed = (fwd + bwd) * 0.5
    return [tuple(int(round(v)) for v in row) for row in smoothed]


def crop_face_region_from_box(
    frame: np.ndarray,
    crop_box: tuple[int, int, int, int],
    target_size: int = FACE_SIZE,
) -> tuple[np.ndarray, CropInfo]:
    import cv2

    h, w = frame.shape[:2]
    x1, y1, x2, y2 = _clip_box(*crop_box, width=w, height=h)
    crop = frame[y1:y2, x1:x2]
    face_region = cv2.resize(crop, (target_size, target_size), interpolation=cv2.INTER_LINEAR)
    crop_info = CropInfo(x1=x1, y1=y1, x2=x2, y2=y2, original_h=h, original_w=w)
    return face_region, crop_info


def crop_face_region(
    frame: np.ndarray,
    bbox: tuple[int, int, int, int] | None = None,
    target_size: int = FACE_SIZE,
) -> tuple[np.ndarray, CropInfo]:
    """Crop and resize face region to target_size x target_size."""
    h, w = frame.shape[:2]

    if bbox is None:
        bbox = detect_face_box(frame)
    if bbox is None:
        bbox = (0, 0, w, h)

    crop_box = estimate_face_crop_box(frame, bbox)
    return crop_face_region_from_box(frame, crop_box, target_size=target_size)


def create_lower_face_mask(
    face_region: np.ndarray,
    target_size: int = FACE_SIZE,
) -> np.ndarray:
    """Create a mouth-focused lower-face mask."""
    mask = np.zeros((target_size, target_size), dtype=np.uint8)
    yy, xx = np.ogrid[:target_size, :target_size]
    cx = target_size // 2
    cy = int(target_size * 0.69)
    rx = int(target_size * 0.20)
    ry = int(target_size * 0.12)
    ellipse = ((xx - cx) / max(1, rx)) ** 2 + ((yy - cy) / max(1, ry)) ** 2 <= 1.0
    mask[ellipse] = 255
    return mask


def mask_to_latent_mask(mask: np.ndarray, latent_size: int = 32) -> Any:
    """Downsample binary mask to latent space resolution."""
    import cv2
    import torch

    small = cv2.resize(mask, (latent_size, latent_size), interpolation=cv2.INTER_NEAREST)
    tensor = torch.from_numpy(small.astype(np.float32) / 255.0)
    return tensor.unsqueeze(0).unsqueeze(0)


def paste_face_back(
    full_frame: np.ndarray,
    face_region: np.ndarray,
    crop_info: CropInfo,
    mask: np.ndarray | None = None,
) -> np.ndarray:
    """Paste generated face region back onto the full frame."""
    import cv2

    out = full_frame.copy()
    crop_h = crop_info.y2 - crop_info.y1
    crop_w = crop_info.x2 - crop_info.x1
    resized = cv2.resize(face_region, (crop_w, crop_h), interpolation=cv2.INTER_LINEAR)

    if mask is not None:
        mask_resized = cv2.resize(mask, (crop_w, crop_h), interpolation=cv2.INTER_LINEAR)
        mask_f = cv2.GaussianBlur(mask_resized, (21, 21), 10).astype(np.float32) / 255.0
        if mask_f.ndim == 2:
            mask_f = mask_f[:, :, np.newaxis]

        roi = out[crop_info.y1 : crop_info.y2, crop_info.x1 : crop_info.x2]
        blended = resized.astype(np.float32) * mask_f + roi.astype(np.float32) * (1.0 - mask_f)
        out[crop_info.y1 : crop_info.y2, crop_info.x1 : crop_info.x2] = blended.astype(np.uint8)
    else:
        out[crop_info.y1 : crop_info.y2, crop_info.x1 : crop_info.x2] = resized

    return out


def paste_face_back_with_prepared_mask(
    full_frame: np.ndarray,
    face_region: np.ndarray,
    crop_info: CropInfo,
    mask: np.ndarray,
    mask_crop_box: tuple[int, int, int, int],
) -> np.ndarray:
    """Blend a generated face crop back using prepared assets without crushing motion."""
    import cv2

    out = full_frame.copy()
    x1, y1, x2, y2 = crop_info.x1, crop_info.y1, crop_info.x2, crop_info.y2
    mx1, my1, mx2, my2 = (int(v) for v in mask_crop_box)
    mx1 = max(0, mx1)
    my1 = max(0, my1)
    mx2 = min(out.shape[1], mx2)
    my2 = min(out.shape[0], my2)
    if mx2 <= mx1 or my2 <= my1:
        return paste_face_back(full_frame, face_region, crop_info, None)

    crop_h = max(1, y2 - y1)
    crop_w = max(1, x2 - x1)
    roi = out[my1:my2, mx1:mx2]
    if roi.size == 0:
        return paste_face_back(full_frame, face_region, crop_info, None)

    composed_roi = roi.copy()
    resized_face = cv2.resize(face_region, (crop_w, crop_h), interpolation=cv2.INTER_LINEAR)
    dx1 = max(0, x1 - mx1)
    dy1 = max(0, y1 - my1)
    dx2 = min(composed_roi.shape[1], dx1 + crop_w)
    dy2 = min(composed_roi.shape[0], dy1 + crop_h)
    src_w = dx2 - dx1
    src_h = dy2 - dy1
    if src_w <= 0 or src_h <= 0:
        return paste_face_back(full_frame, face_region, crop_info, None)

    composed_roi[dy1:dy2, dx1:dx2] = resized_face[:src_h, :src_w]

    if mask.shape[:2] != roi.shape[:2]:
        mask = cv2.resize(mask, (roi.shape[1], roi.shape[0]), interpolation=cv2.INTER_LINEAR)

    raw_mask = mask.astype(np.uint8, copy=False)
    prep_mask = cv2.GaussianBlur(raw_mask, (0, 0), 3)
    kernel_size = max(9, int(round(min(roi.shape[0], roi.shape[1]) * 0.08)) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    prep_mask = cv2.dilate(prep_mask, kernel, iterations=1)
    prep_mask_f = prep_mask.astype(np.float32) / 255.0
    prep_mask_f = np.clip((prep_mask_f - 0.08) / 0.92, 0.0, 1.0)

    local_alpha = np.zeros((roi.shape[0], roi.shape[1]), dtype=np.float32)
    yy, xx = np.ogrid[:crop_h, :crop_w]
    cx = crop_w * 0.5
    cy = crop_h * 0.66
    rx = max(8.0, crop_w * 0.34)
    ry = max(8.0, crop_h * 0.24)
    ellipse = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2
    inner = np.clip(1.0 - ellipse, 0.0, 1.0)
    inner = cv2.GaussianBlur((inner * 255.0).astype(np.uint8), (0, 0), 9).astype(np.float32) / 255.0
    local_alpha[dy1:dy2, dx1:dx2] = inner[:src_h, :src_w]

    focus = np.zeros((roi.shape[0], roi.shape[1]), dtype=np.float32)
    yy_focus = np.linspace(0.0, 1.0, crop_h, dtype=np.float32)[:, None]
    focus_crop = np.clip((yy_focus - 0.34) / 0.34, 0.0, 1.0)
    focus_crop = focus_crop * focus_crop * (3.0 - 2.0 * focus_crop)
    focus[dy1:dy2, dx1:dx2] = focus_crop[:src_h, :1]

    prep_mask_f = prep_mask_f * focus
    local_alpha = local_alpha * focus
    alpha = np.maximum(prep_mask_f * 0.85, local_alpha)
    alpha = np.clip(alpha, 0.0, 1.0)
    if alpha.ndim == 2:
        alpha = alpha[:, :, np.newaxis]

    blended = composed_roi.astype(np.float32) * alpha + roi.astype(np.float32) * (1.0 - alpha)
    out[my1:my2, mx1:mx2] = blended.astype(np.uint8)
    return out


def paste_face_back_with_crop_feather(
    full_frame: np.ndarray,
    face_region: np.ndarray,
    crop_info: CropInfo,
    *,
    edge_softness: float = 0.12,
) -> np.ndarray:
    """Paste the full predicted crop back with a soft border feather."""
    import cv2

    out = full_frame.copy()
    crop_h = max(1, crop_info.y2 - crop_info.y1)
    crop_w = max(1, crop_info.x2 - crop_info.x1)
    resized = cv2.resize(face_region, (crop_w, crop_h), interpolation=cv2.INTER_LINEAR)

    roi = out[crop_info.y1 : crop_info.y2, crop_info.x1 : crop_info.x2]
    if roi.size == 0:
        return paste_face_back(full_frame, face_region, crop_info, None)

    edge_px = max(4, int(round(min(crop_h, crop_w) * edge_softness)))
    alpha = np.ones((crop_h, crop_w), dtype=np.float32)
    ramp_x = np.ones((crop_w,), dtype=np.float32)
    ramp_y = np.ones((crop_h,), dtype=np.float32)
    if edge_px > 0:
        edge = np.linspace(0.0, 1.0, num=edge_px, endpoint=False, dtype=np.float32)
        ramp_x[:edge_px] = edge
        ramp_x[-edge_px:] = edge[::-1]
        ramp_y[:edge_px] = edge
        ramp_y[-edge_px:] = edge[::-1]
        alpha = np.minimum.outer(ramp_y, ramp_x)
        alpha = cv2.GaussianBlur(alpha, (0, 0), max(1.0, edge_px * 0.35))
    alpha = np.clip(alpha, 0.0, 1.0)
    alpha = alpha[:, :, np.newaxis]

    blended = resized.astype(np.float32) * alpha + roi.astype(np.float32) * (1.0 - alpha)
    out[crop_info.y1 : crop_info.y2, crop_info.x1 : crop_info.x2] = blended.astype(np.uint8)
    return out
