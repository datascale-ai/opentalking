from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from opentalking.avatars.loader import load_avatar_bundle
from opentalking.core.types.frames import AudioChunk, VideoFrameData
from opentalking.models.common.frame_avatar import (
    FrameAvatarState,
    load_frame_avatar_state,
    numpy_bgr_to_videoframe,
)
from opentalking.models.musetalk.composer import compose_simple
from opentalking.models.musetalk.feature_extractor import (
    DrivingFeatures,
    extract_mel_placeholder,
    extract_whisper_features,
)
from opentalking.models.musetalk.loader import (
    load_musetalk_torch,
    load_musetalk_v15_bundle,
    resolve_musetalk_checkpoint,
    resolve_musetalk_v15,
)
from opentalking.models.registry import register_model

logger = logging.getLogger(__name__)


@register_model("musetalk")
class MuseTalkAdapter:
    """MuseTalk adapter with v1.5 neural inference and fallback frame-cycle mode.

    When v1.5 checkpoints are present, runs full Whisper + UNet + VAE pipeline.
    When checkpoints are missing, gracefully falls back to frame cycling.
    """

    model_type = "musetalk"

    def __init__(self) -> None:
        self._device = os.environ.get("OPENTALKING_TORCH_DEVICE", "cuda")
        self._models_dir = Path(os.environ.get("OPENTALKING_MODELS_DIR", "./models")).resolve()
        self._torch_bundle: dict[str, Any] | None = None
        self._v15_bundle: dict[str, Any] | None = None
        self._fps = int(os.environ.get("OPENTALKING_DEFAULT_FPS", "25"))

    @property
    def is_v15(self) -> bool:
        """True when full v1.5 models are loaded."""
        return self._v15_bundle is not None

    def load_model(self, device: str = "cuda") -> None:
        self._device = device

        # Try v1.5 first (full pipeline)
        v15_paths = resolve_musetalk_v15(self._models_dir)
        if v15_paths is not None:
            try:
                self._v15_bundle = load_musetalk_v15_bundle(v15_paths, device)
                logger.info("MuseTalk v1.5 loaded successfully on %s", device)
                return
            except Exception:
                logger.warning("Failed to load MuseTalk v1.5, falling back", exc_info=True)
                self._v15_bundle = None

        # Legacy single-weight fallback
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

        # Pre-compute face crops and masks for v1.5
        if self.is_v15:
            self._precompute_avatar_data(state)

        return state

    def _precompute_avatar_data(self, state: FrameAvatarState) -> None:
        """Pre-compute face crop info, masks, and VAE latents for all avatar frames."""
        from opentalking.models.musetalk.face_utils import (
            create_lower_face_mask,
            crop_face_region,
            mask_to_latent_mask,
        )
        from opentalking.models.musetalk.inference import encode_face_to_latent

        assert self._v15_bundle is not None
        vae = self._v15_bundle["vae"]
        device = self._v15_bundle["device"]

        crop_infos = []
        face_masks = []
        face_latents = []
        mask_latents = []

        for frame in state.frames:
            face_region, crop_info = crop_face_region(frame)
            mask = create_lower_face_mask(face_region)
            latent = encode_face_to_latent(face_region, vae, device)
            m_latent = mask_to_latent_mask(mask).to(device=device, dtype=vae.dtype)

            crop_infos.append(crop_info)
            face_masks.append(mask)
            face_latents.append(latent)
            mask_latents.append(m_latent)

        state.extra["crop_infos"] = crop_infos
        state.extra["face_masks"] = face_masks
        state.extra["face_latents"] = face_latents
        state.extra["mask_latents"] = mask_latents

        logger.info(
            "Pre-computed %d avatar frames (crops, masks, latents)", len(state.frames)
        )

    def warmup(self) -> None:
        """Warm up v1.5 models with a dummy forward pass."""
        if not self.is_v15:
            return

        import numpy as np

        from opentalking.models.musetalk.inference import (
            FACE_SIZE,
            encode_face_to_latent,
            infer_single_step,
        )
        from opentalking.models.musetalk.face_utils import (
            create_lower_face_mask,
            mask_to_latent_mask,
        )

        bundle = self._v15_bundle
        assert bundle is not None
        device = bundle["device"]

        # Dummy face
        dummy_face = np.zeros((FACE_SIZE, FACE_SIZE, 3), dtype=np.uint8)
        dummy_latent = encode_face_to_latent(dummy_face, bundle["vae"], device)
        dummy_mask = create_lower_face_mask(dummy_face)
        dummy_mask_latent = mask_to_latent_mask(dummy_mask).to(
            device=device, dtype=bundle["vae"].dtype
        )

        # Dummy audio feature
        import torch

        dummy_audio = torch.zeros(1, 1, 384, device=device, dtype=bundle["unet"].dtype)

        infer_single_step(
            unet=bundle["unet"],
            vae=bundle["vae"],
            face_latent=dummy_latent,
            mask_latent=dummy_mask_latent,
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

    def infer(self, features: Any, avatar_state: FrameAvatarState) -> list[Any]:
        if not isinstance(features, DrivingFeatures):
            return [None]

        n = max(1, features.frame_count)

        if not self.is_v15:
            return [None] * n

        # v1.5 neural inference
        import torch

        from opentalking.models.musetalk.inference import infer_batch_frames

        bundle = self._v15_bundle
        assert bundle is not None
        device = bundle["device"]

        # Get pre-computed latents and masks for the avatar frames we need
        face_latents = avatar_state.extra["face_latents"]
        mask_latents = avatar_state.extra["mask_latents"]
        num_avatar_frames = len(face_latents)

        # Select latents for the frames we need to generate
        # Use current frame index cycling through avatar frames
        frame_lats = [face_latents[i % num_avatar_frames] for i in range(n)]
        mask_lats = [mask_latents[i % num_avatar_frames] for i in range(n)]

        # Convert whisper features to tensor
        audio_feat = torch.from_numpy(features.vector).unsqueeze(0)  # (1, T, D)
        audio_feat = audio_feat.to(device=device, dtype=bundle["unet"].dtype)

        results = infer_batch_frames(
            unet=bundle["unet"],
            vae=bundle["vae"],
            face_latents=frame_lats,
            mask_latents=mask_lats,
            audio_features=audio_feat,
            device=device,
        )

        return results  # list[np.ndarray], each (256, 256, 3) BGR

    def compose_frame(
        self,
        avatar_state: Any,
        frame_idx: int,
        prediction: Any,
    ) -> VideoFrameData:
        state: FrameAvatarState = avatar_state
        ts = frame_idx * (1000.0 / max(1, state.manifest.fps))
        return compose_simple(state, frame_idx, prediction, timestamp_ms=ts)

    def idle_frame(self, avatar_state: Any, frame_idx: int) -> VideoFrameData:
        state: FrameAvatarState = avatar_state
        ts = frame_idx * (1000.0 / max(1, state.manifest.fps))
        return numpy_bgr_to_videoframe(
            state.frames[frame_idx % len(state.frames)].copy(),
            ts,
        )
