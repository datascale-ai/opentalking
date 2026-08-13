from __future__ import annotations

import asyncio

import numpy as np

from opentalking.streaming.chunks import ChunkEOF, ChunkHub, ChunkQueue, MediaChunk
from opentalking.streaming.types import ProgramVideo


def _chunk(sequence: int, *, keyframe: bool = False) -> MediaChunk:
    frame = ProgramVideo(
        data=np.zeros((4, 4, 3), dtype=np.uint8),
        width=4,
        height=4,
        timestamp_ms=float(sequence * 1000),
    )
    return MediaChunk(
        sequence=sequence,
        start_pts_ms=float(sequence * 1000),
        end_pts_ms=float((sequence + 1) * 1000),
        video=(frame,),
        starts_with_keyframe=keyframe,
    )


def test_chunk_queue_is_lossless_and_tracks_buffer() -> None:
    async def run() -> None:
        queue = ChunkQueue(max_chunks=1)
        first = _chunk(0, keyframe=True)
        second = _chunk(1)
        await queue.put(first)
        consumed: list[object] = []

        async def consume() -> None:
            consumed.append(await queue.get())

        task = asyncio.create_task(consume())
        await queue.put(second)
        await task
        assert [item.sequence for item in consumed if isinstance(item, MediaChunk)] == [0]
        second_consumed = await queue.get()
        assert isinstance(second_consumed, MediaChunk) and second_consumed.sequence == 1
        assert queue.buffer_duration_ms == 0
        assert queue.blocked_ms >= 0
        await queue.finish()
        assert queue.closed

    asyncio.run(run())


def test_chunk_hub_replays_from_latest_keyframe_and_finishes_subscriber() -> None:
    async def run() -> None:
        hub = ChunkHub(max_chunks=4, replay_chunks=4)
        await hub.publish(_chunk(0, keyframe=True))
        await hub.publish(_chunk(1))
        await hub.publish(_chunk(2, keyframe=True))
        await hub.publish(_chunk(3))
        queue = await hub.subscribe()
        replay = [await queue.get(), await queue.get()]
        assert [item.sequence for item in replay if isinstance(item, MediaChunk)] == [2, 3]
        await hub.finish()
        marker = await queue.get()
        assert marker.__class__.__name__ == "ChunkEOF"

    asyncio.run(run())


def test_chunk_queue_can_append_eof_when_media_quota_is_full() -> None:
    async def run() -> None:
        queue = ChunkQueue(max_chunks=2)
        await queue.put(_chunk(0, keyframe=True))
        await queue.put(_chunk(1))

        # EOF is a terminal control marker, not another media slot.  This
        # must complete even before a consumer starts draining the queue.
        await asyncio.wait_for(queue.finish(), timeout=0.1)

        assert isinstance(await queue.get(), MediaChunk)
        assert isinstance(await queue.get(), MediaChunk)
        assert isinstance(await queue.get(), ChunkEOF)

    asyncio.run(run())


def test_unsubscribing_a_full_subscriber_unblocks_hub_publish() -> None:
    async def run() -> None:
        hub = ChunkHub(max_chunks=1, replay_chunks=1)
        queue = await hub.subscribe()
        await hub.publish(_chunk(0, keyframe=True))

        blocked_publish = asyncio.create_task(hub.publish(_chunk(1)))
        await asyncio.sleep(0)
        assert not blocked_publish.done()

        await hub.unsubscribe(queue)
        await asyncio.wait_for(blocked_publish, timeout=0.1)
        assert hub.subscriber_count == 0

    asyncio.run(run())
