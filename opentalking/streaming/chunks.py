from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Deque
from .types import ProgramAudio, ProgramVideo


@dataclass(frozen=True, slots=True)
class MediaChunk:
    """A finite, timestamped piece of an offline video program.

    The frames keep the job-wide media clock.  A chunk boundary is only a
    queue/framing boundary; it must never reset either audio or video PTS.
    """

    sequence: int
    start_pts_ms: float
    end_pts_ms: float
    video: tuple[ProgramVideo, ...] = ()
    audio: tuple[ProgramAudio, ...] = ()
    starts_with_keyframe: bool = False
    is_final: bool = False

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("chunk sequence must be non-negative")
        if self.start_pts_ms < 0 or self.end_pts_ms < self.start_pts_ms:
            raise ValueError("chunk PTS range is invalid")
        if not self.video and not self.audio and not self.is_final:
            raise ValueError("non-final media chunk must contain audio or video")

    @property
    def duration_ms(self) -> float:
        return max(0.0, float(self.end_pts_ms) - float(self.start_pts_ms))


@dataclass(frozen=True, slots=True)
class ChunkEOF:
    """Normal end-of-stream marker."""


@dataclass(frozen=True, slots=True)
class ChunkFailure:
    """Safe producer failure marker; never carries secret-bearing exceptions."""

    code: str
    detail: str = ""


ChunkMessage = MediaChunk | ChunkEOF | ChunkFailure


class ChunkQueueClosed(RuntimeError):
    """Raised when a producer writes to a queue that was unsubscribed."""


class ChunkQueue:
    """A bounded, lossless queue for one offline RTMPS subscriber."""

    def __init__(self, *, max_chunks: int = 8) -> None:
        self.max_chunks = max(1, int(max_chunks))
        # Keep the terminal marker outside the media quota.  A queue can hold
        # ``max_chunks`` media items and one EOF/failure marker, so closing a
        # subscriber can never wait for a consumer to make room for EOF.
        #
        # This uses a condition rather than asyncio.Queue.put() so a pending
        # media producer is woken when unsubscribe/finish closes the queue.
        # Otherwise a failed publisher could leave VideoCreationJob blocked
        # forever in ChunkHub.publish().
        self._queue: Deque[ChunkMessage] = deque()
        self._condition = asyncio.Condition()
        self._closed = False
        self._media_depth = 0
        self._buffer_duration_ms = 0.0
        self._last_sequence: int | None = None
        self._last_end_pts_ms: float | None = None
        self._put_wait_ms = 0.0

    @property
    def depth(self) -> int:
        return self._media_depth

    @property
    def buffer_duration_ms(self) -> float:
        return max(0.0, self._buffer_duration_ms)

    @property
    def blocked_ms(self) -> float:
        return max(0.0, self._put_wait_ms)

    @property
    def closed(self) -> bool:
        return self._closed

    async def put(self, chunk: MediaChunk) -> None:
        loop = asyncio.get_running_loop()
        started = loop.time()
        async with self._condition:
            while self._media_depth >= self.max_chunks and not self._closed:
                await self._condition.wait()
            self._put_wait_ms += max(0.0, (loop.time() - started) * 1000.0)
            if self._closed:
                raise ChunkQueueClosed("chunk queue is closed")
            if self._last_sequence is not None and chunk.sequence <= self._last_sequence:
                raise ValueError("chunk sequence must increase monotonically")
            if self._last_end_pts_ms is not None and chunk.start_pts_ms < self._last_end_pts_ms:
                raise ValueError("chunk PTS must not move backwards")
            self._queue.append(chunk)
            self._last_sequence = chunk.sequence
            self._last_end_pts_ms = float(chunk.end_pts_ms)
            self._media_depth += 1
            self._buffer_duration_ms += chunk.duration_ms
            self._condition.notify_all()

    async def finish(self) -> None:
        async with self._condition:
            if self._closed:
                return
            self._closed = True
            self._queue.append(ChunkEOF())
            self._condition.notify_all()

    async def fail(self, code: str, detail: str = "") -> None:
        async with self._condition:
            if self._closed:
                return
            self._closed = True
            self._queue.append(ChunkFailure(code=str(code), detail=str(detail)))
            self._condition.notify_all()

    async def get(self) -> ChunkMessage:
        async with self._condition:
            while not self._queue:
                await self._condition.wait()
            message = self._queue.popleft()
            if isinstance(message, MediaChunk):
                self._media_depth = max(0, self._media_depth - 1)
                self._buffer_duration_ms = max(0.0, self._buffer_duration_ms - message.duration_ms)
            self._condition.notify_all()
            return message


class ChunkHub:
    """Fan out generated chunks to RTMPS subscribers with a short GOP replay.

    A subscriber can join after the first frame and still begin at the latest
    keyframe-aligned replay window.  The hub deliberately retains only a
    bounded recent window; it is not an archive of the whole video.
    """

    def __init__(
        self,
        *,
        max_chunks: int = 8,
        replay_chunks: int = 8,
        subscriber_put_timeout_sec: float = 5.0,
    ) -> None:
        self.max_chunks = max(1, int(max_chunks))
        self.replay_chunks = min(self.max_chunks, max(1, int(replay_chunks)))
        self.subscriber_put_timeout_sec = max(0.0, float(subscriber_put_timeout_sec))
        self._subscribers: set[ChunkQueue] = set()
        self._history: deque[MediaChunk] = deque(maxlen=self.replay_chunks)
        self._closed = False
        self._failure: ChunkFailure | None = None
        self._last_sequence: int | None = None
        self._last_end_pts_ms: float | None = None
        self._lock = asyncio.Lock()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def history(self) -> tuple[MediaChunk, ...]:
        return tuple(self._history)

    async def subscribe(self) -> ChunkQueue:
        queue = ChunkQueue(max_chunks=self.max_chunks)
        async with self._lock:
            for chunk in self._history:
                await queue.put(chunk)
            closed = self._closed
            failure = self._failure
            if not closed:
                self._subscribers.add(queue)
        if closed:
            if failure is not None:
                await queue.fail(failure.code, failure.detail)
            else:
                await queue.finish()
        return queue

    async def unsubscribe(self, queue: ChunkQueue) -> None:
        async with self._lock:
            self._subscribers.discard(queue)
        if not queue.closed:
            await queue.finish()

    async def publish(self, chunk: MediaChunk) -> None:
        async with self._lock:
            if self._closed:
                raise RuntimeError("chunk hub is closed")
            if self._last_sequence is not None and chunk.sequence <= self._last_sequence:
                raise ValueError("chunk sequence must increase monotonically")
            if self._last_end_pts_ms is not None and chunk.start_pts_ms < self._last_end_pts_ms:
                raise ValueError("chunk PTS must not move backwards")
            if chunk.starts_with_keyframe:
                self._history.clear()
            self._history.append(chunk)
            self._last_sequence = chunk.sequence
            self._last_end_pts_ms = float(chunk.end_pts_ms)
            subscribers = tuple(self._subscribers)
        # Await every subscriber.  This is intentional: offline generation
        # must backpressure instead of dropping media when RTMPS is slow.
        for queue in subscribers:
            if not queue.closed:
                try:
                    put = queue.put(chunk)
                    if self.subscriber_put_timeout_sec > 0:
                        await asyncio.wait_for(put, timeout=self.subscriber_put_timeout_sec)
                    else:
                        await put
                except ChunkQueueClosed:
                    # A publisher may fail or be stopped concurrently with
                    # this fan-out.  Its queue is no longer a live consumer;
                    # do not let that stale snapshot stop video generation.
                    async with self._lock:
                        self._subscribers.discard(queue)
                except asyncio.TimeoutError:
                    # A dead/blocked RTMPS consumer must not become the
                    # backpressure path for the source job.  Preserve all
                    # chunks already queued, terminate this subscriber with
                    # a classified failure, and let MP4 archiving continue.
                    await queue.fail("backpressure_timeout")
                    async with self._lock:
                        self._subscribers.discard(queue)

    async def finish(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            subscribers = tuple(self._subscribers)
            self._subscribers.clear()
        for queue in subscribers:
            await queue.finish()

    async def fail(self, code: str, detail: str = "") -> None:
        failure = ChunkFailure(code=str(code), detail=str(detail))
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            self._failure = failure
            subscribers = tuple(self._subscribers)
            self._subscribers.clear()
        for queue in subscribers:
            await queue.fail(failure.code, failure.detail)
