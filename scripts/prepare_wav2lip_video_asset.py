#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import cv2
from PIL import Image

from opentalking.avatar.mouth_metadata import (
    _animation_from_landmarks,
    _normalized_face_box,
    detect_mouth_landmarks,
    image_file_sha256,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_frame_metadata(frame_path: Path, frame_bgr) -> dict[str, Any] | None:
    landmarks = detect_mouth_landmarks(frame_bgr)
    if landmarks is None:
        return None
    height, width = frame_bgr.shape[:2]
    face_box = _normalized_face_box(landmarks, width=width, height=height)
    return {
        "mouth_polygon_source": "mediapipe",
        "source_frame_hash": _sha256(frame_path),
        "face_box": face_box,
        "animation": _animation_from_landmarks(landmarks, width=width, height=height),
    }


def prepare_asset(
    *,
    source_video: Path,
    out_dir: Path,
    avatar_id: str,
    name: str,
    target_width: int | None,
    target_height: int | None,
    fps: int | None,
    max_frames: int,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = out_dir / "frames"
    source_dir = out_dir / "source"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True)
    source_dir.mkdir(parents=True, exist_ok=True)
    copied_source = source_dir / source_video.name
    if source_video.resolve() != copied_source.resolve():
        shutil.copy2(source_video, copied_source)

    cap = cv2.VideoCapture(str(source_video))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open source video: {source_video}")
    source_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    effective_fps = int(fps or round(source_fps) or 25)
    source_frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    frames: dict[str, Any] = {}
    missing_frames: list[str] = []
    first_frame_path: Path | None = None
    index = 0
    while index < max_frames:
        ok, frame = cap.read()
        if not ok:
            break
        if target_width and target_height:
            frame = cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_AREA)
        frame_name = f"frame_{index:05d}.jpg"
        frame_path = frames_dir / frame_name
        cv2.imwrite(str(frame_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        if first_frame_path is None:
            first_frame_path = frame_path
        metadata = _write_frame_metadata(frame_path, frame)
        if metadata is None:
            missing_frames.append(frame_name)
        else:
            frames[frame_name] = metadata
        index += 1
    cap.release()
    if first_frame_path is None:
        raise RuntimeError(f"No frames extracted from source video: {source_video}")

    reference = out_dir / "reference.png"
    preview = out_dir / "preview.png"
    first_img = Image.open(first_frame_path).convert("RGB")
    first_img.save(reference, format="PNG")
    first_img.save(preview, format="PNG")
    width, height = first_img.size

    (frames_dir / "mouth_metadata.json").write_text(
        json.dumps(
            {
                "version": 1,
                "frames": frames,
                "missing_frames": missing_frames,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "id": avatar_id,
        "name": name,
        "model_type": "wav2lip",
        "fps": effective_fps,
        "sample_rate": 16000,
        "width": width,
        "height": height,
        "version": "1.0",
        "metadata": {
            "description": "Preprocessed built-in Wav2Lip video avatar asset.",
            "reference_mode": "frames",
            "frame_dir": "frames",
            "frame_metadata": "frames/mouth_metadata.json",
            "preprocessed": True,
            "preprocess_version": 1,
            "source_video": str(copied_source.relative_to(out_dir)),
            "source_fps": source_fps,
            "source_frame_count": source_frame_count,
            "extracted_frame_count": index,
            "source_image_path": "reference.png",
            "source_image_hash": image_file_sha256(reference),
        },
    }
    if frames:
        first_meta = next(iter(frames.values()))
        for key in ("mouth_polygon_source", "face_box", "animation"):
            manifest["metadata"][key] = first_meta.get(key)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a built-in preprocessed Wav2Lip video avatar asset.")
    parser.add_argument("--source-video", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--avatar-id", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--target-width", type=int)
    parser.add_argument("--target-height", type=int)
    parser.add_argument("--fps", type=int)
    parser.add_argument("--max-frames", type=int, default=125)
    args = parser.parse_args()
    prepare_asset(
        source_video=args.source_video,
        out_dir=args.out,
        avatar_id=args.avatar_id,
        name=args.name,
        target_width=args.target_width,
        target_height=args.target_height,
        fps=args.fps,
        max_frames=max(1, args.max_frames),
    )


if __name__ == "__main__":
    main()
