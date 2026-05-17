"""Enhanced Wav2Lip mouth postprocessing utilities."""

from __future__ import annotations

# mypy: ignore-errors

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class BlendConfig:
    mouth_dilation: float = 1.35
    feather: float = 1.15
    lower_lip_expand: float = 0.45
    lower_lip_dynamic_expand: float = 0.25
    corner_expand: float = 0.12
    lower_margin: float = 0.45
    upper_margin: float = 0.85
    horizontal_margin: float = 0.22
    skin_ring_inner: float = 1.12
    skin_ring_outer: float = 1.65
    color_match_strength: float = 0.75
    enable_jaw_motion_blend: bool = False
    jaw_blend_alpha: float = 0.22
    jaw_mask_expand_x: float = 0.25
    jaw_mask_expand_y: float = 0.55
    jaw_mask_offset_y: float = 1.05
    jaw_mask_feather: float = 1.25


@dataclass(frozen=True)
class MouthGeometry:
    center: tuple[int, int]
    rx: int
    ry: int
    outer_lip: tuple[tuple[int, int], ...] = ()
    inner_mouth: tuple[tuple[int, int], ...] = ()

    @classmethod
    def ellipse(cls, *, center: tuple[int, int], rx: int, ry: int) -> "MouthGeometry":
        return cls(center=center, rx=max(1, int(rx)), ry=max(1, int(ry)))


def _odd_kernel(value: float, *, minimum: int = 3) -> int:
    size = max(minimum, int(round(value)))
    return size if size % 2 == 1 else size + 1


def metadata_face_box_to_crop(
    metadata: dict[str, object],
    frame_shape: tuple[int, int],
) -> tuple[int, int, int, int] | None:
    raw = metadata.get("face_box") if isinstance(metadata, dict) else None
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        left, top, right, bottom = (float(item) for item in raw)
    except (TypeError, ValueError):
        return None
    if not (0.0 <= left < right <= 1.0 and 0.0 <= top < bottom <= 1.0):
        return None
    frame_h, frame_w = frame_shape
    x1 = int(round(left * frame_w))
    y1 = int(round(top * frame_h))
    x2 = int(round(right * frame_w))
    y2 = int(round(bottom * frame_h))
    x1 = int(np.clip(x1, 0, max(0, frame_w - 1)))
    y1 = int(np.clip(y1, 0, max(0, frame_h - 1)))
    x2 = int(np.clip(x2, x1 + 1, frame_w))
    y2 = int(np.clip(y2, y1 + 1, frame_h))
    return y1, y2, x1, x2


def select_wav2lip_model_crop(
    *,
    detector_crop: tuple[int, int, int, int],
    metadata_crop: tuple[int, int, int, int] | None,
    use_opentalking_improved: bool,
) -> tuple[int, int, int, int]:
    """Select the crop used as Wav2Lip model input.

    OpenTalking improved postprocessing can use metadata for the final mouth mask, but the
    model input should remain on the legacy detector crop so the enhanced path
    is comparable to basic blending.
    """

    return detector_crop


def metadata_radius_to_input_crop(
    *,
    normalized_radius: float,
    frame_size: int,
    crop_size: int,
    input_size: int,
) -> int:
    if frame_size <= 0 or crop_size <= 0 or input_size <= 0:
        return 1
    radius_in_frame = float(normalized_radius) * float(frame_size)
    radius_in_input = radius_in_frame / float(crop_size) * float(input_size)
    return max(1, int(round(radius_in_input)))


def resize_reference_frame(
    frame: np.ndarray,
    *,
    width: int,
    height: int,
) -> np.ndarray:
    if width <= 0 or height <= 0:
        return frame
    current_h, current_w = frame.shape[:2]
    if current_w == width and current_h == height:
        return frame
    interpolation = cv2.INTER_AREA if width * height < current_w * current_h else cv2.INTER_LINEAR
    return cv2.resize(frame, (width, height), interpolation=interpolation)


def _ellipse_mask(
    shape: tuple[int, int],
    center: tuple[int, int],
    rx: int,
    ry: int,
    *,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
) -> np.ndarray:
    height, width = shape
    mask = np.zeros((height, width), dtype=np.uint8)
    cx = int(np.clip(center[0], 0, max(0, width - 1)))
    cy = int(np.clip(center[1], 0, max(0, height - 1)))
    cv2.ellipse(
        mask,
        (cx, cy),
        (max(1, int(round(rx * scale_x))), max(1, int(round(ry * scale_y)))),
        0,
        0,
        360,
        255,
        -1,
    )
    return mask


def _polygon_mask(shape: tuple[int, int], points: tuple[tuple[int, int], ...]) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    if len(points) < 3:
        return mask
    pts = np.asarray(points, dtype=np.int32).reshape((-1, 1, 2))
    cv2.fillConvexPoly(mask, cv2.convexHull(pts), 255)
    return mask


def _base_lip_mask(shape: tuple[int, int], geometry: MouthGeometry) -> np.ndarray:
    if geometry.outer_lip:
        return _polygon_mask(shape, geometry.outer_lip)
    return _ellipse_mask(shape, geometry.center, geometry.rx, geometry.ry)


def _expand_polygon_mouth_mask(
    base: np.ndarray,
    geometry: MouthGeometry,
    config: BlendConfig,
) -> np.ndarray:
    if not geometry.outer_lip:
        return base
    out = base.copy()
    lower_expand = max(0.0, config.lower_lip_expand) + max(0.0, config.lower_lip_dynamic_expand)
    lower_px = max(0, int(round(geometry.ry * lower_expand)))
    corner_px = max(0, int(round(geometry.rx * max(0.0, config.corner_expand))))
    if lower_px > 0:
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (_odd_kernel(max(1, corner_px), minimum=1), _odd_kernel(lower_px, minimum=1)),
        )
        lower = cv2.dilate(base, kernel, iterations=1)
        limit = min(out.shape[0], int(round(geometry.center[1] + geometry.ry + lower_px + 1)))
        if limit > geometry.center[1]:
            out[geometry.center[1] : limit, :] = np.maximum(
                out[geometry.center[1] : limit, :],
                lower[geometry.center[1] : limit, :],
            )
    if corner_px > 0:
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (_odd_kernel(corner_px, minimum=1), 1),
        )
        corner = cv2.dilate(base, kernel, iterations=1)
        y1 = max(0, int(round(geometry.center[1] - geometry.ry * 0.8)))
        y2 = min(out.shape[0], int(round(geometry.center[1] + geometry.ry * 0.8 + 1)))
        out[y1:y2, :] = np.maximum(out[y1:y2, :], corner[y1:y2, :])
    return out


def _clamp_lower_mouth(
    mask: np.ndarray,
    geometry: MouthGeometry,
    lower_margin: float,
    *,
    lower_extra: float = 0.0,
) -> np.ndarray:
    out = mask.copy()
    lower_limit = int(round(geometry.center[1] + geometry.ry * max(0.0, lower_margin)))
    if geometry.outer_lip:
        lip_bottom = max(point[1] for point in geometry.outer_lip)
        lower_limit = max(lower_limit, int(round(lip_bottom + geometry.ry * max(0.0, lower_extra))))
    if lower_limit + 1 < out.shape[0]:
        out[lower_limit + 1 :, :] = 0
    return out


def _soften(mask: np.ndarray, *, feather_px: float) -> np.ndarray:
    mask_f = mask.astype(np.float32) / 255.0
    blur = _odd_kernel(feather_px, minimum=3)
    mask_f = cv2.GaussianBlur(mask_f, (blur, blur), 0)
    peak = float(mask_f.max())
    if peak > 1e-6:
        mask_f = mask_f / peak
    return np.clip(mask_f, 0.0, 1.0)


def build_mouth_blend_mask(
    shape: tuple[int, int],
    geometry: MouthGeometry,
    config: BlendConfig | None = None,
) -> np.ndarray:
    config = config or BlendConfig()
    base = _base_lip_mask(shape, geometry)
    base = _expand_polygon_mouth_mask(base, geometry, config)
    dilation = max(0.1, config.mouth_dilation)
    kernel_w = max(1, int(round(geometry.rx * max(0.0, config.horizontal_margin) * dilation)))
    kernel_h = max(1, int(round(geometry.ry * max(0.0, config.upper_margin) * dilation)))
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (_odd_kernel(kernel_w, minimum=1), _odd_kernel(kernel_h, minimum=1)),
    )
    expanded = cv2.dilate(base, kernel, iterations=1)
    expanded = _clamp_lower_mouth(
        expanded,
        geometry,
        config.lower_margin,
        lower_extra=config.lower_lip_expand + config.lower_lip_dynamic_expand,
    )
    feather_px = max(1.0, max(geometry.rx, geometry.ry) * max(0.0, config.feather))
    mask = _soften(expanded, feather_px=feather_px)
    mask[mask < 0.02] = 0.0
    return np.expand_dims(mask, axis=2)


def _easy_roi_guard_mask(
    shape: tuple[int, int],
    geometry: MouthGeometry,
    *,
    mask_dilation: float,
    mask_feathering: float,
) -> np.ndarray:
    height, width = shape
    cx, cy = geometry.center
    x_radius = max(geometry.rx * (1.35 + mask_dilation * 0.55), geometry.rx + 12.0)
    upper_radius = max(geometry.ry * (2.0 + mask_dilation * 0.7), geometry.ry + 12.0)
    lower_radius = max(geometry.ry * (3.2 + mask_dilation * 0.9), geometry.ry + 18.0)
    left = max(0, int(np.floor(cx - x_radius)))
    right = min(width, int(np.ceil(cx + x_radius + 1)))
    top = max(0, int(np.floor(cy - upper_radius)))
    bottom = min(height, int(np.ceil(cy + lower_radius + 1)))
    guard = np.zeros(shape, dtype=np.uint8)
    if right <= left or bottom <= top:
        return guard.astype(np.float32)
    guard[top:bottom, left:right] = 255
    feather = max(3.0, min(geometry.rx, geometry.ry) * max(0.0, mask_feathering) * 0.35)
    return _soften(guard, feather_px=feather)


def _ellipse_points(geometry: MouthGeometry, *, samples: int = 20) -> np.ndarray:
    angles = np.linspace(0.0, 2.0 * np.pi, num=max(8, samples), endpoint=False)
    cx, cy = geometry.center
    points = np.stack(
        (
            cx + np.cos(angles) * max(1, geometry.rx),
            cy + np.sin(angles) * max(1, geometry.ry),
        ),
        axis=1,
    )
    return np.rint(points).astype(np.int32)


def _easy_mouth_points(shape: tuple[int, int], geometry: MouthGeometry) -> np.ndarray:
    height, width = shape
    if len(geometry.outer_lip) >= 3:
        points = np.asarray(geometry.outer_lip, dtype=np.int32)
    else:
        points = _ellipse_points(geometry)
    points[:, 0] = np.clip(points[:, 0], 0, max(0, width - 1))
    points[:, 1] = np.clip(points[:, 1], 0, max(0, height - 1))
    return points


def build_easy_mouth_blend_mask(
    shape: tuple[int, int],
    geometry: MouthGeometry,
    *,
    mask_dilation: float = 2.5,
    mask_feathering: float = 2.0,
) -> np.ndarray:
    """Build an Easy-Wav2Lip-style mouth mask.

    Easy-Wav2Lip detects mouth points, fills their convex polygon, dilates by a
    multiple of the mouth bounding box, applies a distance transform threshold,
    then feathers the binary mask. This variant uses precomputed mouth geometry
    instead of dlib landmarks so deployment does not gain a new dependency.
    """

    points = _easy_mouth_points(shape, geometry)
    _, _, w, h = cv2.boundingRect(points)
    mouth_size = max(1, w, h)
    kernel_size = max(1, int(mouth_size * max(0.0, mask_dilation)))
    kernel = np.ones((kernel_size, kernel_size), np.uint8)

    mask = np.zeros(shape, dtype=np.uint8)
    cv2.fillConvexPoly(mask, cv2.convexHull(points.reshape((-1, 1, 2))), 255)
    dilated_mask = cv2.dilate(mask, kernel)
    dist_transform = cv2.distanceTransform(dilated_mask, cv2.DIST_L2, 5)
    if float(dist_transform.max()) > 0.0:
        cv2.normalize(dist_transform, dist_transform, 0, 255, cv2.NORM_MINMAX)
    _, masked_diff = cv2.threshold(dist_transform, 50, 255, cv2.THRESH_BINARY)
    masked_diff = masked_diff.astype(np.uint8)

    if mask_feathering != 0:
        blur = max(1, int(mouth_size * max(0.0, mask_feathering)))
        if blur % 2 == 0:
            blur += 1
        masked_diff = cv2.GaussianBlur(masked_diff, (blur, blur), 0)
    mask_f = masked_diff.astype(np.float32) / 255.0
    guard = _easy_roi_guard_mask(
        shape,
        geometry,
        mask_dilation=mask_dilation,
        mask_feathering=mask_feathering,
    )
    mask_f = np.clip(mask_f * guard, 0.0, 1.0)
    mask_f[mask_f < 0.02] = 0.0
    mask_f[:, 0] = 0.0
    mask_f[:, -1] = 0.0
    mask_f[0, :] = 0.0
    mask_f[-1, :] = 0.0
    peak = float(mask_f.max())
    if peak > 1e-6:
        mask_f = mask_f / peak
    return np.expand_dims(mask_f, axis=2)


def build_jaw_motion_mask(
    shape: tuple[int, int],
    geometry: MouthGeometry,
    mouth_mask: np.ndarray,
    config: BlendConfig | None = None,
) -> np.ndarray:
    """Build a soft, low-alpha motion-transfer mask below and around the mouth."""

    config = config or BlendConfig()
    height, width = shape
    cx, cy = geometry.center
    center = (
        int(np.clip(cx, 0, max(0, width - 1))),
        int(np.clip(cy + geometry.ry * max(0.0, config.jaw_mask_offset_y), 0, max(0, height - 1))),
    )
    jaw = _ellipse_mask(
        shape,
        center,
        geometry.rx,
        geometry.ry,
        scale_x=1.25 + max(0.0, config.jaw_mask_expand_x),
        scale_y=2.25 + max(0.0, config.jaw_mask_expand_y),
    )

    top_limit = max(0, int(round(cy - geometry.ry * 0.25)))
    bottom_limit = min(height, int(round(cy + geometry.ry * (3.6 + max(0.0, config.jaw_mask_expand_y)))))
    if top_limit > 0:
        jaw[:top_limit, :] = 0
    if bottom_limit < height:
        jaw[bottom_limit:, :] = 0

    jaw_f = _soften(jaw, feather_px=max(3.0, geometry.ry * max(0.0, config.jaw_mask_feather)))
    mouth = np.squeeze(np.clip(mouth_mask, 0.0, 1.0))
    jaw_f = jaw_f * np.clip(1.0 - mouth, 0.0, 1.0)
    jaw_f[jaw_f < 0.02] = 0.0
    alpha = float(np.clip(config.jaw_blend_alpha, 0.0, 1.0))
    return np.expand_dims(jaw_f * alpha, axis=2)


def build_skin_ring_mask(
    shape: tuple[int, int],
    geometry: MouthGeometry,
    blend_mask: np.ndarray | None = None,
    config: BlendConfig | None = None,
) -> np.ndarray:
    config = config or BlendConfig()
    outer = _ellipse_mask(
        shape,
        geometry.center,
        geometry.rx,
        geometry.ry,
        scale_x=config.skin_ring_outer,
        scale_y=config.skin_ring_outer,
    ).astype(np.float32)
    inner = _ellipse_mask(
        shape,
        geometry.center,
        geometry.rx,
        geometry.ry,
        scale_x=config.skin_ring_inner,
        scale_y=config.skin_ring_inner,
    ).astype(np.float32)
    ring = np.clip((outer - inner) / 255.0, 0.0, 1.0)
    if blend_mask is not None:
        ring = ring * (1.0 - np.squeeze(np.clip(blend_mask, 0.0, 1.0)))
    ring = _clamp_lower_mouth((ring * 255.0).astype(np.uint8), geometry, config.lower_margin)
    ring = _soften(ring, feather_px=max(3.0, geometry.ry * 0.8))
    return np.expand_dims(ring, axis=2)


def _channel_stats(image: np.ndarray, mask: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    if mask is None:
        return (
            image.mean(axis=(0, 1), keepdims=True),
            image.std(axis=(0, 1), keepdims=True),
        )
    weights = mask.astype(np.float32)
    if weights.ndim == 2:
        weights = weights[:, :, None]
    weights = np.clip(weights, 0.0, 1.0)
    total = float(weights.sum())
    if total <= 1e-3:
        return (
            image.mean(axis=(0, 1), keepdims=True),
            image.std(axis=(0, 1), keepdims=True),
        )
    mean = (image * weights).sum(axis=(0, 1), keepdims=True) / total
    variance = (((image - mean) ** 2) * weights).sum(axis=(0, 1), keepdims=True) / total
    return mean, np.sqrt(np.maximum(variance, 0.0))


def match_patch_color(
    pred: np.ndarray,
    original: np.ndarray,
    *,
    mask: np.ndarray | None = None,
    strength: float = 1.0,
) -> np.ndarray:
    pred_f = pred.astype(np.float32)
    original_f = original.astype(np.float32)
    pred_mean, pred_std = _channel_stats(pred_f, mask)
    orig_mean, orig_std = _channel_stats(original_f, mask)
    matched = (pred_f - pred_mean) * (orig_std / np.maximum(pred_std, 1.0)) + orig_mean
    strength = float(np.clip(strength, 0.0, 1.0))
    corrected = pred_f * (1.0 - strength) + matched * strength
    return np.clip(corrected, 0.0, 255.0).astype(np.uint8)


def blend_mouth_patch(
    pred: np.ndarray,
    original: np.ndarray,
    *,
    geometry: MouthGeometry,
    config: BlendConfig | None = None,
) -> np.ndarray:
    config = config or BlendConfig()
    blend_mask = build_mouth_blend_mask(pred.shape[:2], geometry, config)
    color_mask = build_skin_ring_mask(pred.shape[:2], geometry, blend_mask, config)
    matched = match_patch_color(
        pred,
        original,
        mask=color_mask,
        strength=config.color_match_strength,
    )
    original_f = original.astype(np.float32)
    matched_f = matched.astype(np.float32)
    out = original_f
    if config.enable_jaw_motion_blend and config.jaw_blend_alpha > 0:
        jaw_mask = build_jaw_motion_mask(pred.shape[:2], geometry, blend_mask, config)
        out = matched_f * jaw_mask + out * (1.0 - jaw_mask)
    out = matched_f * blend_mask + out * (1.0 - blend_mask)
    return np.clip(out, 0.0, 255.0).astype(np.uint8)


def blend_mouth_patch_easy(
    pred: np.ndarray,
    original: np.ndarray,
    *,
    geometry: MouthGeometry,
    mask_dilation: float = 2.5,
    mask_feathering: float = 2.0,
    debug_mask: bool = False,
) -> np.ndarray:
    mask = build_easy_mouth_blend_mask(
        pred.shape[:2],
        geometry,
        mask_dilation=mask_dilation,
        mask_feathering=mask_feathering,
    )
    original_base = original
    if debug_mask:
        gray = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
        original_base = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    blended = pred.astype(np.float32) * mask + original_base.astype(np.float32) * (1.0 - mask)
    return np.clip(blended, 0.0, 255.0).astype(np.uint8)


def blend_mouth_patch_basic(pred: np.ndarray, original: np.ndarray) -> np.ndarray:
    height, width = pred.shape[:2]
    mask = np.zeros((height, width), dtype=np.float32)
    x1 = int(width * 0.18)
    x2 = int(width * 0.82)
    y1 = int(height * 0.42)
    y2 = int(height * 0.90)
    mask[y1:y2, x1:x2] = 1.0
    blur_w = max(3, ((width // 7) | 1))
    blur_h = max(3, ((height // 7) | 1))
    mask = np.expand_dims(cv2.GaussianBlur(mask, (blur_w, blur_h), 0), axis=2)
    blended = pred.astype(np.float32) * mask + original.astype(np.float32) * (1.0 - mask)
    return np.clip(blended, 0.0, 255.0).astype(np.uint8)
