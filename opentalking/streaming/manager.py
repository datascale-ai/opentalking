from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import numpy as np
from av import AudioFrame
from av.audio.resampler import AudioResampler

from opentalking.core.types.frames import AudioChunk, VideoFrameData

from .clock import ProgramClock
from .types import OutputBranchStats, ProgramAudio, ProgramVideo

log = logging.getLogger(__name__)

VideoCallback = Callable[[ProgramVideo], Awaitable[None] | None]
AudioCallback = Callable[[ProgramAudio], Awaitable[None] | None]


async def _invoke(callback: Callable[[Any], Awaitable[None] | None], item: Any) -> None:
    result = callback(item)
    if inspect.isawaitable(result):
        await result


@dataclass
class _Branch:
    name: str
    video_callback: VideoCallback | None
    audio_callback: AudioCallback | None
    max_video: int
    max_audio: int
    video_queue: asyncio.Queue[ProgramVideo | None] = field(init=False)
    audio_queue: asyncio.Queue[ProgramAudio | None] = field(init=False)
    stats: OutputBranchStats = field(default_factory=OutputBranchStats)
    video_task: asyncio.Task[None] | None = None
    audio_task: asyncio.Task[None] | None = None
    closed: bool = False

    def __post_init__(self) -> None:
        self.video_queue = asyncio.Queue(maxsize=max(1, self.max_video))
        self.audio_queue = asyncio.Queue(maxsize=max(1, self.max_audio))


class ProgramOutputManager:
    """Fan-out raw program media to independently backpressured branches.

    Producers never await a branch callback.  Each branch owns separate audio
    and video queues and workers, so a stalled RTMPS socket cannot stop model
    rendering, Studio WebRTC, or another external output.
    """

    def __init__(
        self,
        *,
        fps: float = 25.0,
        sample_rate: int = 48_000,
        audio_tick_ms: int = 20,
        max_video_frames: int = 128,
        max_audio_ticks: int | None = None,
    ) -> None:
        self.clock = ProgramClock(fps=fps, sample_rate=sample_rate, audio_tick_ms=audio_tick_ms)
        self.max_video_frames = max(1, int(max_video_frames))
        self.max_audio_ticks = max_audio_ticks or max(1, int(round(2000 / audio_tick_ms)))
        self._branches: dict[str, _Branch] = {}
        self._closed = False
        self._lock = asyncio.Lock()
        self._resamplers: dict[int, AudioResampler] = {}

    @property
    def branches(self) -> tuple[str, ...]:
        return tuple(self._branches)

    def add_branch(
        self,
        name: str,
        *,
        video_callback: VideoCallback | None = None,
        audio_callback: AudioCallback | None = None,
        max_video_frames: int | None = None,
        max_audio_ticks: int | None = None,
    ) -> None:
        if self._closed:
            raise RuntimeError("program output manager is closed")
        key = name.strip()
        if not key or key in self._branches:
            raise ValueError("branch name must be non-empty and unique")
        if video_callback is None and audio_callback is None:
            raise ValueError("branch requires an audio or video callback")
        branch = _Branch(
            key,
            video_callback,
            audio_callback,
            max_video_frames or self.max_video_frames,
            max_audio_ticks or self.max_audio_ticks,
        )
        self._branches[key] = branch
        if video_callback is not None:
            branch.video_task = asyncio.create_task(self._run_video(branch), name=f"program-video-{key}")
        if audio_callback is not None:
            branch.audio_task = asyncio.create_task(self._run_audio(branch), name=f"program-audio-{key}")

    def remove_branch(self, name: str) -> None:
        branch = self._branches.pop(name, None)
        if branch is not None:
            branch.closed = True
            for task in (branch.video_task, branch.audio_task):
                if task is not None:
                    task.cancel()
            self._put_sentinel(branch.video_queue)
            self._put_sentinel(branch.audio_queue)

    @staticmethod
    def _put_sentinel(queue: asyncio.Queue[Any]) -> None:
        try:
            queue.put_nowait(None)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(None)
            except asyncio.QueueFull:
                pass

    @staticmethod
    def _offer_nowait(queue: asyncio.Queue[Any], item: Any) -> tuple[bool, bool]:
        try:
            queue.put_nowait(item)
            return True, False
        except asyncio.QueueFull:
            # Live output is only useful when current.  Drop the oldest item
            # from this branch, never block the renderer waiting for a dead
            # receiver.
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                return False, False
            try:
                queue.put_nowait(item)
                return True, True
            except asyncio.QueueFull:
                return False, True

    async def offer_video(
        self,
        frame: VideoFrameData | ProgramVideo,
        *,
        source: str = "unknown",
        utterance_id: str | None = None,
    ) -> ProgramVideo:
        if self._closed:
            raise RuntimeError("program output manager is closed")
        if isinstance(frame, ProgramVideo):
            data = frame.data
            width, height = frame.width, frame.height
        else:
            data = np.asarray(frame.data, dtype=np.uint8)
            height, width = data.shape[:2]
        item = ProgramVideo(
            data=np.ascontiguousarray(data),
            width=int(width),
            height=int(height),
            timestamp_ms=self.clock.next_video(),
            source=source,
            utterance_id=utterance_id,
        )
        for branch in tuple(self._branches.values()):
            if branch.closed or branch.video_callback is None:
                continue
            branch.stats.offered_video += 1
            accepted, dropped = self._offer_nowait(branch.video_queue, item)
            if dropped or not accepted:
                branch.stats.dropped_video += 1
        return item

    async def offer_audio(
        self,
        pcm: np.ndarray | AudioChunk | ProgramAudio,
        sample_rate: int | None = None,
        *,
        source: str = "unknown",
        utterance_id: str | None = None,
    ) -> list[ProgramAudio]:
        if self._closed:
            raise RuntimeError("program output manager is closed")
        if isinstance(pcm, ProgramAudio):
            data = np.asarray(pcm.data, dtype=np.int16).reshape(-1)
            rate = pcm.sample_rate
        elif isinstance(pcm, AudioChunk):
            data = np.asarray(pcm.data, dtype=np.int16).reshape(-1)
            rate = pcm.sample_rate
        else:
            data = np.asarray(pcm, dtype=np.int16).reshape(-1)
            rate = int(sample_rate or self.clock.sample_rate)
        if rate != self.clock.sample_rate:
            data = self._resample(data, src_rate=rate, dst_rate=self.clock.sample_rate)
            rate = self.clock.sample_rate
        if data.size == 0:
            return []
        tick = self.clock.audio_tick_samples
        result: list[ProgramAudio] = []
        for start in range(0, data.size, tick):
            part = data[start:start + tick]
            if part.size < tick:
                part = np.pad(part, (0, tick - part.size))
            timestamp, _ = self.clock.next_audio_tick()
            item = ProgramAudio(
                data=np.ascontiguousarray(part, dtype=np.int16),
                sample_rate=rate,
                timestamp_ms=timestamp,
                source=source,
                utterance_id=utterance_id,
            )
            result.append(item)
            for branch in tuple(self._branches.values()):
                if branch.closed or branch.audio_callback is None:
                    continue
                branch.stats.offered_audio += 1
                accepted, dropped = self._offer_nowait(branch.audio_queue, item)
                if dropped or not accepted:
                    branch.stats.dropped_audio += 1
        return result

    def _resample(self, data: np.ndarray, *, src_rate: int, dst_rate: int) -> np.ndarray:
        if data.size == 0 or src_rate == dst_rate:
            return data
        resampler = self._resamplers.get(src_rate)
        if resampler is None:
            resampler = AudioResampler(format="s16", layout="mono", rate=dst_rate)
            self._resamplers[src_rate] = resampler
        frame = AudioFrame(format="s16", layout="mono", samples=int(data.size))
        frame.planes[0].update(np.asarray(data, dtype=np.int16).astype("<i2", copy=False).tobytes())
        frame.sample_rate = int(src_rate)
        parts = [item.to_ndarray().reshape(-1).astype(np.int16, copy=False) for item in resampler.resample(frame)]
        if not parts:
            return np.zeros(0, dtype=np.int16)
        return np.concatenate(parts).astype(np.int16, copy=False)

    async def offer_silence(self, *, source: str = "silence") -> ProgramAudio:
        item = await self.offer_audio(
            np.zeros(self.clock.audio_tick_samples, dtype=np.int16),
            self.clock.sample_rate,
            source=source,
        )
        return item[-1]

    async def mark_utterance_end(self, utterance_id: str | None = None) -> None:
        # Kept as an explicit hook for publishers that need to close an
        # encoder access unit.  The clock intentionally does not reset here.
        del utterance_id

    async def _run_video(self, branch: _Branch) -> None:
        assert branch.video_callback is not None
        while not branch.closed:
            item = await branch.video_queue.get()
            if item is None:
                break
            try:
                await _invoke(branch.video_callback, item)
                branch.stats.delivered_video += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - exercised by integration sinks
                branch.stats.callback_errors += 1
                branch.stats.last_error = type(exc).__name__
                log.warning("program video branch %s failed: %s", branch.name, exc)

    async def _run_audio(self, branch: _Branch) -> None:
        assert branch.audio_callback is not None
        while not branch.closed:
            item = await branch.audio_queue.get()
            if item is None:
                break
            try:
                await _invoke(branch.audio_callback, item)
                branch.stats.delivered_audio += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - exercised by integration sinks
                branch.stats.callback_errors += 1
                branch.stats.last_error = type(exc).__name__
                log.warning("program audio branch %s failed: %s", branch.name, exc)

    def branch_stats(self) -> dict[str, OutputBranchStats]:
        return {name: branch.stats for name, branch in self._branches.items()}

    def branch_metrics(self, name: str) -> dict[str, int]:
        """Return queue/counter metrics without exposing media payloads."""
        branch = self._branches.get(name)
        if branch is None:
            return {}
        return {
            "video_queue_depth": branch.video_queue.qsize(),
            "audio_queue_depth": branch.audio_queue.qsize(),
            "dropped_video": branch.stats.dropped_video,
            "dropped_audio": branch.stats.dropped_audio,
            "callback_errors": branch.stats.callback_errors,
        }

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        branches = list(self._branches.values())
        self._branches.clear()
        for branch in branches:
            branch.closed = True
            for task in (branch.video_task, branch.audio_task):
                if task is not None:
                    task.cancel()
            self._put_sentinel(branch.video_queue)
            self._put_sentinel(branch.audio_queue)
        tasks = [
            task
            for branch in branches
            for task in (branch.video_task, branch.audio_task)
            if task is not None
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
