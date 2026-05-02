from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

FACE_SIZE = 256
LATENT_SIZE = FACE_SIZE // 8


class PositionalEncoding:
    """Sinusoidal positional encoding matching MuseTalk's PositionalEncoding."""

    def __init__(self, d_model: int = 384, max_len: int = 5000) -> None:
        import torch

        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(
            torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model)
        )
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        self.pe = pe.unsqueeze(0)

    def __call__(self, x: Any) -> Any:
        _, seq_len, _ = x.size()
        return x + self.pe[:, :seq_len, :].to(x.device, dtype=x.dtype)


_pe_instance: PositionalEncoding | None = None


def _get_pe() -> PositionalEncoding:
    global _pe_instance
    if _pe_instance is None:
        _pe_instance = PositionalEncoding(d_model=384)
    return _pe_instance


def encode_face_to_latent(
    face_region: np.ndarray,
    vae: Any,
    device: str,
    half_mask: bool = False,
) -> Any:
    """Encode a 256x256 BGR face region to VAE latent space."""
    import torch

    rgb = face_region[:, :, ::-1].copy().astype(np.float32) / 255.0
    tensor = torch.from_numpy(rgb).permute(2, 0, 1)

    if half_mask:
        h = tensor.shape[1]
        tensor[:, h // 2 :, :] = 0.0

    tensor = (tensor - 0.5) / 0.5
    tensor = tensor.unsqueeze(0).to(device=device, dtype=vae.dtype)

    with torch.no_grad():
        latent = vae.encode(tensor).latent_dist.sample()
        latent = latent * vae.config.scaling_factor

    return latent


def get_latents_for_unet(
    face_region: np.ndarray,
    vae: Any,
    device: str,
) -> Any:
    """Prepare 8-channel latent input for UNet, matching MuseTalk original."""
    import torch

    masked_latents = encode_face_to_latent(face_region, vae, device, half_mask=True)
    ref_latents = encode_face_to_latent(face_region, vae, device, half_mask=False)
    return torch.cat([masked_latents, ref_latents], dim=1)


def decode_latent_to_face(
    latent: Any,
    vae: Any,
) -> np.ndarray:
    """Decode a VAE latent back to a 256x256 BGR face region."""
    import torch

    with torch.no_grad():
        latent_scaled = (1.0 / vae.config.scaling_factor) * latent
        decoded = vae.decode(latent_scaled.to(dtype=vae.dtype)).sample

    img = decoded[0].permute(1, 2, 0).cpu().float()
    img = (img / 2.0 + 0.5).clamp(0, 1).numpy()
    img = (img * 255).round().astype(np.uint8)
    return img[:, :, ::-1].copy()


def decode_latents_to_faces(
    latents: Any,
    vae: Any,
) -> list[np.ndarray]:
    """Decode a batch of VAE latents to BGR face regions."""
    import torch

    with torch.no_grad():
        latents_scaled = (1.0 / vae.config.scaling_factor) * latents
        decoded = vae.decode(latents_scaled.to(dtype=vae.dtype)).sample

    imgs = decoded.permute(0, 2, 3, 1).cpu().float()
    imgs = (imgs / 2.0 + 0.5).clamp(0, 1).numpy()
    imgs = (imgs * 255).round().astype(np.uint8)
    return [img[:, :, ::-1].copy() for img in imgs]


def infer_single_step(
    unet: Any,
    vae: Any,
    latent_input: Any,
    audio_feature: Any,
    device: str,
) -> np.ndarray:
    """Run MuseTalk single-step UNet inference."""
    import torch

    with torch.no_grad():
        dtype = unet.dtype
        latent_input = latent_input.to(device=device, dtype=dtype)
        encoder_hidden = audio_feature.to(device=device, dtype=dtype)
        timestep = torch.tensor([0], device=device, dtype=torch.long)

        pred_latents = unet(
            latent_input,
            timestep,
            encoder_hidden_states=encoder_hidden,
            return_dict=False,
        )[0]

    return decode_latent_to_face(pred_latents, vae)


def _audio_features_for_frames(
    audio_features: Any, frame_count: int, device: str, dtype: Any
) -> Any:
    """Return per-frame audio features with PE applied, shaped for batched inference."""
    import torch

    pe = _get_pe()
    features = audio_features.to(device=device, dtype=dtype)

    if features.ndim == 2:
        features = features.unsqueeze(0)

    features = pe(features)

    if features.shape[0] == frame_count:
        return features
    if features.shape[0] != 1 or frame_count <= 1:
        return features.expand(frame_count, -1, -1)

    tokens = int(features.shape[1])
    if tokens <= 1:
        return features.expand(frame_count, -1, -1)

    tokens_per_frame = max(1.0, tokens / frame_count)
    window = max(1, min(tokens, int(round(tokens_per_frame))))
    frame_features = []
    for i in range(frame_count):
        start = int(round(i * tokens_per_frame))
        start = max(0, min(tokens - window, start))
        frame_features.append(features[:, start : start + window, :])

    return torch.cat(frame_features, dim=0)


def infer_batch_frames(
    unet: Any,
    vae: Any,
    unet_latents: list[Any],
    audio_features: Any,
    device: str,
) -> list[np.ndarray]:
    """Run batched inference for multiple frames from one audio chunk."""
    import torch

    if not unet_latents:
        return []

    pe = _get_pe()

    with torch.no_grad():
        dtype = unet.dtype
        latent_batch = torch.cat(unet_latents, dim=0).to(device=device, dtype=dtype)
        encoder_hidden = audio_features.to(device=device, dtype=dtype)
        encoder_hidden = pe(encoder_hidden)

        n_latents = latent_batch.shape[0]
        n_audio = encoder_hidden.shape[0]
        if n_audio < n_latents:
            pad = encoder_hidden[-1:].expand(n_latents - n_audio, -1, -1)
            encoder_hidden = torch.cat([encoder_hidden, pad], dim=0)
        elif n_audio > n_latents:
            encoder_hidden = encoder_hidden[:n_latents]

        timestep = torch.zeros(latent_batch.shape[0], device=device, dtype=torch.long)
        pred_latents = unet(
            latent_batch,
            timestep,
            encoder_hidden_states=encoder_hidden,
            return_dict=False,
        )[0]

    return decode_latents_to_faces(pred_latents, vae)
