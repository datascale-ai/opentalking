from __future__ import annotations

import asyncio

import numpy as np

from opentalking.core.types.frames import VideoFrameData
from opentalking.streaming.manager import ProgramOutputManager


def test_branches_are_independent_and_slow_branch_is_bounded() -> None:
    async def run() -> None:
        fast_video: list[float] = []
        slow_gate = asyncio.Event()

        async def fast(item) -> None:
            fast_video.append(item.timestamp_ms)

        async def slow(item) -> None:
            await slow_gate.wait()

        manager = ProgramOutputManager(fps=25, sample_rate=48_000, max_video_frames=2)
        manager.add_branch("fast", video_callback=fast, max_video_frames=16)
        manager.add_branch("slow", video_callback=slow, max_video_frames=2)

        for _ in range(6):
            await manager.offer_video(VideoFrameData(np.zeros((2, 2, 3), dtype=np.uint8), 2, 2, 0))
        await asyncio.sleep(0.01)

        assert manager.branch_stats()["slow"].dropped_video > 0
        # Fast branch is not blocked by the slow callback.
        assert len(fast_video) == 6
        slow_gate.set()
        await manager.close()

    asyncio.run(run())


def test_audio_is_split_into_constant_20ms_program_ticks() -> None:
    async def run() -> None:
        received = []

        async def sink(item) -> None:
            received.append(item)

        manager = ProgramOutputManager(sample_rate=48_000, audio_tick_ms=20)
        manager.add_branch("sink", audio_callback=sink)
        await manager.offer_audio(np.ones(2_000, dtype=np.int16), 48_000, source="speech")
        await asyncio.sleep(0.01)

        assert [item.timestamp_ms for item in received] == [0.0, 20.0, 40.0]
        assert [len(item.data) for item in received] == [960, 960, 960]
        assert all(item.source == "speech" for item in received)
        await manager.close()

    asyncio.run(run())


def test_audio_source_is_resampled_to_program_clock() -> None:
    async def run() -> None:
        received = []

        async def sink(item) -> None:
            received.append(item)

        manager = ProgramOutputManager(sample_rate=48_000, audio_tick_ms=20)
        manager.add_branch("sink", audio_callback=sink)
        await manager.offer_audio(np.ones(320, dtype=np.int16), 16_000, source="speech")
        await asyncio.sleep(0.01)

        assert received
        assert received[0].sample_rate == 48_000
        assert all(len(item.data) == 960 for item in received)
        await manager.close()

    asyncio.run(run())


def test_close_cancels_blocked_branch_callback() -> None:
    async def run() -> None:
        gate = asyncio.Event()

        async def blocked(item) -> None:
            del item
            await gate.wait()

        manager = ProgramOutputManager(max_video_frames=2)
        manager.add_branch("blocked", video_callback=blocked)
        await manager.offer_video(VideoFrameData(np.zeros((2, 2, 3), dtype=np.uint8), 2, 2, 0))
        await asyncio.sleep(0)
        await asyncio.wait_for(manager.close(), timeout=1.0)

    asyncio.run(run())
