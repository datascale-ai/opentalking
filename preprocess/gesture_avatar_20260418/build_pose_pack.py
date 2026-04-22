from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

os.environ.setdefault("MEDIAPIPE_DISABLE_GPU", "1")
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

import cv2
import mediapipe as mp
import numpy as np


FACE_LEFT_EYE = [33, 133, 159, 145]
FACE_RIGHT_EYE = [362, 263, 386, 374]
POSE_LEFT_SHOULDER = 11
POSE_RIGHT_SHOULDER = 12

ROW_MAJOR_STATE_NAMES_4 = ["confidence", "explain", "emphasis", "idle"]
ROW_MAJOR_STATE_NAMES_2 = ["hands_down", "subtle_hands"]


@dataclass
class SplitPanel:
    source_path: Path
    panel_index: int
    label: str
    row: int
    col: int
    bounds: tuple[int, int, int, int]
    image: np.ndarray
    landmarks: dict[str, Any]
    anchor: dict[str, float]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def clear_generated_files(path: Path, patterns: list[str]) -> None:
    for pattern in patterns:
        for item in path.glob(pattern):
            if item.is_file():
                item.unlink()


def contiguous_ranges(mask: np.ndarray, *, min_len: int) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    start: int | None = None
    for idx, flag in enumerate(mask.tolist()):
        if flag and start is None:
            start = idx
        elif not flag and start is not None:
            if idx - start >= min_len:
                ranges.append((start, idx))
            start = None
    if start is not None and len(mask) - start >= min_len:
        ranges.append((start, len(mask)))
    return ranges


def find_gutters(gray: np.ndarray, axis: int) -> list[tuple[int, int]]:
    whiteness = (gray >= 245).mean(axis=axis)
    length = gray.shape[1 if axis == 0 else 0]
    min_len = max(4, length // 400)
    raw = contiguous_ranges(whiteness >= 0.98, min_len=min_len)
    filtered: list[tuple[int, int]] = []
    for start, end in raw:
        center = (start + end) / 2.0
        if center < length * 0.12 or center > length * 0.88:
            continue
        filtered.append((start, end))
    return filtered


def build_segments(length: int, gutters: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not gutters:
        return [(0, length)]
    segments: list[tuple[int, int]] = []
    cur = 0
    for start, end in gutters:
        segments.append((cur, start))
        cur = end
    segments.append((cur, length))
    valid = []
    for start, end in segments:
        if end - start >= max(64, length // 8):
            valid.append((start, end))
    return valid


def split_collage(image: np.ndarray) -> list[tuple[int, int, int, int, np.ndarray]]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    x_segments = build_segments(image.shape[1], find_gutters(gray, axis=0))
    y_segments = build_segments(image.shape[0], find_gutters(gray, axis=1))

    panels: list[tuple[int, int, int, int, np.ndarray]] = []
    margin = 2
    for row_idx, (y0, y1) in enumerate(y_segments):
        for col_idx, (x0, x1) in enumerate(x_segments):
            tx0 = min(max(x0 + margin, 0), image.shape[1])
            tx1 = max(min(x1 - margin, image.shape[1]), tx0 + 1)
            ty0 = min(max(y0 + margin, 0), image.shape[0])
            ty1 = max(min(y1 - margin, image.shape[0]), ty0 + 1)
            crop = image[ty0:ty1, tx0:tx1].copy()
            panels.append((row_idx, col_idx, tx0, ty0, crop))
    return panels


def landmark_entries(landmarks: Any, width: int, height: int) -> list[dict[str, float]]:
    if landmarks is None:
        return []
    result: list[dict[str, float]] = []
    for idx, lm in enumerate(landmarks.landmark):
        item = {
            "index": idx,
            "x": float(lm.x * width),
            "y": float(lm.y * height),
            "z": float(lm.z),
            "x_norm": float(lm.x),
            "y_norm": float(lm.y),
        }
        if hasattr(lm, "visibility"):
            item["visibility"] = float(lm.visibility)
        if hasattr(lm, "presence"):
            item["presence"] = float(lm.presence)
        result.append(item)
    return result


def mean_face_points(points: list[dict[str, float]], indices: list[int]) -> tuple[float, float]:
    chosen = [points[i] for i in indices if i < len(points)]
    if not chosen:
        raise ValueError("missing face points")
    return (
        float(np.mean([pt["x"] for pt in chosen])),
        float(np.mean([pt["y"] for pt in chosen])),
    )


def pose_point(points: list[dict[str, float]], index: int) -> tuple[float, float]:
    if index >= len(points):
        raise ValueError("missing pose point")
    return points[index]["x"], points[index]["y"]


def build_anchor(landmarks: dict[str, Any]) -> dict[str, float]:
    face = landmarks["face"]
    pose = landmarks["pose"]
    if not face or not pose:
        raise ValueError("face or pose landmarks missing")

    left_eye = mean_face_points(face, FACE_LEFT_EYE)
    right_eye = mean_face_points(face, FACE_RIGHT_EYE)
    eye_mid = ((left_eye[0] + right_eye[0]) / 2.0, (left_eye[1] + right_eye[1]) / 2.0)

    left_shoulder = pose_point(pose, POSE_LEFT_SHOULDER)
    right_shoulder = pose_point(pose, POSE_RIGHT_SHOULDER)
    shoulder_mid = (
        (left_shoulder[0] + right_shoulder[0]) / 2.0,
        (left_shoulder[1] + right_shoulder[1]) / 2.0,
    )

    left_hip = pose_point(pose, 23)
    right_hip = pose_point(pose, 24)
    hip_mid = (
        (left_hip[0] + right_hip[0]) / 2.0,
        (left_hip[1] + right_hip[1]) / 2.0,
    )

    left_ankle = pose_point(pose, 27)
    right_ankle = pose_point(pose, 28)
    ankle_mid = (
        (left_ankle[0] + right_ankle[0]) / 2.0,
        (left_ankle[1] + right_ankle[1]) / 2.0,
    )

    shoulder_width = max(1.0, float(abs(right_shoulder[0] - left_shoulder[0])))
    eye_to_shoulder = max(1.0, float(abs(shoulder_mid[1] - eye_mid[1])))
    shoulder_to_hip = max(1.0, float(abs(hip_mid[1] - shoulder_mid[1])))
    shoulder_to_ankle = max(1.0, float(abs(ankle_mid[1] - shoulder_mid[1])))
    return {
        "eye_mid_x": float(eye_mid[0]),
        "eye_mid_y": float(eye_mid[1]),
        "shoulder_mid_x": float(shoulder_mid[0]),
        "shoulder_mid_y": float(shoulder_mid[1]),
        "hip_mid_x": float(hip_mid[0]),
        "hip_mid_y": float(hip_mid[1]),
        "ankle_mid_x": float(ankle_mid[0]),
        "ankle_mid_y": float(ankle_mid[1]),
        "shoulder_width": shoulder_width,
        "eye_to_shoulder": eye_to_shoulder,
        "shoulder_to_hip": shoulder_to_hip,
        "shoulder_to_ankle": shoulder_to_ankle,
    }


def extract_landmarks(image: np.ndarray, holistic: Any) -> dict[str, Any]:
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    results = holistic.process(rgb)
    h, w = image.shape[:2]
    return {
        "face": landmark_entries(results.face_landmarks, w, h),
        "pose": landmark_entries(results.pose_landmarks, w, h),
        "left_hand": landmark_entries(results.left_hand_landmarks, w, h),
        "right_hand": landmark_entries(results.right_hand_landmarks, w, h),
    }


def draw_landmarks(image: np.ndarray, holistic: Any) -> np.ndarray:
    drawing_utils = mp.solutions.drawing_utils
    drawing_styles = mp.solutions.drawing_styles
    holistic_mod = mp.solutions.holistic

    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    results = holistic.process(rgb)
    canvas = image.copy()
    if results.face_landmarks:
        drawing_utils.draw_landmarks(
            canvas,
            results.face_landmarks,
            mp.solutions.face_mesh.FACEMESH_CONTOURS,
            landmark_drawing_spec=None,
            connection_drawing_spec=drawing_styles.get_default_face_mesh_contours_style(),
        )
    if results.pose_landmarks:
        drawing_utils.draw_landmarks(
            canvas,
            results.pose_landmarks,
            holistic_mod.POSE_CONNECTIONS,
            landmark_drawing_spec=drawing_styles.get_default_pose_landmarks_style(),
        )
    if results.left_hand_landmarks:
        drawing_utils.draw_landmarks(
            canvas,
            results.left_hand_landmarks,
            holistic_mod.HAND_CONNECTIONS,
            drawing_styles.get_default_hand_landmarks_style(),
            drawing_styles.get_default_hand_connections_style(),
        )
    if results.right_hand_landmarks:
        drawing_utils.draw_landmarks(
            canvas,
            results.right_hand_landmarks,
            holistic_mod.HAND_CONNECTIONS,
            drawing_styles.get_default_hand_landmarks_style(),
            drawing_styles.get_default_hand_connections_style(),
        )
    return canvas


def draw_landmarks_from_entries(image: np.ndarray, landmarks: dict[str, Any]) -> np.ndarray:
    canvas = image.copy()
    colors = {
        "face": (80, 180, 255),
        "pose": (80, 255, 120),
        "left_hand": (255, 120, 80),
        "right_hand": (180, 80, 255),
    }
    skips = {
        "face": 8,
        "pose": 1,
        "left_hand": 1,
        "right_hand": 1,
    }
    for key, points in landmarks.items():
        color = colors[key]
        step = skips[key]
        for idx, item in enumerate(points):
            if idx % step != 0:
                continue
            x = int(round(item["x"]))
            y = int(round(item["y"]))
            if 0 <= x < canvas.shape[1] and 0 <= y < canvas.shape[0]:
                radius = 1 if key == "face" else 3
                cv2.circle(canvas, (x, y), radius, color, -1, lineType=cv2.LINE_AA)
    return canvas


def background_color(image: np.ndarray) -> tuple[int, int, int]:
    top = image[:10, :, :].reshape(-1, 3)
    bottom = image[-10:, :, :].reshape(-1, 3)
    left = image[:, :10, :].reshape(-1, 3)
    right = image[:, -10:, :].reshape(-1, 3)
    border = np.concatenate([top, bottom, left, right], axis=0)
    med = np.median(border, axis=0).astype(np.uint8)
    return int(med[0]), int(med[1]), int(med[2])


def build_contact_sheet(images: list[tuple[str, np.ndarray]], *, columns: int = 3) -> np.ndarray:
    if not images:
        raise ValueError("no images for contact sheet")
    widths = [img.shape[1] for _, img in images]
    heights = [img.shape[0] for _, img in images]
    cell_w = max(widths)
    cell_h = max(heights)
    rows = int(np.ceil(len(images) / columns))
    margin = 16
    sheet = np.full(
        (
            rows * (cell_h + margin) + margin,
            columns * (cell_w + margin) + margin,
            3,
        ),
        238,
        dtype=np.uint8,
    )
    for idx, (label, img) in enumerate(images):
        row = idx // columns
        col = idx % columns
        x0 = margin + col * (cell_w + margin)
        y0 = margin + row * (cell_h + margin)
        sheet[y0:y0 + img.shape[0], x0:x0 + img.shape[1]] = img
        cv2.putText(
            sheet,
            label,
            (x0 + 10, y0 + 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (30, 30, 30),
            2,
            cv2.LINE_AA,
        )
    return sheet


def transform_landmarks(
    landmarks: dict[str, Any],
    *,
    scale: float,
    tx: float,
    ty: float,
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, entries in landmarks.items():
        transformed = []
        for item in entries:
            next_item = dict(item)
            next_item["x"] = float(item["x"] * scale + tx)
            next_item["y"] = float(item["y"] * scale + ty)
            transformed.append(next_item)
        output[key] = transformed
    return output


def largest_subject_bbox(
    image: np.ndarray,
    *,
    threshold: float,
) -> tuple[int, int, int, int] | None:
    bg = np.array(background_color(image), dtype=np.float32)
    dist = np.linalg.norm(image.astype(np.float32) - bg, axis=2)
    mask = (dist >= float(threshold)).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if num_labels <= 1:
        return None
    areas = stats[1:, cv2.CC_STAT_AREA]
    best_idx = int(np.argmax(areas)) + 1
    x = int(stats[best_idx, cv2.CC_STAT_LEFT])
    y = int(stats[best_idx, cv2.CC_STAT_TOP])
    w = int(stats[best_idx, cv2.CC_STAT_WIDTH])
    h = int(stats[best_idx, cv2.CC_STAT_HEIGHT])
    if w <= 0 or h <= 0:
        return None
    return (x, y, x + w, y + h)


def compute_shared_subject_crop(
    images: list[np.ndarray],
    *,
    target_width: int,
    target_height: int,
    threshold: float,
    pad_ratio_x: float = 0.1,
    pad_ratio_y: float = 0.08,
) -> tuple[float, float, float, float] | None:
    boxes = [
        box
        for box in (largest_subject_bbox(image, threshold=threshold) for image in images)
        if box is not None
    ]
    if not boxes:
        return None

    x0 = float(min(box[0] for box in boxes))
    y0 = float(min(box[1] for box in boxes))
    x1 = float(max(box[2] for box in boxes))
    y1 = float(max(box[3] for box in boxes))
    width = max(1.0, x1 - x0)
    height = max(1.0, y1 - y0)
    x0 -= width * pad_ratio_x
    x1 += width * pad_ratio_x
    y0 -= height * pad_ratio_y
    y1 += height * pad_ratio_y

    crop_w = max(1.0, x1 - x0)
    crop_h = max(1.0, y1 - y0)
    target_aspect = float(target_width) / float(target_height)
    crop_aspect = crop_w / crop_h

    if crop_aspect < target_aspect:
        desired_w = crop_h * target_aspect
        expand = (desired_w - crop_w) / 2.0
        x0 -= expand
        x1 += expand
    else:
        desired_h = crop_w / target_aspect
        expand = (desired_h - crop_h) / 2.0
        y0 -= expand
        y1 += expand
    return (x0, y0, x1, y1)


def crop_resize_with_border(
    image: np.ndarray,
    crop_box: tuple[float, float, float, float],
    *,
    target_width: int,
    target_height: int,
) -> tuple[np.ndarray, dict[str, float]]:
    x0, y0, x1, y1 = crop_box
    crop_w = max(1.0, x1 - x0)
    crop_h = max(1.0, y1 - y0)
    matrix = np.array(
        [
            [target_width / crop_w, 0.0, -x0 * target_width / crop_w],
            [0.0, target_height / crop_h, -y0 * target_height / crop_h],
        ],
        dtype=np.float32,
    )
    cropped = cv2.warpAffine(
        image,
        matrix,
        (target_width, target_height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=background_color(image),
    )
    return cropped, {
        "scale_x": float(target_width / crop_w),
        "scale_y": float(target_height / crop_h),
        "crop_x0": float(x0),
        "crop_y0": float(y0),
    }


def transform_landmarks_by_crop(
    landmarks: dict[str, Any],
    crop_meta: dict[str, float],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    scale_x = float(crop_meta["scale_x"])
    scale_y = float(crop_meta["scale_y"])
    crop_x0 = float(crop_meta["crop_x0"])
    crop_y0 = float(crop_meta["crop_y0"])
    for key, entries in landmarks.items():
        transformed = []
        for item in entries:
            next_item = dict(item)
            next_item["x"] = float((item["x"] - crop_x0) * scale_x)
            next_item["y"] = float((item["y"] - crop_y0) * scale_y)
            transformed.append(next_item)
        output[key] = transformed
    return output


def align_to_reference(
    panel: SplitPanel,
    reference: SplitPanel,
    *,
    target_width: int,
    target_height: int,
    scale_mode: str,
) -> tuple[np.ndarray, dict[str, float], dict[str, Any]]:
    metric_map = {
        "eye_shoulder": "eye_to_shoulder",
        "shoulder_hip": "shoulder_to_hip",
        "shoulder_ankle": "shoulder_to_ankle",
    }
    metric = metric_map.get(scale_mode, "eye_to_shoulder")
    ref_dist = reference.anchor[metric]
    cur_dist = panel.anchor[metric]
    scale = ref_dist / max(cur_dist, 1e-6)
    tx = reference.anchor["shoulder_mid_x"] - panel.anchor["shoulder_mid_x"] * scale
    ty = reference.anchor["shoulder_mid_y"] - panel.anchor["shoulder_mid_y"] * scale
    matrix = np.array([[scale, 0.0, tx], [0.0, scale, ty]], dtype=np.float32)
    aligned = cv2.warpAffine(
        panel.image,
        matrix,
        (target_width, target_height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=background_color(panel.image),
    )
    transformed = transform_landmarks(panel.landmarks, scale=scale, tx=tx, ty=ty)
    return aligned, {"scale": float(scale), "tx": float(tx), "ty": float(ty)}, transformed


def panel_labels(count: int) -> list[str]:
    if count == 2:
        return ROW_MAJOR_STATE_NAMES_2
    if count == 4:
        return ROW_MAJOR_STATE_NAMES_4
    return [f"panel_{idx + 1:02d}" for idx in range(count)]


def state_machine_manifest(output_dir: Path, panels: list[dict[str, Any]]) -> dict[str, Any]:
    state_files = {item["label"]: f"aligned/{item['label']}.png" for item in panels}
    return {
        "version": 1,
        "idle_cycle": ["idle", "hands_down", "subtle_hands"],
        "states": {
            "idle": {
                "image": state_files["idle"],
                "fallbacks": [state_files["hands_down"], state_files["subtle_hands"]],
                "trigger": {"default": True},
            },
            "explain": {
                "image": state_files["explain"],
                "trigger": {
                    "keywords": ["怎么", "为什么", "解释", "说明", "介绍", "演示"],
                    "pause_window_ms": 250,
                    "min_energy": 0.28,
                },
            },
            "emphasis": {
                "image": state_files["emphasis"],
                "trigger": {
                    "keywords": ["重点", "注意", "就是", "必须", "关键", "你看"],
                    "min_energy": 0.4,
                    "burst": True,
                },
            },
            "confidence": {
                "image": state_files["confidence"],
                "trigger": {
                    "keywords": ["可以", "当然", "没问题", "确定", "放心"],
                    "min_energy": 0.32,
                },
            },
            "hands_down": {
                "image": state_files["hands_down"],
                "role": "idle_variant",
            },
            "subtle_hands": {
                "image": state_files["subtle_hands"],
                "role": "idle_variant",
            },
        },
        "notes": [
            "Use idle, hands_down, and subtle_hands as the silent loop.",
            "Switch to explain, emphasis, or confidence only on chunk boundaries.",
        ],
    }


def transition_manifest(panels: list[dict[str, Any]]) -> dict[str, Any]:
    states = ["idle", "explain", "emphasis", "confidence", "hands_down", "subtle_hands"]
    transitions = []
    for src in states:
        for dst in states:
            if src == dst:
                continue
            transitions.append(
                {
                    "from": src,
                    "to": dst,
                    "method": "crossfade_position_compensated",
                    "duration_frames": 6 if {src, dst} <= {"idle", "hands_down", "subtle_hands"} else 8,
                    "position_compensation": {
                        "use_eye_and_shoulder_alignment": True,
                        "fallback": "crossfade_only",
                    },
                    "optional_refinement": {
                        "method": "dense_optical_flow",
                        "enabled": False,
                    },
                }
            )
    return {
        "version": 1,
        "default_transition": "crossfade_position_compensated",
        "transitions": transitions,
    }


def build_panels(image_paths: list[Path], output_dir: Path) -> list[SplitPanel]:
    holistic_mod = mp.solutions.holistic
    panels: list[SplitPanel] = []
    with holistic_mod.Holistic(
        static_image_mode=True,
        model_complexity=1,
        refine_face_landmarks=True,
        min_detection_confidence=0.5,
    ) as holistic:
        for source_path in image_paths:
            image = cv2.imread(str(source_path))
            if image is None:
                raise FileNotFoundError(f"failed to read image: {source_path}")
            parts = split_collage(image)
            labels = panel_labels(len(parts))
            for idx, (row, col, x0, y0, crop) in enumerate(parts):
                label = labels[idx]
                raw_path = output_dir / "raw_split" / f"{label}.png"
                cv2.imwrite(str(raw_path), crop)
                landmarks = extract_landmarks(crop, holistic)
                anchor = build_anchor(landmarks)
                panels.append(
                    SplitPanel(
                        source_path=source_path,
                        panel_index=idx,
                        label=label,
                        row=row,
                        col=col,
                        bounds=(x0, y0, x0 + crop.shape[1], y0 + crop.shape[0]),
                        image=crop,
                        landmarks=landmarks,
                        anchor=anchor,
                    )
                )
    return panels


def main() -> None:
    parser = argparse.ArgumentParser(description="Split, align, and landmark gesture poses")
    parser.add_argument(
        "--image",
        action="append",
        dest="images",
        required=True,
        help="Input collage image. Pass twice for both source images.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parent),
        help="Output directory for split images and metadata.",
    )
    parser.add_argument("--target-width", type=int, default=768, help="Aligned output width.")
    parser.add_argument("--target-height", type=int, default=1024, help="Aligned output height.")
    parser.add_argument(
        "--scale-mode",
        choices=["eye_shoulder", "shoulder_hip", "shoulder_ankle"],
        default="shoulder_ankle",
        help="Landmark distance used to normalize person size before cropping.",
    )
    parser.add_argument(
        "--subject-fit-threshold",
        type=float,
        default=30.0,
        help="If > 0, auto-crop around the shared subject bbox before final resize.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    ensure_dir(output_dir / "raw_split")
    ensure_dir(output_dir / "aligned")
    ensure_dir(output_dir / "annotated")
    ensure_dir(output_dir / "landmarks")
    ensure_dir(output_dir / "manifests")
    clear_generated_files(output_dir / "raw_split", ["*.png"])
    clear_generated_files(output_dir / "aligned", ["*.png"])
    clear_generated_files(output_dir / "annotated", ["*.png"])
    clear_generated_files(output_dir / "landmarks", ["*.json"])
    clear_generated_files(output_dir / "manifests", ["*.json", "*.png"])

    image_paths = [Path(item).resolve() for item in args.images]
    panels = build_panels(image_paths, output_dir)
    panel_by_label = {panel.label: panel for panel in panels}
    reference = panel_by_label["idle"]
    target_height = int(args.target_height)
    target_width = int(args.target_width)

    aligned_entries: list[dict[str, Any]] = []
    for panel in panels:
        aligned, matrix, aligned_landmarks = align_to_reference(
            panel,
            reference,
            target_width=target_width,
            target_height=target_height,
            scale_mode=args.scale_mode,
        )
        aligned_entries.append(
            {
                "panel": panel,
                "aligned": aligned,
                "alignment_matrix": matrix,
                "aligned_landmarks": aligned_landmarks,
            }
        )

    shared_crop = None
    if float(args.subject_fit_threshold) > 0.0:
        shared_crop = compute_shared_subject_crop(
            [item["aligned"] for item in aligned_entries],
            target_width=target_width,
            target_height=target_height,
            threshold=float(args.subject_fit_threshold),
        )

    panel_manifest: list[dict[str, Any]] = []
    for item in aligned_entries:
        panel = item["panel"]
        aligned = item["aligned"]
        matrix = item["alignment_matrix"]
        aligned_landmarks = item["aligned_landmarks"]
        crop_meta = None
        if shared_crop is not None:
            aligned, crop_meta = crop_resize_with_border(
                aligned,
                shared_crop,
                target_width=target_width,
                target_height=target_height,
            )
            aligned_landmarks = transform_landmarks_by_crop(aligned_landmarks, crop_meta)
        aligned_path = output_dir / "aligned" / f"{panel.label}.png"
        cv2.imwrite(str(aligned_path), aligned)

        annotated = draw_landmarks_from_entries(aligned, aligned_landmarks)
        cv2.putText(
            annotated,
            panel.label,
            (20, 36),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (30, 30, 30),
            2,
            cv2.LINE_AA,
        )
        cv2.imwrite(str(output_dir / "annotated" / f"{panel.label}.png"), annotated)

        landmark_payload = {
            "label": panel.label,
            "source_path": str(panel.source_path),
            "source_bounds": {
                "x0": panel.bounds[0],
                "y0": panel.bounds[1],
                "x1": panel.bounds[2],
                "y1": panel.bounds[3],
            },
            "alignment": matrix,
            "shared_crop": {
                "x0": shared_crop[0],
                "y0": shared_crop[1],
                "x1": shared_crop[2],
                "y1": shared_crop[3],
            } if shared_crop is not None else None,
            "crop_resize": crop_meta,
            "raw_anchor": panel.anchor,
            "aligned_landmarks": aligned_landmarks,
        }
        (output_dir / "landmarks" / f"{panel.label}.json").write_text(
            json.dumps(landmark_payload, indent=2),
            encoding="utf-8",
        )
        panel_manifest.append(
            {
                "label": panel.label,
                "source_path": str(panel.source_path),
                "row": panel.row,
                "col": panel.col,
                "raw_image": f"raw_split/{panel.label}.png",
                "aligned_image": f"aligned/{panel.label}.png",
                "annotated_image": f"annotated/{panel.label}.png",
                "landmarks": f"landmarks/{panel.label}.json",
                "alignment": matrix,
            }
        )

    (output_dir / "manifests" / "panel_manifest.json").write_text(
        json.dumps({"panels": panel_manifest}, indent=2),
        encoding="utf-8",
    )
    (output_dir / "manifests" / "state_machine.json").write_text(
        json.dumps(state_machine_manifest(output_dir, panel_manifest), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "manifests" / "transition_manifest.json").write_text(
        json.dumps(transition_manifest(panel_manifest), indent=2),
        encoding="utf-8",
    )

    raw_sheet = build_contact_sheet(
        [(panel.label, panel.image) for panel in panels],
        columns=3,
    )
    cv2.imwrite(str(output_dir / "manifests" / "raw_split_overview.png"), raw_sheet)

    aligned_sheet_items = []
    for panel in panels:
        img = cv2.imread(str(output_dir / "aligned" / f"{panel.label}.png"))
        if img is not None:
            aligned_sheet_items.append((panel.label, img))
    aligned_sheet = build_contact_sheet(aligned_sheet_items, columns=3)
    cv2.imwrite(str(output_dir / "manifests" / "aligned_overview.png"), aligned_sheet)


if __name__ == "__main__":
    main()
