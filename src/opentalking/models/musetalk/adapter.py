from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from opentalking.avatars.loader import load_avatar_bundle
from opentalking.core.types.frames import AudioChunk, VideoFrameData
from opentalking.models.common.frame_avatar import (
    FrameAvatarState,
    load_frame_avatar_state,
    load_preview_frame,
    numpy_bgr_to_videoframe,
)
from opentalking.models.musetalk.composer import compose_simple, resolve_avatar_frame_index
from opentalking.models.musetalk.feature_extractor import (
    DrivingFeatures,
    extract_mel_placeholder,
    extract_whisper_features,
    extract_whisper_features_with_left_context,
)
from opentalking.models.musetalk.loader import (
    load_musetalk_torch,
    load_musetalk_v15_bundle,
    resolve_musetalk_checkpoint,
    resolve_musetalk_v15,
)
from opentalking.models.musetalk.prepared_assets import resolve_prepared_musetalk_assets
from opentalking.models.registry import register_model

logger = logging.getLogger(__name__)


def _runtime_preview_frame(preview: np.ndarray, frames: list[np.ndarray]) -> np.ndarray:
    """Use the real frame as runtime preview for single-frame avatars.

    Prepared MuseTalk assets are aligned to the frame sequence, not to an arbitrary
    selection preview. When there is only one frame, composing speech on top of another
    preview image creates visible geometry mismatch. Keep the UI preview file, but make
    runtime speaking use the actual frame.
    """
    if len(frames) == 1 and isinstance(frames[0], np.ndarray):
        return frames[0].copy()
    return preview


@dataclass
class _ClosedMouthPrediction:
    prediction: np.ndarray
    closed_prediction: np.ndarray
    amount: float


@register_model("musetalk")
class MuseTalkAdapter:
    """MuseTalk adapter with v1.5 neural inference and fallback frame-cycle mode."""

    model_type = "musetalk"

    def __init__(self) -> None:
        self._device = os.environ.get("OPENTALKING_TORCH_DEVICE", "cuda")
        self._models_dir = Path(os.environ.get("OPENTALKING_MODELS_DIR", "./models")).resolve()
        self._torch_bundle: dict[str, Any] | None = None
        self._v15_bundle: dict[str, Any] | None = None
        self._fps = int(os.environ.get("OPENTALKING_DEFAULT_FPS", "25"))
        self._stream_context_ms = float(
            os.environ.get("OPENTALKING_MUSETALK_CONTEXT_MS", "320.0")
        )
        self._stream_overlap_frames = int(
            os.environ.get("OPENTALKING_MUSETALK_OVERLAP_FRAMES", "0")
        )
        self._silence_gate_threshold = float(
            os.environ.get("OPENTALKING_MUSETALK_SILENCE_GATE", "0.04")
        )
        self._smooth_crop_boxes = os.environ.get("OPENTALKING_MUSETALK_SMOOTH_CROP", "0") == "1"
        self._energy_gain = float(os.environ.get("OPENTALKING_MUSETALK_ENERGY_GAIN", "0.0"))
        self._energy_attack = float(os.environ.get("OPENTALKING_MUSETALK_ENERGY_ATTACK", "0.28"))
        self._energy_release = float(os.environ.get("OPENTALKING_MUSETALK_ENERGY_RELEASE", "0.16"))
        self._energy_max_step_up = float(
            os.environ.get("OPENTALKING_MUSETALK_ENERGY_MAX_STEP_UP", "0.075")
        )
        self._energy_max_step_down = float(
            os.environ.get("OPENTALKING_MUSETALK_ENERGY_MAX_STEP_DOWN", "0.06")
        )

    def _small_face_ratio(self, avatar_state: FrameAvatarState, avatar_frame_idx: int) -> float:
        crop_infos = avatar_state.extra.get("crop_infos")
        if not isinstance(crop_infos, list) or not crop_infos:
            return 1.0
        ci = crop_infos[avatar_frame_idx % len(crop_infos)]
        face_area = max(1, (ci.x2 - ci.x1) * (ci.y2 - ci.y1))
        frame_area = max(1, avatar_state.manifest.width * avatar_state.manifest.height)
        return float(face_area) / float(frame_area)

    def _needs_small_face_assist(
        self,
        avatar_state: FrameAvatarState,
        avatar_frame_idx: int,
    ) -> bool:
        crop_infos = avatar_state.extra.get("crop_infos")
        if not isinstance(crop_infos, list) or not crop_infos:
            return False
        ci = crop_infos[avatar_frame_idx % len(crop_infos)]
        face_ratio = self._small_face_ratio(avatar_state, avatar_frame_idx)
        portrait_fullbody = (
            avatar_state.manifest.height >= int(avatar_state.manifest.width * 1.65)
            and (ci.x2 - ci.x1) <= int(avatar_state.manifest.width * 0.34)
        )
        return portrait_fullbody or face_ratio <= 0.05

    def _add_visible_mouth_cue(
        self,
        prediction: np.ndarray,
        *,
        energy: float,
        assist_strength: float = 1.0,
    ) -> np.ndarray:
        if prediction.ndim != 3:
            return prediction

        assist = float(max(1.0, assist_strength))
        open_amount = float(np.clip((energy - 0.14) / 0.34, 0.0, 1.0))
        if open_amount <= 1e-3:
            return prediction

        import cv2

        out = prediction.copy()
        h, w = out.shape[:2]
        cx = int(round(w * 0.5))
        cy = int(round(h * 0.735))
        rx = max(5, int(round(w * (0.070 + 0.008 * (assist - 1.0)))))
        ry = max(2, int(round(h * (0.008 + 0.020 * open_amount * assist))))

        mouth_mask = np.zeros((h, w), dtype=np.uint8)
        cv2.ellipse(mouth_mask, (cx, cy), (rx, ry), 0, 0, 360, 255, -1)
        mouth_mask = cv2.GaussianBlur(mouth_mask, (0, 0), max(1.2, h * 0.008))
        mouth_mask_f = (mouth_mask.astype(np.float32) / 255.0)[:, :, np.newaxis]

        mouth_color = np.array([30, 18, 58], dtype=np.float32)
        blend = min(0.22, 0.08 + 0.10 * open_amount * assist)
        out = np.clip(
            out.astype(np.float32) * (1.0 - mouth_mask_f * blend) + mouth_color * mouth_mask_f * blend,
            0.0,
            255.0,
        ).astype(np.uint8)

        split_mask = np.zeros((h, w), dtype=np.uint8)
        split_half_w = max(4, int(round(rx * 0.72)))
        split_half_h = max(1, int(round(max(1, ry * 0.20))))
        cv2.ellipse(
            split_mask,
            (cx, cy),
            (split_half_w, split_half_h),
            0,
            0,
            360,
            255,
            -1,
        )
        split_mask = cv2.GaussianBlur(split_mask, (0, 0), max(0.8, h * 0.004))
        split_mask_f = (split_mask.astype(np.float32) / 255.0)[:, :, np.newaxis]
        split_blend = min(0.28, 0.10 + 0.14 * open_amount * assist)
        split_color = np.array([20, 12, 40], dtype=np.float32)
        out = np.clip(
            out.astype(np.float32) * (1.0 - split_mask_f * split_blend)
            + split_color * split_mask_f * split_blend,
            0.0,
            255.0,
        ).astype(np.uint8)
        return out

    def _enhance_small_face_predictions(
        self,
        avatar_state: FrameAvatarState,
        *,
        frame_index_start: int,
        predictions: list[Any],
        frame_energy: np.ndarray,
    ) -> list[Any]:
        enhanced: list[Any] = []
        for i, pred in enumerate(predictions):
            if not isinstance(pred, np.ndarray) or pred.ndim != 3:
                enhanced.append(pred)
                continue
            avatar_frame_idx = resolve_avatar_frame_index(avatar_state, frame_index_start + i)
            if self._small_face_ratio(avatar_state, avatar_frame_idx) > 0.018:
                enhanced.append(pred)
                continue
            energy = float(frame_energy[min(i, frame_energy.shape[0] - 1)])
            enhanced.append(
                self._add_visible_mouth_cue(
                    pred,
                    energy=energy,
                    assist_strength=1.0,
                )
            )
        return enhanced

    @property
    def is_v15(self) -> bool:
        return self._v15_bundle is not None

    def load_model(self, device: str = "cuda") -> None:
        self._device = device

        v15_paths = resolve_musetalk_v15(self._models_dir)
        if v15_paths is not None:
            try:
                self._v15_bundle = load_musetalk_v15_bundle(v15_paths, device)
                logger.info("MuseTalk v1.5 loaded successfully on %s", device)
                return
            except Exception:
                logger.warning("Failed to load MuseTalk v1.5, falling back", exc_info=True)
                self._v15_bundle = None

        ckpt = resolve_musetalk_checkpoint(self._models_dir)
        if ckpt is not None:
            self._torch_bundle = load_musetalk_torch(ckpt, device)
        else:
            logger.info("No MuseTalk weights found; running in fallback frame-cycle mode")
            self._torch_bundle = None

    def load_avatar(self, avatar_path: str) -> FrameAvatarState:
        bundle = load_avatar_bundle(Path(avatar_path))
        if bundle.manifest.model_type != "musetalk":
            raise ValueError(
                f"Avatar {bundle.manifest.id} model_type={bundle.manifest.model_type}, "
                "expected musetalk"
            )
        self._fps = bundle.manifest.fps
        state = load_frame_avatar_state(bundle.path, bundle.manifest)
        metadata = getattr(bundle.manifest, "metadata", None) or {}
        state.extra["preview_frame"] = _runtime_preview_frame(
            load_preview_frame(bundle.path, state.frames[0], bundle.manifest),
            state.frames,
        )
        state.extra["preview_frame_index"] = 0
        state.extra["freeze_speaking_to_preview"] = bool(
            metadata.get("freeze_speaking_to_preview", False)
        )
        prepared_compose_mode = str(metadata.get("prepared_compose_mode", "")).strip().lower()
        if prepared_compose_mode in {"raw_crop", "strict_mask", "feather_crop"}:
            state.extra["musetalk_prepared_compose_mode"] = prepared_compose_mode
        if self.is_v15:
            self._precompute_avatar_data(state)
            state.extra["audio_context_pcm"] = np.zeros(0, dtype=np.int16)
            state.extra["feature_overlap_tail"] = None
            state.extra["prediction_overlap_tail"] = []
            state.extra["audio_total_samples"] = 0
            state.extra["musetalk_prev_energy"] = 0.0
            state.extra["closed_prediction_cache"] = {}

        return state

    def _precompute_avatar_data(self, state: FrameAvatarState) -> None:
        """Pre-compute face crop info and 8-ch UNet latents for all avatar frames."""
        from opentalking.models.musetalk.face_utils import (
            CropInfo,
            create_lower_face_mask,
            crop_face_region_from_box,
            estimate_face_crop_box,
            estimate_infer_face_crop_box,
            smooth_crop_boxes,
        )
        from opentalking.models.musetalk.inference import get_latents_for_unet

        assert self._v15_bundle is not None
        vae = self._v15_bundle["vae"]
        device = self._v15_bundle["device"]

        prepared = resolve_prepared_musetalk_assets(state.avatar_path)
        if prepared is not None:
            crop_infos = [
                CropInfo(
                    x1=x1,
                    y1=y1,
                    x2=x2,
                    y2=y2,
                    original_h=frame.shape[0],
                    original_w=frame.shape[1],
                )
                for frame, (x1, y1, x2, y2) in zip(state.frames, prepared.coords)
            ]
            infer_crop_infos = [
                CropInfo(
                    x1=x1,
                    y1=y1,
                    x2=x2,
                    y2=y2,
                    original_h=frame.shape[0],
                    original_w=frame.shape[1],
                )
                for frame, (x1, y1, x2, y2) in zip(state.frames, prepared.infer_coords)
            ]
            n = min(
                len(crop_infos),
                len(infer_crop_infos),
                len(prepared.latents),
                len(prepared.masks),
                len(prepared.mask_coords),
            )
            state.extra["crop_infos"] = crop_infos[:n]
            state.extra["infer_crop_infos"] = infer_crop_infos[:n]
            state.extra["face_masks"] = prepared.masks[:n]
            state.extra["unet_latents"] = prepared.latents[:n]
            state.extra["prepared_mask_coords"] = prepared.mask_coords[:n]
            state.extra["prepared_assets_root"] = str(prepared.root)
            logger.info(
                "Loaded %d LiveTalking-style prepared MuseTalk assets from %s",
                n,
                prepared.root,
            )
            return

        crop_infos = []
        infer_crop_infos = []
        face_masks = []
        unet_latents = []

        crop_boxes = [estimate_face_crop_box(frame) for frame in state.frames]
        infer_crop_boxes = [estimate_infer_face_crop_box(frame) for frame in state.frames]
        if self._smooth_crop_boxes:
            crop_boxes = smooth_crop_boxes(crop_boxes)
            infer_crop_boxes = smooth_crop_boxes(infer_crop_boxes)

        for frame, crop_box, infer_crop_box in zip(state.frames, crop_boxes, infer_crop_boxes):
            face_region, infer_crop_info = crop_face_region_from_box(frame, infer_crop_box)
            mask = create_lower_face_mask(face_region)
            latent_8ch = get_latents_for_unet(face_region, vae, device)

            x1, y1, x2, y2 = crop_box
            crop_info = CropInfo(
                x1=x1,
                y1=y1,
                x2=x2,
                y2=y2,
                original_h=frame.shape[0],
                original_w=frame.shape[1],
            )

            crop_infos.append(crop_info)
            infer_crop_infos.append(infer_crop_info)
            face_masks.append(mask)
            unet_latents.append(latent_8ch)

        state.extra["crop_infos"] = crop_infos
        state.extra["infer_crop_infos"] = infer_crop_infos
        state.extra["face_masks"] = face_masks
        state.extra["unet_latents"] = unet_latents

        logger.info(
            "Pre-computed %d avatar frames (crops, masks, latents)", len(state.frames)
        )

    def warmup(self) -> None:
        """Warm up v1.5 models with a dummy forward pass."""
        if not self.is_v15:
            return

        import numpy as np
        import torch

        from opentalking.models.musetalk.inference import (
            FACE_SIZE,
            get_latents_for_unet,
            infer_single_step,
        )

        bundle = self._v15_bundle
        assert bundle is not None
        device = bundle["device"]

        dummy_face = np.zeros((FACE_SIZE, FACE_SIZE, 3), dtype=np.uint8)
        dummy_latent = get_latents_for_unet(dummy_face, bundle["vae"], device)
        dummy_audio = torch.zeros(1, 1, 384, device=device, dtype=bundle["unet"].dtype)

        infer_single_step(
            unet=bundle["unet"],
            vae=bundle["vae"],
            latent_input=dummy_latent,
            audio_feature=dummy_audio,
            device=device,
        )
        logger.info("MuseTalk v1.5 warmup complete")

    def extract_features(self, audio_chunk: AudioChunk) -> Any:
        if self.is_v15:
            assert self._v15_bundle is not None
            return extract_whisper_features(
                audio_chunk,
                self._v15_bundle["whisper_model"],
                self._fps,
                self._v15_bundle["device"],
            )
        return extract_mel_placeholder(audio_chunk, self._fps)

    def extract_features_for_stream(self, audio_chunk: AudioChunk, avatar_state: FrameAvatarState) -> Any:
        if not self.is_v15:
            return self.extract_features(audio_chunk)

        assert self._v15_bundle is not None
        left_context_pcm = avatar_state.extra.get("audio_context_pcm")
        if left_context_pcm is None:
            left_context_pcm = np.zeros(0, dtype=np.int16)
        speech_frame_index_start = int(avatar_state.extra.get("speech_frame_index_start", 0))
        samples_before_chunk = int(avatar_state.extra.get("audio_total_samples", 0))

        features, new_context, samples_after_chunk = extract_whisper_features_with_left_context(
            audio_chunk,
            left_context_pcm,
            self._v15_bundle["whisper_model"],
            self._fps,
            device=self._v15_bundle["device"],
            context_keep_ms=self._stream_context_ms,
            frame_index_start=speech_frame_index_start,
            samples_before_chunk=samples_before_chunk,
        )
        prev_tail = avatar_state.extra.get("feature_overlap_tail")
        if isinstance(prev_tail, np.ndarray) and prev_tail.ndim == 3 and features.vector.ndim == 3:
            overlap = min(
                self._stream_overlap_frames,
                prev_tail.shape[0],
                features.vector.shape[0],
            )
            for i in range(overlap):
                prev_idx = prev_tail.shape[0] - overlap + i
                alpha = float(i + 1) / float(overlap + 1)
                features.vector[i] = (
                    prev_tail[prev_idx].astype(np.float32) * (1.0 - alpha)
                    + features.vector[i].astype(np.float32) * alpha
                ).astype(np.float32)
        avatar_state.extra["audio_context_pcm"] = new_context
        avatar_state.extra["audio_total_samples"] = samples_after_chunk
        if features.vector.ndim == 3 and features.vector.shape[0] > 0:
            tail = features.vector[-max(1, self._stream_overlap_frames) :].copy()
        else:
            tail = None
        avatar_state.extra["feature_overlap_tail"] = tail
        return features

    def infer(self, features: Any, avatar_state: FrameAvatarState) -> list[Any]:
        if not isinstance(features, DrivingFeatures):
            return [None]

        n = max(1, features.frame_count)

        if not self.is_v15:
            return [None] * n

        import torch

        from opentalking.models.musetalk.inference import infer_batch_frames

        bundle = self._v15_bundle
        assert bundle is not None
        device = bundle["device"]

        unet_latents = avatar_state.extra["unet_latents"]
        num_avatar_frames = len(unet_latents)
        frame_index_start = int(avatar_state.extra.get("frame_index_start", 0))

        frame_lats = [
            unet_latents[
                resolve_avatar_frame_index(avatar_state, frame_index_start + i)
                % num_avatar_frames
            ]
            for i in range(n)
        ]

        audio_feat = torch.from_numpy(features.vector).to(
            device=device, dtype=bundle["unet"].dtype
        )

        results = infer_batch_frames(
            unet=bundle["unet"],
            vae=bundle["vae"],
            unet_latents=frame_lats,
            audio_features=audio_feat,
            device=device,
        )

        frame_energy = features.frame_energy
        gate_energy = (
            frame_energy.astype(np.float32, copy=False)
            if isinstance(frame_energy, np.ndarray)
            else None
        )
        if isinstance(frame_energy, np.ndarray) and frame_energy.size > 0:
            frame_energy = self._smooth_frame_energy(avatar_state, frame_energy)
            results = self._enhance_small_face_predictions(
                avatar_state,
                frame_index_start=frame_index_start,
                predictions=results,
                frame_energy=frame_energy,
            )
            if self._energy_gain > 1e-6:
                results = self._amplify_predictions_with_energy(
                    avatar_state,
                    frame_index_start=frame_index_start,
                    predictions=results,
                    frame_energy=frame_energy,
                )

        if gate_energy is not None and gate_energy.size > 0 and self._silence_gate_threshold > 0.0:
            silent_indices = [
                i
                for i in range(len(results))
                if float(gate_energy[min(i, gate_energy.shape[0] - 1)]) <= self._silence_gate_threshold
                and isinstance(results[i], np.ndarray)
                and results[i].ndim == 3
            ]
            silent_closed_predictions: dict[int, np.ndarray] = {}
            if silent_indices:
                cache = avatar_state.extra.setdefault("closed_prediction_cache", {})
                silent_latent_indices = {
                    i: resolve_avatar_frame_index(avatar_state, frame_index_start + i)
                    % num_avatar_frames
                    for i in silent_indices
                }
                missing_latent_indices = [
                    latent_idx
                    for latent_idx in dict.fromkeys(silent_latent_indices.values())
                    if latent_idx not in cache
                ]
                if missing_latent_indices:
                    silent_frame_lats = [unet_latents[latent_idx] for latent_idx in missing_latent_indices]
                    silent_audio_feat = torch.from_numpy(
                        np.zeros(
                            (
                                len(missing_latent_indices),
                                features.vector.shape[1],
                                features.vector.shape[2],
                            ),
                            dtype=np.float32,
                        )
                    ).to(device=device, dtype=bundle["unet"].dtype)
                    silent_results = infer_batch_frames(
                        unet=bundle["unet"],
                        vae=bundle["vae"],
                        unet_latents=silent_frame_lats,
                        audio_features=silent_audio_feat,
                        device=device,
                    )
                    for latent_idx, pred in zip(missing_latent_indices, silent_results):
                        if isinstance(pred, np.ndarray) and pred.ndim == 3:
                            cache[latent_idx] = pred
                silent_closed_predictions = {
                    idx: cache[latent_idx]
                    for idx, latent_idx in silent_latent_indices.items()
                    if latent_idx in cache
                }

            gated_results: list[Any] = []
            for i, pred in enumerate(results):
                energy = float(gate_energy[min(i, gate_energy.shape[0] - 1)])
                if (
                    isinstance(pred, np.ndarray)
                    and pred.ndim == 3
                    and energy <= self._silence_gate_threshold
                    and i in silent_closed_predictions
                ):
                    closed_amount = 1.0 - (energy / max(1e-6, self._silence_gate_threshold))
                    gated_results.append(
                        _ClosedMouthPrediction(
                            prediction=pred,
                            closed_prediction=silent_closed_predictions[i],
                            amount=float(np.clip(closed_amount, 0.0, 1.0)),
                        )
                    )
                else:
                    gated_results.append(pred)
            results = gated_results

        return results

    def compose_frame(
        self,
        avatar_state: Any,
        frame_idx: int,
        prediction: Any,
    ) -> VideoFrameData:
        state: FrameAvatarState = avatar_state
        ts = frame_idx * (1000.0 / max(1, state.manifest.fps))
        if isinstance(prediction, _ClosedMouthPrediction):
            prediction = self._blend_prediction_toward_closed_mouth(
                prediction=prediction.prediction,
                closed_prediction=prediction.closed_prediction,
                amount=prediction.amount,
            )
        return compose_simple(state, frame_idx, prediction, timestamp_ms=ts)

    def _blend_prediction_toward_closed_mouth(
        self,
        *,
        prediction: np.ndarray,
        closed_prediction: np.ndarray,
        amount: float,
    ) -> np.ndarray:
        if amount <= 1e-4 or prediction.ndim != 3:
            return prediction

        import cv2

        from opentalking.models.musetalk.face_utils import create_lower_face_mask

        if closed_prediction.ndim != 3 or closed_prediction.shape != prediction.shape:
            return prediction

        pred_f = prediction.astype(np.float32)
        closed_f = closed_prediction.astype(np.float32)
        mask = create_lower_face_mask(prediction, target_size=prediction.shape[0]).astype(np.float32) / 255.0
        mask = cv2.GaussianBlur(mask, (0, 0), prediction.shape[0] * 0.045)
        mask = (mask * float(np.clip(amount, 0.0, 1.0)))[:, :, np.newaxis]

        blended = pred_f * (1.0 - mask) + closed_f * mask
        return np.clip(blended, 0.0, 255.0).astype(np.uint8)

    def idle_frame(self, avatar_state: Any, frame_idx: int) -> VideoFrameData:
        state: FrameAvatarState = avatar_state
        ts = frame_idx * (1000.0 / max(1, state.manifest.fps))
        return numpy_bgr_to_videoframe(
            state.frames[frame_idx % len(state.frames)].copy(),
            ts,
        )

    def _amplify_predictions_with_energy(
        self,
        avatar_state: FrameAvatarState,
        *,
        frame_index_start: int,
        predictions: list[np.ndarray],
        frame_energy: np.ndarray,
    ) -> list[np.ndarray]:
        import cv2

        from opentalking.models.musetalk.face_utils import create_lower_face_mask

        crop_infos = avatar_state.extra.get("crop_infos")
        infer_crop_infos = avatar_state.extra.get("infer_crop_infos")
        if not crop_infos:
            return predictions

        out: list[np.ndarray] = []
        for i, pred in enumerate(predictions):
            if not isinstance(pred, np.ndarray) or pred.ndim != 3:
                out.append(pred)
                continue
            frame_idx = frame_index_start + i
            avatar_frame_idx = resolve_avatar_frame_index(avatar_state, frame_idx)
            energy = float(frame_energy[min(i, frame_energy.shape[0] - 1)])
            local_gain = self._energy_gain
            if self._needs_small_face_assist(avatar_state, avatar_frame_idx):
                local_gain = max(local_gain, 1.2)

            if energy <= 1e-4 or local_gain <= 1e-6:
                out.append(pred)
                continue

            ci = crop_infos[avatar_frame_idx % len(crop_infos)]
            infer_ci = (
                infer_crop_infos[avatar_frame_idx % len(infer_crop_infos)]
                if isinstance(infer_crop_infos, list) and infer_crop_infos
                else ci
            )
            base = avatar_state.frames[avatar_frame_idx]
            base_crop = cv2.resize(
                base[infer_ci.y1 : infer_ci.y2, infer_ci.x1 : infer_ci.x2],
                (pred.shape[1], pred.shape[0]),
                interpolation=cv2.INTER_LINEAR,
            )

            mask = create_lower_face_mask(pred, target_size=pred.shape[0])
            kernel_size = max(11, int(round(pred.shape[0] * 0.12)) | 1)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
            mask = cv2.dilate(mask, kernel, iterations=1)
            mask = cv2.GaussianBlur(mask, (0, 0), pred.shape[0] * 0.05)
            mask_f = (mask.astype(np.float32) / 255.0)[:, :, np.newaxis]

            pred_f = pred.astype(np.float32)
            base_f = base_crop.astype(np.float32)

            pred_luma = 0.114 * pred_f[:, :, 0] + 0.587 * pred_f[:, :, 1] + 0.299 * pred_f[:, :, 2]
            base_luma = 0.114 * base_f[:, :, 0] + 0.587 * base_f[:, :, 1] + 0.299 * base_f[:, :, 2]
            pred_redness = pred_f[:, :, 2] - np.maximum(pred_f[:, :, 1], pred_f[:, :, 0])
            base_redness = base_f[:, :, 2] - np.maximum(base_f[:, :, 1], base_f[:, :, 0])
            dark_gain = np.clip((base_luma - pred_luma + 10.0) / 60.0, 0.0, 1.0)
            red_gain = np.clip((pred_redness - base_redness + 8.0) / 64.0, 0.0, 1.0)
            emphasis = np.maximum(dark_gain, red_gain).astype(np.float32)
            emphasis = cv2.GaussianBlur(emphasis, (0, 0), pred.shape[0] * 0.03)
            emphasis = emphasis[:, :, np.newaxis]
            mask_f = mask_f * emphasis

            scale = 1.0 + local_gain * (energy ** 1.05)
            amplified_crop = base_f + (pred_f - base_f) * scale

            amp_luma = 0.114 * amplified_crop[:, :, 0] + 0.587 * amplified_crop[:, :, 1] + 0.299 * amplified_crop[:, :, 2]
            allowed_luma = np.maximum(pred_luma, base_luma) + (4.0 + 10.0 * energy)
            halo = np.clip((amp_luma - allowed_luma) / 32.0, 0.0, 1.0)[:, :, np.newaxis]
            amplified_crop = amplified_crop * (1.0 - halo) + pred_f * halo

            amplified_crop = np.clip(amplified_crop, 0.0, 255.0)
            mixed = pred_f * (1.0 - mask_f) + amplified_crop * mask_f
            out.append(np.clip(mixed, 0.0, 255.0).astype(np.uint8))
        return out

    def _smooth_frame_energy(
        self,
        avatar_state: FrameAvatarState,
        frame_energy: np.ndarray,
    ) -> np.ndarray:
        prev = float(avatar_state.extra.get("musetalk_prev_energy", 0.0))
        smoothed = np.zeros_like(frame_energy, dtype=np.float32)
        for i, raw in enumerate(frame_energy.astype(np.float32, copy=False)):
            target = float(np.clip(raw, 0.0, 1.0))
            alpha = self._energy_attack if target >= prev else self._energy_release
            proposed = prev + (target - prev) * alpha
            delta = proposed - prev
            if delta > 0.0:
                delta = min(delta, self._energy_max_step_up)
            else:
                delta = max(delta, -self._energy_max_step_down)
            prev = np.clip(prev + delta, 0.0, 1.0)
            smoothed[i] = prev
        avatar_state.extra["musetalk_prev_energy"] = prev
        return smoothed
