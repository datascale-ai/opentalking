from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

FACE_SIZE = 256


@dataclass
class CropInfo:
    """Stores face crop coordinates for paste-back."""

    x1: int
    y1: int
    x2: int
    y2: int
    original_h: int
    original_w: int


def detect_face_box(frame: np.ndarray) -> tuple[int, int, int, int] | None:
    """Detect face bounding box using simple heuristic or cv2 cascade.

    Returns (x1, y1, x2, y2) or None if no face found.
    Uses OpenCV's DNN face detector for reliability.
    """
    try:
        import cv2

        # Use cv2 DNN face detection if available
        h, w = frame.shape[:2]
        # Convert BGR to RGB for face detection
        blob = cv2.dnn.blobFromImage(
            frame, 1.0, (300, 300), (104.0, 177.0, 123.0), swapRB=False
        )

        # Fallback: use center crop heuristic based on typical portrait framing
        # Assume face is roughly centered in the upper 2/3 of the frame
        face_h = int(h * 0.6)
        face_w = int(face_h * 0.85)  # typical face aspect ratio
        cx, cy = w // 2, int(h * 0.35)
        x1 = max(0, cx - face_w // 2)
        y1 = max(0, cy - face_h // 2)
        x2 = min(w, x1 + face_w)
        y2 = min(h, y1 + face_h)
        return (x1, y1, x2, y2)
    except ImportError:
        # No cv2 -- use center crop
        h, w = frame.shape[:2]
        size = min(h, w)
        cx, cy = w // 2, h // 2
        half = size // 2
        return (cx - half, cy - half, cx + half, cy + half)


def crop_face_region(
    frame: np.ndarray,
    bbox: tuple[int, int, int, int] | None = None,
    target_size: int = FACE_SIZE,
) -> tuple[np.ndarray, CropInfo]:
    """Crop and resize face region to target_size x target_size.

    Args:
        frame: BGR uint8 full frame.
        bbox: Optional (x1, y1, x2, y2) face bounding box. Auto-detected if None.
        target_size: Output face region size (default 256).

    Returns:
        (face_region, crop_info) where face_region is BGR uint8 of shape
        (target_size, target_size, 3).
    """
    import cv2

    h, w = frame.shape[:2]

    if bbox is None:
        bbox = detect_face_box(frame)
    if bbox is None:
        # Worst case: use full frame
        bbox = (0, 0, w, h)

    x1, y1, x2, y2 = bbox

    # Expand bbox by 20% for context (MuseTalk needs some context around face)
    bw, bh = x2 - x1, y2 - y1
    expand = 0.2
    x1 = max(0, int(x1 - bw * expand))
    y1 = max(0, int(y1 - bh * expand))
    x2 = min(w, int(x2 + bw * expand))
    y2 = min(h, int(y2 + bh * expand))

    crop = frame[y1:y2, x1:x2]
    face_region = cv2.resize(crop, (target_size, target_size), interpolation=cv2.INTER_LINEAR)

    crop_info = CropInfo(x1=x1, y1=y1, x2=x2, y2=y2, original_h=h, original_w=w)
    return face_region, crop_info


def create_lower_face_mask(
    face_region: np.ndarray,
    target_size: int = FACE_SIZE,
) -> np.ndarray:
    """Create a mask for the lower half of the face (mouth region).

    MuseTalk inpaints the lower face region. This creates a simple
    rectangular mask covering approximately the mouth/chin area.

    Args:
        face_region: BGR uint8 of shape (target_size, target_size, 3).
        target_size: Size of the face region.

    Returns:
        Binary mask uint8 of shape (target_size, target_size), 255 for
        region to inpaint, 0 for region to keep.
    """
    mask = np.zeros((target_size, target_size), dtype=np.uint8)
    # Lower half of face: roughly from 50% to 90% vertically
    # This covers the mouth and chin area
    top = int(target_size * 0.5)
    bottom = int(target_size * 0.9)
    left = int(target_size * 0.15)
    right = int(target_size * 0.85)
    mask[top:bottom, left:right] = 255
    return mask


def mask_to_latent_mask(mask: np.ndarray, latent_size: int = 32) -> Any:
    """Downsample binary mask to latent space resolution.

    Args:
        mask: uint8 mask of shape (256, 256).
        latent_size: Target latent spatial size (default 32 for 8x downsample).

    Returns:
        torch.Tensor of shape (1, 1, latent_size, latent_size).
    """
    import cv2
    import torch

    small = cv2.resize(mask, (latent_size, latent_size), interpolation=cv2.INTER_NEAREST)
    tensor = torch.from_numpy(small.astype(np.float32) / 255.0)
    return tensor.unsqueeze(0).unsqueeze(0)  # (1, 1, H, W)


def paste_face_back(
    full_frame: np.ndarray,
    face_region: np.ndarray,
    crop_info: CropInfo,
    mask: np.ndarray | None = None,
) -> np.ndarray:
    """Paste generated face region back onto the full frame.

    Args:
        full_frame: Original BGR uint8 full frame.
        face_region: Generated BGR uint8 face of shape (256, 256, 3).
        crop_info: Crop coordinates from crop_face_region.
        mask: Optional blending mask. If provided, only masked region is blended.

    Returns:
        BGR uint8 full frame with face composited.
    """
    import cv2

    out = full_frame.copy()
    crop_h = crop_info.y2 - crop_info.y1
    crop_w = crop_info.x2 - crop_info.x1

    # Resize generated face back to crop region size
    resized = cv2.resize(face_region, (crop_w, crop_h), interpolation=cv2.INTER_LINEAR)

    if mask is not None:
        # Resize mask and use it for smooth blending
        mask_resized = cv2.resize(mask, (crop_w, crop_h), interpolation=cv2.INTER_LINEAR)
        # Feather the mask edges for seamless blending
        mask_f = cv2.GaussianBlur(mask_resized, (21, 21), 10).astype(np.float32) / 255.0
        if mask_f.ndim == 2:
            mask_f = mask_f[:, :, np.newaxis]

        roi = out[crop_info.y1 : crop_info.y2, crop_info.x1 : crop_info.x2]
        blended = (resized.astype(np.float32) * mask_f + roi.astype(np.float32) * (1.0 - mask_f))
        out[crop_info.y1 : crop_info.y2, crop_info.x1 : crop_info.x2] = blended.astype(np.uint8)
    else:
        out[crop_info.y1 : crop_info.y2, crop_info.x1 : crop_info.x2] = resized

    return out
