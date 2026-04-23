from __future__ import annotations

from pathlib import Path
from typing import Any


def resolve_wav2lip_checkpoint(models_dir: Path) -> Path | None:
    for name in ("wav2lip.pth", "wav2lip_gan.pth"):
        p = models_dir / name
        if p.is_file():
            return p
    return None


def load_wav2lip_torch(weights: Path, device: str) -> Any:
    try:
        import torch
    except ImportError as e:
        raise RuntimeError("Wav2Lip neural path requires torch. pip install opentalking[torch]") from e
    _ = torch.load(weights, map_location=device)
    return {"weights": str(weights), "device": device}
