from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from opentalking.core.types.frames import AudioChunk


class AudioPipeline:
    """Consumes TTS stream and pushes audio chunks to a sink."""

    def __init__(
        self,
        sink: Callable[[AudioChunk], Awaitable[None]],
    ) -> None:
        self._sink = sink

    async def run_tts_chunks(self, chunks: list[AudioChunk]) -> None:
        for c in chunks:
            await self._sink(c)

    async def drain_queue(self, q: asyncio.Queue[AudioChunk | None]) -> None:
        while True:
            item = await q.get()
            if item is None:
                return
            await self._sink(item)
