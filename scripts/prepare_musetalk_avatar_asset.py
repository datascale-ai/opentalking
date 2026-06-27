#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import json
import os
import pickle
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
from PIL import Image

from opentalking.avatar.manifest import parse_manifest
from opentalking.media.frame_avatar import (
    load_frame_avatar_state,
    resize_reference_image_to_video,
)
from opentalking.models.musetalk.face_utils import (
    CropInfo,
    create_lower_face_mask,
    create_manifest_mouth_mask,
    crop_face_region_from_box,
    estimate_face_crop_box,
    estimate_infer_face_crop_box,
    smooth_crop_boxes,
)
from opentalking.models.musetalk.inference import get_latents_for_unet
from opentalking.models.musetalk.loader import (
    load_musetalk_v15_bundle,
    resolve_musetalk_v15,
)

OFFICIAL_FORMAT = "opentalking-musetalk-official-prepared-v1"
FALLBACK_FORMAT = "opentalking-musetalk-prepared-v1"


def _official_prepared_ready(output_dir: Path) -> bool:
    metadata_path = output_dir / "prepared_info.json"
    required_files = [
        output_dir / "coords.pkl",
        output_dir / "infer_coords.pkl",
        output_dir / "mask_coords.pkl",
        output_dir / "latents.pt",
    ]
    mask_dir = output_dir / "mask"
    if not metadata_path.is_file() or not all(path.is_file() for path in required_files):
        return False
    if not mask_dir.is_dir() or not any(mask_dir.glob("*.png")):
        return False
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return (
        metadata.get("source_preprocess") == "musetalk_official"
        or metadata.get("format") == OFFICIAL_FORMAT
    )


@contextlib.contextmanager
def _temporary_cwd(path: Path):
    old = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def _load_single_frame(avatar_path: Path, manifest: Any) -> tuple[list[np.ndarray], list[Path]]:
    for name in ("reference.png", "reference.jpg", "reference.jpeg", "preview.png", "preview.jpg"):
        path = avatar_path / name
        if path.is_file():
            image = Image.open(path).convert("RGB")
            image = resize_reference_image_to_video(
                image,
                width=int(manifest.width),
                height=int(manifest.height),
            )
            frame = np.asarray(image, dtype=np.uint8)[:, :, ::-1].copy()
            return [frame], [path]
    raise FileNotFoundError(f"Expected frames/full_imgs or reference image under {avatar_path}")


def _load_avatar_frames(avatar_path: Path) -> tuple[Any, list[np.ndarray], list[Path]]:
    manifest = parse_manifest(avatar_path / "manifest.json")
    try:
        state = load_frame_avatar_state(avatar_path, manifest)
        return manifest, state.frames, state.frame_paths
    except (FileNotFoundError, ValueError):
        frames, frame_paths = _load_single_frame(avatar_path, manifest)
        return manifest, frames, frame_paths


def _resolve_official_musetalk_repo(explicit: Path | None) -> Path | None:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit)
    for env_name in ("OPENTALKING_MUSETALK_REPO",):
        raw = os.environ.get(env_name)
        if raw:
            candidates.append(Path(raw))
    digital_home = os.environ.get("DIGITAL_HUMAN_HOME")
    if digital_home:
        candidates.append(Path(digital_home) / "model-repos" / "MuseTalk")

    for candidate in candidates:
        repo = candidate.expanduser().resolve()
        if (repo / "musetalk" / "utils" / "preprocessing.py").is_file() and (
            repo / "musetalk" / "utils" / "blending.py"
        ).is_file():
            return repo
    return None


def _resolve_official_python(explicit: Path | None) -> Path | None:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit)
    for env_name in ("OPENTALKING_MUSETALK_PREPROCESS_PYTHON",):
        raw = os.environ.get(env_name)
        if raw:
            candidates.append(Path(raw))
    digital_home = os.environ.get("DIGITAL_HUMAN_HOME")
    if digital_home:
        candidates.append(
            Path(digital_home) / "runtimes" / "musetalk-preprocess" / "venv" / "bin" / "python"
        )

    for candidate in candidates:
        py = candidate.expanduser().absolute()
        if py.is_file() and os.access(py, os.X_OK):
            return py
    return None


def _prepare_repo_model_links(repo: Path, models_dir: Path) -> None:
    """Expose shared model weights at the relative paths expected by MuseTalk."""

    links = {
        "dwpose": models_dir / "dwpose",
        "face-parse-bisenet": models_dir / "face-parse-bisenet",
        "face-parse-bisent": models_dir / "face-parse-bisenet",
    }
    repo_models = repo / "models"
    repo_models.mkdir(exist_ok=True)
    for name, target in links.items():
        link = repo_models / name
        if link.exists() or link.is_symlink():
            continue
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            if target.is_dir():
                shutil.copytree(target, link, dirs_exist_ok=True)


def _prepend_env_path(env: dict[str, str], name: str, paths: list[Path]) -> None:
    existing = env.get(name, "")
    values: list[str] = []
    seen: set[str] = set()
    for path in paths:
        value = str(path)
        if value and path.exists() and value not in seen:
            values.append(value)
            seen.add(value)
    for value in existing.split(os.pathsep):
        if value and value not in seen:
            values.append(value)
            seen.add(value)
    if values:
        env[name] = os.pathsep.join(values)


def _python_site_packages(py: Path) -> Path | None:
    cp = subprocess.run(
        [
            str(py),
            "-c",
            "import site; paths=site.getsitepackages(); print(paths[0] if paths else '')",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if cp.returncode != 0:
        return None
    raw = cp.stdout.strip()
    return Path(raw) if raw else None


def _augment_preprocess_env(env: dict[str, str], py: Path) -> None:
    library_paths: list[Path] = []
    site_packages = _python_site_packages(py)
    if site_packages is not None:
        library_paths.append(site_packages / "torch" / "lib")
    library_paths.extend(
        Path(path)
        for path in (
            "/usr/local/cuda/lib64",
            "/usr/local/cuda/extras/CUPTI/lib64",
            "/usr/local/cuda-11.8/lib64",
            "/usr/local/cuda-11.8/extras/CUPTI/lib64",
            "/usr/local/cuda-11.8/nsight-systems-2022.4.2/target-linux-x64",
            "/usr/local/cuda-11.7/lib64",
            "/usr/local/cuda-11.7/extras/CUPTI/lib64",
        )
    )
    _prepend_env_path(env, "LD_LIBRARY_PATH", library_paths)


def _official_preprocess_frames(
    *,
    repo: Path,
    models_dir: Path,
    frames: list[np.ndarray],
    output_dir: Path,
    bbox_shift: int,
    official_python: Path | None,
) -> tuple[
    list[tuple[int, int, int, int]],
    list[np.ndarray],
    list[np.ndarray],
    list[tuple[int, int, int, int]],
]:
    _prepare_repo_model_links(repo, models_dir)
    tmp_frames = output_dir / "_official_input"
    tmp_frames.mkdir()
    image_paths: list[str] = []
    for idx, frame in enumerate(frames):
        path = tmp_frames / f"{idx:08d}.png"
        cv2.imwrite(str(path), frame)
        image_paths.append(str(path))

    current_python = Path(sys.executable).expanduser().absolute()
    requested_python = (
        official_python.expanduser().absolute() if official_python is not None else None
    )
    if requested_python is not None and requested_python != current_python:
        worker_dir = output_dir / "_official_output"
        worker_dir.mkdir()
        worker_script = output_dir / "_official_preprocess_worker.py"
        worker_script.write_text(
            r'''
from __future__ import annotations

import argparse
import os
import pickle
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--bbox-shift", type=int, default=0)
    args = parser.parse_args()

    repo = args.repo.resolve()
    input_dir = args.input_dir.resolve()
    out = args.out.resolve()
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    os.chdir(repo)

    import torch

    original_torch_load = torch.load

    def torch_load_wrapped(*load_args, **load_kwargs):
        load_kwargs.setdefault("weights_only", False)
        return original_torch_load(*load_args, **load_kwargs)

    torch.load = torch_load_wrapped

    from musetalk.utils.blending import get_image_prepare_material
    from musetalk.utils.face_parsing import FaceParsing
    from musetalk.utils.preprocessing import coord_placeholder, get_landmark_and_bbox

    image_paths = [str(path) for path in sorted(input_dir.glob("*.png"))]
    coords_raw, official_frames = get_landmark_and_bbox(image_paths, args.bbox_shift)
    face_parser = FaceParsing()

    full_imgs_dir = out / "full_imgs"
    mask_dir = out / "mask"
    if out.exists():
        shutil.rmtree(out)
    full_imgs_dir.mkdir(parents=True)
    mask_dir.mkdir()

    coords = []
    mask_coords = []
    for idx, (coord, frame) in enumerate(zip(coords_raw, official_frames)):
        if coord == coord_placeholder:
            raise RuntimeError(f"MuseTalk official preprocessing did not detect a face in frame {idx}")
        x1, y1, x2, y2 = (int(v) for v in coord)
        if x2 <= x1 or y2 <= y1:
            raise RuntimeError(f"MuseTalk official preprocessing returned invalid bbox for frame {idx}: {coord}")
        mask, crop_box = get_image_prepare_material(
            frame,
            (x1, y1, x2, y2),
            upper_boundary_ratio=0.5,
            expand=1.2,
            fp=face_parser,
        )
        cv2.imwrite(str(full_imgs_dir / f"{idx:08d}.png"), frame)
        cv2.imwrite(str(mask_dir / f"{idx:08d}.png"), mask.astype(np.uint8, copy=False))
        coords.append((x1, y1, x2, y2))
        mask_coords.append(tuple(int(v) for v in crop_box))

    with (out / "coords.pkl").open("wb") as handle:
        pickle.dump(coords, handle)
    with (out / "mask_coords.pkl").open("wb") as handle:
        pickle.dump(mask_coords, handle)


if __name__ == "__main__":
    main()
'''.lstrip(),
            encoding="utf-8",
        )
        env = os.environ.copy()
        env.setdefault("TMPDIR", str(output_dir.parent))
        _augment_preprocess_env(env, requested_python)
        cp = subprocess.run(
            [
                str(requested_python),
                str(worker_script),
                "--repo",
                str(repo),
                "--input-dir",
                str(tmp_frames),
                "--out",
                str(worker_dir),
                "--bbox-shift",
                str(bbox_shift),
            ],
            cwd=str(repo),
            env=env,
            text=True,
            capture_output=True,
        )
        if cp.returncode != 0:
            raise RuntimeError(
                "MuseTalk official preprocessing failed with "
                f"{requested_python}:\nSTDOUT:\n{cp.stdout}\nSTDERR:\n{cp.stderr}"
            )
        with (worker_dir / "coords.pkl").open("rb") as handle:
            coords = pickle.load(handle)
        with (worker_dir / "mask_coords.pkl").open("rb") as handle:
            mask_coords = pickle.load(handle)
        official_frames = [
            cv2.imread(str(path))
            for path in sorted((worker_dir / "full_imgs").glob("*.png"))
        ]
        masks = [
            cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            for path in sorted((worker_dir / "mask").glob("*.png"))
        ]
        if any(frame is None for frame in official_frames) or any(mask is None for mask in masks):
            raise RuntimeError("MuseTalk official preprocessing produced unreadable frame or mask files")
        shutil.rmtree(tmp_frames, ignore_errors=True)
        shutil.rmtree(worker_dir, ignore_errors=True)
        worker_script.unlink(missing_ok=True)
        return coords, official_frames, masks, mask_coords

    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))

    with _temporary_cwd(repo):
        from musetalk.utils.blending import get_image_prepare_material
        from musetalk.utils.face_parsing import FaceParsing
        from musetalk.utils.preprocessing import coord_placeholder, get_landmark_and_bbox

        coords_raw, official_frames = get_landmark_and_bbox(image_paths, bbox_shift)
        face_parser = FaceParsing()
        coords: list[tuple[int, int, int, int]] = []
        masks: list[np.ndarray] = []
        mask_coords: list[tuple[int, int, int, int]] = []
        valid_frames: list[np.ndarray] = []
        for idx, (coord, frame) in enumerate(zip(coords_raw, official_frames)):
            if coord == coord_placeholder:
                raise RuntimeError(f"MuseTalk official preprocessing did not detect a face in frame {idx}")
            x1, y1, x2, y2 = (int(v) for v in coord)
            if x2 <= x1 or y2 <= y1:
                raise RuntimeError(f"MuseTalk official preprocessing returned invalid bbox for frame {idx}: {coord}")
            mask, crop_box = get_image_prepare_material(
                frame,
                (x1, y1, x2, y2),
                upper_boundary_ratio=0.5,
                expand=1.2,
                fp=face_parser,
            )
            coords.append((x1, y1, x2, y2))
            valid_frames.append(frame)
            masks.append(mask.astype(np.uint8, copy=False))
            mask_coords.append(tuple(int(v) for v in crop_box))
    shutil.rmtree(tmp_frames, ignore_errors=True)
    return coords, valid_frames, masks, mask_coords


def prepare_musetalk_avatar(
    *,
    avatar_path: Path,
    models_dir: Path,
    device: str,
    output_dir: Path,
    force: bool,
    smooth: bool,
    musetalk_repo: Path | None,
    official_python: Path | None,
    official_preprocess: bool,
    require_official: bool,
    skip_if_ready: bool,
    bbox_shift: int,
) -> None:
    avatar_path = avatar_path.resolve()
    output_dir = output_dir.resolve()
    if skip_if_ready and _official_prepared_ready(output_dir):
        print(f"MuseTalk official prepared assets already exist at {output_dir}")
        return
    if output_dir.exists():
        if not force:
            raise FileExistsError(f"{output_dir} already exists; pass --force to replace it")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    mask_dir = output_dir / "mask"
    full_imgs_dir = output_dir / "full_imgs"
    mask_dir.mkdir()
    full_imgs_dir.mkdir()

    manifest, frames, frame_paths = _load_avatar_frames(avatar_path)
    metadata = getattr(manifest, "metadata", None) or {}
    animation = metadata.get("animation") if isinstance(metadata, dict) else None

    paths = resolve_musetalk_v15(models_dir.resolve())
    if paths is None:
        raise RuntimeError(f"Incomplete MuseTalk v1.5 checkpoint layout under {models_dir}")
    bundle = load_musetalk_v15_bundle(paths, device)
    vae = bundle["vae"]

    repo = _resolve_official_musetalk_repo(musetalk_repo) if official_preprocess else None
    if official_preprocess and require_official and repo is None:
        raise RuntimeError(
            "Official MuseTalk preprocessing was required, but no usable MuseTalk repo was found. "
            "Set OPENTALKING_MUSETALK_REPO or pass --musetalk-repo."
        )
    resolved_official_python = _resolve_official_python(official_python) if repo is not None else None
    official_masks: list[np.ndarray] | None = None
    official_mask_coords: list[tuple[int, int, int, int]] | None = None
    if repo is not None:
        crop_boxes, frames, official_masks, official_mask_coords = _official_preprocess_frames(
            repo=repo,
            models_dir=models_dir.resolve(),
            frames=frames,
            output_dir=output_dir,
            bbox_shift=bbox_shift,
            official_python=resolved_official_python,
        )
        infer_crop_boxes = list(crop_boxes)
        format_name = OFFICIAL_FORMAT
        compose_mode = "strict_mask"
        source_preprocess = "musetalk_official"
    else:
        crop_boxes = [estimate_face_crop_box(frame) for frame in frames]
        infer_crop_boxes = [estimate_infer_face_crop_box(frame) for frame in frames]
        if smooth:
            crop_boxes = smooth_crop_boxes(crop_boxes)
            infer_crop_boxes = smooth_crop_boxes(infer_crop_boxes)
        format_name = FALLBACK_FORMAT
        compose_mode = ""
        source_preprocess = "opentalking_fallback"

    coords: list[tuple[int, int, int, int]] = []
    infer_coords: list[tuple[int, int, int, int]] = []
    mask_coords: list[tuple[int, int, int, int]] = []
    latents: list[Any] = []

    for idx, (frame, crop_box, infer_crop_box) in enumerate(
        zip(frames, crop_boxes, infer_crop_boxes)
    ):
        face_region, infer_ci = crop_face_region_from_box(frame, infer_crop_box)
        latent = get_latents_for_unet(face_region, vae, device).detach().cpu()

        x1, y1, x2, y2 = (int(v) for v in crop_box)
        crop_info = CropInfo(
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
            original_h=frame.shape[0],
            original_w=frame.shape[1],
        )
        if official_masks is not None and official_mask_coords is not None:
            mask = official_masks[idx]
            mask_coord = official_mask_coords[idx]
        else:
            mask = create_lower_face_mask(face_region)
            if isinstance(animation, dict):
                manifest_mask = create_manifest_mouth_mask(animation, crop_info)
                if manifest_mask is not None:
                    mask = manifest_mask
            mask_coord = (x1, y1, x2, y2)

        cv2.imwrite(str(full_imgs_dir / f"{idx:08d}.png"), frame)
        cv2.imwrite(str(mask_dir / f"{idx:08d}.png"), mask)

        coords.append((x1, y1, x2, y2))
        infer_coords.append((infer_ci.x1, infer_ci.y1, infer_ci.x2, infer_ci.y2))
        mask_coords.append(mask_coord)
        latents.append(latent)

    with (output_dir / "coords.pkl").open("wb") as handle:
        pickle.dump(coords, handle)
    with (output_dir / "infer_coords.pkl").open("wb") as handle:
        pickle.dump(infer_coords, handle)
    with (output_dir / "mask_coords.pkl").open("wb") as handle:
        pickle.dump(mask_coords, handle)
    torch.save(latents, output_dir / "latents.pt")

    info = {
        "avatar_id": manifest.id,
        "source": str(avatar_path),
        "frame_count": len(frames),
        "frame_paths": [str(p) for p in frame_paths],
        "device": device,
        "format": format_name,
        "source_preprocess": source_preprocess,
        "musetalk_repo": str(repo) if repo is not None else None,
        "official_python": str(resolved_official_python) if resolved_official_python is not None else None,
        "bbox_shift": bbox_shift,
        "prepared_compose_mode": compose_mode,
    }
    (output_dir / "prepared_info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare MuseTalk avatar assets for OpenTalking local backend."
    )
    parser.add_argument("--avatar", required=True, type=Path, help="Avatar directory")
    parser.add_argument("--models-dir", required=True, type=Path)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-smooth", action="store_true")
    parser.add_argument(
        "--musetalk-repo",
        type=Path,
        default=None,
        help="Official MuseTalk source checkout. Defaults to OPENTALKING_MUSETALK_REPO or DIGITAL_HUMAN_HOME/model-repos/MuseTalk.",
    )
    parser.add_argument(
        "--official-python",
        type=Path,
        default=None,
        help="Python interpreter with MuseTalk official preprocessing dependencies. Defaults to OPENTALKING_MUSETALK_PREPROCESS_PYTHON or DIGITAL_HUMAN_HOME/runtimes/musetalk-preprocess/venv/bin/python.",
    )
    parser.add_argument(
        "--fallback-preprocess",
        action="store_true",
        help="Use OpenTalking's legacy heuristic crop/mask preprocessing instead of official MuseTalk preprocessing.",
    )
    parser.add_argument(
        "--require-official",
        action="store_true",
        help="Fail instead of falling back when official MuseTalk preprocessing is unavailable.",
    )
    parser.add_argument(
        "--skip-if-ready",
        action="store_true",
        help="Return successfully if the output directory already contains official MuseTalk prepared assets.",
    )
    parser.add_argument("--bbox-shift", type=int, default=0)
    args = parser.parse_args()

    out = args.out or (args.avatar / "prepared")
    prepare_musetalk_avatar(
        avatar_path=args.avatar,
        models_dir=args.models_dir,
        device=args.device,
        output_dir=out,
        force=args.force,
        smooth=not args.no_smooth,
        musetalk_repo=args.musetalk_repo,
        official_python=args.official_python,
        official_preprocess=not args.fallback_preprocess,
        require_official=args.require_official,
        skip_if_ready=args.skip_if_ready,
        bbox_shift=args.bbox_shift,
    )
    print(f"MuseTalk prepared assets written to {out}")


if __name__ == "__main__":
    main()
