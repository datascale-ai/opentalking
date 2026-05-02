from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

import cv2
import numpy as np

from .face_detection import FaceAlignment, LandmarksType
from .feature_extractor import MEL_STEP_SIZE, pcm_to_wav2lip_mel
from .loader import load_wav2lip_torch, resolve_wav2lip_checkpoint, resolve_wav2lip_s3fd


REPO_ROOT = Path(__file__).resolve().parents[4]
MODELS_ROOT = REPO_ROOT / "models"

DEFAULT_S3FD_SOURCES = [
    Path("/data1/xuxin/s3fd-619a316812.pth"),
    Path("/home/xuxin/s3fd-619a316812.pth"),
]
DEFAULT_CHECKPOINT_CANDIDATES = [
    MODELS_ROOT / "wav2lip_gan.pth",
    MODELS_ROOT / "wav2lip.pth",
    MODELS_ROOT / "wav2lip" / "wav2lip_gan.pth",
    MODELS_ROOT / "wav2lip" / "wav2lip.pth",
    REPO_ROOT / "wav2lip_gan.pth",
    REPO_ROOT / "wav2lip.pth",
    Path("/data1/xuxin/wav2lip_gan.pth"),
    Path("/data1/xuxin/wav2lip.pth"),
    Path("/home/xuxin/wav2lip_gan.pth"),
    Path("/home/xuxin/wav2lip.pth"),
]


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _models_dir() -> Path:
    raw = os.environ.get("OPENTALKING_MODELS_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return MODELS_ROOT.resolve()


def _runtime_device() -> str:
    try:
        import torch
    except ImportError:
        return "cpu"
    raw = os.environ.get("OPENTALKING_TORCH_DEVICE", "").strip()
    if raw:
        if raw.startswith("cuda") and not torch.cuda.is_available():
            return "cpu"
        return raw
    return "cuda" if torch.cuda.is_available() else "cpu"


def _save_wav(path: Path, pcm: np.ndarray, sample_rate: int) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.astype(np.int16).tobytes())


def resolve_face_image(avatar_path: Path) -> Path:
    for name in ("preview.png", "preview.jpg", "preview.jpeg"):
        candidate = avatar_path / name
        if candidate.is_file():
            return candidate.resolve()

    frames_dir = avatar_path / "frames"
    if frames_dir.is_dir():
        for pattern in ("*.png", "*.jpg", "*.jpeg"):
            matches = sorted(frames_dir.glob(pattern))
            if matches:
                return matches[0].resolve()
    raise FileNotFoundError(f"No preview image found for wav2lip avatar: {avatar_path}")


def _ensure_support_file(target: Path, sources: list[Path], *, min_bytes: int, label: str) -> Path:
    _ensure_dir(target.parent)
    if target.is_file() and target.stat().st_size >= min_bytes:
        return target.resolve()

    for source in sources:
        if source.is_file() and source.stat().st_size >= min_bytes:
            shutil.copy2(source, target)
            return target.resolve()

    checked = [str(target), *[str(path) for path in sources]]
    raise FileNotFoundError(
        f"Missing usable {label}. Checked: {checked}. "
        f"Please download the file and place it in one of these paths."
    )


def resolve_checkpoint_path(override: str | None = None) -> Path:
    if override:
        checkpoint = Path(override).expanduser()
        if checkpoint.is_file() and checkpoint.stat().st_size >= 50 * 1024 * 1024:
            return checkpoint.resolve()
        raise FileNotFoundError(f"Wav2Lip checkpoint not found or incomplete: {checkpoint}")

    resolved = resolve_wav2lip_checkpoint(_models_dir())
    if resolved is not None and resolved.stat().st_size >= 50 * 1024 * 1024:
        return resolved.resolve()
    for candidate in DEFAULT_CHECKPOINT_CANDIDATES:
        if candidate.is_file() and candidate.stat().st_size >= 50 * 1024 * 1024:
            return candidate.resolve()
    checked = [str(path) for path in DEFAULT_CHECKPOINT_CANDIDATES]
    raise FileNotFoundError(
        "No usable Wav2Lip checkpoint was found. "
        f"Checked: {checked}"
    )


def ensure_s3fd() -> Path:
    resolved = resolve_wav2lip_s3fd(_models_dir())
    if resolved is not None and resolved.stat().st_size >= 80 * 1024 * 1024:
        return resolved.resolve()
    return _ensure_support_file(
        _models_dir() / "s3fd.pth",
        DEFAULT_S3FD_SOURCES,
        min_bytes=80 * 1024 * 1024,
        label="s3fd face detector checkpoint",
    )


def official_runtime_available() -> bool:
    try:
        import torch  # noqa: F401
        resolve_checkpoint_path()
        ensure_s3fd()
    except Exception:
        return False
    return True


def _mouth_blend_mask(height: int, width: int) -> np.ndarray:
    mask = np.zeros((height, width), dtype=np.float32)
    x1 = int(width * 0.18)
    x2 = int(width * 0.82)
    y1 = int(height * 0.42)
    y2 = int(height * 0.90)
    mask[y1:y2, x1:x2] = 1.0
    blur_w = max(3, ((width // 7) | 1))
    blur_h = max(3, ((height // 7) | 1))
    return np.expand_dims(cv2.GaussianBlur(mask, (blur_w, blur_h), 0), axis=2)


def _blend_mouth_only(pred: np.ndarray, original: np.ndarray) -> np.ndarray:
    mask = _mouth_blend_mask(pred.shape[0], pred.shape[1])
    blended = pred.astype(np.float32) * mask + original.astype(np.float32) * (1.0 - mask)
    return np.clip(blended, 0.0, 255.0).astype(np.uint8)


def _mel_chunks_from_pcm(pcm: np.ndarray, sample_rate: int, fps: int) -> list[np.ndarray]:
    mel = pcm_to_wav2lip_mel(pcm, sample_rate)
    if mel.shape[1] <= 0:
        return []
    mel_chunks: list[np.ndarray] = []
    mel_idx_multiplier = 80.0 / max(1, fps)
    idx = 0
    while True:
        start_idx = int(idx * mel_idx_multiplier)
        if start_idx + MEL_STEP_SIZE > len(mel[0]):
            mel_chunks.append(mel[:, len(mel[0]) - MEL_STEP_SIZE :])
            break
        mel_chunks.append(mel[:, start_idx : start_idx + MEL_STEP_SIZE])
        idx += 1
    return [np.asarray(chunk, dtype=np.float32) for chunk in mel_chunks if chunk.shape[1] == MEL_STEP_SIZE]


def _detect_face_box(
    frame: np.ndarray,
    *,
    detector: FaceAlignment,
    pads: tuple[int, int, int, int],
    box: tuple[int, int, int, int] | None,
) -> tuple[int, int, int, int]:
    if box is not None:
        y1, y2, x1, x2 = box
        return int(y1), int(y2), int(x1), int(x2)
    rects = detector.get_detections_for_batch(np.asarray([frame]))
    if not rects or rects[0] is None:
        raise RuntimeError("Face not detected for wav2lip official runtime")
    rect = rects[0]
    pady1, pady2, padx1, padx2 = pads
    y1 = max(0, int(rect[1]) - pady1)
    y2 = min(frame.shape[0], int(rect[3]) + pady2)
    x1 = max(0, int(rect[0]) - padx1)
    x2 = min(frame.shape[1], int(rect[2]) + padx2)
    return y1, y2, x1, x2


def run_official_inference(
    *,
    avatar_path: Path,
    face_image: Path | None = None,
    pcm: np.ndarray,
    sample_rate: int,
    fps: int,
    ffmpeg_bin: str,
    checkpoint_path: Path | None = None,
    pads: tuple[int, int, int, int] = (0, 10, 0, 0),
    box: tuple[int, int, int, int] | None = None,
    resize_factor: int = 1,
    face_det_batch_size: int = 8,
    wav2lip_batch_size: int = 64,
    nosmooth: bool = False,
) -> tuple[Path, Path, Path]:
    checkpoint = checkpoint_path or resolve_checkpoint_path()
    s3fd_path = ensure_s3fd()
    face_image = face_image.resolve() if face_image is not None else resolve_face_image(avatar_path)
    device = _runtime_device()
    debug_dir = (REPO_ROOT / "debug").resolve()
    debug_dir.mkdir(parents=True, exist_ok=True)

    work_dir = Path(
        tempfile.mkdtemp(prefix="opentalking-wav2lip-live-", dir=str(debug_dir))
    ).resolve()
    wav_path = work_dir / "tts.wav"
    silent_path = work_dir / "rendered_silent.mp4"
    out_path = work_dir / "rendered.mp4"
    _save_wav(wav_path, pcm, sample_rate)
    image = cv2.imread(str(face_image))
    if image is None:
        raise FileNotFoundError(f"Failed to read wav2lip face image: {face_image}")
    if max(1, int(resize_factor)) > 1:
        image = cv2.resize(
            image,
            (image.shape[1] // max(1, int(resize_factor)), image.shape[0] // max(1, int(resize_factor))),
        )

    detector = FaceAlignment(
        LandmarksType._2D,
        flip_input=False,
        device=device,
        path_to_detector=s3fd_path,
    )
    y1, y2, x1, x2 = _detect_face_box(image, detector=detector, pads=pads, box=box)
    face = image[y1:y2, x1:x2].copy()
    if face.size == 0:
        raise RuntimeError(f"Invalid wav2lip crop box: {(y1, y2, x1, x2)}")

    bundle = load_wav2lip_torch(checkpoint, device)
    torch = bundle["torch"]
    model = bundle["model"]
    input_size = int(bundle["input_size"])
    face = cv2.resize(face, (input_size, input_size))
    masked = face.copy()
    masked[input_size // 2 :, :] = 0
    face_input = np.concatenate((masked, face), axis=2).astype(np.float32) / 255.0

    mel_chunks = _mel_chunks_from_pcm(pcm, sample_rate, fps)
    if not mel_chunks:
        raise RuntimeError("No mel chunks generated for wav2lip official runtime")

    writer = cv2.VideoWriter(
        str(silent_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        float(fps),
        (image.shape[1], image.shape[0]),
    )
    if not writer.isOpened():
        raise RuntimeError(f"Failed to open wav2lip video writer: {silent_path}")
    try:
        for start in range(0, len(mel_chunks), max(1, wav2lip_batch_size)):
            batch_chunks = mel_chunks[start : start + max(1, wav2lip_batch_size)]
            face_batch = np.repeat(face_input[None, ...], len(batch_chunks), axis=0)
            mel_batch = np.stack(batch_chunks, axis=0)
            img_batch = torch.FloatTensor(np.transpose(face_batch, (0, 3, 1, 2))).to(device)
            mel_batch_tensor = torch.FloatTensor(
                np.transpose(np.reshape(mel_batch, (len(batch_chunks), 80, MEL_STEP_SIZE, 1)), (0, 3, 1, 2))
            ).to(device)
            with torch.no_grad():
                pred = model(mel_batch_tensor, img_batch)
            pred_np = pred.detach().cpu().numpy().transpose(0, 2, 3, 1) * 255.0
            for patch in pred_np:
                frame = image.copy()
                resized = cv2.resize(np.clip(patch, 0.0, 255.0).astype(np.uint8), (x2 - x1, y2 - y1))
                original = frame[y1:y2, x1:x2].copy()
                frame[y1:y2, x1:x2] = _blend_mouth_only(resized, original)
                writer.write(frame)
    finally:
        writer.release()

    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            str(silent_path),
            "-i",
            str(wav_path),
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "12",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(out_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if not out_path.is_file():
        raise RuntimeError(f"Wav2Lip runtime did not produce output video: {out_path}")
    return work_dir, wav_path, out_path


def load_video_frames(video_path: Path) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open rendered video: {video_path}")
    frames: list[np.ndarray] = []
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frames.append(frame)
    finally:
        cap.release()
    if not frames:
        raise RuntimeError(f"No frames decoded from rendered video: {video_path}")
    return frames
