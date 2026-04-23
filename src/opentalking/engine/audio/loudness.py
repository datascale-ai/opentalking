from __future__ import annotations

import math
import os

import numpy as np
import pyloudnorm as pyln
import torch
import torch.nn.functional as F
from PIL import Image


def rgb_to_lab_torch(rgb: torch.Tensor) -> torch.Tensor:
    linear_rgb = torch.where(
        rgb > 0.04045,
        ((rgb + 0.055) / 1.055) ** 2.4,
        rgb / 12.92,
    )
    xyz_from_rgb = torch.tensor(
        [
            [0.4124564, 0.3575761, 0.1804375],
            [0.2126729, 0.7151522, 0.0721750],
            [0.0193339, 0.1191920, 0.9503041],
        ],
        dtype=rgb.dtype,
        device=rgb.device,
    )
    shape = linear_rgb.shape
    xyz = (linear_rgb.reshape(-1, 3) @ xyz_from_rgb.T).reshape(shape)
    xyz_ref = torch.tensor([0.95047, 1.0, 1.08883], dtype=rgb.dtype, device=rgb.device)
    xyz_normalized = xyz / xyz_ref[None, None, None, None, :]

    epsilon = 0.008856
    kappa = 903.3
    xyz_normalized = torch.clamp(xyz_normalized, 1e-8, 1.0)
    f_xyz = torch.where(
        xyz_normalized > epsilon,
        xyz_normalized ** (1 / 3),
        (kappa * xyz_normalized + 16) / 116,
    )
    lab = torch.stack(
        [
            116 * f_xyz[..., 1] - 16,
            500 * (f_xyz[..., 0] - f_xyz[..., 1]),
            200 * (f_xyz[..., 1] - f_xyz[..., 2]),
        ],
        dim=-1,
    )
    return lab


def lab_to_rgb_torch(lab: torch.Tensor) -> torch.Tensor:
    l_chan = lab[..., 0]
    a_chan = lab[..., 1]
    b_chan = lab[..., 2]
    f_y = (l_chan + 16) / 116
    f_x = (a_chan / 500) + f_y
    f_z = f_y - (b_chan / 200)

    epsilon = 0.008856
    kappa = 903.3
    xyz = torch.stack(
        [
            torch.where(f_x**3 > epsilon, f_x**3, (116 * f_x - 16) / kappa),
            torch.where(l_chan > kappa * epsilon, ((l_chan + 16) / 116) ** 3, l_chan / kappa),
            torch.where(f_z**3 > epsilon, f_z**3, (116 * f_z - 16) / kappa),
        ],
        dim=-1,
    )
    xyz_ref = torch.tensor([0.95047, 1.0, 1.08883], dtype=lab.dtype, device=lab.device)
    xyz = xyz * xyz_ref[None, None, None, None, :]
    rgb_from_xyz = torch.tensor(
        [
            [3.2404542, -1.5371385, -0.4985314],
            [-0.9692660, 1.8760108, 0.0415560],
            [0.0556434, -0.2040259, 1.0572252],
        ],
        dtype=lab.dtype,
        device=lab.device,
    )
    linear_rgb = (xyz.reshape(-1, 3) @ rgb_from_xyz.T).reshape(xyz.shape)
    rgb = torch.where(
        linear_rgb > 0.0031308,
        1.055 * (linear_rgb ** (1 / 2.4)) - 0.055,
        12.92 * linear_rgb,
    )
    return torch.clamp(rgb, 0.0, 1.0)


def match_and_blend_colors_torch(
    source_chunk: torch.Tensor,
    reference_image: torch.Tensor,
    strength: float,
) -> torch.Tensor:
    if strength <= 0.0:
        return source_chunk.clone()
    if not 0.0 <= strength <= 1.0:
        raise ValueError(f"strength must be within 0.0-1.0, got {strength}")

    batch_size, channels, _, height, width = source_chunk.shape
    if reference_image.shape != (batch_size, channels, 1, height, width):
        raise ValueError(f"unexpected reference image shape: {reference_image.shape}")

    source_01 = (source_chunk + 1.0) / 2.0
    ref_01 = (reference_image + 1.0) / 2.0
    source_lab = rgb_to_lab_torch(source_01.permute(0, 2, 3, 4, 1))
    ref_lab = rgb_to_lab_torch(ref_01.permute(0, 2, 3, 4, 1))

    ref_mean = ref_lab.mean(dim=[2, 3], keepdim=True)
    ref_std = ref_lab.std(dim=[2, 3], keepdim=True, unbiased=False)
    source_mean = source_lab.mean(dim=[2, 3], keepdim=True)
    source_std = source_lab.std(dim=[2, 3], keepdim=True, unbiased=False)
    source_std = torch.where(source_std < 1e-8, torch.ones_like(source_std), source_std)
    corrected_lab = (source_lab - source_mean) * (ref_std / source_std) + ref_mean
    corrected_rgb = lab_to_rgb_torch(corrected_lab)
    blended = (1 - strength) * source_01.permute(0, 2, 3, 4, 1) + strength * corrected_rgb
    return (blended.permute(0, 4, 1, 2, 3) * 2.0 - 1.0).contiguous().to(source_chunk.dtype)


def _cond_crop_biases() -> tuple[float, float]:
    """Vertical/horizontal crop anchor in [0,1]. 0.5 = center (legacy center_crop).

    FLASHTALK_COND_CROP_VERTICAL_BIAS > 0.5 shifts the crop window downward on the
    resized image (keeps more of the bottom: hands on a desk, etc.).
    """
    def _f(name: str, default: float) -> float:
        raw = os.environ.get(name)
        if raw is None or not raw.strip():
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    v = max(0.0, min(1.0, _f("FLASHTALK_COND_CROP_VERTICAL_BIAS", 0.5)))
    h = max(0.0, min(1.0, _f("FLASHTALK_COND_CROP_HORIZONTAL_BIAS", 0.5)))
    return v, h


def _biased_crop_top_left(
    final_h: int,
    final_w: int,
    target_h: int,
    target_w: int,
    vertical_bias: float,
    horizontal_bias: float,
) -> tuple[int, int]:
    margin_h = final_h - target_h
    margin_w = final_w - target_w
    top = int(round(margin_h * vertical_bias)) if margin_h > 0 else 0
    left = int(round(margin_w * horizontal_bias)) if margin_w > 0 else 0
    top = max(0, min(top, max(margin_h, 0)))
    left = max(0, min(left, max(margin_w, 0)))
    return top, left


def resize_and_centercrop(cond_image, target_size: tuple[int, int]) -> torch.Tensor:
    """Resize (cover) then crop to target_size.

    Crop position is controlled by FLASHTALK_COND_CROP_VERTICAL_BIAS /
    FLASHTALK_COND_CROP_HORIZONTAL_BIAS in [0, 1], default 0.5 (center).
    """
    if isinstance(cond_image, torch.Tensor):
        _, orig_h, orig_w = cond_image.shape
    else:
        orig_h, orig_w = cond_image.height, cond_image.width

    target_h, target_w = target_size
    scale = max(target_h / orig_h, target_w / orig_w)
    final_h = math.ceil(scale * orig_h)
    final_w = math.ceil(scale * orig_w)
    v_bias, h_bias = _cond_crop_biases()
    top, left = _biased_crop_top_left(final_h, final_w, target_h, target_w, v_bias, h_bias)

    if isinstance(cond_image, torch.Tensor):
        if len(cond_image.shape) == 3:
            cond_image = cond_image[None]
        resized = F.interpolate(cond_image, size=(final_h, final_w), mode="nearest").contiguous()
        cropped = resized[:, :, top : top + target_h, left : left + target_w]
        return cropped.squeeze(0)

    resized_image = cond_image.resize((final_w, final_h), resample=Image.BILINEAR)
    resized_tensor = torch.from_numpy(np.array(resized_image))[None, ...].permute(0, 3, 1, 2).contiguous()
    cropped = resized_tensor[:, :, top : top + target_h, left : left + target_w]
    return cropped[:, :, None, :, :]


def loudness_norm(audio_array, sr: int = 16000, lufs: float = -23) -> np.ndarray:
    meter = pyln.Meter(sr)
    loudness = meter.integrated_loudness(audio_array)
    if abs(loudness) > 100:
        return audio_array
    return pyln.normalize.loudness(audio_array, loudness, lufs)
