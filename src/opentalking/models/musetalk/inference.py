from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# MuseTalk v1.5 face region size
FACE_SIZE = 256
LATENT_SIZE = FACE_SIZE // 8  # VAE downscale factor = 8


def encode_face_to_latent(
    face_region: np.ndarray,
    vae: Any,
    device: str,
) -> Any:
    """Encode a 256x256 BGR face region to VAE latent space.

    Args:
        face_region: BGR uint8 array of shape (256, 256, 3).
        vae: diffusers AutoencoderKL model.
        device: torch device string.

    Returns:
        Latent tensor of shape (1, 4, 32, 32).
    """
    import torch

    # BGR -> RGB, normalize to [-1, 1]
    rgb = face_region[:, :, ::-1].copy().astype(np.float32) / 127.5 - 1.0
    # (H, W, 3) -> (1, 3, H, W)
    tensor = torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0)
    tensor = tensor.to(device=device, dtype=vae.dtype)

    with torch.no_grad():
        latent = vae.encode(tensor).latent_dist.sample()
        latent = latent * vae.config.scaling_factor

    return latent


def decode_latent_to_face(
    latent: Any,
    vae: Any,
) -> np.ndarray:
    """Decode a VAE latent back to a 256x256 BGR face region.

    Args:
        latent: Tensor of shape (1, 4, 32, 32).
        vae: diffusers AutoencoderKL model.

    Returns:
        BGR uint8 array of shape (256, 256, 3).
    """
    import torch

    with torch.no_grad():
        latent_scaled = latent / vae.config.scaling_factor
        decoded = vae.decode(latent_scaled).sample

    # (1, 3, H, W) -> (H, W, 3), denormalize
    img = decoded[0].permute(1, 2, 0).cpu().float().numpy()
    img = ((img + 1.0) * 127.5).clip(0, 255).astype(np.uint8)
    # RGB -> BGR
    return img[:, :, ::-1].copy()


def infer_single_step(
    unet: Any,
    vae: Any,
    face_latent: Any,
    mask_latent: Any,
    audio_feature: Any,
    device: str,
) -> np.ndarray:
    """Run MuseTalk single-step UNet inference.

    The UNet expects 8-channel input: [face_latent(4), masked_face_latent(4)].
    The mask_latent is used to create a masked version of the face latent
    (lower face zeroed out), which is concatenated with the original face latent.
    Audio features drive cross-attention conditioning.

    Args:
        unet: UNet2DConditionModel (in_channels=8).
        vae: AutoencoderKL (for decoding).
        face_latent: (1, 4, 32, 32) encoded face region.
        mask_latent: (1, 1, 32, 32) face mask in latent space.
        audio_feature: (1, T, D) Whisper encoder output for this chunk.
        device: torch device string.

    Returns:
        BGR uint8 face region of shape (256, 256, 3).
    """
    import torch

    with torch.no_grad():
        dtype = unet.dtype

        # Create masked face latent: zero out the lower face region
        # mask_latent: (1, 1, 32, 32), broadcast to (1, 4, 32, 32)
        masked_face = face_latent * mask_latent

        # Concatenate: [original_face_latent, masked_face_latent]
        # (1, 4, 32, 32) + (1, 4, 32, 32) -> (1, 8, 32, 32)
        latent_input = torch.cat([face_latent, masked_face], dim=1).to(dtype=dtype)

        # Audio feature as encoder hidden states for cross-attention
        encoder_hidden = audio_feature.to(device=device, dtype=dtype)

        # Single-step inference (timestep=0 for single-step models)
        timestep = torch.tensor([0], device=device, dtype=torch.long)
        noise_pred = unet(
            latent_input,
            timestep,
            encoder_hidden_states=encoder_hidden,
            return_dict=False,
        )[0]

        # The output is the predicted clean latent (not noise for single-step)
        # Take only the first 4 channels (face latent channels)
        result_latent = noise_pred[:, :4, :, :]

    return decode_latent_to_face(result_latent, vae)


def infer_batch_frames(
    unet: Any,
    vae: Any,
    face_latents: list[Any],
    mask_latents: list[Any],
    audio_features: Any,
    device: str,
) -> list[np.ndarray]:
    """Run inference for multiple frames from one audio chunk.

    Distributes the audio feature across frames and runs single-step
    inference for each.

    Args:
        unet: UNet2DConditionModel.
        vae: AutoencoderKL.
        face_latents: List of (1, 4, 32, 32) latent tensors per frame.
        mask_latents: List of (1, 1, 32, 32) mask tensors per frame.
        audio_features: (1, T, D) Whisper features for this chunk.
        device: torch device string.

    Returns:
        List of BGR uint8 face region arrays, one per frame.
    """
    results: list[np.ndarray] = []

    for face_lat, mask_lat in zip(face_latents, mask_latents):
        face_region = infer_single_step(
            unet=unet,
            vae=vae,
            face_latent=face_lat,
            mask_latent=mask_lat,
            audio_feature=audio_features,
            device=device,
        )
        results.append(face_region)

    return results
