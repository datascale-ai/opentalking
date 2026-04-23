from __future__ import annotations

import asyncio
import fractions
import os
import time

import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaBlackhole
from av import AudioFrame, VideoFrame

from opentalking.core.types.frames import VideoFrameData

try:
    from aiortc.mediastreams import MediaStreamTrack
except ImportError:  # pragma: no cover
    from aiortc import MediaStreamTrack  # type: ignore


class _LegacyNumpyVideoTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, fps: float = 25.0) -> None:
        super().__init__()
        self._fps = fps
        self._interval = 1.0 / fps
        self._queue: asyncio.Queue[VideoFrameData | None] = asyncio.Queue(maxsize=256)
        self._frame_count = 0
        self._next_send: float = 0.0
        self._pacing = False

    async def put(self, frame: VideoFrameData | None) -> None:
        await self._queue.put(frame)

    def reset_clock(self) -> None:
        self._frame_count = 0
        self._next_send = time.monotonic()
        self._pacing = True

    def clear_pending(self) -> None:
        return

    async def recv(self) -> VideoFrame:
        item = await self._queue.get()
        if item is None:
            raise asyncio.CancelledError

        if self._pacing:
            now = time.monotonic()
            if now < self._next_send:
                await asyncio.sleep(self._next_send - now)
            self._next_send += self._interval
            now2 = time.monotonic()
            if self._next_send < now2 - self._interval * 2:
                self._next_send = now2

        vf = VideoFrame.from_ndarray(item.data, format="bgr24")
        self._frame_count += 1
        vf.pts = self._frame_count
        vf.time_base = fractions.Fraction(1, int(max(1, round(self._fps))))
        return vf


class _BufferedNumpyVideoTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, fps: float = 25.0) -> None:
        super().__init__()
        self._fps = fps
        self._queue: asyncio.Queue[VideoFrameData | None] = asyncio.Queue(maxsize=256)
        self._timeline_start: float | None = None
        self._timeline_base_ms: float | None = None
        self._prev_source_ts_ms: float | None = None
        self._next_pts_ms = 0

    async def put(self, frame: VideoFrameData | None) -> None:
        await self._queue.put(frame)

    def reset_clock(self) -> None:
        self._timeline_start = None
        self._timeline_base_ms = None
        self._prev_source_ts_ms = None

    def clear_pending(self) -> None:
        return

    async def recv(self) -> VideoFrame:
        item = await self._queue.get()
        if item is None:
            raise asyncio.CancelledError

        frame_ts_ms = max(0.0, float(item.timestamp_ms))
        if self._timeline_start is None or self._timeline_base_ms is None:
            self._timeline_start = time.monotonic()
            self._timeline_base_ms = frame_ts_ms

        target = self._timeline_start + max(
            0.0,
            (frame_ts_ms - self._timeline_base_ms) / 1000.0,
        )
        now = time.monotonic()
        if now < target:
            await asyncio.sleep(target - now)

        vf = VideoFrame.from_ndarray(item.data, format="bgr24")
        vf.pts = self._next_pts_ms
        vf.time_base = fractions.Fraction(1, 1000)

        if self._prev_source_ts_ms is None:
            delta_ms = int(round(1000.0 / max(1.0, self._fps)))
        else:
            delta_ms = int(round(frame_ts_ms - self._prev_source_ts_ms))
            if delta_ms <= 0:
                delta_ms = int(round(1000.0 / max(1.0, self._fps)))
        self._prev_source_ts_ms = frame_ts_ms
        self._next_pts_ms += max(1, delta_ms)
        return vf


class _LegacyPCM16AudioTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self, sample_rate: int = 16000) -> None:
        super().__init__()
        self.sample_rate = sample_rate
        self._queue: asyncio.Queue[np.ndarray | None] = asyncio.Queue(maxsize=512)
        self._timestamp = 0
        self._time_base = fractions.Fraction(1, sample_rate)
        self._next_send: float = 0.0
        self._pacing = False

    async def put_pcm(self, samples: np.ndarray | None) -> None:
        await self._queue.put(samples)

    def reset_clock(self) -> None:
        self._timestamp = 0
        self._next_send = time.monotonic()
        self._pacing = True

    def clear_pending(self) -> None:
        return

    async def recv(self) -> AudioFrame:
        samples = await self._queue.get()
        if samples is None:
            raise asyncio.CancelledError
        if samples.dtype != np.int16:
            samples = samples.astype(np.int16)
        n = int(samples.shape[0])

        if self._pacing:
            chunk_duration = n / self.sample_rate
            now = time.monotonic()
            if now < self._next_send:
                await asyncio.sleep(self._next_send - now)
            self._next_send += chunk_duration
            now2 = time.monotonic()
            if self._next_send < now2 - chunk_duration * 2:
                self._next_send = now2

        frame = AudioFrame(format="s16", layout="mono", samples=n)
        frame.planes[0].update(samples.tobytes())
        frame.sample_rate = self.sample_rate
        frame.pts = self._timestamp
        frame.time_base = self._time_base
        self._timestamp += n
        return frame


class _BufferedPCM16AudioTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self, sample_rate: int = 16000) -> None:
        super().__init__()
        self.sample_rate = sample_rate
        self._queue: asyncio.Queue[np.ndarray | None] = asyncio.Queue(maxsize=512)
        self._time_base = fractions.Fraction(1, sample_rate)
        self._next_pts = 0
        frame_ms = float(os.environ.get("OPENTALKING_RTC_AUDIO_FRAME_MS", "20.0"))
        self._frame_samples = max(1, int(round(self.sample_rate * frame_ms / 1000.0)))
        self._buffer = np.zeros((0,), dtype=np.int16)
        self._start_time: float | None = None
        self._clock_start_pts = 0
        self._seen_audio = False
        self._eof = False

    async def put_pcm(self, samples: np.ndarray | None) -> None:
        await self._queue.put(samples)

    def reset_clock(self) -> None:
        self._start_time = None
        self._clock_start_pts = self._next_pts
        self._seen_audio = False

    def clear_pending(self) -> None:
        self._buffer = np.zeros((0,), dtype=np.int16)
        self._eof = False

    async def _fill_buffer(self) -> None:
        while self._buffer.size < self._frame_samples and not self._eof:
            samples = await self._queue.get()
            if samples is None:
                self._eof = True
                break
            arr = np.asarray(samples, dtype=np.int16).reshape(-1)
            if arr.size == 0:
                continue
            if self._buffer.size == 0:
                self._buffer = arr.copy()
            else:
                self._buffer = np.concatenate((self._buffer, arr)).astype(np.int16, copy=False)

    async def recv(self) -> AudioFrame:
        await self._fill_buffer()
        if self._buffer.size == 0 and self._eof:
            raise asyncio.CancelledError
        if self._buffer.size == 0:
            return await self.recv()

        n = min(self._frame_samples, int(self._buffer.shape[0]))
        samples = self._buffer[:n]
        self._buffer = self._buffer[n:]

        pts = self._next_pts
        if self._start_time is None:
            self._start_time = time.monotonic()
            self._clock_start_pts = pts
            self._seen_audio = True

        assert self._start_time is not None
        target = self._start_time + ((pts - self._clock_start_pts) / self.sample_rate)
        now = time.monotonic()
        if now < target:
            await asyncio.sleep(target - now)

        frame = AudioFrame(format="s16", layout="mono", samples=n)
        frame.planes[0].update(samples.tobytes())
        frame.sample_rate = self.sample_rate
        frame.pts = pts
        frame.time_base = self._time_base
        self._next_pts += n
        return frame


class WebRTCSession:
    """Wraps RTCPeerConnection with numpy video/audio queues."""

    def __init__(
        self,
        *,
        fps: float = 25.0,
        sample_rate: int = 16000,
        mode: str = "buffered",
    ) -> None:
        self.pc = RTCPeerConnection()
        normalized_mode = mode.strip().lower()
        if normalized_mode == "legacy":
            self.video = _LegacyNumpyVideoTrack(fps=fps)
            self.audio = _LegacyPCM16AudioTrack(sample_rate=sample_rate)
        else:
            self.video = _BufferedNumpyVideoTrack(fps=fps)
            self.audio = _BufferedPCM16AudioTrack(sample_rate=sample_rate)
        self.mode = normalized_mode
        self.pc.addTrack(self.video)
        self.pc.addTrack(self.audio)
        self.draining = False  # True while clearing queues for speech start

    def reset_clocks(self) -> None:
        """Reset pacing wall-clock so next frame/audio is sent immediately.
        Does NOT reset PTS counters — keeps the RTP stream continuous."""
        now = time.monotonic()
        self.video._next_send = now
        self.video._pacing = True
        self.audio._next_send = now
        self.audio._pacing = True
        self.draining = False

    def clear_media_queues(self) -> None:
        while True:
            try:
                self.video._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        while True:
            try:
                self.audio._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self.video.clear_pending()
        self.audio.clear_pending()

    async def handle_offer(self, sdp: str, type_: str) -> RTCSessionDescription:
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=type_))
        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)
        return self.pc.localDescription  # type: ignore[return-value]

    @staticmethod
    def _put_close_sentinel(q: asyncio.Queue) -> None:
        try:
            q.put_nowait(None)
            return
        except asyncio.QueueFull:
            pass

        while True:
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                break

        try:
            q.put_nowait(None)
        except asyncio.QueueFull:
            pass

    async def close(self) -> None:
        self._put_close_sentinel(self.video._queue)
        self._put_close_sentinel(self.audio._queue)
        await self.pc.close()


def attach_blackhole(pc: RTCPeerConnection) -> MediaBlackhole:
    return MediaBlackhole()
