"""SynthesisAdapter — audio stream to video frame stream.

All implementations are thin clients backed by an external inference runtime
(omnirt). Local synthesis was removed; see docs/architecture-review.md.
"""
from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable


@runtime_checkable
class SynthesisAdapter(Protocol):
    async def stream_audio_to_video(
        self,
        audio_chunks: AsyncIterator[bytes],
        *,
        reference_image: bytes,
        params: dict | None = None,
    ) -> AsyncIterator[bytes]:
        """Yield video frame bytes (encoded JPEG/PNG or raw RGB)."""
        ...
