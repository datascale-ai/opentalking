from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable

from opentalking.core.types.frames import AudioChunk


@runtime_checkable
class TTSAdapter(Protocol):
    """Text-to-speech streaming interface."""

    async def synthesize_stream(
        self,
        text: str,
        voice: str | None = None,
    ) -> AsyncIterator[AudioChunk]:
        """Yield audio chunks (PCM) as they are synthesized."""
        ...
