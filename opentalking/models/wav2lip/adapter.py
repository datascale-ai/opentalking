from __future__ import annotations

import io
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from opentalking.avatar.loader import load_avatar_bundle
from opentalking.avatar.mouth_metadata import image_file_sha256
from opentalking.avatar.wav2lip_config import (
    normalize_wav2lip_postprocess_mode,
    optional_wav2lip_postprocess_mode,
)
from opentalking.core.interfaces.avatar_asset import AvatarManifest
from opentalking.core.types.frames import AudioChunk, VideoFrameData
from opentalking.media.frame_avatar import (
    FrameAvatarState,
    load_frame_avatar_state,
    numpy_bgr_to_videoframe,
    resize_reference_image_to_video,
)
from opentalking.models.registry import register_model


class Wav2LipLocalRuntimeError(RuntimeError):
    """Raised when the local Wav2Lip runtime is unavailable."""


@dataclass
class Wav2LipFeatures:
    pcm_s16le: bytes
    sample_rate: int
    duration_ms: float
    frame_count: int
    vector: np.ndarray
    frame_energy: np.ndarray


@dataclass(frozen=True)
class Wav2LipPrediction:
    frame: np.ndarray
    timestamp_ms: float


@dataclass(frozen=True)
class _LegacyWav2LipPrediction:
    base_frame_index: int
    openness: float


@dataclass
class _Wav2LipLocalState:
    manifest: AvatarManifest
    avatar_path: Path
    session: Any
    runtime: Any
    emitted_frames: int = 0
    extra: dict[str, Any] | None = None


def _load_reference_frame(avatar_path: Path, manifest: AvatarManifest) -> np.ndarray:
    for name in ("reference.png", "reference.jpg", "reference.jpeg", "preview.png"):
        candidate = avatar_path / name
        if candidate.is_file():
            image = Image.open(candidate).convert("RGB")
            image = resize_reference_image_to_video(
                image,
                width=int(manifest.width),
                height=int(manifest.height),
            )
            return np.asarray(image, dtype=np.uint8)[:, :, ::-1].copy()
    raise FileNotFoundError(f"Expected reference image under {avatar_path}")


def _load_legacy_avatar_state(avatar_path: Path, manifest: AvatarManifest) -> FrameAvatarState:
    try:
        state = load_frame_avatar_state(avatar_path, manifest)
    except (FileNotFoundError, ValueError):
        frame = _load_reference_frame(avatar_path, manifest)
        state = FrameAvatarState(
            manifest=manifest,
            frames=[frame],
            avatar_path=avatar_path.resolve(),
            frame_paths=[],
        )
    metadata = manifest.metadata or {}
    state.extra.update(
        {
            "animation": metadata.get("animation") if isinstance(metadata.get("animation"), dict) else {},
            "idle_mode": str(metadata.get("idle_mode") or "static").strip().lower(),
            "wav2lip_prev_open": 0.0,
            "wav2lip_prev_frame_pos": 0.0,
            "legacy_fallback": True,
        }
    )
    return state


def _frame_count(audio_chunk: AudioChunk, fps: float) -> int:
    pcm = np.asarray(audio_chunk.data, dtype=np.int16).reshape(-1)
    if pcm.size and audio_chunk.sample_rate > 0:
        duration_s = pcm.size / float(audio_chunk.sample_rate)
    else:
        duration_s = max(0.001, float(audio_chunk.duration_ms) / 1000.0)
    return max(1, int(np.ceil(duration_s * max(1.0, fps))))


def _frame_energy(audio_chunk: AudioChunk, frame_count: int, fps: float) -> np.ndarray:
    pcm = np.asarray(audio_chunk.data, dtype=np.int16).reshape(-1)
    if pcm.size == 0:
        return np.zeros(frame_count, dtype=np.float32)
    samples_per_frame = max(1.0, float(audio_chunk.sample_rate) / max(1.0, fps))
    energies: list[float] = []
    for idx in range(frame_count):
        start = int(round(idx * samples_per_frame))
        end = int(round((idx + 1) * samples_per_frame))
        segment = pcm[start:end]
        if segment.size == 0:
            energies.append(0.0)
            continue
        rms = float(np.sqrt(np.mean(segment.astype(np.float32) ** 2)))
        energies.append(min(1.0, rms / 3600.0))
    if not energies:
        return np.zeros(frame_count, dtype=np.float32)
    energy = np.asarray(energies, dtype=np.float32)
    peak = float(np.max(energy))
    if peak > 0.25:
        energy = np.clip(energy / peak, 0.0, 1.0).astype(np.float32)
    return energy


def _point_to_xy(point: Any, width: int, height: int) -> tuple[float, float] | None:
    if not isinstance(point, (list, tuple)) or len(point) < 2:
        return None
    try:
        return float(point[0]) * width, float(point[1]) * height
    except (TypeError, ValueError):
        return None


def _animation_center(animation: dict[str, Any], width: int, height: int) -> tuple[float, float]:
    center = _point_to_xy(animation.get("mouth_center"), width, height)
    if center is not None:
        return center
    return width * 0.5, height * 0.62


def _draw_audio_mouth(frame_bgr: np.ndarray, animation: dict[str, Any], openness: float) -> np.ndarray:
    open_amount = float(np.clip(openness, 0.0, 1.0))
    if open_amount <= 0.02:
        return frame_bgr

    height, width = frame_bgr.shape[:2]
    cx, cy = _animation_center(animation, width, height)
    rx = float(animation.get("mouth_rx") or 0.045) * width
    ry = float(animation.get("mouth_ry") or 0.018) * height
    rx = max(6.0, rx * (1.0 + 0.16 * open_amount))
    ry = max(3.0, ry * (0.7 + 3.2 * open_amount))

    rgb = Image.fromarray(frame_bgr[:, :, ::-1], mode="RGB").convert("RGBA")
    overlay = Image.new("RGBA", rgb.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    inner_points = animation.get("inner_mouth")
    polygon: list[tuple[float, float]] = []
    if isinstance(inner_points, list):
        for point in inner_points:
            xy = _point_to_xy(point, width, height)
            if xy is None:
                continue
            x, y = xy
            polygon.append((x, cy + (y - cy) * (1.0 + 3.0 * open_amount)))
    if len(polygon) >= 3:
        draw.polygon(polygon, fill=(18, 8, 10, 185))
    else:
        draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=(18, 8, 10, 185))

    highlight_y = cy - ry * 0.75
    draw.arc(
        (cx - rx * 1.06, highlight_y - ry * 0.5, cx + rx * 1.06, highlight_y + ry * 0.6),
        start=8,
        end=172,
        fill=(130, 70, 76, int(80 + 70 * open_amount)),
        width=max(1, int(min(width, height) * 0.004)),
    )
    composed = Image.alpha_composite(rgb, overlay).convert("RGB")
    return np.asarray(composed, dtype=np.uint8)[:, :, ::-1].copy()


def _env_bool(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _first_reference_image(avatar_path: Path) -> Path:
    for name in ("reference.png", "reference.jpg", "reference.jpeg", "reference.webp", "preview.png"):
        path = avatar_path / name
        if path.is_file():
            return path
    raise Wav2LipLocalRuntimeError(f"Missing Wav2Lip reference image under {avatar_path}")


def _read_manifest_metadata(manifest: AvatarManifest) -> dict[str, Any]:
    metadata = manifest.metadata
    return metadata if isinstance(metadata, dict) else {}


def _resolve_avatar_child(avatar_path: Path, raw: object, *, must_be_file: bool = False) -> Path | None:
    value = str(raw or "").strip()
    if not value:
        return None
    path = (avatar_path / value).resolve()
    try:
        path.relative_to(avatar_path.resolve())
    except ValueError:
        return None
    if must_be_file:
        return path if path.is_file() else None
    return path if path.exists() else None


def _mouth_metadata(avatar_path: Path, manifest: AvatarManifest) -> dict[str, Any]:
    metadata = _read_manifest_metadata(manifest)
    animation = metadata.get("animation")
    if not isinstance(animation, dict):
        return {}
    source_image_hash = metadata.get("source_image_hash")
    if source_image_hash:
        try:
            if image_file_sha256(_first_reference_image(avatar_path)) != source_image_hash:
                return {}
        except Exception:
            return {}
    return {
        "source_image_hash": source_image_hash,
        "source_image_path": metadata.get("source_image_path"),
        "face_box": metadata.get("face_box"),
        "animation": animation,
    }


def _video_config(manifest: AvatarManifest) -> dict[str, int]:
    return {
        "fps": int(manifest.fps),
        "width": int(manifest.width),
        "height": int(manifest.height),
    }


def _frame_reference_config(avatar_path: Path, manifest: AvatarManifest) -> dict[str, Any]:
    metadata = _read_manifest_metadata(manifest)
    mode = str(metadata.get("reference_mode") or "").strip().lower()
    if mode != "frames":
        return {"reference_mode": "image"}
    frame_dir = _resolve_avatar_child(avatar_path, metadata.get("frame_dir") or "frames")
    if frame_dir is None or not frame_dir.is_dir():
        return {"reference_mode": "image"}
    config: dict[str, Any] = {
        "reference_mode": "frames",
        "ref_frame_dir": str(frame_dir),
        "preprocessed": bool(metadata.get("preprocessed")),
    }
    metadata_path = _resolve_avatar_child(
        avatar_path,
        metadata.get("frame_metadata"),
        must_be_file=True,
    )
    if metadata_path is not None:
        config["ref_frame_metadata_path"] = str(metadata_path)
    return config


def _postprocess_mode(manifest: AvatarManifest, *, override: str | None = None) -> str:
    override_mode = optional_wav2lip_postprocess_mode(override)
    if override_mode is not None:
        return override_mode
    raw = os.environ.get("OPENTALKING_WAV2LIP_POSTPROCESS_MODE", "easy_improved")
    metadata = _read_manifest_metadata(manifest)
    preferred = metadata.get("preferred_wav2lip_postprocess_mode")
    return normalize_wav2lip_postprocess_mode(preferred or raw)


def _decode_jpeg_sequence(payload: bytes) -> list[np.ndarray]:
    try:
        from opentalking.models.wav2lip.realtime import decode_jpeg_sequence
    except Exception as exc:
        raise Wav2LipLocalRuntimeError("Wav2Lip decode_jpeg_sequence is unavailable.") from exc

    frames: list[np.ndarray] = []
    for jpeg in decode_jpeg_sequence(payload):
        image = Image.open(io.BytesIO(jpeg)).convert("RGB")
        frames.append(np.asarray(image, dtype=np.uint8)[:, :, ::-1].copy())
    return frames


def _build_wav2lip_session(
    avatar_path: Path,
    manifest: AvatarManifest,
    runtime: Any,
    *,
    postprocess_mode_override: str | None = None,
) -> _Wav2LipLocalState:
    try:
        from opentalking.models.wav2lip.realtime import RealtimeAvatarService
    except Exception as exc:
        raise Wav2LipLocalRuntimeError(
            "Wav2Lip runtime is required for OPENTALKING_WAV2LIP_BACKEND=local. "
            "Install OpenTalking with the models extra and provide wav2lip384.pth/s3fd.pth."
        ) from exc

    ref_image = _first_reference_image(avatar_path)
    video_config = _video_config(manifest)
    frame_config = _frame_reference_config(avatar_path, manifest)
    config: dict[str, object] = {
        **video_config,
        "wav2lip_postprocess_mode": _postprocess_mode(manifest, override=postprocess_mode_override),
        "mouth_metadata": _mouth_metadata(avatar_path, manifest),
    }
    if frame_config.get("reference_mode"):
        config["reference_mode"] = frame_config["reference_mode"]
    if frame_config.get("ref_frame_dir"):
        config["ref_frame_dir"] = frame_config["ref_frame_dir"]
    if frame_config.get("ref_frame_metadata_path"):
        config["ref_frame_metadata_path"] = frame_config["ref_frame_metadata_path"]
    if frame_config.get("reference_mode") == "frames":
        config["prepared_cache_dir"] = str((avatar_path / "wav2lip").resolve())
    if frame_config.get("preprocessed") is not None:
        config["preprocessed"] = bool(frame_config.get("preprocessed"))

    service = RealtimeAvatarService(runtime=runtime, allowed_frame_roots=[avatar_path])
    session = service.create_session(
        model="wav2lip",
        backend="local",
        prompt="",
        image_bytes=ref_image.read_bytes(),
        config=config,
    )
    preload_result = None
    if frame_config.get("reference_mode") == "frames" and hasattr(runtime, "preload_reference"):
        preload_result = runtime.preload_reference(session)
    else:
        runtime._session_state(session)
    return _Wav2LipLocalState(
        manifest=manifest,
        avatar_path=avatar_path,
        session=session,
        runtime=runtime,
        extra={
            "idle_mode": str(_read_manifest_metadata(manifest).get("idle_mode") or "static").lower(),
            "reference_mode": frame_config.get("reference_mode"),
            "ref_frame_dir": frame_config.get("ref_frame_dir"),
            "ref_frame_metadata_path": frame_config.get("ref_frame_metadata_path"),
            "prepared_cache_dir": config.get("prepared_cache_dir"),
            "preprocessed": bool(frame_config.get("preprocessed")),
            "wav2lip_postprocess_mode": session.wav2lip_postprocess_mode,
            "video_width": session.video.width,
            "video_height": session.video.height,
            "video_fps": session.video.fps,
            "preload_result": preload_result,
        },
    )


def _configure_runtime_checkpoint(runtime: Any) -> bool:
    checkpoint = getattr(runtime, "checkpoint", None)
    if isinstance(checkpoint, Path) and checkpoint.is_file():
        return True
    try:
        from opentalking.models.wav2lip.loader import resolve_wav2lip_checkpoint
    except Exception:
        return False
    models_dir = getattr(runtime, "models_dir", None)
    if not isinstance(models_dir, Path):
        return False
    resolved = resolve_wav2lip_checkpoint(models_dir)
    if resolved is None:
        return False
    runtime.checkpoint = resolved
    return True


@register_model("wav2lip")
class Wav2LipAdapter:
    """Local Wav2Lip adapter backed by OpenTalking's in-process runtime."""

    model_type = "wav2lip"

    def __init__(self) -> None:
        self._device = "cuda"
        self._runtime: Any | None = None
        self._legacy_fallback = _env_bool("OPENTALKING_WAV2LIP_LEGACY_LOCAL_FALLBACK")
        self._postprocess_mode_override: str | None = None

    @staticmethod
    def runtime_available() -> bool:
        if _env_bool("OPENTALKING_WAV2LIP_LEGACY_LOCAL_FALLBACK"):
            return True
        try:
            import torch

            from opentalking.models.wav2lip.loader import _resolve_torch_device, resolve_wav2lip_s3fd
            from opentalking.models.wav2lip.runtime import Wav2LipRealtimeRuntime

            runtime = Wav2LipRealtimeRuntime(device=os.environ.get("OPENTALKING_WAV2LIP_DEVICE", "cpu"))
            _resolve_torch_device(torch, runtime.device)
            if not _configure_runtime_checkpoint(runtime):
                return False
            if resolve_wav2lip_s3fd(runtime.models_dir) is None:
                return False
        except Exception:
            return False
        return True

    def load_model(self, device: str = "cuda") -> None:
        self._device = device
        if self._legacy_fallback:
            return
        try:
            from opentalking.models.wav2lip.runtime import Wav2LipRealtimeRuntime
        except Exception as exc:
            raise Wav2LipLocalRuntimeError(
                "Wav2Lip runtime is required for local Wav2Lip parity. "
                "Install OpenTalking with the models extra and provide wav2lip384.pth/s3fd.pth."
            ) from exc
        runtime_device = os.environ.get("OPENTALKING_WAV2LIP_DEVICE") or device
        self._runtime = Wav2LipRealtimeRuntime(device=runtime_device)
        if not _configure_runtime_checkpoint(self._runtime):
            raise Wav2LipLocalRuntimeError(
                "Wav2Lip checkpoint not found. Set OPENTALKING_WAV2LIP_MODEL_ROOT to a directory "
                "containing wav2lip384.pth/s3fd.pth, or set OPENTALKING_WAV2LIP_CHECKPOINT explicitly."
            )

    def set_wav2lip_postprocess_mode(self, mode: str | None) -> None:
        self._postprocess_mode_override = optional_wav2lip_postprocess_mode(mode)

    def load_avatar(self, avatar_path: str) -> _Wav2LipLocalState | FrameAvatarState:
        bundle = load_avatar_bundle(Path(avatar_path), strict=False)
        if self._legacy_fallback:
            return _load_legacy_avatar_state(bundle.path, bundle.manifest)
        if self._runtime is None:
            self.load_model(self._device)
        assert self._runtime is not None
        return _build_wav2lip_session(
            bundle.path,
            bundle.manifest,
            self._runtime,
            postprocess_mode_override=self._postprocess_mode_override,
        )

    def warmup(self, avatar_state: Any | None = None) -> None:
        if self._legacy_fallback or not isinstance(avatar_state, _Wav2LipLocalState):
            return
        runtime_state = avatar_state.runtime._session_state(avatar_state.session)
        previous_adapter_frames = avatar_state.emitted_frames
        previous_runtime_frames = getattr(runtime_state, "emitted_frames", 0)
        previous_pcm_history = getattr(runtime_state, "pcm_history", None)
        if isinstance(previous_pcm_history, np.ndarray):
            previous_pcm_history = previous_pcm_history.copy()
        sample_rate = int(getattr(avatar_state.session.audio, "sample_rate", 16000) or 16000)
        samples = max(3200, sample_rate // 4)
        silence = np.zeros(samples, dtype=np.int16).tobytes()
        try:
            avatar_state.runtime.render_chunk(avatar_state.session, silence)
        finally:
            avatar_state.emitted_frames = previous_adapter_frames
            if hasattr(runtime_state, "emitted_frames"):
                runtime_state.emitted_frames = previous_runtime_frames
            if hasattr(runtime_state, "pcm_history"):
                runtime_state.pcm_history = previous_pcm_history

    def extract_features(self, audio_chunk: AudioChunk) -> Wav2LipFeatures:
        fps = 25.0
        count = _frame_count(audio_chunk, fps)
        energy = _frame_energy(audio_chunk, count, fps)
        pcm = np.asarray(audio_chunk.data, dtype=np.int16).reshape(-1).copy()
        return Wav2LipFeatures(
            pcm_s16le=pcm.tobytes(),
            sample_rate=int(audio_chunk.sample_rate),
            duration_ms=float(audio_chunk.duration_ms),
            frame_count=count,
            vector=energy.reshape(-1, 1),
            frame_energy=energy,
        )

    def extract_features_for_stream(
        self,
        audio_chunk: AudioChunk,
        avatar_state: _Wav2LipLocalState | FrameAvatarState,
    ) -> Wav2LipFeatures:
        fps = float(max(1, int(avatar_state.manifest.fps)))
        count = _frame_count(audio_chunk, fps)
        energy = _frame_energy(audio_chunk, count, fps)
        pcm = np.asarray(audio_chunk.data, dtype=np.int16).reshape(-1).copy()
        return Wav2LipFeatures(
            pcm_s16le=pcm.tobytes(),
            sample_rate=int(audio_chunk.sample_rate),
            duration_ms=float(audio_chunk.duration_ms),
            frame_count=count,
            vector=energy.reshape(-1, 1),
            frame_energy=energy,
        )

    def infer(
        self,
        features: Wav2LipFeatures,
        avatar_state: _Wav2LipLocalState | FrameAvatarState,
    ) -> list[Wav2LipPrediction | _LegacyWav2LipPrediction]:
        if isinstance(avatar_state, FrameAvatarState):
            return self._infer_legacy(features, avatar_state)
        payload = avatar_state.runtime.render_chunk(avatar_state.session, features.pcm_s16le)
        frames = _decode_jpeg_sequence(payload)
        predictions: list[Wav2LipPrediction | _LegacyWav2LipPrediction] = []
        fps = max(1.0, float(avatar_state.manifest.fps))
        for frame in frames:
            predictions.append(
                Wav2LipPrediction(
                    frame=frame,
                    timestamp_ms=avatar_state.emitted_frames * (1000.0 / fps),
                )
            )
            avatar_state.emitted_frames += 1
        return predictions

    def _infer_legacy(
        self,
        features: Wav2LipFeatures,
        avatar_state: FrameAvatarState,
    ) -> list[Wav2LipPrediction | _LegacyWav2LipPrediction]:
        extra = avatar_state.extra
        frame_index_start = int(extra.get("frame_index_start", 0) or 0)
        prev_open = float(extra.get("wav2lip_prev_open", 0.0) or 0.0)
        predictions: list[Wav2LipPrediction | _LegacyWav2LipPrediction] = []
        frame_total = max(1, len(avatar_state.frames))
        for offset, energy in enumerate(np.asarray(features.frame_energy, dtype=np.float32).reshape(-1)):
            target = float(np.clip(energy, 0.0, 1.0))
            prev_open = (prev_open * 0.55) + (target * 0.45)
            base_idx = (frame_index_start + offset) % frame_total
            predictions.append(_LegacyWav2LipPrediction(base_frame_index=base_idx, openness=prev_open))
        extra["wav2lip_prev_open"] = prev_open
        return predictions

    def compose_frame(
        self,
        avatar_state: _Wav2LipLocalState | FrameAvatarState,
        frame_idx: int,
        prediction: Any,
    ) -> VideoFrameData:
        if isinstance(prediction, Wav2LipPrediction):
            h, w = prediction.frame.shape[:2]
            return VideoFrameData(
                data=prediction.frame,
                width=w,
                height=h,
                timestamp_ms=prediction.timestamp_ms,
            )
        if isinstance(avatar_state, FrameAvatarState) and isinstance(prediction, _LegacyWav2LipPrediction):
            base = avatar_state.frames[prediction.base_frame_index % len(avatar_state.frames)].copy()
            animation = avatar_state.extra.get("animation")
            if isinstance(animation, dict):
                base = _draw_audio_mouth(base, animation, prediction.openness)
            return numpy_bgr_to_videoframe(base, self._timestamp_ms(avatar_state, frame_idx))
        return self.idle_frame(avatar_state, frame_idx)

    def idle_frame(
        self,
        avatar_state: _Wav2LipLocalState | FrameAvatarState,
        frame_idx: int,
    ) -> VideoFrameData:
        if isinstance(avatar_state, _Wav2LipLocalState):
            state = avatar_state.runtime._session_state(avatar_state.session)
            prepared = state.frame_at(frame_idx)
            frame = prepared.base_frame.copy()
            return numpy_bgr_to_videoframe(frame, self._timestamp_ms(avatar_state, frame_idx))
        idle_mode = str(avatar_state.extra.get("idle_mode") or "static").strip().lower()
        if idle_mode == "loop" and len(avatar_state.frames) > 1:
            frame = avatar_state.frames[frame_idx % len(avatar_state.frames)].copy()
        else:
            frame = avatar_state.frames[0].copy()
        return numpy_bgr_to_videoframe(frame, self._timestamp_ms(avatar_state, frame_idx))

    @staticmethod
    def _timestamp_ms(avatar_state: _Wav2LipLocalState | FrameAvatarState, frame_idx: int) -> float:
        fps = max(1.0, float(avatar_state.manifest.fps))
        return frame_idx * (1000.0 / fps)
