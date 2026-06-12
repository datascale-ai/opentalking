from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np


class CacheValidationError(RuntimeError):
    """Raised when a generated runtime cache is missing or malformed."""


@dataclass(frozen=True)
class TemplateSource:
    path: Path
    mode: str


@dataclass(frozen=True)
class CacheInfo:
    path: Path
    frames: int


@dataclass(frozen=True)
class PreparedAssetResult:
    avatar_id: str
    status: str
    source_mode: str
    template_path: Path | None
    cache_path: Path | None
    frames: int | None = None
    detail: str = ""


def _even(value: int) -> int:
    value = max(2, int(value))
    return value - (value % 2)


def _target_video_size(manifest: dict, *, max_long_edge: int) -> tuple[int, int]:
    width = int(manifest.get("width") or 0)
    height = int(manifest.get("height") or 0)
    if width <= 0 or height <= 0:
        raise ValueError("avatar manifest must define positive width and height")
    max_long_edge = max(2, int(max_long_edge))
    long_edge = max(width, height)
    if long_edge > max_long_edge:
        scale = max_long_edge / float(long_edge)
        width = int(round(width * scale))
        height = int(round(height * scale))
    return _even(width), _even(height)


def _manifest_metadata(manifest: dict) -> dict:
    metadata = manifest.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _quicktalk_metadata(manifest: dict) -> dict:
    quicktalk = _manifest_metadata(manifest).get("quicktalk")
    return quicktalk if isinstance(quicktalk, dict) else {}


def _resolve_avatar_relative_path(avatar_dir: Path, raw: object) -> Path | None:
    value = str(raw or "").strip()
    if not value:
        return None
    path = (avatar_dir / value).resolve()
    try:
        path.relative_to(avatar_dir.resolve())
    except ValueError:
        return None
    return path


def _resolve_quicktalk_template_source(avatar_dir: Path, manifest: dict) -> TemplateSource | None:
    metadata = _manifest_metadata(manifest)
    quicktalk = _quicktalk_metadata(manifest)
    for source in (quicktalk, metadata):
        for key in ("template_video", "source_video"):
            path = _resolve_avatar_relative_path(avatar_dir, source.get(key))
            if path is not None and path.is_file():
                return TemplateSource(path=path, mode="video")
    for name in ("idle.mp4", "idle.mov", "idle.webm", "idle.avi", "source.mp4"):
        path = (avatar_dir / name).resolve()
        if path.is_file():
            return TemplateSource(path=path, mode="video")
    for key in ("source_image", "source_image_path", "reference_image"):
        path = _resolve_avatar_relative_path(avatar_dir, metadata.get(key))
        if path is not None and path.is_file():
            return TemplateSource(path=path, mode="image")
    for name in ("reference.png", "reference.jpg", "preview.png", "preview.jpg", "source.png"):
        path = (avatar_dir / name).resolve()
        if path.is_file():
            return TemplateSource(path=path, mode="image")
    return None


def _read_video_fps(video: Path) -> float:
    cap = cv2.VideoCapture(str(video))
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    finally:
        cap.release()
    return fps if fps > 0 else 25.0


def _write_video_template(
    *,
    source_video: Path,
    output_path: Path,
    width: int,
    height: int,
    fps: float,
    max_seconds: float | None,
) -> int:
    cap = cv2.VideoCapture(str(source_video))
    if not cap.isOpened():
        raise RuntimeError(f"failed to open source video: {source_video}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fourcc = int(getattr(cv2, "VideoWriter_fourcc")(*"mp4v"))
    writer = cv2.VideoWriter(
        str(output_path),
        fourcc,
        float(fps or 25.0),
        (int(width), int(height)),
    )
    if not writer.isOpened():
        cap.release()
        raise RuntimeError(f"failed to write template video: {output_path}")
    limit = None if max_seconds is None else max(1, int(round(float(max_seconds) * float(fps or 25.0))))
    frames = 0
    try:
        while limit is None or frames < limit:
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.resize(frame, (int(width), int(height)), interpolation=cv2.INTER_AREA)
            writer.write(frame)
            frames += 1
    finally:
        cap.release()
        writer.release()
    if frames <= 0:
        output_path.unlink(missing_ok=True)
        raise RuntimeError(f"no frames written for template video: {source_video}")
    return frames


def _write_image_template(
    *,
    source_image: Path,
    output_path: Path,
    width: int,
    height: int,
    fps: float,
    max_seconds: float | None,
) -> int:
    image = cv2.imread(str(source_image))
    if image is None:
        raise RuntimeError(f"failed to read source image: {source_image}")
    frame = cv2.resize(image, (int(width), int(height)), interpolation=cv2.INTER_AREA)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fourcc = int(getattr(cv2, "VideoWriter_fourcc")(*"mp4v"))
    writer = cv2.VideoWriter(
        str(output_path),
        fourcc,
        float(fps or 25.0),
        (int(width), int(height)),
    )
    if not writer.isOpened():
        raise RuntimeError(f"failed to write template video: {output_path}")
    frames = max(1, int(round(float(max_seconds or 1.0) * float(fps or 25.0))))
    try:
        for _ in range(frames):
            writer.write(frame)
    finally:
        writer.release()
    return frames


def _runtime_25fps_template(template_video: Path, workdir: Path, max_seconds: float | None) -> Path:
    src_fps = _read_video_fps(template_video)
    if abs(src_fps - 25.0) <= 1e-3:
        return template_video
    from opentalking.models.quicktalk.runtime_v2 import ensure_ffmpeg, run_cmd

    out = workdir / "template_25fps.mp4"
    cmd = [ensure_ffmpeg(), "-y", "-i", str(template_video), "-r", "25"]
    if max_seconds is not None:
        cmd += ["-t", str(max_seconds)]
    cmd += ["-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p", str(out)]
    run_cmd(cmd)
    return out


def _validate_quicktalk_face_cache(cache_path: Path) -> CacheInfo:
    path = cache_path.resolve()
    if not path.is_file():
        raise CacheValidationError(f"cache file does not exist: {path}")
    try:
        with np.load(str(path), allow_pickle=False) as data:
            missing = {"faces", "boxes", "affines"} - set(data.files)
            if missing:
                raise CacheValidationError(f"cache missing keys: {', '.join(sorted(missing))}")
            faces = data["faces"]
            boxes = data["boxes"]
            affines = data["affines"]
            if faces.ndim != 4 or faces.shape[1:] != (256, 256, 3):
                raise CacheValidationError(
                    f"faces must have shape (N, 256, 256, 3), got {faces.shape}"
                )
            if boxes.ndim != 2 or boxes.shape != (faces.shape[0], 4):
                raise CacheValidationError(
                    f"boxes must have shape ({faces.shape[0]}, 4), got {boxes.shape}"
                )
            if affines.ndim != 3 or affines.shape != (faces.shape[0], 2, 3):
                raise CacheValidationError(
                    f"affines must have shape ({faces.shape[0]}, 2, 3), got {affines.shape}"
                )
            if faces.shape[0] <= 0:
                raise CacheValidationError("cache must contain at least one frame")
            return CacheInfo(path=path, frames=int(faces.shape[0]))
    except CacheValidationError:
        raise
    except Exception as exc:
        raise CacheValidationError(f"failed to read cache file {path}: {exc}") from exc


def _normalized_model_crop_from_coords(
    coords: tuple[int, int, int, int],
    *,
    width: int,
    height: int,
) -> list[float]:
    y1, y2, x1, x2 = (int(value) for value in coords)
    width = max(1, int(width))
    height = max(1, int(height))
    return [
        round(float(x1) / float(width), 6),
        round(float(y1) / float(height), 6),
        round(float(x2) / float(width), 6),
        round(float(y2) / float(height), 6),
    ]


def _valid_model_crop(raw: object) -> bool:
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return False
    try:
        left, top, right, bottom = (float(item) for item in raw)
    except (TypeError, ValueError):
        return False
    return 0.0 <= left < right <= 1.0 and 0.0 <= top < bottom <= 1.0


def _write_wav2lip_model_crops(
    metadata_path: Path,
    crops_by_frame: dict[str, list[float]],
    *,
    source: str,
    overwrite: bool,
) -> dict[str, int]:
    raw = json.loads(metadata_path.read_text(encoding="utf-8"))
    frames = raw.get("frames") if isinstance(raw, dict) else None
    if not isinstance(frames, dict):
        raise ValueError(f"Wav2Lip frame metadata must contain a frames object: {metadata_path}")
    updated = 0
    skipped = 0
    for frame_name, crop in crops_by_frame.items():
        entry = frames.get(frame_name)
        if not isinstance(entry, dict):
            entry = {}
            frames[frame_name] = entry
        if (
            not overwrite
            and _valid_model_crop(entry.get("model_crop"))
            and str(entry.get("model_crop_source") or "").strip()
        ):
            skipped += 1
            continue
        if not _valid_model_crop(crop):
            continue
        entry["model_crop"] = [round(float(value), 6) for value in crop]
        entry["model_crop_source"] = source
        updated += 1
    if updated:
        metadata_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"updated": updated, "skipped": skipped}


def _prepare_wav2lip_model_crop_asset(
    *,
    avatar_dir: Path,
    manifest: dict,
    runtime: Any,
    max_reference_frames: int,
    overwrite: bool,
) -> PreparedAssetResult:
    avatar_id = str(manifest.get("id") or avatar_dir.name)
    metadata = _manifest_metadata(manifest)
    if metadata.get("reference_mode") != "frames" or metadata.get("preprocessed") is not True:
        return PreparedAssetResult(
            avatar_id=avatar_id,
            status="skipped",
            source_mode="unsupported",
            template_path=None,
            cache_path=None,
            detail="wav2lip model_crop preparation requires a preprocessed frame avatar",
        )
    frame_dir = _resolve_avatar_relative_path(avatar_dir, metadata.get("frame_dir") or "frames")
    metadata_path = _resolve_avatar_relative_path(avatar_dir, metadata.get("frame_metadata"))
    if frame_dir is None or not frame_dir.is_dir() or metadata_path is None or not metadata_path.is_file():
        return PreparedAssetResult(
            avatar_id=avatar_id,
            status="skipped",
            source_mode="missing",
            template_path=None,
            cache_path=metadata_path,
            detail="missing wav2lip frame directory or mouth_metadata.json",
        )
    raw = json.loads(metadata_path.read_text(encoding="utf-8"))
    frames = raw.get("frames") if isinstance(raw, dict) else None
    if not isinstance(frames, dict):
        raise ValueError(f"Wav2Lip frame metadata must contain a frames object: {metadata_path}")
    frame_names = sorted(str(name) for name in frames)
    max_reference_frames = max(1, int(max_reference_frames))
    frame_names = frame_names[:max_reference_frames]
    crops: dict[str, list[float]] = {}
    existing = 0
    missing = 0
    for frame_name in frame_names:
        entry = frames.get(frame_name)
        if (
            not overwrite
            and isinstance(entry, dict)
            and _valid_model_crop(entry.get("model_crop"))
            and str(entry.get("model_crop_source") or "").strip()
        ):
            existing += 1
            continue
        frame_path = frame_dir / frame_name
        frame = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
        if frame is None:
            missing += 1
            continue
        coords = runtime._detect_face_box(frame)
        height, width = frame.shape[:2]
        crops[frame_name] = _normalized_model_crop_from_coords(coords, width=width, height=height)
    write_result = _write_wav2lip_model_crops(
        metadata_path,
        crops,
        source="wav2lip_detector",
        overwrite=overwrite,
    )
    updated = int(write_result["updated"])
    if updated:
        status = "generated"
    elif existing:
        status = "hit"
    else:
        status = "skipped"
    detail = f"updated={updated} existing={existing} missing={missing}"
    return PreparedAssetResult(
        avatar_id=avatar_id,
        status=status,
        source_mode="frames",
        template_path=None,
        cache_path=metadata_path,
        frames=updated + existing,
        detail=detail,
    )


def _iter_avatar_dirs(avatars_root: Path, selected: Sequence[str]) -> list[Path]:
    root = avatars_root.resolve()
    if selected:
        return [(root / avatar_id).resolve() for avatar_id in selected]
    return [path.parent.resolve() for path in sorted(root.glob("*/manifest.json"))]


def _read_manifest(avatar_dir: Path) -> dict:
    manifest_path = avatar_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"missing manifest.json under {avatar_dir}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _prepare_quicktalk_asset(
    *,
    avatar_dir: Path,
    manifest: dict,
    rebuild: Any,
    max_long_edge: int,
    max_template_seconds: float | None,
    overwrite: bool,
    verify: bool,
) -> PreparedAssetResult:
    avatar_id = str(manifest.get("id") or avatar_dir.name)
    width, height = _target_video_size(manifest, max_long_edge=max_long_edge)
    quicktalk_dir = avatar_dir / "quicktalk"
    template_path = quicktalk_dir / f"template_{width}x{height}.mp4"
    cache_path = quicktalk_dir / f"face_cache_v3_{width}x{height}.npz"
    source = _resolve_quicktalk_template_source(avatar_dir, manifest)
    if source is None:
        return PreparedAssetResult(
            avatar_id=avatar_id,
            status="skipped",
            source_mode="missing",
            template_path=None,
            cache_path=None,
            detail="no template video or reference image found",
        )
    if cache_path.is_file() and not overwrite:
        info = _validate_quicktalk_face_cache(cache_path) if verify else None
        return PreparedAssetResult(
            avatar_id=avatar_id,
            status="hit",
            source_mode=source.mode,
            template_path=template_path if template_path.is_file() else None,
            cache_path=cache_path,
            frames=info.frames if info else None,
        )
    fps = _read_video_fps(source.path) if source.mode == "video" else 25.0
    if source.mode == "video":
        _write_video_template(
            source_video=source.path,
            output_path=template_path,
            width=width,
            height=height,
            fps=fps,
            max_seconds=max_template_seconds,
        )
    else:
        _write_image_template(
            source_image=source.path,
            output_path=template_path,
            width=width,
            height=height,
            fps=25.0,
            max_seconds=max_template_seconds,
        )
    with tempfile.TemporaryDirectory(prefix="opentalking_quicktalk_cache_") as tmpdir:
        runtime_template = _runtime_25fps_template(
            template_path,
            Path(tmpdir),
            max_template_seconds,
        )
        frames, _resolved_fps = rebuild.read_frames(
            runtime_template,
            max_seconds=max_template_seconds,
        )
        if not frames:
            return PreparedAssetResult(
                avatar_id=avatar_id,
                status="skipped",
                source_mode=source.mode,
                template_path=template_path,
                cache_path=None,
                detail="template produced zero runtime frames",
            )
        face_det_results = rebuild.face_detect_frames(frames)
    rebuild.save_face_cache(cache_path, face_det_results)
    info = _validate_quicktalk_face_cache(cache_path)
    return PreparedAssetResult(
        avatar_id=avatar_id,
        status="generated",
        source_mode=source.mode,
        template_path=template_path,
        cache_path=cache_path,
        frames=info.frames,
    )


def _print_results(results: Sequence[PreparedAssetResult]) -> None:
    headers = ("avatar", "status", "source", "frames", "template", "cache", "detail")
    rows = []
    for item in results:
        rows.append(
            (
                item.avatar_id,
                item.status,
                item.source_mode,
                "" if item.frames is None else str(item.frames),
                "" if item.template_path is None else str(item.template_path),
                "" if item.cache_path is None else str(item.cache_path),
                item.detail,
            )
        )
    widths = [
        max(len(headers[idx]), *(len(row[idx]) for row in rows)) if rows else len(headers[idx])
        for idx in range(len(headers))
    ]
    print("  ".join(header.ljust(widths[idx]) for idx, header in enumerate(headers)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(row[idx].ljust(widths[idx]) for idx in range(len(headers))))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare OpenTalking avatar runtime caches.")
    parser.add_argument(
        "--model",
        action="append",
        required=True,
        choices=["quicktalk", "wav2lip"],
        help="Model cache to prepare. Repeatable.",
    )
    parser.add_argument("--avatars-root", type=Path, required=True)
    parser.add_argument("--avatar", action="append", default=[], help="Avatar id to process.")
    parser.add_argument("--quicktalk-asset-root", type=Path)
    parser.add_argument("--quicktalk-model-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--wav2lip-model-root", type=Path)
    parser.add_argument("--wav2lip-face-det-device")
    parser.add_argument("--wav2lip-max-reference-frames", type=int, default=125)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--hubert-device", default=None)
    parser.add_argument("--model-backend", default="auto", choices=["auto", "pth", "onnx"])
    parser.add_argument("--max-long-edge", type=int, default=900)
    parser.add_argument(
        "--max-template-seconds",
        type=float,
        default=None,
        help="Limit QuickTalk video template duration. Defaults to the full source video.",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--verify", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    avatars_root = args.avatars_root.expanduser().resolve()
    quicktalk_asset_root = args.quicktalk_asset_root or args.quicktalk_model_root
    if "quicktalk" in args.model and quicktalk_asset_root is None:
        raise SystemExit("--quicktalk-asset-root is required when --model quicktalk is selected")
    rebuild = None
    if "quicktalk" in args.model:
        from opentalking.models.quicktalk.runtime_v2 import QuickTalkRebuild

        quicktalk_root = quicktalk_asset_root.expanduser().resolve()
        rebuild = QuickTalkRebuild(
            asset_root=quicktalk_root,
            device=args.device,
            hubert_device=args.hubert_device,
            model_backend=args.model_backend,
            video_padding_seconds=0.0,
        )
    wav2lip_runtime = None
    if "wav2lip" in args.model:
        from opentalking.models.wav2lip.runtime import Wav2LipRealtimeRuntime

        if args.wav2lip_face_det_device:
            os.environ["OPENTALKING_WAV2LIP_FACE_DET_DEVICE"] = str(args.wav2lip_face_det_device)
        wav2lip_model_root = (
            args.wav2lip_model_root
            or Path(os.environ.get("OPENTALKING_WAV2LIP_MODEL_ROOT", "./models/wav2lip"))
        )
        wav2lip_runtime = Wav2LipRealtimeRuntime(
            models_dir=wav2lip_model_root.expanduser().resolve(),
            device=args.device,
        )
    results: list[PreparedAssetResult] = []
    had_failure = False
    for avatar_dir in _iter_avatar_dirs(avatars_root, args.avatar):
        try:
            manifest = _read_manifest(avatar_dir)
            if "quicktalk" in args.model:
                assert rebuild is not None
                results.append(
                    _prepare_quicktalk_asset(
                        avatar_dir=avatar_dir,
                        manifest=manifest,
                        rebuild=rebuild,
                        max_long_edge=args.max_long_edge,
                        max_template_seconds=args.max_template_seconds,
                        overwrite=args.overwrite,
                        verify=args.verify,
                    )
                )
            if "wav2lip" in args.model:
                assert wav2lip_runtime is not None
                results.append(
                    _prepare_wav2lip_model_crop_asset(
                        avatar_dir=avatar_dir,
                        manifest=manifest,
                        runtime=wav2lip_runtime,
                        max_reference_frames=args.wav2lip_max_reference_frames,
                        overwrite=args.overwrite,
                    )
                )
        except Exception as exc:
            had_failure = True
            results.append(
                PreparedAssetResult(
                    avatar_id=avatar_dir.name,
                    status="failed",
                    source_mode="",
                    template_path=None,
                    cache_path=None,
                    detail=str(exc),
                )
            )
    if any(result.status == "failed" for result in results):
        had_failure = True
    _print_results(results)
    return 1 if had_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
