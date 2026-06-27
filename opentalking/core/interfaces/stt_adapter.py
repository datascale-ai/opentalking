"""STTAdapter — streaming speech-to-text."""
from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable


@runtime_checkable
class STTAdapter(Protocol):
    async def transcribe(
        self,
        pcm_chunks: AsyncIterator[bytes],
        *,
        sample_rate: int = 16000,
    ) -> AsyncIterator[str]:
        ...
