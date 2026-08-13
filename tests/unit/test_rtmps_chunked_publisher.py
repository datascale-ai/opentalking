from __future__ import annotations

import asyncio

import av
import numpy as np

from opentalking.streaming.chunks import ChunkQueue, MediaChunk
from opentalking.streaming.destinations import rtmps_chunked
from opentalking.streaming.types import ProgramAudio, ProgramVideo


def test_chunked_publisher_writes_h264_aac_and_closes_on_eof(tmp_path, monkeypatch) -> None:
    output = tmp_path / "capture.flv"

    monkeypatch.setattr(
        rtmps_chunked,
        "_open_av_output",
        lambda _url, _options: av.open(str(output), mode="w", format="flv"),
    )
    monkeypatch.setattr(rtmps_chunked, "validate_resolved_target", lambda *_args, **_kwargs: ["127.0.0.1"])

    async def run() -> None:
        settings = rtmps_chunked.RTMPSSettings(
            endpoint="rtmp://127.0.0.1:1936/live",
            stream_key="test",
            allow_local=True,
            fps=25,
            gop_seconds=1,
            width=96,
            height=64,
        )
        queue = ChunkQueue(max_chunks=2)
        publisher = rtmps_chunked.ChunkedRTMPSPublisher(settings)
        await publisher.start(queue)
        videos = tuple(
            ProgramVideo(
                data=np.zeros((64, 96, 3), dtype=np.uint8),
                width=96,
                height=64,
                timestamp_ms=float(index * 40),
            )
            for index in range(25)
        )
        audio = ProgramAudio(
            data=np.zeros(16_000, dtype=np.int16),
            sample_rate=16_000,
            timestamp_ms=0,
        )
        await queue.put(
            MediaChunk(
                sequence=0,
                start_pts_ms=0,
                end_pts_ms=1000,
                video=videos,
                audio=(audio,),
                starts_with_keyframe=True,
            )
        )
        await queue.finish()
        await publisher.wait()
        assert publisher.state == "completed"
        assert publisher.health == "healthy"
        assert publisher.sent_video == 25
        assert publisher.sent_audio == 1
        assert publisher.dropped_chunks == 0

    asyncio.run(run())
    container = av.open(str(output), mode="r")
    try:
        assert {stream.codec_context.name for stream in container.streams} >= {"h264", "aac"}
        video_packets = [packet for packet in container.demux() if packet.stream.type == "video"]
        assert video_packets and video_packets[0].is_keyframe
    finally:
        container.close()


def test_chunked_publisher_closes_container_on_source_failure(monkeypatch) -> None:
    class _Container:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    async def run() -> None:
        monkeypatch.setattr(
            rtmps_chunked,
            "validate_resolved_target",
            lambda *_args, **_kwargs: ["127.0.0.1"],
        )
        settings = rtmps_chunked.RTMPSSettings(
            endpoint="rtmp://127.0.0.1:1936/live",
            stream_key="test",
            allow_local=True,
        )
        queue = ChunkQueue(max_chunks=2)
        publisher = rtmps_chunked.ChunkedRTMPSPublisher(settings)
        await publisher.start(queue)
        container = _Container()
        publisher._container = container
        await queue.fail("video_generation_failed")
        await publisher.wait()

        assert publisher.state == "failed"
        assert container.closed

    asyncio.run(run())


def test_chunked_publisher_reconnects_when_broken_socket_close_raises(monkeypatch) -> None:
    class _BrokenContainer:
        def close(self) -> None:
            raise BrokenPipeError("socket already closed")

    async def run() -> None:
        monkeypatch.setattr(
            rtmps_chunked,
            "validate_resolved_target",
            lambda *_args, **_kwargs: ["127.0.0.1"],
        )
        settings = rtmps_chunked.RTMPSSettings(
            endpoint="rtmp://127.0.0.1:1936/live",
            stream_key="test",
            allow_local=True,
            reconnect_max_attempts=1,
            reconnect_max_delay_sec=0,
        )
        queue = ChunkQueue(max_chunks=2)
        publisher = rtmps_chunked.ChunkedRTMPSPublisher(settings)
        await publisher.start(queue)
        publisher._container = _BrokenContainer()
        calls = 0

        async def write_once_then_recover(_chunk: MediaChunk) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise BrokenPipeError("socket disconnected")

        monkeypatch.setattr(publisher, "_write_chunk", write_once_then_recover)
        await queue.put(
            MediaChunk(
                sequence=0,
                start_pts_ms=0,
                end_pts_ms=1000,
                video=(
                    ProgramVideo(
                        data=np.zeros((8, 8, 3), dtype=np.uint8),
                        width=8,
                        height=8,
                        timestamp_ms=0,
                    ),
                ),
                starts_with_keyframe=True,
            )
        )
        await queue.finish()
        await publisher.wait()

        assert publisher.state == "completed"
        assert calls == 2
        # The first socket failure was recovered by the replayed chunk.  It
        # must not remain as an active error after publishing resumes.
        assert publisher.last_error is None
        assert publisher.error_code is None

    asyncio.run(run())
