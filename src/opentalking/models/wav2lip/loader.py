from __future__ import annotations

import os
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]


def ensure_wav2lip_imports() -> None:
    return None


def resolve_wav2lip_checkpoint(models_dir: Path) -> Path | None:
    override = os.environ.get("OPENTALKING_WAV2LIP_CHECKPOINT", "").strip()
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_file():
            return candidate.resolve()
    candidates = [
        models_dir / "wav2lip" / "wav2lip256.pth",
        models_dir / "wav2lip256.pth",
        models_dir / "wav2lip" / "wav2lip_gan.pth",
        models_dir / "wav2lip_gan.pth",
        models_dir / "wav2lip" / "wav2lip.pth",
        models_dir / "wav2lip.pth",
        REPO_ROOT / "wav2lip_gan.pth",
        REPO_ROOT / "wav2lip.pth",
    ]
    for p in candidates:
        if p.is_file():
            return p.resolve()
    return None


def resolve_wav2lip_s3fd(models_dir: Path) -> Path | None:
    candidates = [
        models_dir / "wav2lip" / "s3fd.pth",
        models_dir / "s3fd.pth",
    ]
    for p in candidates:
        if p.is_file():
            return p.resolve()
    return None


def load_wav2lip_torch(weights: Path, device: str) -> Any:
    try:
        import torch
    except ImportError as e:
        raise RuntimeError("Wav2Lip neural path requires torch. pip install opentalking[torch]") from e
    from opentalking.models.wav2lip.model_defs import Wav2Lip256
    from opentalking.models.wav2lip.network import Wav2Lip

    if device.startswith("cuda") and not torch.cuda.is_available():
        device = "cpu"
    checkpoint = torch.load(weights, map_location=device)
    state_dict = checkpoint.get("state_dict", checkpoint)
    clean_state_dict = {
        key.replace("module.", "", 1): value
        for key, value in state_dict.items()
    }

    if any(key.startswith("face_encoder_blocks.7.") for key in clean_state_dict):
        model = Wav2Lip256()
        input_size = 256
        variant = "wav2lip256"
    else:
        model = Wav2Lip()
        input_size = 96
        variant = "wav2lip96"

    model.load_state_dict(clean_state_dict)
    model = model.to(device).eval()
    return {
        "weights": str(weights),
        "device": device,
        "model": model,
        "torch": torch,
        "input_size": input_size,
        "variant": variant,
    }
