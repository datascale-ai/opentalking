from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


@dataclass
class PreparedMuseTalkAssets:
    coords: list[tuple[int, int, int, int]]
    infer_coords: list[tuple[int, int, int, int]]
    latents: list[Any]
    masks: list[np.ndarray]
    mask_coords: list[tuple[int, int, int, int]]
    root: Path


def _candidate_paths(avatar_path: Path) -> list[dict[str, Path]]:
    return [
        {
            "root": avatar_path / "prepared",
            "coords": avatar_path / "prepared" / "coords.pkl",
            "infer_coords": avatar_path / "prepared" / "infer_coords.pkl",
            "latents": avatar_path / "prepared" / "latents.pt",
            "mask_dir": avatar_path / "prepared" / "mask",
            "mask_coords": avatar_path / "prepared" / "mask_coords.pkl",
        },
        {
            "root": avatar_path,
            "coords": avatar_path / "coords.pkl",
            "infer_coords": avatar_path / "infer_coords.pkl",
            "latents": avatar_path / "latents.pt",
            "mask_dir": avatar_path / "mask",
            "mask_coords": avatar_path / "mask_coords.pkl",
        },
    ]


def _load_pickle(path: Path) -> Any:
    with path.open("rb") as handle:
        return pickle.load(handle)


def _load_masks(mask_dir: Path) -> list[np.ndarray]:
    paths = sorted(
        p for p in mask_dir.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
    )
    masks: list[np.ndarray] = []
    for path in paths:
        img = Image.open(path).convert("L")
        masks.append(np.array(img, dtype=np.uint8))
    return masks


def _normalize_boxes(boxes: Any) -> list[tuple[int, int, int, int]]:
    out: list[tuple[int, int, int, int]] = []
    for box in boxes:
        if box is None:
            continue
        vals = tuple(int(round(float(v))) for v in box[:4])
        out.append(vals)
    return out


def _normalize_latents(raw: Any) -> list[Any]:
    try:
        import torch
    except Exception:
        torch = None  # type: ignore[assignment]

    if torch is not None and isinstance(raw, torch.Tensor):
        if raw.ndim == 4:
            return [raw[i : i + 1].cpu() for i in range(raw.shape[0])]
        if raw.ndim == 5:
            return [raw[i].cpu() for i in range(raw.shape[0])]
    if isinstance(raw, list):
        return raw
    raise TypeError(f"Unsupported latent payload type: {type(raw)!r}")


def resolve_prepared_musetalk_assets(avatar_path: Path) -> PreparedMuseTalkAssets | None:
    avatar_path = avatar_path.resolve()
    for candidate in _candidate_paths(avatar_path):
        coords_path = candidate["coords"]
        infer_coords_path = candidate["infer_coords"]
        latents_path = candidate["latents"]
        mask_dir = candidate["mask_dir"]
        mask_coords_path = candidate["mask_coords"]
        if not (
            coords_path.is_file()
            and latents_path.is_file()
            and mask_dir.is_dir()
            and mask_coords_path.is_file()
        ):
            continue

        try:
            import torch
        except Exception as e:
            raise RuntimeError("Loading prepared MuseTalk assets requires torch") from e

        coords = _normalize_boxes(_load_pickle(coords_path))
        infer_coords = (
            _normalize_boxes(_load_pickle(infer_coords_path))
            if infer_coords_path.is_file()
            else list(coords)
        )
        mask_coords = _normalize_boxes(_load_pickle(mask_coords_path))
        masks = _load_masks(mask_dir)
        latents = _normalize_latents(torch.load(latents_path, map_location="cpu"))
        if not coords or not infer_coords or not masks or not latents or not mask_coords:
            continue
        n = min(len(coords), len(infer_coords), len(mask_coords), len(masks), len(latents))
        return PreparedMuseTalkAssets(
            coords=coords[:n],
            infer_coords=infer_coords[:n],
            latents=latents[:n],
            masks=masks[:n],
            mask_coords=mask_coords[:n],
            root=candidate["root"],
        )
    return None
