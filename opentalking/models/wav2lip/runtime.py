"""Realtime Wav2Lip runtime owned by OpenTalking."""

from __future__ import annotations

# mypy: ignore-errors

from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import tempfile
import time
from typing import Any


def _configure_wav2lip_cpu_thread_env() -> int:
    """Keep CPU-side video work from oversubscribing host threads by default."""

    raw = os.environ.get("OPENTALKING_WAV2LIP_CPU_THREADS", "4").strip()
    try:
        threads = max(1, int(raw))
    except ValueError:
        threads = 4
    value = str(threads)
    for key in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "OPENCV_FOR_THREADS_NUM",
    ):
        os.environ.setdefault(key, value)
    return threads


_configure_wav2lip_cpu_thread_env()

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from opentalking.models.wav2lip.face_detection import FaceAlignment, LandmarksType  # noqa: E402
from opentalking.models.wav2lip.feature_extractor import MEL_STEP_SIZE, pcm_to_wav2lip_mel  # noqa: E402
from opentalking.models.wav2lip.loader import load_wav2lip_torch, resolve_wav2lip_s3fd  # noqa: E402
from opentalking.models.wav2lip.postprocess import (  # noqa: E402
    BlendConfig,
    MouthGeometry,
    blend_mouth_patch_basic,
    blend_mouth_patch_easy,
    blend_mouth_patch,
    metadata_face_box_to_crop,
    metadata_radius_to_input_crop,
    resize_reference_frame,
    select_wav2lip_model_crop,
)
from opentalking.models.wav2lip.realtime import RealtimeAvatarSession, encode_jpeg_sequence  # noqa: E402


log = logging.getLogger(__name__)


class Wav2LipRuntimeError(RuntimeError):
    """Raised when Wav2Lip cannot initialize or render."""


@dataclass
class _PreparedFrame:
    base_frame: np.ndarray
    face_crop: np.ndarray
    coords: tuple[int, int, int, int]
    geometry: MouthGeometry | None


@dataclass
class _SessionState:
    prepared_frames: list[_PreparedFrame]
    emitted_frames: int = 0
    pcm_history: np.ndarray | None = None

    def frame_at(self, index: int) -> _PreparedFrame:
        return self.prepared_frames[index % len(self.prepared_frames)]


class Wav2LipRealtimeRuntime:
    """Streaming Wav2Lip runtime.

    The model loader, network definitions, feature extractor, face detector, and
    enhanced postprocessor live under ``opentalking.models.wav2lip`` and run in the OpenTalking process.
    """

    def __init__(
        self,
        *,
        models_dir: str | Path | None = None,
        device: str | None = None,
        work_root: str | Path | None = None,
    ) -> None:
        self.models_dir = Path(
            models_dir or os.environ.get("OPENTALKING_WAV2LIP_MODEL_ROOT", "./models/wav2lip")
        ).resolve()
        self.device = device or os.environ.get("OPENTALKING_WAV2LIP_DEVICE", "cuda")
        self.face_detection_device = self._resolve_face_detection_device(self.device)
        self.work_root = Path(work_root or os.environ.get("OPENTALKING_WAV2LIP_WORK_DIR", tempfile.gettempdir())).resolve()
        self.checkpoint = Path(
            os.environ.get("OPENTALKING_WAV2LIP_CHECKPOINT", "") or (self.models_dir / "wav2lip384.pth")
        ).expanduser().resolve()
        self.batch_size = max(1, int(os.environ.get("OPENTALKING_WAV2LIP_BATCH_SIZE", "8")))
        self.jpeg_quality = int(np.clip(self._parse_int(os.environ.get("OPENTALKING_WAV2LIP_JPEG_QUALITY"), 85), 1, 100))
        self.pads = self._parse_pads(os.environ.get("OPENTALKING_WAV2LIP_PADS", "0,10,0,0"))
        self.easy_mask_dilation = self._parse_float(os.environ.get("OPENTALKING_WAV2LIP_EASY_MASK_DILATION"), 2.5)
        self.easy_mask_feathering = self._parse_float(os.environ.get("OPENTALKING_WAV2LIP_EASY_MASK_FEATHERING"), 2.0)
        self.easy_debug_mask = self._parse_bool(os.environ.get("OPENTALKING_WAV2LIP_EASY_DEBUG_MASK"), default=False)
        self.gfpgan_checkpoint = Path(
            os.environ.get("OPENTALKING_WAV2LIP_GFPGAN_CHECKPOINT", "checkpoints/GFPGANv1.4.pth")
        ).expanduser().resolve()
        self.blend_config = BlendConfig(
            lower_lip_dynamic_expand=self._parse_float(
                os.environ.get("OPENTALKING_WAV2LIP_LOWER_LIP_DYNAMIC_EXPAND"),
                0.25,
            ),
            enable_jaw_motion_blend=self._parse_bool(
                os.environ.get("OPENTALKING_WAV2LIP_ENABLE_JAW_MOTION_BLEND"),
                default=False,
            ),
            jaw_blend_alpha=self._parse_float(os.environ.get("OPENTALKING_WAV2LIP_JAW_BLEND_ALPHA"), 0.22),
            jaw_mask_expand_x=self._parse_float(os.environ.get("OPENTALKING_WAV2LIP_JAW_MASK_EXPAND_X"), 0.25),
            jaw_mask_expand_y=self._parse_float(os.environ.get("OPENTALKING_WAV2LIP_JAW_MASK_EXPAND_Y"), 0.55),
            jaw_mask_offset_y=self._parse_float(os.environ.get("OPENTALKING_WAV2LIP_JAW_MASK_OFFSET_Y"), 1.05),
            jaw_mask_feather=self._parse_float(os.environ.get("OPENTALKING_WAV2LIP_JAW_MASK_FEATHER"), 1.25),
        )
        self._torch_bundle: dict[str, Any] | None = None
        self._gfpgan_restorer: Any | None = None
        self._face_detector: FaceAlignment | None = None
        self._sessions: dict[str, _SessionState] = {}
        self._frame_sequence_cache: dict[str, list[_PreparedFrame]] = {}
        self._configure_cpu_thread_limits()

    @staticmethod
    def _configure_cpu_thread_limits() -> int:
        threads = _configure_wav2lip_cpu_thread_env()
        try:
            cv2.setNumThreads(threads)
        except Exception:
            log.debug("Failed to set OpenCV thread count", exc_info=True)
        try:
            import torch

            torch.set_num_threads(threads)
            if not getattr(torch, "_opentalking_wav2lip_interop_configured", False):
                interop_threads = max(
                    1,
                    int(os.environ.get("OPENTALKING_WAV2LIP_INTEROP_THREADS", "1").strip() or "1"),
                )
                torch.set_num_interop_threads(interop_threads)
                setattr(torch, "_opentalking_wav2lip_interop_configured", True)
        except Exception:
            log.debug("Failed to set torch thread count", exc_info=True)
        return threads

    def render_chunk(self, session: RealtimeAvatarSession, pcm_s16le: bytes) -> bytes:
        state = self._session_state(session)
        bundle = self._model_bundle()
        torch = bundle["torch"]
        model = bundle["model"]
        input_size = int(bundle["input_size"])

        current_pcm = np.frombuffer(pcm_s16le, dtype=np.int16).copy()
        history = state.pcm_history
        total_pcm = (
            current_pcm
            if history is None
            else np.concatenate((history, current_pcm)).astype(np.int16, copy=False)
        )
        state.pcm_history = total_pcm
        mel_chunks = self._mel_chunks(
            total_pcm,
            sample_rate=session.audio.sample_rate,
            fps=session.video.fps,
            start_frame=state.emitted_frames,
        )
        if not mel_chunks:
            return encode_jpeg_sequence(
                [self._encode_jpeg_bgr(state.frame_at(state.emitted_frames).base_frame)]
            )

        prepared_for_chunk = [
            state.frame_at(state.emitted_frames + idx) for idx in range(len(mel_chunks))
        ]
        face_crops = np.stack([frame.face_crop for frame in prepared_for_chunk], axis=0)
        mel_batch = np.stack(mel_chunks, axis=0)
        face_tensor = torch.from_numpy(
            np.ascontiguousarray(np.transpose(face_crops, (0, 3, 1, 2)))
        ).to(device=self.device, dtype=torch.float32).div_(255.0)
        masked_tensor = face_tensor.clone()
        masked_tensor[:, :, input_size // 2 :, :] = 0
        img_tensor = torch.cat((masked_tensor, face_tensor), dim=1)
        mel_tensor = torch.FloatTensor(
            np.transpose(np.reshape(mel_batch, (len(mel_chunks), 80, MEL_STEP_SIZE, 1)), (0, 3, 1, 2))
        ).to(self.device)
        frames: list[bytes] = []
        with torch.no_grad():
            for start in range(0, len(mel_chunks), self.batch_size):
                end = min(len(mel_chunks), start + self.batch_size)
                pred = model(mel_tensor[start:end], img_tensor[start:end])
                pred_np = pred.detach().cpu().numpy().transpose(0, 2, 3, 1) * 255.0
                for local_offset, patch in enumerate(pred_np):
                    frames.append(
                        self._compose_frame(
                            prepared_for_chunk[start + local_offset],
                            patch,
                            input_size,
                            session.wav2lip_postprocess_mode,
                        )
                    )
        state.emitted_frames += len(frames)
        return encode_jpeg_sequence(
            frames or [self._encode_jpeg_bgr(state.frame_at(state.emitted_frames).base_frame)]
        )

    def close_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def preload_reference(self, session: RealtimeAvatarSession) -> dict[str, object]:
        if session.reference_mode != "frames":
            raise Wav2LipRuntimeError("Wav2Lip preload requires frame reference mode.")
        frame_dir = Path(session.ref_frame_dir or "").expanduser().resolve()
        frame_paths = sorted(
            path
            for path in frame_dir.iterdir()
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        )
        max_frames = max(1, int(os.environ.get("OPENTALKING_WAV2LIP_MAX_REFERENCE_FRAMES", "125")))
        frame_paths = frame_paths[:max_frames]
        cache_key = self._frame_sequence_cache_key(session, frame_paths)
        cache_hit = cache_key in self._frame_sequence_cache
        started = time.monotonic()
        prepared = self._prepare_frame_sequence(session)
        return {
            "type": "preload_result",
            "frames": len(prepared),
            "elapsed_ms": round((time.monotonic() - started) * 1000.0, 3),
            "cache_hit": cache_hit,
        }

    def _session_state(self, session: RealtimeAvatarSession) -> _SessionState:
        existing = self._sessions.get(session.session_id)
        if existing is not None:
            return existing
        if session.reference_mode == "frames":
            prepared_frames = self._prepare_frame_sequence(session)
        else:
            prepared_frames = [self._prepare_image_reference(session)]
        state = _SessionState(prepared_frames=prepared_frames)
        self._sessions[session.session_id] = state
        log.info(
            "wav2lip session ready: id=%s reference_mode=%s frames=%d postprocess=%s",
            session.session_id,
            session.reference_mode,
            len(prepared_frames),
            session.wav2lip_postprocess_mode,
        )
        return state

    def _prepare_image_reference(self, session: RealtimeAvatarSession) -> _PreparedFrame:
        if not session.image_bytes:
            raise Wav2LipRuntimeError("Wav2Lip session has no reference image bytes.")
        image_buf = np.frombuffer(session.image_bytes, dtype=np.uint8)
        frame = cv2.imdecode(image_buf, cv2.IMREAD_COLOR)
        if frame is None:
            raise Wav2LipRuntimeError("Failed to decode Wav2Lip reference image.")
        return self._prepare_reference_frame(session, frame, frame_index=0)

    def _prepare_frame_sequence(self, session: RealtimeAvatarSession) -> list[_PreparedFrame]:
        if not session.ref_frame_dir:
            raise Wav2LipRuntimeError("Wav2Lip frame reference mode requires ref_frame_dir.")
        frame_dir = Path(session.ref_frame_dir).expanduser().resolve()
        if not frame_dir.is_dir():
            raise Wav2LipRuntimeError(f"Wav2Lip ref_frame_dir not found: {frame_dir}")
        frame_paths = sorted(
            path
            for path in frame_dir.iterdir()
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        )
        max_frames = max(1, int(os.environ.get("OPENTALKING_WAV2LIP_MAX_REFERENCE_FRAMES", "125")))
        frame_paths = frame_paths[:max_frames]
        if not frame_paths:
            raise Wav2LipRuntimeError(f"No reference frames found under: {frame_dir}")
        cache_key = self._frame_sequence_cache_key(session, frame_paths)
        cached = self._frame_sequence_cache.get(cache_key)
        if cached is not None:
            log.info(
                "wav2lip reference frame cache hit: id=%s frames=%d key=%s",
                session.session_id,
                len(cached),
                cache_key[:16],
            )
            return cached
        started = time.monotonic()
        metadata_by_frame = self._load_frame_metadata(session.ref_frame_metadata_path)
        prepared: list[_PreparedFrame] = []
        for index, path in enumerate(frame_paths):
            frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if frame is None:
                log.warning("Skipping unreadable Wav2Lip reference frame: %s", path)
                continue
            frame_metadata = metadata_by_frame.get(path.name) or session.mouth_metadata
            if session.preprocessed and not frame_metadata:
                raise Wav2LipRuntimeError(
                    f"preprocessed Wav2Lip frame has no metadata: {path.name}"
                )
            if session.preprocessed:
                self._validate_preprocessed_frame_hash(path, frame_metadata)
            prepared.append(
                self._prepare_reference_frame(
                    session,
                    frame,
                    frame_index=index,
                    mouth_metadata=frame_metadata,
                )
            )
        if not prepared:
            raise Wav2LipRuntimeError(f"No readable reference frames found under: {frame_dir}")
        self._frame_sequence_cache[cache_key] = prepared
        log.info(
            "wav2lip reference frame cache built: id=%s frames=%d key=%s elapsed_ms=%.1f",
            session.session_id,
            len(prepared),
            cache_key[:16],
            (time.monotonic() - started) * 1000.0,
        )
        return prepared

    @staticmethod
    def _validate_preprocessed_frame_hash(path: Path, metadata: dict[str, Any]) -> None:
        expected = str(metadata.get("source_frame_hash") or "").strip().lower()
        if not expected:
            raise Wav2LipRuntimeError(f"preprocessed Wav2Lip frame metadata missing source_frame_hash: {path.name}")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        actual = digest.hexdigest()
        if actual != expected:
            raise Wav2LipRuntimeError(f"preprocessed Wav2Lip frame hash mismatch: {path.name}")

    def _frame_sequence_cache_key(
        self,
        session: RealtimeAvatarSession,
        frame_paths: list[Path],
    ) -> str:
        metadata_stat = ""
        if session.ref_frame_metadata_path:
            path = Path(session.ref_frame_metadata_path).expanduser().resolve()
            try:
                stat = path.stat()
                metadata_stat = f"{path}:{stat.st_mtime_ns}:{stat.st_size}"
            except OSError:
                metadata_stat = str(path)
        frame_sig = []
        for path in frame_paths:
            try:
                stat = path.stat()
                frame_sig.append(f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}")
            except OSError:
                frame_sig.append(path.name)
        mouth_metadata_sig = (
            ""
            if session.ref_frame_metadata_path
            else json.dumps(session.mouth_metadata or {}, sort_keys=True, ensure_ascii=True)
        )
        return "::".join(
            [
                str(Path(session.ref_frame_dir or "").expanduser().resolve()),
                str(session.video.width),
                str(session.video.height),
                str(session.video.fps),
                session.wav2lip_postprocess_mode,
                str(bool(session.preprocessed)),
                str(self.checkpoint),
                str(self.pads),
                str(self.easy_mask_dilation),
                str(self.easy_mask_feathering),
                str(bool(self.easy_debug_mask)),
                str(self.gfpgan_checkpoint),
                metadata_stat,
                mouth_metadata_sig,
                "|".join(frame_sig),
            ]
        )

    @staticmethod
    def _load_frame_metadata(path: str | None) -> dict[str, dict[str, Any]]:
        if not path:
            return {}
        metadata_path = Path(path).expanduser().resolve()
        try:
            raw = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            log.warning("Failed to read Wav2Lip frame metadata: %s", metadata_path, exc_info=True)
            return {}
        frames = raw.get("frames") if isinstance(raw, dict) else None
        if not isinstance(frames, dict):
            return {}
        return {
            str(name): value
            for name, value in frames.items()
            if isinstance(value, dict)
        }

    def _prepare_reference_frame(
        self,
        session: RealtimeAvatarSession,
        frame: np.ndarray,
        *,
        frame_index: int,
        mouth_metadata: dict[str, Any] | None = None,
    ) -> _PreparedFrame:
        frame = resize_reference_frame(
            frame,
            width=int(session.video.width),
            height=int(session.video.height),
        )
        input_size = int(self._model_bundle()["input_size"])
        postprocess_mode = session.wav2lip_postprocess_mode
        use_opentalking = postprocess_mode == "opentalking_improved"
        use_easy = postprocess_mode in {"easy_improved", "easy_enhanced"}
        needs_geometry = use_opentalking or use_easy
        metadata = mouth_metadata if mouth_metadata is not None else session.mouth_metadata
        preprocessed_crop = self._preprocessed_metadata_crop(metadata, frame.shape[:2]) if session.preprocessed else None
        if preprocessed_crop is not None:
            detector_crop = preprocessed_crop
            crop_source = "preprocessed"
        else:
            detector_crop = self._detect_face_box(frame)
            crop_source = "detector"
        metadata_crop = metadata_face_box_to_crop(metadata, frame.shape[:2]) if needs_geometry else None
        y1, y2, x1, x2 = select_wav2lip_model_crop(
            detector_crop=detector_crop,
            metadata_crop=metadata_crop,
            use_opentalking_improved=use_opentalking,
        )
        face = cv2.resize(frame[y1:y2, x1:x2].copy(), (input_size, input_size))
        geometry = (
            self._geometry_from_metadata(
                metadata,
                (y1, y2, x1, x2),
                (input_size, input_size),
                frame.shape[:2],
            )
            if needs_geometry
            else None
        )
        geometry_source = "metadata"
        if geometry is None and needs_geometry:
            geometry = self._fallback_mouth_geometry(face)
            geometry_source = "fallback"
        log.info(
            "wav2lip reference frame prepared: id=%s frame=%d postprocess=%s geometry=%s crop_source=%s crop=%s input_size=%s",
            session.session_id,
            frame_index,
            session.wav2lip_postprocess_mode,
            geometry_source if geometry is not None else "none",
            "metadata" if (y1, y2, x1, x2) == metadata_crop else crop_source,
            (y1, y2, x1, x2),
            input_size,
        )
        return _PreparedFrame(
            base_frame=frame,
            face_crop=np.ascontiguousarray(face),
            coords=(y1, y2, x1, x2),
            geometry=geometry,
        )

    @staticmethod
    def _metadata_model_crop(
        metadata: dict[str, Any] | None,
        frame_shape: tuple[int, int],
    ) -> tuple[int, int, int, int] | None:
        if not isinstance(metadata, dict):
            return None
        if metadata.get("model_crop_source") != "wav2lip_detector":
            return None
        raw = metadata.get("model_crop")
        if not isinstance(raw, (list, tuple)) or len(raw) != 4:
            return None
        try:
            left, top, right, bottom = (float(item) for item in raw)
        except (TypeError, ValueError):
            return None
        if not (0.0 <= left < right <= 1.0 and 0.0 <= top < bottom <= 1.0):
            return None
        frame_h, frame_w = frame_shape
        x1 = int(round(left * frame_w))
        y1 = int(round(top * frame_h))
        x2 = int(round(right * frame_w))
        y2 = int(round(bottom * frame_h))
        x1 = int(np.clip(x1, 0, max(0, frame_w - 1)))
        y1 = int(np.clip(y1, 0, max(0, frame_h - 1)))
        x2 = int(np.clip(x2, x1 + 1, frame_w))
        y2 = int(np.clip(y2, y1 + 1, frame_h))
        return y1, y2, x1, x2

    @classmethod
    def _preprocessed_metadata_crop(
        cls,
        metadata: dict[str, Any] | None,
        frame_shape: tuple[int, int],
    ) -> tuple[int, int, int, int] | None:
        crop = cls._metadata_model_crop(metadata, frame_shape)
        if crop is not None:
            return crop
        if isinstance(metadata, dict):
            return metadata_face_box_to_crop(metadata, frame_shape)
        return None

    def _model_bundle(self) -> dict[str, Any]:
        if self._torch_bundle is None:
            if not self.checkpoint.is_file():
                raise Wav2LipRuntimeError(f"Wav2Lip checkpoint not found: {self.checkpoint}")
            self._torch_bundle = load_wav2lip_torch(self.checkpoint, self.device)
            self.device = str(self._torch_bundle["device"])
            log.info(
                "Wav2Lip inference device=%s | face_detection device=%s | checkpoint=%s | jpeg_quality=%d",
                self.device,
                self.face_detection_device,
                self.checkpoint,
                self.jpeg_quality,
            )
        return self._torch_bundle

    def _face_alignment(self) -> FaceAlignment:
        if self._face_detector is not None:
            return self._face_detector
        s3fd = resolve_wav2lip_s3fd(self.models_dir)
        if s3fd is None:
            raise Wav2LipRuntimeError(f"Missing s3fd.pth under {self.models_dir}/wav2lip or {self.models_dir}")
        self._face_detector = FaceAlignment(
            LandmarksType._2D,
            flip_input=False,
            device=self.face_detection_device,
            path_to_detector=s3fd,
        )
        return self._face_detector

    @staticmethod
    def _resolve_face_detection_device(model_device: str) -> str:
        raw = os.environ.get("OPENTALKING_WAV2LIP_FACE_DET_DEVICE", "").strip()
        if raw:
            return raw
        if model_device.lower().startswith("npu"):
            return "cpu"
        return model_device

    def _detect_face_box(self, frame: np.ndarray) -> tuple[int, int, int, int]:
        rects = self._face_alignment().get_detections_for_batch(np.asarray([frame]))
        if not rects or rects[0] is None:
            raise Wav2LipRuntimeError("Face not detected for Wav2Lip reference image.")
        rect = rects[0]
        pady1, pady2, padx1, padx2 = self.pads
        y1 = max(0, int(rect[1]) - pady1)
        y2 = min(frame.shape[0], int(rect[3]) + pady2)
        x1 = max(0, int(rect[0]) - padx1)
        x2 = min(frame.shape[1], int(rect[2]) + padx2)
        if x2 <= x1 or y2 <= y1:
            raise Wav2LipRuntimeError(f"Invalid Wav2Lip face box: {(y1, y2, x1, x2)}")
        return y1, y2, x1, x2

    def _mel_chunks(self, pcm: np.ndarray, *, sample_rate: int, fps: int, start_frame: int) -> list[np.ndarray]:
        mel = pcm_to_wav2lip_mel(pcm, sample_rate)
        if mel.shape[1] <= 0:
            return []
        mel_idx_multiplier = 80.0 / max(1, fps)
        chunks: list[np.ndarray] = []
        frame_idx = max(0, start_frame)
        while True:
            start_idx = int(frame_idx * mel_idx_multiplier)
            if start_idx + MEL_STEP_SIZE > mel.shape[1]:
                break
            chunks.append(np.asarray(mel[:, start_idx : start_idx + MEL_STEP_SIZE], dtype=np.float32))
            frame_idx += 1
        return chunks

    def _compose_frame(
        self,
        state: _PreparedFrame,
        patch: np.ndarray,
        input_size: int,
        postprocess_mode: str,
    ) -> bytes:
        y1, y2, x1, x2 = state.coords
        frame = state.base_frame.copy()
        resized = cv2.resize(np.clip(patch, 0.0, 255.0).astype(np.uint8), (x2 - x1, y2 - y1))
        original = frame[y1:y2, x1:x2].copy()
        if postprocess_mode in {"easy_improved", "easy_enhanced"} and state.geometry is not None:
            patch_geometry = self._scale_geometry(state.geometry, original.shape[:2], (input_size, input_size))
            if postprocess_mode == "easy_enhanced":
                resized = self._enhance_patch_gfpgan(resized)
            blended = blend_mouth_patch_easy(
                resized,
                original,
                geometry=patch_geometry,
                mask_dilation=self.easy_mask_dilation,
                mask_feathering=self.easy_mask_feathering,
                debug_mask=self.easy_debug_mask,
            )
        elif postprocess_mode == "opentalking_improved" and state.geometry is not None:
            patch_geometry = self._scale_geometry(state.geometry, original.shape[:2], (input_size, input_size))
            blended = blend_mouth_patch(resized, original, geometry=patch_geometry, config=self.blend_config)
        else:
            blended = blend_mouth_patch_basic(resized, original)
        frame[y1:y2, x1:x2] = blended
        return self._encode_jpeg_bgr(frame)

    def _enhance_patch_gfpgan(self, patch_bgr: np.ndarray) -> np.ndarray:
        if self._gfpgan_restorer is None:
            if not self.gfpgan_checkpoint.is_file():
                raise Wav2LipRuntimeError(f"GFPGAN checkpoint not found: {self.gfpgan_checkpoint}")
            try:
                from gfpgan import GFPGANer
            except Exception as exc:
                raise Wav2LipRuntimeError("GFPGAN package is not available in this Python environment.") from exc
            self._gfpgan_restorer = GFPGANer(
                model_path=str(self.gfpgan_checkpoint),
                upscale=1,
                arch="clean",
                channel_multiplier=2,
                bg_upsampler=None,
            )
            log.info("GFPGAN restorer loaded: checkpoint=%s", self.gfpgan_checkpoint)
        _, _, output = self._gfpgan_restorer.enhance(
            patch_bgr,
            has_aligned=False,
            only_center_face=False,
            paste_back=True,
        )
        return output

    @staticmethod
    def _geometry_from_metadata(
        metadata: dict[str, Any],
        coords: tuple[int, int, int, int],
        input_shape: tuple[int, int],
        frame_shape: tuple[int, int],
    ) -> MouthGeometry | None:
        animation = metadata.get("animation") if isinstance(metadata, dict) else None
        if not isinstance(animation, dict):
            return None
        y1, y2, x1, x2 = coords
        height, width = input_shape
        crop_w = max(1, x2 - x1)
        crop_h = max(1, y2 - y1)
        frame_h, frame_w = frame_shape

        def point(raw: Any) -> tuple[int, int] | None:
            if not isinstance(raw, (list, tuple)) or len(raw) != 2:
                return None
            full_x = float(raw[0]) * frame_w
            full_y = float(raw[1]) * frame_h
            crop_x = (full_x - x1) / crop_w * width
            crop_y = (full_y - y1) / crop_h * height
            if crop_x < -width * 0.15 or crop_x > width * 1.15 or crop_y < -height * 0.15 or crop_y > height * 1.15:
                return None
            return int(round(np.clip(crop_x, 0, width - 1))), int(round(np.clip(crop_y, 0, height - 1)))

        center = point(animation.get("mouth_center"))
        if center is None:
            return None
        rx = metadata_radius_to_input_crop(
            normalized_radius=float(animation.get("mouth_rx", 0.06)),
            frame_size=frame_w,
            crop_size=crop_w,
            input_size=width,
        )
        ry = metadata_radius_to_input_crop(
            normalized_radius=float(animation.get("mouth_ry", 0.02)),
            frame_size=frame_h,
            crop_size=crop_h,
            input_size=height,
        )
        outer = tuple(p for item in animation.get("outer_lip", []) if (p := point(item)) is not None)
        inner = tuple(p for item in animation.get("inner_mouth", []) if (p := point(item)) is not None)
        return MouthGeometry(center=center, rx=rx, ry=ry, outer_lip=outer, inner_mouth=inner)

    @staticmethod
    def _fallback_mouth_geometry(face_bgr: np.ndarray) -> MouthGeometry:
        height, width = face_bgr.shape[:2]
        roi_y1 = int(round(height * 0.46))
        roi_y2 = int(round(height * 0.86))
        roi_x1 = int(round(width * 0.22))
        roi_x2 = int(round(width * 0.78))
        roi = face_bgr[roi_y1:roi_y2, roi_x1:roi_x2]
        if roi.size == 0:
            return MouthGeometry.ellipse(
                center=(width // 2, int(round(height * 0.66))),
                rx=max(8, int(round(width * 0.16))),
                ry=max(4, int(round(height * 0.045))),
            )

        roi_f = roi.astype(np.float32)
        b = roi_f[:, :, 0]
        g = roi_f[:, :, 1]
        r = roi_f[:, :, 2]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV).astype(np.float32)
        saturation = hsv[:, :, 1] / 255.0
        lip_score = np.maximum(0.0, r - 0.72 * g - 0.45 * b) * saturation
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY).astype(np.float32)
        dark_score = np.clip(150.0 - gray, 0.0, 150.0) / 150.0
        score = cv2.GaussianBlur(lip_score + dark_score * 18.0, (0, 0), 4.0)

        yy, xx = np.indices(score.shape, dtype=np.float32)
        center_prior = np.exp(-((xx / max(1, score.shape[1] - 1) - 0.5) ** 2) / (2 * 0.23**2))
        center_prior *= np.exp(-((yy / max(1, score.shape[0] - 1) - 0.48) ** 2) / (2 * 0.25**2))
        score *= center_prior
        total = float(score.sum())
        if total <= 1e-3:
            cx = width // 2
            cy = int(round(height * 0.66))
            sx = width * 0.16
            sy = height * 0.045
        else:
            cx_roi = float((xx * score).sum() / total)
            cy_roi = float((yy * score).sum() / total)
            var_x = float((((xx - cx_roi) ** 2) * score).sum() / total)
            var_y = float((((yy - cy_roi) ** 2) * score).sum() / total)
            cx = roi_x1 + int(round(cx_roi))
            cy = roi_y1 + int(round(cy_roi))
            sx = max(width * 0.10, min(width * 0.22, np.sqrt(max(1.0, var_x)) * 1.9))
            sy = max(height * 0.025, min(height * 0.075, np.sqrt(max(1.0, var_y)) * 0.95))

        rx = max(8, int(round(sx)))
        ry = max(4, int(round(sy)))
        outer = (
            (cx - rx, cy),
            (cx - rx // 2, cy - ry),
            (cx, cy - int(round(ry * 1.15))),
            (cx + rx // 2, cy - ry),
            (cx + rx, cy),
            (cx + rx // 2, cy + ry),
            (cx, cy + int(round(ry * 1.35))),
            (cx - rx // 2, cy + ry),
        )
        return MouthGeometry(
            center=(int(np.clip(cx, 0, width - 1)), int(np.clip(cy, 0, height - 1))),
            rx=rx,
            ry=ry,
            outer_lip=tuple(
                (int(np.clip(x, 0, width - 1)), int(np.clip(y, 0, height - 1)))
                for x, y in outer
            ),
        )

    @staticmethod
    def _scale_geometry(
        geometry: MouthGeometry,
        target_shape: tuple[int, int],
        source_shape: tuple[int, int],
    ) -> MouthGeometry:
        th, tw = target_shape
        sh, sw = source_shape
        sx = tw / max(1, sw)
        sy = th / max(1, sh)

        def point(p: tuple[int, int]) -> tuple[int, int]:
            return int(round(p[0] * sx)), int(round(p[1] * sy))

        return MouthGeometry(
            center=point(geometry.center),
            rx=max(1, int(round(geometry.rx * sx))),
            ry=max(1, int(round(geometry.ry * sy))),
            outer_lip=tuple(point(p) for p in geometry.outer_lip),
            inner_mouth=tuple(point(p) for p in geometry.inner_mouth),
        )

    def _encode_jpeg_bgr(self, frame_bgr: np.ndarray) -> bytes:
        ok, encoded = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
        if not ok:
            raise Wav2LipRuntimeError("Failed to JPEG-encode Wav2Lip frame.")
        return encoded.tobytes()

    @staticmethod
    def _parse_pads(raw: str) -> tuple[int, int, int, int]:
        parts = [part.strip() for part in raw.split(",")]
        if len(parts) != 4:
            return (0, 10, 0, 0)
        try:
            return tuple(int(part) for part in parts)  # type: ignore[return-value]
        except ValueError:
            return (0, 10, 0, 0)

    @staticmethod
    def _parse_bool(raw: str | None, *, default: bool = False) -> bool:
        if raw is None:
            return default
        value = raw.strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off"}:
            return False
        return default

    @staticmethod
    def _parse_float(raw: str | None, default: float) -> float:
        if raw is None or not raw.strip():
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    @staticmethod
    def _parse_postprocess_mode(raw: str | None) -> str:
        mode = (raw or "easy_improved").strip().lower().replace("-", "_")
        if mode in {"basic", "opentalking_improved", "easy_improved", "easy_enhanced"}:
            return mode
        return "easy_improved"

    @staticmethod
    def _parse_int(raw: str | None, default: int) -> int:
        if raw is None or not raw.strip():
            return default
        try:
            return int(raw)
        except ValueError:
            return default


class AvatarRuntimeRouter:
    """Route realtime avatar sessions to model-specific runtimes."""

    def __init__(
        self,
        *,
        fallback: Any,
        wav2lip: Wav2LipRealtimeRuntime | None = None,
        quicktalk: Any | None = None,
    ) -> None:
        self.fallback = fallback
        self.wav2lip = wav2lip
        self.quicktalk = quicktalk

    def render_chunk(self, session: RealtimeAvatarSession, pcm_s16le: bytes) -> bytes:
        if session.model == "wav2lip" and self.wav2lip is not None:
            return self.wav2lip.render_chunk(session, pcm_s16le)
        if session.model == "quicktalk" and self.quicktalk is not None:
            return self.quicktalk.render_chunk(session, pcm_s16le)
        return self.fallback.render_chunk(session, pcm_s16le)

    def preload_reference(self, session: RealtimeAvatarSession) -> dict[str, object]:
        if session.model != "wav2lip" or self.wav2lip is None:
            raise Wav2LipRuntimeError(f"Preload is not supported for model: {session.model}")
        return self.wav2lip.preload_reference(session)

    def close_session(self, session_id: str) -> None:
        if self.wav2lip is not None:
            self.wav2lip.close_session(session_id)
        if self.quicktalk is not None:
            close = getattr(self.quicktalk, "close_session", None)
            if callable(close):
                close(session_id)
