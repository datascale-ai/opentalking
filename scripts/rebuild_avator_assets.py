from __future__ import annotations

import argparse
import json
import pickle
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np


def _bootstrap_local_paths(root: Path) -> None:
    sys.path[:0] = [str(root), str(root / "src")]


ROOT = Path(__file__).resolve().parents[1]
_bootstrap_local_paths(ROOT)

from opentalking.models.musetalk.face_utils import (  # noqa: E402
    create_lower_face_mask,
    detect_face_box,
    estimate_face_crop_box,
    estimate_infer_face_crop_box,
    smooth_crop_boxes,
    crop_face_region_from_box,
)
from opentalking.models.musetalk.inference import get_latents_for_unet  # noqa: E402
from opentalking.models.musetalk.loader import (  # noqa: E402
    load_musetalk_v15_bundle,
    resolve_musetalk_v15,
)


def _clip_box(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    x1 = max(0, min(width - 2, int(round(x1))))
    y1 = max(0, min(height - 2, int(round(y1))))
    x2 = max(x1 + 1, min(width, int(round(x2))))
    y2 = max(y1 + 1, min(height, int(round(y2))))
    return x1, y1, x2, y2


def _median_box(boxes: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    arr = np.asarray(boxes, dtype=np.float32)
    return tuple(int(round(float(np.median(arr[:, i])))) for i in range(4))


def _expand_box(
    box: tuple[int, int, int, int],
    *,
    width: int,
    height: int,
    pad_x_ratio: float,
    pad_top_ratio: float,
    pad_bottom_ratio: float,
) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    bw = x2 - x1
    bh = y2 - y1
    return _clip_box(
        x1 - bw * pad_x_ratio,
        y1 - bh * pad_top_ratio,
        x2 + bw * pad_x_ratio,
        y2 + bh * pad_bottom_ratio,
        width=width,
        height=height,
    )


def _square_box(
    box: tuple[int, int, int, int],
    *,
    width: int,
    height: int,
    scale: float,
    center_y_bias: float = 0.0,
) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    bw = x2 - x1
    bh = y2 - y1
    size = max(bw, bh) * scale
    cx = (x1 + x2) * 0.5
    cy = (y1 + y2) * 0.5 + bh * center_y_bias
    half = size * 0.5
    return _clip_box(cx - half, cy - half, cx + half, cy + half, width=width, height=height)


def _load_video_frames(video_path: Path) -> tuple[list[np.ndarray], float]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open video: {video_path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    frames: list[np.ndarray] = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(frame)
    cap.release()

    if not frames:
        raise RuntimeError(f"No frames decoded from {video_path}")
    if fps <= 0.0:
        fps = 30.0
    return frames, fps


def _resolve_boxes(
    frames: list[np.ndarray],
) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
    raw_crop_boxes: list[tuple[int, int, int, int]] = []
    raw_infer_boxes: list[tuple[int, int, int, int]] = []
    for frame in frames:
        bbox = detect_face_box(frame)
        raw_crop_boxes.append(estimate_face_crop_box(frame, bbox))
        raw_infer_boxes.append(estimate_infer_face_crop_box(frame, bbox))

    smooth_crop = smooth_crop_boxes(raw_crop_boxes)
    smooth_infer = smooth_crop_boxes(raw_infer_boxes)

    crop_box = _median_box(smooth_crop)
    infer_box = _median_box(smooth_infer)
    return crop_box, infer_box


def _ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _write_frames(out_dir: Path, frames: list[np.ndarray]) -> None:
    _ensure_clean_dir(out_dir)
    for idx, frame in enumerate(frames):
        cv2.imwrite(str(out_dir / f"frame_{idx:05d}.png"), frame)


def _build_musetalk_prepared(
    frames: list[np.ndarray],
    *,
    crop_box: tuple[int, int, int, int],
    infer_box: tuple[int, int, int, int],
    prepared_dir: Path,
    models_dir: Path,
    device: str,
    source_video: Path,
    source_fps: float,
) -> None:
    try:
        import torch
    except Exception as exc:  # pragma: no cover - environment issue
        raise RuntimeError("Generating prepared MuseTalk assets requires torch") from exc

    paths = resolve_musetalk_v15(models_dir)
    if paths is None:
        raise RuntimeError(f"MuseTalk v1.5 checkpoints not found under {models_dir}")

    bundle = load_musetalk_v15_bundle(paths, device=device)
    vae = bundle["vae"]

    _ensure_clean_dir(prepared_dir)
    mask_dir = prepared_dir / "mask"
    mask_dir.mkdir(parents=True, exist_ok=True)

    h, w = frames[0].shape[:2]
    mask_box = _square_box(
        crop_box,
        width=w,
        height=h,
        scale=2.0,
        center_y_bias=0.05,
    )

    coords = [crop_box for _ in frames]
    infer_coords = [infer_box for _ in frames]
    mask_coords = [mask_box for _ in frames]
    latents = []

    for idx, frame in enumerate(frames):
        face_region, _ = crop_face_region_from_box(frame, infer_box)
        mask = create_lower_face_mask(face_region)
        latent = get_latents_for_unet(face_region, vae, bundle["device"]).cpu()
        latents.append(latent)
        cv2.imwrite(str(mask_dir / f"{idx:08d}.png"), mask)

    with (prepared_dir / "coords.pkl").open("wb") as handle:
        pickle.dump(coords, handle)
    with (prepared_dir / "infer_coords.pkl").open("wb") as handle:
        pickle.dump(infer_coords, handle)
    with (prepared_dir / "mask_coords.pkl").open("wb") as handle:
        pickle.dump(mask_coords, handle)
    torch.save(latents, prepared_dir / "latents.pt")
    (prepared_dir / "manifest.source.json").write_text(
        json.dumps(
            {
                "source_video": str(source_video),
                "source_fps": source_fps,
                "frame_count": len(frames),
                "crop_box": list(crop_box),
                "infer_box": list(infer_box),
                "mask_box": list(mask_box),
                "stabilized_non_face_region": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild musetalk_new and wav2lip_new assets from avator.mp4."
    )
    parser.add_argument(
        "--video",
        type=Path,
        default=ROOT / "avator.mp4",
    )
    parser.add_argument(
        "--musetalk-avatar",
        type=Path,
        default=ROOT / "examples" / "avatars" / "musetalk_new",
    )
    parser.add_argument(
        "--wav2lip-avatar",
        type=Path,
        default=ROOT / "examples" / "avatars" / "wav2lip_new",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=ROOT / "models",
    )
    parser.add_argument(
        "--device",
        default="cuda",
    )
    args = parser.parse_args()

    frames, source_fps = _load_video_frames(args.video)
    crop_box, infer_box = _resolve_boxes(frames)

    _write_frames(args.musetalk_avatar / "full_frames", frames)
    _write_frames(args.wav2lip_avatar / "frames", frames)
    cv2.imwrite(str(args.musetalk_avatar / "preview.png"), frames[0])
    cv2.imwrite(str(args.wav2lip_avatar / "preview.png"), frames[0])

    _build_musetalk_prepared(
        frames,
        crop_box=crop_box,
        infer_box=infer_box,
        prepared_dir=args.musetalk_avatar / "prepared",
        models_dir=args.models_dir,
        device=args.device,
        source_video=args.video,
        source_fps=source_fps,
    )

    print(
        json.dumps(
            {
                "video": str(args.video),
                "source_fps": source_fps,
                "frame_count": len(frames),
                "crop_box": crop_box,
                "infer_box": infer_box,
                "musetalk_avatar": str(args.musetalk_avatar),
                "wav2lip_avatar": str(args.wav2lip_avatar),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
