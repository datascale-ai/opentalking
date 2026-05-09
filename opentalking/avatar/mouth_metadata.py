from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

import cv2


@dataclass(frozen=True)
class AvatarMouthLandmarks:
    mouth_center: tuple[int, int]
    mouth_rx: int
    mouth_ry: int
    outer_lip: tuple[tuple[int, int], ...] = ()
    inner_mouth: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class MouthMetadataUpdate:
    updated: bool
    image_hash: str
    landmarks: AvatarMouthLandmarks | None


def image_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _round_ratio(value: float) -> float:
    return round(float(value), 5)


def _normalized_points(points: tuple[tuple[int, int], ...], *, width: int, height: int) -> list[list[float]]:
    return [[_round_ratio(x / width), _round_ratio(y / height)] for x, y in points]


def _animation_from_landmarks(
    landmarks: AvatarMouthLandmarks,
    *,
    width: int,
    height: int,
) -> dict[str, Any]:
    animation: dict[str, Any] = {
        "mouth_center": [
            _round_ratio(landmarks.mouth_center[0] / width),
            _round_ratio(landmarks.mouth_center[1] / height),
        ],
        "mouth_rx": _round_ratio(landmarks.mouth_rx / width),
        "mouth_ry": _round_ratio(landmarks.mouth_ry / height),
    }
    if landmarks.outer_lip:
        animation["outer_lip"] = _normalized_points(landmarks.outer_lip, width=width, height=height)
    if landmarks.inner_mouth:
        animation["inner_mouth"] = _normalized_points(landmarks.inner_mouth, width=width, height=height)
    return animation


def _normalized_face_box(
    landmarks: AvatarMouthLandmarks,
    *,
    width: int,
    height: int,
) -> list[float]:
    xs = [x for x, _ in landmarks.outer_lip] or [landmarks.mouth_center[0]]
    ys = [y for _, y in landmarks.outer_lip] or [landmarks.mouth_center[1]]
    cx = landmarks.mouth_center[0]
    cy = landmarks.mouth_center[1]
    mouth_w = max(1, max(xs) - min(xs), landmarks.mouth_rx * 2)
    mouth_h = max(1, max(ys) - min(ys), landmarks.mouth_ry * 2)

    left = max(0.0, cx - mouth_w * 3.0)
    right = min(float(width), cx + mouth_w * 3.0)
    top = max(0.0, cy - mouth_h * 12.0)
    bottom = min(float(height), cy + mouth_h * 8.0)

    # Keep a roughly portrait face crop so Wav2Lip receives a stable face area.
    box_w = right - left
    box_h = bottom - top
    target_h = max(box_h, box_w * 1.25)
    extra_h = max(0.0, target_h - box_h)
    top = max(0.0, top - extra_h * 0.45)
    bottom = min(float(height), bottom + extra_h * 0.55)

    return [
        _round_ratio(left / width),
        _round_ratio(top / height),
        _round_ratio(right / width),
        _round_ratio(bottom / height),
    ]


def detect_mouth_landmarks(frame: Any) -> AvatarMouthLandmarks | None:
    try:
        import mediapipe as mp  # type: ignore[import-not-found]
    except Exception:
        return None

    height, width = frame.shape[:2]
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    face_mesh = mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
    )
    try:
        result = face_mesh.process(rgb)
    finally:
        face_mesh.close()
    if not result.multi_face_landmarks:
        return None

    landmarks = result.multi_face_landmarks[0].landmark
    outer_indices = (61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185)
    inner_indices = (78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308, 415, 310, 311, 312, 13, 82, 81, 80, 191)

    def point(index: int) -> tuple[int, int]:
        item = landmarks[index]
        return int(round(item.x * width)), int(round(item.y * height))

    outer = tuple(point(i) for i in outer_indices)
    inner = tuple(point(i) for i in inner_indices)
    xs = [p[0] for p in outer]
    ys = [p[1] for p in outer]
    return AvatarMouthLandmarks(
        mouth_center=(int(round(sum(xs) / len(xs))), int(round(sum(ys) / len(ys)))),
        mouth_rx=max(1, int(round((max(xs) - min(xs)) / 2))),
        mouth_ry=max(1, int(round((max(ys) - min(ys)) / 2))),
        outer_lip=outer,
        inner_mouth=inner,
    )


def update_manifest_mouth_metadata(
    manifest_path: Path,
    image_path: Path,
    *,
    force: bool = False,
) -> MouthMetadataUpdate:
    image_hash = image_file_sha256(image_path)
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    metadata = dict(raw.get("metadata") or {})
    animation = metadata.get("animation")
    has_polygon = isinstance(animation, dict) and bool(animation.get("outer_lip"))
    if not force and metadata.get("source_image_hash") == image_hash and has_polygon:
        return MouthMetadataUpdate(updated=False, image_hash=image_hash, landmarks=None)

    metadata["source_image_hash"] = image_hash
    try:
        metadata["source_image_path"] = str(image_path.resolve().relative_to(manifest_path.parent.resolve()))
    except ValueError:
        metadata["source_image_path"] = str(image_path)

    frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if frame is None:
        _clear_mouth_metadata(metadata)
        raw["metadata"] = metadata
        manifest_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return MouthMetadataUpdate(updated=True, image_hash=image_hash, landmarks=None)
    landmarks = detect_mouth_landmarks(frame)
    if landmarks is None:
        _clear_mouth_metadata(metadata)
        raw["metadata"] = metadata
        manifest_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return MouthMetadataUpdate(updated=True, image_hash=image_hash, landmarks=None)

    height, width = frame.shape[:2]
    metadata["mouth_polygon_source"] = "mediapipe"
    metadata["face_box"] = _normalized_face_box(landmarks, width=width, height=height)
    metadata["animation"] = _animation_from_landmarks(landmarks, width=width, height=height)
    raw["metadata"] = metadata
    manifest_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return MouthMetadataUpdate(updated=True, image_hash=image_hash, landmarks=landmarks)


def _clear_mouth_metadata(metadata: dict[str, Any]) -> None:
    metadata.pop("animation", None)
    metadata.pop("face_box", None)
    metadata["mouth_polygon_source"] = "unavailable"
