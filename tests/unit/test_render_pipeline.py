from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Iterator

import numpy as np
import pytest

from opentalking.core.types.frames import AudioChunk, VideoFrameData
from opentalking.worker.session_runner import SessionRunner, _IdleFrameCacheEntry, _SpeechChunkEnvelope
from opentalking.worker.pipeline.render_pipeline import iter_rendered_frames_sync


@dataclass
class _StreamFeatures:
    reps: list[int]


class _StreamingAdapter:
    model_type = "streaming-test"

    def __init__(self) -> None:
        self.produced = 0
        self.composed: list[int] = []

    def extract_features(self, audio_chunk: AudioChunk) -> _StreamFeatures:
        return _StreamFeatures(reps=[1, 2, 3])

    def infer(self, features: _StreamFeatures, avatar_state: Any) -> Iterator[int]:
        for value in features.reps:
            self.produced += 1
            yield value

    def compose_frame(self, avatar_state: Any, frame_idx: int, prediction: int) -> VideoFrameData:
        self.composed.append(frame_idx)
        frame = np.full((2, 2, 3), prediction, dtype=np.uint8)
        return VideoFrameData(data=frame, width=2, height=2, timestamp_ms=float(frame_idx))


def test_iter_rendered_frames_sync_is_lazy() -> None:
    adapter = _StreamingAdapter()
    chunk = AudioChunk(data=np.zeros(160, dtype=np.int16), sample_rate=16000, duration_ms=10.0)

    next_idx, features, frames = iter_rendered_frames_sync(
        adapter,
        avatar_state={"extra": {}},
        chunk=chunk,
        frame_index_start=7,
        speech_frame_index_start=0,
        streaming=False,
    )

    assert next_idx == 10
    assert features.reps == [1, 2, 3]
    assert adapter.produced == 0

    first = next(iter(frames))

    assert first.timestamp_ms == 7.0
    assert adapter.produced == 1
    assert adapter.composed == [7]


@pytest.mark.asyncio
async def test_quicktalk_prefetch_stops_when_sentinel_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = object.__new__(SessionRunner)
    runner.model_type = "quicktalk"
    runner.session_id = "sess_test"
    runner.adapter = _StreamingAdapter()
    runner.avatar_state = {"extra": {}}
    runner._frame_idx = 0
    runner._speech_frame_idx = 0
    runner._rendered_chunk_count = 0
    runner._audio_preroll_chunks = 1
    runner._speech_video_ready = asyncio.Event()
    runner._render_in_executor = False
    runner._render_executor = None
    runner._active_timing = None
    runner._render_chunk_events = {}
    runner.frames: list[VideoFrameData] = []

    async def fake_video_sink(frame: VideoFrameData) -> None:
        runner.frames.append(frame)

    runner._video_sink = fake_video_sink  # type: ignore[method-assign]
    monkeypatch.setenv("OPENTALKING_QUICKTALK_PREFETCH", "1")

    queue: asyncio.Queue[_SpeechChunkEnvelope | None] = asyncio.Queue()
    chunk = AudioChunk(data=np.zeros(160, dtype=np.int16), sample_rate=16000, duration_ms=10.0)
    await queue.put(_SpeechChunkEnvelope(idx=0, chunk=chunk))
    await queue.put(None)

    await asyncio.wait_for(runner._render_chunk_worker_streaming(queue), timeout=1.0)

    assert [frame.timestamp_ms for frame in runner.frames] == [0.0, 1.0, 2.0]


@pytest.mark.asyncio
async def test_quicktalk_audio_does_not_wait_for_entire_chunk_video_enqueue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = object.__new__(SessionRunner)
    runner.model_type = "quicktalk"
    runner.session_id = "sess_sync"
    runner._frame_idx = 0
    runner._speech_frame_idx = 0
    runner._rendered_chunk_count = 0
    runner._audio_preroll_chunks = 1
    runner._speech_video_ready = asyncio.Event()
    runner._render_in_executor = False
    runner._render_executor = None
    runner._active_timing = None
    runner._render_chunk_events = {}
    runner._render_chunk_audio_events = {}
    runner._quicktalk_audio_delay_ms = 0.0

    frames = [
        VideoFrameData(
            data=np.zeros((2, 2, 3), dtype=np.uint8),
            width=2,
            height=2,
            timestamp_ms=float(idx),
        )
        for idx in range(3)
    ]

    async def fake_iter_render_chunk_frames(
        chunk: AudioChunk,
        *,
        frame_index_start: int,
        speech_frame_index_start: int,
    ) -> tuple[int, Any, Iterator[VideoFrameData]]:
        return frame_index_start + len(frames), _StreamFeatures(reps=[]), iter(frames)

    video_started = asyncio.Event()
    allow_video_finish = asyncio.Event()
    audio_started = asyncio.Event()
    seen_frames = 0

    async def fake_video_sink(frame: VideoFrameData) -> None:
        nonlocal seen_frames
        seen_frames += 1
        if seen_frames == 1:
            video_started.set()
            return
        if seen_frames == 2:
            await allow_video_finish.wait()

    async def fake_audio_sink(pcm: Any, sample_rate: int) -> None:
        audio_started.set()

    runner._iter_render_chunk_frames = fake_iter_render_chunk_frames  # type: ignore[method-assign]
    runner._video_sink = fake_video_sink  # type: ignore[method-assign]
    runner._audio_sink = fake_audio_sink  # type: ignore[method-assign]

    monkeypatch.setenv("OPENTALKING_QUICKTALK_PREFETCH", "0")

    render_queue: asyncio.Queue[_SpeechChunkEnvelope | None] = asyncio.Queue()
    audio_queue: asyncio.Queue[_SpeechChunkEnvelope | None] = asyncio.Queue()
    chunk = AudioChunk(data=np.zeros(160, dtype=np.int16), sample_rate=16000, duration_ms=10.0)
    envelope = _SpeechChunkEnvelope(idx=0, chunk=chunk)
    runner._ensure_render_chunk_event(envelope.idx)
    await render_queue.put(envelope)
    await audio_queue.put(envelope)
    await render_queue.put(None)
    await audio_queue.put(None)

    render_task = asyncio.create_task(runner._render_chunk_worker_streaming(render_queue))
    audio_task = asyncio.create_task(runner._audio_chunk_worker(audio_queue))

    try:
        await asyncio.wait_for(video_started.wait(), timeout=1.0)
        await asyncio.wait_for(audio_started.wait(), timeout=0.1)
    finally:
        allow_video_finish.set()
        await asyncio.gather(render_task, audio_task)


@pytest.mark.asyncio
async def test_quicktalk_audio_delay_prepends_silence_once() -> None:
    runner = object.__new__(SessionRunner)
    runner.model_type = "quicktalk"
    runner.session_id = "sess_audio_delay"
    runner._audio_preroll_chunks = 1
    runner._speech_video_ready = asyncio.Event()
    runner._speech_video_ready.set()
    runner._active_timing = None
    runner._render_chunk_events = {}
    runner._render_chunk_audio_events = {}
    runner._quicktalk_audio_delay_ms = 100.0

    seen_pcm: list[np.ndarray] = []

    async def fake_audio_sink(pcm: Any, sample_rate: int) -> None:
        seen_pcm.append(np.asarray(pcm, dtype=np.int16).reshape(-1).copy())

    runner._audio_sink = fake_audio_sink  # type: ignore[method-assign]

    queue: asyncio.Queue[_SpeechChunkEnvelope | None] = asyncio.Queue()
    first = AudioChunk(data=np.array([1, 2, 3], dtype=np.int16), sample_rate=16000, duration_ms=1.0)
    second = AudioChunk(data=np.array([4, 5], dtype=np.int16), sample_rate=16000, duration_ms=1.0)
    runner._mark_render_chunk_audio_ready(0)
    runner._mark_render_chunk_audio_ready(1)
    await queue.put(_SpeechChunkEnvelope(idx=0, chunk=first))
    await queue.put(_SpeechChunkEnvelope(idx=1, chunk=second))
    await queue.put(None)

    await asyncio.wait_for(runner._audio_chunk_worker(queue), timeout=1.0)

    assert len(seen_pcm) == 2
    assert seen_pcm[0].shape[0] == 1603
    assert np.all(seen_pcm[0][:1600] == 0)
    assert seen_pcm[0][-3:].tolist() == [1, 2, 3]
    assert seen_pcm[1].tolist() == [4, 5]


@pytest.mark.asyncio
async def test_idle_tick_uses_cached_frame_without_adapter_call() -> None:
    runner = object.__new__(SessionRunner)
    runner._frame_idx = 3
    runner._idle_frame_cache_cursor = 0
    runner._idle_frame_cache_direction = 1
    runner._idle_frame_cache_playback = "loop"
    runner._idle_frame_cache = [
        _IdleFrameCacheEntry(
            data=np.full((2, 2, 3), 7, dtype=np.uint8),
            width=2,
            height=2,
        )
    ]

    class _Manifest:
        fps = 25.0

    class _AvatarState:
        manifest = _Manifest()

    class _Adapter:
        def idle_frame(self, avatar_state: Any, frame_idx: int) -> VideoFrameData:
            raise AssertionError("cached idle frame should be used")

    class _Video:
        def __init__(self) -> None:
            self.frames: list[VideoFrameData] = []

        async def put(self, frame: VideoFrameData) -> None:
            self.frames.append(frame)

    class _WebRTC:
        def __init__(self) -> None:
            self.video = _Video()

    runner.avatar_state = _AvatarState()
    runner.adapter = _Adapter()
    runner.webrtc = _WebRTC()

    await runner.idle_tick()

    assert runner._frame_idx == 4
    assert runner.webrtc.video.frames[0].timestamp_ms == 120.0
    assert runner.webrtc.video.frames[0].data[0, 0, 0] == 7


def test_idle_cache_pingpong_playback_bounces_at_edges() -> None:
    runner = object.__new__(SessionRunner)
    runner._idle_frame_cache_cursor = 0
    runner._idle_frame_cache_direction = 1
    runner._idle_frame_cache_playback = "pingpong"
    runner._idle_frame_cache = [
        _IdleFrameCacheEntry(
            data=np.full((1, 1, 3), value, dtype=np.uint8),
            width=1,
            height=1,
        )
        for value in (1, 2, 3)
    ]

    values = [
        int(runner._next_idle_cache_entry().data[0, 0, 0])
        for _ in range(7)
    ]

    assert values == [1, 2, 3, 2, 1, 2, 3]
