#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from PIL import Image

from opentalking.avatar.mouth_metadata import image_file_sha256, update_manifest_mouth_metadata


def _resize_image(image: Image.Image, *, max_width: int, max_height: int) -> Image.Image:
    if image.width <= max_width and image.height <= max_height:
        return image.copy()
    fitted = image.copy()
    fitted.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
    return fitted


def prepare_asset(
    *,
    source_image: Path,
    out_dir: Path,
    avatar_id: str,
    name: str,
    max_width: int,
    max_height: int,
    fps: int,
) -> None:
    image = Image.open(source_image)
    image.load()
    image = _resize_image(image.convert("RGB"), max_width=max_width, max_height=max_height)

    if out_dir.exists():
        shutil.rmtree(out_dir)
    frames_dir = out_dir / "frames"
    source_dir = out_dir / "source"
    frames_dir.mkdir(parents=True)
    source_dir.mkdir(parents=True)

    copied_source = source_dir / f"source{source_image.suffix.lower() or '.png'}"
    shutil.copy2(source_image, copied_source)

    reference = out_dir / "reference.png"
    preview = out_dir / "preview.png"
    frame = frames_dir / "frame_00000.png"
    image.save(reference, format="PNG")
    image.save(preview, format="PNG")
    image.save(frame, format="PNG")

    manifest: dict[str, Any] = {
        "id": avatar_id,
        "name": name,
        "model_type": "wav2lip",
        "fps": fps,
        "sample_rate": 16000,
        "width": image.width,
        "height": image.height,
        "version": "1.0",
        "metadata": {
            "description": "Preprocessed built-in Wav2Lip image avatar asset.",
            "idle_mode": "static",
            "reference_mode": "image",
            "frame_dir": "frames",
            "source_image": str(copied_source.relative_to(out_dir)),
            "source_image_path": "reference.png",
            "source_image_hash": image_file_sha256(reference),
            "preprocessed": True,
            "preprocess_version": 1,
        },
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    update_manifest_mouth_metadata(manifest_path, reference, force=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a built-in preprocessed Wav2Lip image avatar asset.")
    parser.add_argument("--source-image", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--avatar-id", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--max-width", type=int, default=720)
    parser.add_argument("--max-height", type=int, default=1280)
    parser.add_argument("--fps", type=int, default=30)
    args = parser.parse_args()
    prepare_asset(
        source_image=args.source_image,
        out_dir=args.out,
        avatar_id=args.avatar_id,
        name=args.name,
        max_width=max(1, args.max_width),
        max_height=max(1, args.max_height),
        fps=max(1, args.fps),
    )


if __name__ == "__main__":
    main()
