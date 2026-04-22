from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def compute_anchor(landmarks: dict) -> tuple[float, float]:
    pose = landmarks.get("pose", [])
    if len(pose) > 12:
        left = pose[11]
        right = pose[12]
        return (
            (left["x"] + right["x"]) / 2.0,
            (left["y"] + right["y"]) / 2.0,
        )
    face = landmarks.get("face", [])
    if face:
        xs = [pt["x"] for pt in face]
        ys = [pt["y"] for pt in face]
        return float(np.mean(xs)), float(np.mean(ys))
    raise ValueError("landmarks missing anchor points")


def shift_image(image: np.ndarray, dx: float, dy: float) -> np.ndarray:
    matrix = np.array([[1.0, 0.0, dx], [0.0, 1.0, dy]], dtype=np.float32)
    border = tuple(int(v) for v in np.median(image[:10, :10], axis=(0, 1)))
    return cv2.warpAffine(
        image,
        matrix,
        (image.shape[1], image.shape[0]),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=border,
    )


def render_transition(
    src_image: np.ndarray,
    dst_image: np.ndarray,
    *,
    src_anchor: tuple[float, float],
    dst_anchor: tuple[float, float],
    frames: int,
) -> list[np.ndarray]:
    dx = src_anchor[0] - dst_anchor[0]
    dy = src_anchor[1] - dst_anchor[1]
    sequence: list[np.ndarray] = []
    for idx in range(frames):
        t = idx / max(frames - 1, 1)
        compensated_dst = shift_image(dst_image, dx * (1.0 - t), dy * (1.0 - t))
        frame = cv2.addWeighted(src_image, 1.0 - t, compensated_dst, t, 0.0)
        sequence.append(frame)
    return sequence


def save_sequence(frames: list[np.ndarray], out_dir: Path, fps: int) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for idx, frame in enumerate(frames):
        cv2.imwrite(str(out_dir / f"{idx:03d}.png"), frame)
    mp4_path = out_dir.with_suffix(".mp4")
    writer = cv2.VideoWriter(
        str(mp4_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (frames[0].shape[1], frames[0].shape[0]),
    )
    for frame in frames:
        writer.write(frame)
    writer.release()


def main() -> None:
    parser = argparse.ArgumentParser(description="Render crossfade plus offset-compensation transition preview")
    parser.add_argument("--src", required=True, help="Source state label")
    parser.add_argument("--dst", required=True, help="Destination state label")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--frames", type=int, default=8)
    parser.add_argument("--fps", type=int, default=25)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    src_image = cv2.imread(str(root / "aligned" / f"{args.src}.png"))
    dst_image = cv2.imread(str(root / "aligned" / f"{args.dst}.png"))
    if src_image is None or dst_image is None:
        raise FileNotFoundError("aligned images not found")

    src_landmarks = load_json(root / "landmarks" / f"{args.src}.json")["aligned_landmarks"]
    dst_landmarks = load_json(root / "landmarks" / f"{args.dst}.json")["aligned_landmarks"]
    frames = render_transition(
        src_image,
        dst_image,
        src_anchor=compute_anchor(src_landmarks),
        dst_anchor=compute_anchor(dst_landmarks),
        frames=args.frames,
    )
    save_sequence(frames, root / "transitions" / f"{args.src}_to_{args.dst}", args.fps)


if __name__ == "__main__":
    main()
