from __future__ import annotations

import numpy as np

from opentalking.core.types.frames import VideoFrameData
from opentalking.rtc.aiortc_adapter import WebRTCSession


def test_buffered_reset_clocks_resets_timeline_without_rewinding_pts() -> None:
    session = WebRTCSession(fps=25.0, sample_rate=16000, mode="buffered")
    try:
        session.video._timeline_start = 12.3
        session.video._timeline_base_ms = 480.0
        session.video._prev_source_ts_ms = 440.0
        session.video._next_pts_ms = 960
        session.audio._start_time = 45.6
        session.audio._clock_start_pts = 32000
        session.audio._next_pts = 32640

        session.reset_clocks()

        assert session.video._timeline_start is None
        assert session.video._timeline_base_ms is None
        assert session.video._prev_source_ts_ms is None
        assert session.video._next_pts_ms == 960
        assert session.audio._start_time is None
        assert session.audio._clock_start_pts == 32640
        assert session.audio._next_pts == 32640
    finally:
        session._put_close_sentinel(session.video._queue)
        session._put_close_sentinel(session.audio._queue)


def test_clear_media_queues_drops_buffered_audio_and_video_without_rewinding_pts() -> None:
    session = WebRTCSession(fps=25.0, sample_rate=16000, mode="buffered")
    try:
        session.video._queue.put_nowait(
            VideoFrameData(
                data=np.zeros((4, 4, 3), dtype=np.uint8),
                width=4,
                height=4,
                timestamp_ms=120.0,
            )
        )
        session.audio._queue.put_nowait(np.ones((320,), dtype=np.int16))
        session.audio._buffer = np.ones((160,), dtype=np.int16)
        session.audio._next_pts = 640
        session.audio._start_time = 1.23
        session.audio._seen_audio = True

        session.clear_media_queues()

        assert session.video._queue.qsize() == 0
        assert session.audio._queue.qsize() == 0
        assert session.audio._buffer.size == 0
        assert session.audio._next_pts == 640
        assert session.audio._start_time == 1.23
        assert session.audio._seen_audio is True
    finally:
        session._put_close_sentinel(session.video._queue)
        session._put_close_sentinel(session.audio._queue)


def test_legacy_reset_clocks_rewinds_per_utterance_timeline() -> None:
    session = WebRTCSession(fps=25.0, sample_rate=16000, mode="legacy")
    try:
        session.video._frame_count = 12
        session.audio._timestamp = 32000

        session.reset_clocks()

        assert session.video._frame_count == 0
        assert session.audio._timestamp == 0
    finally:
        session._put_close_sentinel(session.video._queue)
        session._put_close_sentinel(session.audio._queue)
