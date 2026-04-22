from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Required checkpoint layout under models_dir:
#   musetalk/pytorch_model.bin   -- UNet weights
#   musetalk/musetalk.json       -- UNet config
#   sd-vae-ft-mse/               -- VAE (diffusers format)
#   whisper/tiny.pt              -- Whisper-tiny weights
#   dwpose/dw-ll_ucoco_384.pth  -- DWPose ONNX/PyTorch
#   face-parse-bisenet/79999_iter.pth       -- BiSeNet face parsing
#   face-parse-bisenet/resnet18-5c106cde.pth -- ResNet backbone

_UNET_WEIGHT_NAMES = ("pytorch_model.bin",)
_UNET_CONFIG_NAME = "musetalk.json"
_VAE_DIR_NAME = "sd-vae-ft-mse"
_WHISPER_NAME = "tiny.pt"
_DWPOSE_NAME = "dw-ll_ucoco_384.pth"
_FACE_PARSE_NAME = "79999_iter.pth"


def resolve_musetalk_v15(models_dir: Path) -> dict[str, Path] | None:
    """Resolve all MuseTalk v1.5 checkpoint paths. Returns None if incomplete."""
    musetalk_dir = models_dir / "musetalk"

    # UNet weights
    unet_weights: Path | None = None
    for name in _UNET_WEIGHT_NAMES:
        p = musetalk_dir / name
        if p.is_file():
            unet_weights = p
            break

    # UNet config
    unet_config = musetalk_dir / _UNET_CONFIG_NAME

    # VAE directory
    vae_dir = models_dir / _VAE_DIR_NAME

    # Whisper
    whisper_path = models_dir / "whisper" / _WHISPER_NAME

    # DWPose
    dwpose_path = models_dir / "dwpose" / _DWPOSE_NAME

    # Face parsing
    face_parse_path = models_dir / "face-parse-bisenet" / _FACE_PARSE_NAME

    paths = {
        "unet_weights": unet_weights,
        "unet_config": unet_config,
        "vae_dir": vae_dir,
        "whisper": whisper_path,
        "dwpose": dwpose_path,
        "face_parse": face_parse_path,
    }

    # Check all exist
    for key, p in paths.items():
        if p is None:
            logger.info("MuseTalk v1.5: missing unet weights in %s", musetalk_dir)
            return None
        if key == "vae_dir":
            if not p.is_dir():
                logger.info("MuseTalk v1.5: missing VAE directory %s", p)
                return None
        else:
            if not p.is_file():
                logger.info("MuseTalk v1.5: missing %s at %s", key, p)
                return None

    return paths  # type: ignore[return-value]


def resolve_musetalk_checkpoint(models_dir: Path) -> Path | None:
    """Legacy resolver -- returns any single weight file for backwards compat."""
    for name in ("musetalk.pth", "musetalk.pt", "unet.pth"):
        p = models_dir / name
        if p.is_file():
            return p
    # Also check v1.5 layout
    v15 = resolve_musetalk_v15(models_dir)
    if v15 is not None:
        return v15["unet_weights"]
    return None


def load_musetalk_v15_bundle(paths: dict[str, Path], device: str) -> dict[str, Any]:
    """Load all MuseTalk v1.5 model components onto device.

    Returns dict with keys: unet, vae, whisper_model,
    dwpose_path, face_parse_path, device.
    """
    try:
        import torch
    except ImportError as e:
        raise RuntimeError(
            "MuseTalk v1.5 requires torch. pip install opentalking[torch]"
        ) from e

    bundle: dict[str, Any] = {"device": device}

    # --- VAE ---
    from diffusers import AutoencoderKL

    dtype = torch.float16 if "cuda" in device else torch.float32
    bundle["vae"] = AutoencoderKL.from_pretrained(
        str(paths["vae_dir"]),
        torch_dtype=dtype,
    ).to(device)
    bundle["vae"].requires_grad_(False)
    logger.info("Loaded VAE from %s", paths["vae_dir"])

    # --- UNet ---
    from diffusers import UNet2DConditionModel

    with open(paths["unet_config"], "r") as f:
        unet_config = json.load(f)
    bundle["unet"] = UNet2DConditionModel(**unet_config)
    state_dict = torch.load(
        paths["unet_weights"], map_location="cpu", weights_only=True
    )
    bundle["unet"].load_state_dict(state_dict)
    bundle["unet"] = bundle["unet"].to(device, dtype=dtype)
    bundle["unet"].requires_grad_(False)
    logger.info("Loaded UNet from %s", paths["unet_weights"])

    # --- Whisper-tiny (audio feature encoder) ---
    import whisper

    bundle["whisper_model"] = whisper.load_model(
        str(paths["whisper"]),
        device=device,
        download_root=str(paths["whisper"].parent),
    )
    logger.info("Loaded Whisper-tiny from %s", paths["whisper"])

    # --- DWPose (face landmarks) ---
    bundle["dwpose_path"] = paths["dwpose"]
    logger.info("DWPose checkpoint at %s", paths["dwpose"])

    # --- Face parsing (BiSeNet) ---
    bundle["face_parse_path"] = paths["face_parse"]
    logger.info("Face parsing checkpoint at %s", paths["face_parse"])

    return bundle


def load_musetalk_torch(weights: Path, device: str) -> Any:
    """Legacy single-weight loader for backwards compat."""
    try:
        import torch
    except ImportError as e:
        raise RuntimeError(
            "MuseTalk neural path requires torch. pip install opentalking[torch]"
        ) from e
    _ = torch.load(weights, map_location=device, weights_only=True)
    return {"weights": str(weights), "device": device}
