from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from opentalking.avatars.loader import load_avatar_bundle
from opentalking.core.types.frames import AudioChunk, VideoFrameData
from opentalking.models.common.frame_avatar import (
    FrameAvatarState,
    load_frame_avatar_state,
    load_preview_frame,
    numpy_bgr_to_videoframe,
)
from opentalking.models.registry import register_model
from opentalking.models.wav2lip.feature_extractor import (
    Wav2LipStreamFeatures,
    Wav2LipTestFeatures,
    extract_mel_for_wav2lip,
    extract_stream_mel_chunks,
)
from opentalking.models.wav2lip.loader import (
    ensure_wav2lip_imports,
    load_wav2lip_torch,
    resolve_wav2lip_checkpoint,
    resolve_wav2lip_s3fd,
)

log = logging.getLogger(__name__)


def _is_generic_frame_sequence(frame_paths: list[Path]) -> bool:
    if len(frame_paths) <= 1:
        return False
    return all(path.stem.lower().startswith("frame_") for path in frame_paths)


@dataclass(frozen=True)
class _AvatarLandmarks:
    mouth_center: tuple[int, int]
    mouth_rx: int
    mouth_ry: int


@dataclass(frozen=True)
class _NeuralFaceState:
    base_frame: np.ndarray
    coords: tuple[int, int, int, int]
    face_input: np.ndarray


@dataclass(frozen=True)
class _NeuralPrediction:
    patch: np.ndarray
    coords: tuple[int, int, int, int]


def _weighted_center(mask: np.ndarray) -> tuple[float, float, float, float] | None:
    if mask.size == 0:
        return None
    weights = mask.astype(np.float32)
    total = float(weights.sum())
    if total <= 1e-3:
        return None
    yy, xx = np.indices(mask.shape, dtype=np.float32)
    cx = float((xx * weights).sum() / total)
    cy = float((yy * weights).sum() / total)
    var_x = float(((xx - cx) ** 2 * weights).sum() / total)
    var_y = float(((yy - cy) ** 2 * weights).sum() / total)
    return cx, cy, float(np.sqrt(max(0.0, var_x))), float(np.sqrt(max(0.0, var_y)))


def _estimate_avatar_landmarks(frame: np.ndarray) -> _AvatarLandmarks:
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    darkness = np.clip(185.0 - gray, 0.0, 185.0)
    darkness = cv2.GaussianBlur(darkness, (0, 0), 3.0)

    def _region_center(
        x1_ratio: float,
        x2_ratio: float,
        y1_ratio: float,
        y2_ratio: float,
        fallback: tuple[float, float],
    ) -> tuple[int, int, float, float]:
        x1 = int(w * x1_ratio)
        x2 = int(w * x2_ratio)
        y1 = int(h * y1_ratio)
        y2 = int(h * y2_ratio)
        region = darkness[y1:y2, x1:x2]
        center = _weighted_center(region)
        if center is None:
            return (
                int(w * fallback[0]),
                int(h * fallback[1]),
                max(6.0, w * 0.028),
                max(5.0, h * 0.022),
            )
        cx, cy, sx, sy = center
        return x1 + int(round(cx)), y1 + int(round(cy)), max(6.0, sx), max(5.0, sy)

    mouth_x, mouth_y, mouth_sx, mouth_sy = _region_center(
        0.24,
        0.76,
        0.36,
        0.74,
        (0.50, 0.56),
    )
    return _AvatarLandmarks(
        mouth_center=(mouth_x, mouth_y),
        mouth_rx=max(14, int(mouth_sx * 1.75)),
        mouth_ry=max(6, int(mouth_sy * 0.85)),
    )


def _landmarks_from_metadata(manifest: Any, frame: np.ndarray) -> _AvatarLandmarks | None:
    metadata = getattr(manifest, "metadata", None) or {}
    animation = metadata.get("animation")
    if not isinstance(animation, dict):
        return None

    def _point(name: str, fallback: tuple[float, float]) -> tuple[int, int]:
        raw = animation.get(name)
        if isinstance(raw, (list, tuple)) and len(raw) == 2:
            x = float(raw[0])
            y = float(raw[1])
        else:
            x, y = fallback
        h, w = frame.shape[:2]
        return int(round(w * x)), int(round(h * y))

    def _scalar(name: str, fallback: float, size: int) -> int:
        raw = animation.get(name)
        value = float(raw) if isinstance(raw, (int, float)) else fallback
        return max(1, int(round(size * value)))

    h, w = frame.shape[:2]
    return _AvatarLandmarks(
        mouth_center=_point("mouth_center", (0.50, 0.56)),
        mouth_rx=_scalar("mouth_rx", 0.06, w),
        mouth_ry=_scalar("mouth_ry", 0.02, h),
    )


def _max_frame_delta(frames: list[np.ndarray]) -> float:
    if len(frames) <= 1:
        return 0.0
    base = frames[0].astype(np.int16)
    deltas = [
        float(np.mean(np.abs(frame.astype(np.int16) - base), dtype=np.float32))
        for frame in frames[1:]
    ]
    return max(deltas) if deltas else 0.0


def _ellipse_mask(shape: tuple[int, int], center: tuple[int, int], rx: int, ry: int) -> np.ndarray:
    yy, xx = np.ogrid[:shape[0], :shape[1]]
    return ((xx - center[0]) / max(1, rx)) ** 2 + ((yy - center[1]) / max(1, ry)) ** 2 <= 1.0


def _rescale_box(
    coords: tuple[int, int, int, int],
    *,
    frame_shape: tuple[int, int],
    scale: float,
    center_y_bias: float = 0.0,
) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = coords
    h, w = frame_shape
    box_w = max(1.0, float(x2 - x1))
    box_h = max(1.0, float(y2 - y1))
    cx = (float(x1) + float(x2)) * 0.5
    cy = (float(y1) + float(y2)) * 0.5 + box_h * float(center_y_bias)
    new_w = max(2.0, box_w * float(scale))
    new_h = max(2.0, box_h * float(scale))
    nx1 = int(round(cx - new_w * 0.5))
    nx2 = int(round(cx + new_w * 0.5))
    ny1 = int(round(cy - new_h * 0.5))
    ny2 = int(round(cy + new_h * 0.5))
    nx1 = max(0, nx1)
    ny1 = max(0, ny1)
    nx2 = min(w, nx2)
    ny2 = min(h, ny2)
    if nx2 <= nx1:
        nx2 = min(w, nx1 + 2)
    if ny2 <= ny1:
        ny2 = min(h, ny1 + 2)
    return nx1, ny1, nx2, ny2


def _apply_synthetic_mouth(frame: np.ndarray, landmarks: _AvatarLandmarks, amount: float) -> np.ndarray:
    amount = float(np.clip(amount, 0.0, 1.0))
    out = frame.copy()
    mouth_rx = max(8, int(landmarks.mouth_rx * (0.96 + 0.34 * amount)))
    mouth_ry = max(1, int(landmarks.mouth_ry * (0.58 + 3.4 * amount)))
    mouth_mask = _ellipse_mask(out.shape[:2], landmarks.mouth_center, mouth_rx, mouth_ry)
    inner = np.array([22, 18, 48], dtype=np.uint8)
    out[mouth_mask] = (
        out[mouth_mask].astype(np.uint16) * 1 // 4 + inner.astype(np.uint16) * 3 // 4
    ).astype(np.uint8)

    if amount > 0.16:
        lip_band = _ellipse_mask(
            out.shape[:2],
            (landmarks.mouth_center[0], landmarks.mouth_center[1] - max(1, mouth_ry // 3)),
            max(6, int(mouth_rx * 0.94)),
            max(1, int(mouth_ry * 0.24)),
        )
        out[lip_band] = (
            out[lip_band].astype(np.uint16) * 1 // 2
            + np.array([44, 40, 112], dtype=np.uint16) * 1 // 2
        ).astype(np.uint8)

    if amount > 0.34:
        teeth_mask = _ellipse_mask(
            out.shape[:2],
            (
                landmarks.mouth_center[0],
                landmarks.mouth_center[1] - max(1, int(mouth_ry * 0.24)),
            ),
            max(5, int(mouth_rx * 0.66)),
            max(1, int(mouth_ry * 0.22)),
        )
        teeth = np.array([236, 238, 244], dtype=np.uint8)
        out[teeth_mask & mouth_mask] = (
            out[teeth_mask & mouth_mask].astype(np.uint16) * 1 // 5
            + teeth.astype(np.uint16) * 4 // 5
        ).astype(np.uint8)

    if amount > 0.56:
        tongue_mask = _ellipse_mask(
            out.shape[:2],
            (landmarks.mouth_center[0], landmarks.mouth_center[1] + max(1, mouth_ry // 4)),
            max(4, int(mouth_rx * 0.46)),
            max(2, int(mouth_ry * 0.40)),
        )
        out[tongue_mask & mouth_mask] = np.array([92, 80, 188], dtype=np.uint8)
    return out


def _mouth_blend_mask(height: int, width: int) -> np.ndarray:
    mask = np.zeros((height, width), dtype=np.float32)
    x1 = int(width * 0.14)
    x2 = int(width * 0.86)
    y1 = int(height * 0.34)
    y2 = int(height * 0.92)
    mask[y1:y2, x1:x2] = 0.92
    lower_y1 = int(height * 0.50)
    lower_y2 = int(height * 0.94)
    lower_x1 = int(width * 0.20)
    lower_x2 = int(width * 0.80)
    mask[lower_y1:lower_y2, lower_x1:lower_x2] = 1.0
    blur_w = max(3, ((width // 7) | 1))
    blur_h = max(3, ((height // 7) | 1))
    mask = cv2.GaussianBlur(mask, (blur_w, blur_h), 0)
    return np.expand_dims(mask, axis=2)


def _blend_mouth_only(pred: np.ndarray, original: np.ndarray) -> np.ndarray:
    mask = _mouth_blend_mask(pred.shape[0], pred.shape[1])
    mask = np.clip(mask * 1.15, 0.0, 1.0)
    blended = pred.astype(np.float32) * mask + original.astype(np.float32) * (1.0 - mask)
    return np.clip(blended, 0.0, 255.0).astype(np.uint8)


def _runtime_preview_frame(preview: np.ndarray, frames: list[np.ndarray]) -> np.ndarray:
    """Use the actual avatar frame for single-frame avatars.

    A separate preview.png is useful for the selection UI, but when there is only one
    inference frame it can badly mismatch the talking-head base image. That makes the
    neural crop / paste path look unstable because inference runs against one image while
    the runtime composes onto another. Keep runtime speaking on the exact frame asset.
    """
    if len(frames) == 1 and isinstance(frames[0], np.ndarray):
        return frames[0].copy()
    return preview


@register_model("wav2lip")
class Wav2LipAdapter:
    model_type = "wav2lip"

    def __init__(self) -> None:
        self._device = os.environ.get("OPENTALKING_TORCH_DEVICE", "cuda")
        self._models_dir = Path(os.environ.get("OPENTALKING_MODELS_DIR", "./models")).resolve()
        self._torch_bundle: dict[str, Any] | None = None
        self._fps = int(os.environ.get("OPENTALKING_DEFAULT_FPS", "25"))
        self._prefer_neural = os.environ.get("OPENTALKING_WAV2LIP_USE_NEURAL", "1") != "0"
        self._force_static = os.environ.get("OPENTALKING_WAV2LIP_FORCE_STATIC", "1") != "0"
        self._min_context_frames = int(os.environ.get("OPENTALKING_WAV2LIP_MIN_CONTEXT_FRAMES", "8"))
        self._batch_size = int(os.environ.get("OPENTALKING_WAV2LIP_STREAM_BATCH_SIZE", "8"))
        self._pads = self._parse_pads(os.environ.get("OPENTALKING_WAV2LIP_PADS", "0,10,0,0"))
        self._face_detector: Any = None
        self._neural_warmed_up = False
        self._model_input_size = 96
        self._face_box_scale = float(os.environ.get("OPENTALKING_WAV2LIP_FACE_BOX_SCALE", "0.86"))
        self._face_box_center_y_bias = float(
            os.environ.get("OPENTALKING_WAV2LIP_FACE_BOX_CENTER_Y_BIAS", "0.02")
        )
        self._attack = float(os.environ.get("OPENTALKING_WAV2LIP_ATTACK", "0.72"))
        self._release = float(os.environ.get("OPENTALKING_WAV2LIP_RELEASE", "0.38"))
        self._max_step_up = float(os.environ.get("OPENTALKING_WAV2LIP_MAX_STEP_UP", "0.080"))
        self._max_step_down = float(os.environ.get("OPENTALKING_WAV2LIP_MAX_STEP_DOWN", "0.060"))
        self._frame_step_up = float(os.environ.get("OPENTALKING_WAV2LIP_FRAME_STEP_UP", "1.50"))
        self._frame_step_down = float(os.environ.get("OPENTALKING_WAV2LIP_FRAME_STEP_DOWN", "1.10"))

    @staticmethod
    def _parse_pads(raw: str) -> tuple[int, int, int, int]:
        parts = [part.strip() for part in raw.split(",")]
        if len(parts) != 4:
            return (0, 10, 0, 0)
        try:
            return tuple(int(part) for part in parts)  # type: ignore[return-value]
        except ValueError:
            return (0, 10, 0, 0)

    def load_model(self, device: str = "cuda") -> None:
        self._device = device
        ckpt = resolve_wav2lip_checkpoint(self._models_dir)
        if not self._prefer_neural or ckpt is None:
            self._torch_bundle = None
            self._model_input_size = 96
            return
        self._torch_bundle = load_wav2lip_torch(ckpt, device)
        self._model_input_size = int(self._torch_bundle.get("input_size", 96))

    def load_avatar(self, avatar_path: str) -> FrameAvatarState:
        bundle = load_avatar_bundle(Path(avatar_path))
        if bundle.manifest.model_type != "wav2lip":
            raise ValueError(
                f"Avatar {bundle.manifest.id} model_type={bundle.manifest.model_type}, expected wav2lip"
            )
        self._fps = bundle.manifest.fps
        state = load_frame_avatar_state(bundle.path, bundle.manifest)
        frame_scores = self._estimate_frame_mouth_scores(state.frames)
        order = np.argsort(frame_scores).astype(np.int32)
        landmarks = _landmarks_from_metadata(bundle.manifest, state.frames[0]) or _estimate_avatar_landmarks(state.frames[0])
        metadata = getattr(bundle.manifest, "metadata", None) or {}
        preview = _runtime_preview_frame(
            load_preview_frame(bundle.path, state.frames[0], bundle.manifest),
            state.frames,
        )
        idle_mode = str(metadata.get("idle_mode", "")).strip().lower()
        static_override = idle_mode in {"static", "hold", "first_frame"}
        loop_override = idle_mode in {"loop", "cycle", "frames", "full_frames"}
        generic_sequence = _is_generic_frame_sequence(state.frame_paths)
        static_avatar = static_override or (
            not loop_override
            and not generic_sequence
            and (self._force_static or (_max_frame_delta(state.frames) < 0.75))
        )
        state.extra["wav2lip_static_avatar"] = static_avatar
        state.extra["wav2lip_test_frame_order"] = order.tolist()
        state.extra["wav2lip_test_frame_scores"] = frame_scores.astype(np.float32).tolist()
        state.extra["wav2lip_prev_open"] = 0.0
        state.extra["wav2lip_prev_frame_pos"] = 0.0
        state.extra["wav2lip_landmarks"] = landmarks
        state.extra["preview_frame"] = preview
        state.extra["freeze_speaking_to_preview"] = bool(
            metadata.get("freeze_speaking_to_preview", False)
        )
        state.extra["wav2lip_stream_pcm"] = np.zeros(0, dtype=np.int16)
        state.extra["wav2lip_stream_lookahead_pcm"] = np.zeros(0, dtype=np.int16)
        state.extra["wav2lip_stream_emitted_frames"] = 0
        state.extra["wav2lip_neural_enabled"] = False

        should_enable_neural = bool(
            self._torch_bundle is not None
            and (
                state.extra.get("wav2lip_static_avatar")
                or state.extra.get("freeze_speaking_to_preview")
            )
        )
        if should_enable_neural:
            try:
                state.extra["wav2lip_neural_state"] = self._prepare_neural_face_state(preview)
                state.extra["wav2lip_neural_enabled"] = True
                log.info("wav2lip streaming neural path enabled for avatar %s", bundle.manifest.id)
            except Exception:
                log.warning("failed to prepare wav2lip neural avatar; falling back to synthetic mode", exc_info=True)
        return state

    def warmup(self) -> None:
        if self._torch_bundle is None or self._neural_warmed_up:
            return
        torch = self._torch_bundle["torch"]
        model = self._torch_bundle["model"]
        dummy_face = np.zeros((1, 6, self._model_input_size, self._model_input_size), dtype=np.float32)
        dummy_mel = np.zeros((1, 1, 80, 16), dtype=np.float32)
        with torch.no_grad():
            _ = model(
                torch.from_numpy(dummy_mel).to(self._device),
                torch.from_numpy(dummy_face).to(self._device),
            )
        _ = extract_stream_mel_chunks(
            np.zeros(3200, dtype=np.int16),
            16000,
            self._fps,
            start_frame_index=0,
            min_context_frames=1,
        )
        self._neural_warmed_up = True

    def extract_features(self, audio_chunk: AudioChunk) -> Any:
        return extract_mel_for_wav2lip(audio_chunk, self._fps)

    def extract_features_for_stream(self, audio_chunk: AudioChunk, avatar_state: FrameAvatarState) -> Any:
        if avatar_state.extra.get("wav2lip_neural_enabled") and self._torch_bundle is not None:
            prev_pcm = np.asarray(avatar_state.extra.get("wav2lip_stream_pcm"), dtype=np.int16).reshape(-1)
            cur_pcm = np.asarray(audio_chunk.data, dtype=np.int16).reshape(-1)
            lookahead_pcm = np.asarray(
                avatar_state.extra.get("wav2lip_stream_lookahead_pcm"),
                dtype=np.int16,
            ).reshape(-1)
            committed_pcm = np.concatenate((prev_pcm, cur_pcm)).astype(np.int16, copy=False)
            total_pcm = (
                np.concatenate((committed_pcm, lookahead_pcm)).astype(np.int16, copy=False)
                if lookahead_pcm.size > 0
                else committed_pcm
            )
            avatar_state.extra["wav2lip_stream_pcm"] = committed_pcm
            start_frame_index = int(avatar_state.extra.get("wav2lip_stream_emitted_frames", 0))
            allow_padding = bool(avatar_state.extra.get("wav2lip_stream_is_final", False))
            stop_frame_index = int((committed_pcm.shape[0] / max(1, int(audio_chunk.sample_rate))) * self._fps)
            return extract_stream_mel_chunks(
                total_pcm,
                int(audio_chunk.sample_rate),
                self._fps,
                start_frame_index=start_frame_index,
                stop_frame_index=stop_frame_index,
                min_context_frames=self._min_context_frames,
                allow_padding=allow_padding,
            )
        return self.extract_features(audio_chunk)

    def infer(self, features: Any, avatar_state: FrameAvatarState) -> list[Any]:
        if (
            isinstance(features, Wav2LipStreamFeatures)
            and avatar_state.extra.get("wav2lip_neural_enabled")
            and self._torch_bundle is not None
        ):
            predictions = self._infer_neural(features, avatar_state)
            avatar_state.extra["wav2lip_stream_emitted_frames"] = (
                int(features.start_frame_index) + len(predictions)
            )
            return predictions
        if not isinstance(features, Wav2LipTestFeatures):
            return [None]
        prev = float(avatar_state.extra.get("wav2lip_prev_open", 0.0))
        opens: list[float] = []
        for raw in features.per_frame_energy.tolist():
            target = float(np.clip(raw, 0.0, 1.0))
            alpha = self._attack if target >= prev else self._release
            candidate = prev + (target - prev) * alpha
            max_step = self._max_step_up if candidate >= prev else self._max_step_down
            candidate = prev + float(np.clip(candidate - prev, -self._max_step_down, max_step))
            prev = candidate
            opens.append(float(np.clip(prev, 0.0, 1.0)))
        avatar_state.extra["wav2lip_prev_open"] = prev
        return opens

    def compose_frame(
        self,
        avatar_state: Any,
        frame_idx: int,
        prediction: Any,
    ) -> VideoFrameData:
        state: FrameAvatarState = avatar_state
        ts = frame_idx * (1000.0 / max(1, state.manifest.fps))
        speaking_preview = (
            state.extra.get("rendering_speech")
            and state.extra.get("freeze_speaking_to_preview")
            and isinstance(state.extra.get("preview_frame"), np.ndarray)
        )
        base_preview = (
            state.extra["preview_frame"].copy()
            if speaking_preview
            else None
        )
        if isinstance(prediction, _NeuralPrediction):
            frame = self._compose_neural_frame(state, prediction)
            return numpy_bgr_to_videoframe(frame, ts)
        if isinstance(prediction, (float, int, np.floating, np.integer)):
            if state.extra.get("wav2lip_static_avatar") or base_preview is not None:
                base = base_preview if base_preview is not None else state.frames[0].copy()
                landmarks = state.extra.get("wav2lip_landmarks")
                if isinstance(landmarks, _AvatarLandmarks):
                    base = _apply_synthetic_mouth(base, landmarks, float(prediction))
                return numpy_bgr_to_videoframe(base, ts)
            ordered = state.extra.get("wav2lip_test_frame_order") or list(range(len(state.frames)))
            idx = self._frame_index_for_open_amount(state, float(prediction), ordered)
            frame = state.frames[idx].copy()
            return numpy_bgr_to_videoframe(frame, ts)
        if base_preview is not None:
            return numpy_bgr_to_videoframe(base_preview, ts)
        return numpy_bgr_to_videoframe(
            state.frames[frame_idx % len(state.frames)].copy(),
            ts,
        )

    def idle_frame(self, avatar_state: Any, frame_idx: int) -> VideoFrameData:
        state: FrameAvatarState = avatar_state
        ts = frame_idx * (1000.0 / max(1, state.manifest.fps))
        neural_state = state.extra.get("wav2lip_neural_state")
        if isinstance(neural_state, _NeuralFaceState) and state.extra.get("wav2lip_static_avatar"):
            return numpy_bgr_to_videoframe(neural_state.base_frame.copy(), ts)
        frame = state.frames[0 if state.extra.get("wav2lip_static_avatar") else frame_idx % len(state.frames)].copy()
        return numpy_bgr_to_videoframe(frame, ts)

    def _estimate_frame_mouth_scores(self, frames: list[np.ndarray]) -> np.ndarray:
        scores = np.zeros((len(frames),), dtype=np.float32)
        for i, frame in enumerate(frames):
            h, w = frame.shape[:2]
            x1 = int(w * 0.33)
            x2 = int(w * 0.67)
            y1 = int(h * 0.48)
            y2 = int(h * 0.78)
            roi = frame[y1:y2, x1:x2].astype(np.float32)
            if roi.size == 0:
                continue
            b = roi[:, :, 0]
            g = roi[:, :, 1]
            r = roi[:, :, 2]
            dark = np.clip((110.0 - (r + g + b) / 3.0) / 110.0, 0.0, 1.0)
            red = np.clip((r - (g + b) * 0.5) / 255.0, 0.0, 1.0)
            score = 0.65 * dark + 0.35 * red
            scores[i] = float(score.mean())
        if scores.size and float(scores.max()) > float(scores.min()):
            scores = (scores - float(scores.min())) / max(
                1e-6, float(scores.max()) - float(scores.min())
            )
        return scores

    def _frame_index_for_open_amount(
        self,
        state: FrameAvatarState,
        amount: float,
        ordered: list[int],
    ) -> int:
        if not ordered:
            return 0
        amount = float(np.clip(amount, 0.0, 1.0))
        target_pos = amount * float(len(ordered) - 1)
        prev_pos = float(state.extra.get("wav2lip_prev_frame_pos", target_pos))
        max_step = self._frame_step_up if target_pos >= prev_pos else self._frame_step_down
        pos = prev_pos + float(np.clip(target_pos - prev_pos, -self._frame_step_down, max_step))
        pos = float(np.clip(pos, 0.0, float(len(ordered) - 1)))
        state.extra["wav2lip_prev_frame_pos"] = pos
        idx = int(round(pos))
        return int(ordered[max(0, min(len(ordered) - 1, idx))])

    def _face_alignment(self) -> Any:
        if self._face_detector is not None:
            return self._face_detector
        ensure_wav2lip_imports()
        from opentalking.models.wav2lip.face_detection import FaceAlignment, LandmarksType

        detector_path = resolve_wav2lip_s3fd(self._models_dir)
        if detector_path is None:
            raise RuntimeError("missing s3fd.pth for wav2lip face detection")
        self._face_detector = FaceAlignment(
            LandmarksType._2D,
            flip_input=False,
            device=self._device,
            path_to_detector=detector_path,
        )
        return self._face_detector

    def _prepare_neural_face_state(self, frame: np.ndarray) -> _NeuralFaceState:
        detector = self._face_alignment()
        rects = detector.get_detections_for_batch(np.asarray([frame]))
        if not rects or rects[0] is None:
            raise RuntimeError("face not detected for wav2lip streaming avatar")
        rect = rects[0]
        pady1, pady2, padx1, padx2 = self._pads
        x1 = max(0, int(rect[0]) - padx1)
        y1 = max(0, int(rect[1]) - pady1)
        x2 = min(frame.shape[1], int(rect[2]) + padx2)
        y2 = min(frame.shape[0], int(rect[3]) + pady2)
        x1, y1, x2, y2 = _rescale_box(
            (x1, y1, x2, y2),
            frame_shape=frame.shape[:2],
            scale=self._face_box_scale,
            center_y_bias=self._face_box_center_y_bias,
        )
        if x2 <= x1 or y2 <= y1:
            raise RuntimeError(f"invalid wav2lip face box: {(x1, y1, x2, y2)}")

        face = frame[y1:y2, x1:x2].copy()
        face = cv2.resize(face, (self._model_input_size, self._model_input_size))
        masked = face.copy()
        masked[self._model_input_size // 2 :, :] = 0
        face_input = np.concatenate((masked, face), axis=2).astype(np.float32) / 255.0
        return _NeuralFaceState(
            base_frame=frame.copy(),
            coords=(y1, y2, x1, x2),
            face_input=face_input,
        )

    def _infer_neural(
        self,
        features: Wav2LipStreamFeatures,
        avatar_state: FrameAvatarState,
    ) -> list[_NeuralPrediction]:
        if features.frame_count <= 0:
            return []
        neural_state = avatar_state.extra.get("wav2lip_neural_state")
        if not isinstance(neural_state, _NeuralFaceState):
            return []

        assert self._torch_bundle is not None
        torch = self._torch_bundle["torch"]
        model = self._torch_bundle["model"]
        batch_face = np.repeat(neural_state.face_input[None, ...], features.frame_count, axis=0)
        batch_mel = np.reshape(
            features.mel_chunks,
            (features.frame_count, features.mel_chunks.shape[1], features.mel_chunks.shape[2], 1),
        )

        predictions: list[_NeuralPrediction] = []
        for start in range(0, features.frame_count, max(1, self._batch_size)):
            end = min(features.frame_count, start + max(1, self._batch_size))
            img_batch = torch.FloatTensor(np.transpose(batch_face[start:end], (0, 3, 1, 2))).to(self._device)
            mel_batch = torch.FloatTensor(np.transpose(batch_mel[start:end], (0, 3, 1, 2))).to(self._device)
            with torch.no_grad():
                pred = model(mel_batch, img_batch)
            pred_np = pred.detach().cpu().numpy().transpose(0, 2, 3, 1) * 255.0
            for patch in pred_np:
                predictions.append(
                    _NeuralPrediction(
                        patch=np.clip(patch, 0.0, 255.0).astype(np.uint8),
                        coords=neural_state.coords,
                    )
                )
        return predictions

    def _compose_neural_frame(self, avatar_state: FrameAvatarState, prediction: _NeuralPrediction) -> np.ndarray:
        neural_state = avatar_state.extra.get("wav2lip_neural_state")
        if not isinstance(neural_state, _NeuralFaceState):
            return avatar_state.frames[0].copy()
        y1, y2, x1, x2 = prediction.coords
        frame = neural_state.base_frame.copy()
        patch = cv2.resize(prediction.patch, (x2 - x1, y2 - y1))
        original = frame[y1:y2, x1:x2].copy()
        frame[y1:y2, x1:x2] = _blend_mouth_only(patch, original)
        return frame
