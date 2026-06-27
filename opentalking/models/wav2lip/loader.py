from __future__ import annotations

# mypy: ignore-errors

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
        models_dir / "wav2lip" / "wav2lip384.pth",
        models_dir / "wav2lip384.pth",
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


def detect_wav2lip_variant(state_dict: dict[str, Any]) -> tuple[str, int]:
    keys = set(state_dict)
    if "sam.sa.conv1.weight" in keys or any(key.startswith("audio_refine.") for key in keys):
        return "wav2lip384", 384
    if any(key.startswith("face_encoder_blocks.7.") for key in keys):
        return "wav2lip256", 256
    return "wav2lip96", 96


def _try_import_torch_npu() -> bool:
    try:
        import torch_npu  # noqa: F401

        return True
    except ImportError:
        return False


def _resolve_torch_device(torch: Any, requested: str) -> str:
    raw = (requested or "auto").strip().lower()
    npu_index = os.environ.get("OPENTALKING_WAV2LIP_NPU_INDEX", "0").strip() or "0"
    if raw in {"", "auto"}:
        if _try_import_torch_npu() and getattr(torch, "npu", None) is not None:
            try:
                if torch.npu.is_available():
                    return f"npu:{npu_index}"
            except Exception:
                pass
        if torch.cuda.is_available():
            return "cuda"
        return "cpu"
    if raw == "npu":
        return f"npu:{npu_index}"
    if raw.startswith("npu"):
        _try_import_torch_npu()
        return raw
    if raw.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError(
            f"CUDA was explicitly requested for Wav2Lip ({requested}), but torch.cuda.is_available() is false"
        )
    return raw


def load_wav2lip_torch(weights: Path, device: str) -> Any:
    try:
        import torch
    except ImportError as e:
        raise RuntimeError("Wav2Lip neural path requires torch. pip install opentalking[torch]") from e
    from opentalking.models.wav2lip.model_defs import Wav2Lip256, Wav2Lip384
    from opentalking.models.wav2lip.network import Wav2Lip

    device = _resolve_torch_device(torch, device)
    map_location = "cpu" if device.startswith("npu") else device
    checkpoint = torch.load(weights, map_location=map_location)
    state_dict = checkpoint.get("state_dict", checkpoint)
    clean_state_dict = {
        key.replace("module.", "", 1): value
        for key, value in state_dict.items()
    }

    variant, input_size = detect_wav2lip_variant(clean_state_dict)
    if variant == "wav2lip384":
        model = Wav2Lip384()
    elif variant == "wav2lip256":
        model = Wav2Lip256()
    else:
        model = Wav2Lip()

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
