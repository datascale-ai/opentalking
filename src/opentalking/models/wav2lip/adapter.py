from __future__ import annotations

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
from opentalking.models.musetalk.feature_extractor import DrivingFeatures
from opentalking.models.registry import register_model
from opentalking.models.wav2lip.feature_extractor import extract_mel_for_wav2lip
from opentalking.models.wav2lip.loader import load_wav2lip_torch, resolve_wav2lip_checkpoint


@register_model("wav2lip")
class Wav2LipAdapter:
    model_type = "wav2lip"

    def __init__(self) -> None:
        self._device = os.environ.get("OPENTALKING_TORCH_DEVICE", "cuda")
        self._models_dir = Path(os.environ.get("OPENTALKING_MODELS_DIR", "./models")).resolve()
        self._torch_bundle: dict[str, Any] | None = None
        self._fps = int(os.environ.get("OPENTALKING_DEFAULT_FPS", "25"))

    def load_model(self, device: str = "cuda") -> None:
        self._device = device
        ckpt = resolve_wav2lip_checkpoint(self._models_dir)
        if ckpt is None:
            self._torch_bundle = None
            return
        self._torch_bundle = load_wav2lip_torch(ckpt, device)

    def load_avatar(self, avatar_path: str) -> FrameAvatarState:
        bundle = load_avatar_bundle(Path(avatar_path))
        if bundle.manifest.model_type != "wav2lip":
            raise ValueError(
                f"Avatar {bundle.manifest.id} model_type={bundle.manifest.model_type}, expected wav2lip"
            )
        self._fps = bundle.manifest.fps
        return load_frame_avatar_state(bundle.path, bundle.manifest)

    def warmup(self) -> None:
        return

    def extract_features(self, audio_chunk: AudioChunk) -> Any:
        return extract_mel_for_wav2lip(audio_chunk, self._fps)

    def infer(self, features: Any, avatar_state: FrameAvatarState) -> list[Any]:
        if isinstance(features, DrivingFeatures):
            n = max(1, features.frame_count)
        else:
            n = 1
        return [None] * n

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
