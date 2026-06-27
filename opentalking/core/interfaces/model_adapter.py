from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from opentalking.core.types.frames import AudioChunk, VideoFrameData


@runtime_checkable
class ModelAdapter(Protocol):
    """Unified interface for lip-sync / talking-head models."""

    @property
    def model_type(self) -> str: ...

    def load_model(self, device: str = "cuda") -> None:
        """Load model weights onto device."""

    def load_avatar(self, avatar_path: str) -> Any:
        """Load avatar assets; returns opaque model-specific state."""

    def warmup(self) -> None:
        """Warm up inference (first batch is often slow)."""

    def extract_features(self, audio_chunk: AudioChunk) -> Any:
        """Extract driving features from an audio chunk."""

    def infer(self, features: Any, avatar_state: Any) -> list[Any]:
        """Run model inference; returns per-step predictions."""

    def compose_frame(
        self,
        avatar_state: Any,
        frame_idx: int,
        prediction: Any,
    ) -> VideoFrameData:
        """Compose a full video frame from prediction + avatar state."""

    def idle_frame(self, avatar_state: Any, frame_idx: int) -> VideoFrameData:
        """Return a frame when not speaking (loop / hold last)."""
