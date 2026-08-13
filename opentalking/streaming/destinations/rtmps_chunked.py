from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import time
from collections import deque
from fractions import Fraction
from typing import Any
from urllib.parse import urlparse

import numpy as np
from av import AudioFrame, VideoFrame
from av.video.frame import PictureType
from av.audio.resampler import AudioResampler

from ..chunks import ChunkEOF, ChunkFailure, ChunkMessage, ChunkQueue, MediaChunk
from ..types import ProgramAudio, ProgramVideo
from .rtmps import (
    RTMPSSettings,
    _open_av_output,
    _pin_rtmps_url,
    _verify_tls_peer,
    build_rtmps_url,
    normalize_rtmps_endpoint,
)
from ..security import validate_resolved_target

log = logging.getLogger(__name__)


class ChunkedRTMPSPublisher:
    """Lossless, once-through RTMPS publisher for generated video chunks.

    This is intentionally separate from the live Session ``RTMPSPublisher``:
    generated video applies backpressure instead of dropping old frames, and
    it closes only after the producer sends an explicit EOF marker.
    """

    def __init__(
        self,
        settings: RTMPSSettings,
        *,
        replay_chunks: int = 8,
    ) -> None:
        self.settings = settings
        self.replay_chunks = max(1, int(replay_chunks))
        self.state = "created"
        self.health = "unknown"
        self.last_error: str | None = None
        self.error_code: str | None = None
        self.sent_video = 0
        self.sent_audio = 0
        self.bytes_sent = 0
        self.dropped_chunks = 0
        self.last_program_pts_ms: float | None = None
        self.last_sent_pts_ms: float | None = None
        self.first_media_at: float | None = None
        self.finalized_at: float | None = None
        self._queue: ChunkQueue | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop_requested = False
        self._container: Any = None
        self._video_stream: Any = None
        self._audio_stream: Any = None
        self._video_size: tuple[int, int] | None = None
        self._video_frame_index = 0
        self._audio_pts = 0
        self._audio_resampler: AudioResampler | None = None
        self._wall_origin: float | None = None
        self._output_timestamp_offset_ms = 0.0
        self._replay: deque[MediaChunk] = deque(maxlen=self.replay_chunks)
        self._last_keyframe_window: list[MediaChunk] = []
        self._last_input_sequence: int | None = None
        self._last_input_end_pts_ms: float | None = None
        self.first_input_sequence: int | None = None
        self.first_input_pts_ms: float | None = None

    @property
    def queue_depth(self) -> int:
        return self._queue.depth if self._queue is not None else 0

    @property
    def buffer_duration_ms(self) -> float:
        return self._queue.buffer_duration_ms if self._queue is not None else 0.0

    @property
    def blocked_ms(self) -> float:
        return self._queue.blocked_ms if self._queue is not None else 0.0

    async def start(self, queue: ChunkQueue) -> None:
        if self._task is not None and not self._task.done():
            return
        normalize_rtmps_endpoint(
            self.settings.endpoint,
            allow_local=self.settings.allow_local,
            allowed_hosts=set(self.settings.allowed_hosts),
            allowed_cidrs=list(self.settings.allowed_cidrs),
        )
        build_rtmps_url(self.settings)
        endpoint = urlparse(self.settings.endpoint)
        validate_resolved_target(
            endpoint.hostname or "",
            endpoint.port or 1935,
            allow_local=self.settings.allow_local,
            allowed_cidrs=list(self.settings.allowed_cidrs),
        )
        self._queue = queue
        self._stop_requested = False
        self.state = "connecting"
        self.health = "unknown"
        # In publish-gated video creation, the source is released immediately
        # after this method returns. Establish the RTMPS/FLV container first
        # when the profile already supplies dimensions; otherwise MediaMTX
        # can observe the stream several seconds after media PTS 0 and emit
        # an initial HLS GAP window. The handshake latency is paid before
        # generation, while the first generated chunk remains the first
        # packet on the live connection.
        if self.settings.width and self.settings.height:
            try:
                await self._ensure_container()
                await self._send_startup_preroll()
            except asyncio.CancelledError:
                raise
            except Exception:
                try:
                    await self._close_container(flush=False)
                except Exception:
                    pass
                self._fail("upstream_closed", "publisher startup failed")
                raise
        self._task = asyncio.create_task(self._run(), name="chunked-rtmps-publisher")

    async def _send_startup_preroll(self) -> None:
        """Send a one-frame codec priming packet before source PTS 0.

        MediaMTX does not mark an RTMPS path online until it has received
        decodable H.264/AAC packets. During the encoder/TLS startup interval,
        that used to make HLS synthesize several leading GAP segments even
        though the source queue began at PTS 0. A single black IDR and 21 ms of
        silence establishes both tracks; the real source frame is still forced
        to an IDR at PTS 0 from the publisher's logical counters.
        """

        if self._container is None or self._video_size is None:
            return
        width, height = self._video_size
        await self._write_video(
            ProgramVideo(
                data=np.zeros((height, width, 3), dtype=np.uint8),
                width=width,
                height=height,
                timestamp_ms=0.0,
                source="rtmps_preroll",
            )
        )
        await self._write_audio(
            ProgramAudio(
                data=np.zeros(1024, dtype=np.int16),
                # Video-creation chunks use the source TTS clock (16 kHz);
                # priming the resampler with that rate keeps the first real
                # audio frame on the same configured input format.
                sample_rate=16_000,
                timestamp_ms=0.0,
                source="rtmps_preroll",
            )
        )
        # The priming packets are transport bytes, not source media counters.
        # Keep the public progress and first-media timestamp tied to the real
        # source chunk, while retaining the audio encoder's next PTS so the
        # first source audio follows the short silence without going backward.
        self.sent_video = max(0, self.sent_video - 1)
        self.sent_audio = max(0, self.sent_audio - 1)
        self.first_media_at = None
        self.last_program_pts_ms = None
        self.last_sent_pts_ms = None
        self._video_frame_index = 0
        # Keep the real first source frame after the priming IDR instead of
        # asking the encoder to mux two packets at identical PTS values.
        self._output_timestamp_offset_ms = 1000.0 / max(1.0, float(self.settings.fps))

    async def wait(self) -> None:
        task = self._task
        if task is not None:
            await task

    async def stop(self) -> None:
        self._stop_requested = True
        task = self._task
        if task is None:
            if self.state not in {"completed", "failed"}:
                self.state = "stopped"
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self._task = None
        if self.state not in {"completed", "failed"}:
            self.state = "stopped"
            self.health = "degraded"

    async def _run(self) -> None:
        assert self._queue is not None
        attempts = 0
        replay: deque[MediaChunk] = deque()
        try:
            # The video-creation API supplies the output dimensions in the
            # publisher profile. Open the RTMPS/FLV connection before waiting
            # for the first media chunk so TLS/RTMP handshake latency overlaps
            # with source generation. The queued chunks retain PTS=0 and are
            # still sent in order once the socket is ready.
            if self._container is None and self.settings.width and self.settings.height:
                try:
                    await self._ensure_container()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    if isinstance(exc, ValueError):
                        self._fail(type(exc).__name__, "publisher failed")
                        return
                    attempts += 1
                    if attempts > max(0, self.settings.reconnect_max_attempts):
                        self._fail(type(exc).__name__, "publisher failed")
                        return
                    self.state = "reconnecting"
                    self.health = "degraded"
                    self.last_error = type(exc).__name__
                    self.error_code = "broken_pipe" if isinstance(exc, BrokenPipeError) else "upstream_closed"
                    delay = min(
                        max(0.0, self.settings.reconnect_max_delay_sec),
                        0.25 * (2 ** min(attempts - 1, 8)),
                    )
                    await asyncio.sleep(delay)

            while True:
                is_replay = bool(replay)
                message: ChunkMessage = replay.popleft() if is_replay else await self._queue.get()
                if isinstance(message, ChunkEOF):
                    self.state = "finalizing"
                    try:
                        await self._close_container(flush=True)
                    except Exception:  # noqa: BLE001
                        self._fail("encoder_error", "publisher finalization failed")
                        return
                    self.finalized_at = time.time()
                    self.state = "completed"
                    self.health = "healthy" if self.sent_video or self.sent_audio else "degraded"
                    return
                if isinstance(message, ChunkFailure):
                    # Producer failure is not EOF.  Do not flush a partial
                    # stream as completed, but always release the active
                    # socket/muxer before exposing the failed state.
                    try:
                        await self._close_container(flush=False)
                    except Exception:  # noqa: BLE001
                        pass
                    self._fail(message.code, message.detail)
                    return
                chunk = message
                if not is_replay:
                    self._remember(chunk)
                try:
                    self._validate_chunk(chunk, is_replay=is_replay)
                    self.state = "publishing" if self._container is not None else "connecting"
                    await self._write_chunk(chunk)
                    # ``last_error`` and ``error_code`` describe the current
                    # transport health, not an unbounded error history.  A
                    # BrokenPipeError can be raised while MediaMTX rotates a
                    # socket; once the replayed/keyframe chunk is accepted,
                    # the publisher is healthy again and the stale error
                    # must not remain visible to the API/UI.
                    if self.last_error is not None or self.error_code is not None:
                        self.last_error = None
                        self.error_code = None
                    attempts = 0
                    self.state = "publishing"
                    if self.sent_video and self.sent_audio:
                        self.health = "healthy"
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    try:
                        await self._close_container(flush=False)
                    except Exception:  # noqa: BLE001
                        # A broken socket can make PyAV raise again while
                        # closing the old output container.  That cleanup
                        # error must not mask the original disconnect or
                        # prevent the keyframe replay/reconnect path.
                        pass
                    if self._stop_requested:
                        self.state = "stopped"
                        self.health = "degraded"
                        return
                    attempts += 1
                    if isinstance(exc, ValueError) or attempts > max(0, self.settings.reconnect_max_attempts):
                        self._fail(type(exc).__name__, "publisher failed")
                        return
                    self.state = "reconnecting"
                    self.health = "degraded"
                    self.last_error = type(exc).__name__
                    self.error_code = "broken_pipe" if isinstance(exc, BrokenPipeError) else "upstream_closed"
                    # Replay from the latest keyframe window.  This can
                    # duplicate a small suffix after a socket failure, but it
                    # prevents a decoder from starting on P-frames.
                    replay = deque(self._last_keyframe_window)
                    self._wall_origin = None
                    delay = min(
                        max(0.0, self.settings.reconnect_max_delay_sec),
                        0.25 * (2 ** min(attempts - 1, 8)),
                    )
                    await asyncio.sleep(delay)
                    self.state = "connecting"
        except asyncio.CancelledError:
            await self._close_container(flush=False)
            raise
        finally:
            if self.state not in {"completed", "failed", "stopped"}:
                await self._close_container(flush=False)

    def _fail(self, code: str, detail: str = "") -> None:
        self.state = "failed"
        self.health = "failed"
        self.error_code = str(code)
        self.last_error = str(code)
        # Do not log the supplied detail: it may originate in an upstream
        # library and could contain a secret-bearing URL.
        log.warning("chunked RTMPS publisher failed: %s", str(code))

    def mark_failed(self, code: str) -> None:
        """Move an externally superseded publisher to a terminal safe state."""

        self._stop_requested = True
        self._fail(str(code))

    def _remember(self, chunk: MediaChunk) -> None:
        if chunk.starts_with_keyframe:
            self._last_keyframe_window = []
        self._last_keyframe_window.append(chunk)
        if len(self._last_keyframe_window) > self.replay_chunks:
            self._last_keyframe_window = self._last_keyframe_window[-self.replay_chunks :]
        self._replay.append(chunk)

    def _validate_chunk(self, chunk: MediaChunk, *, is_replay: bool) -> None:
        if not chunk.video and not chunk.audio:
            raise ValueError("media chunk is empty")
        if self._last_input_sequence is None and not chunk.video:
            raise ValueError("first media chunk must contain video")
        if self._last_input_sequence is None and not chunk.starts_with_keyframe:
            raise ValueError("first media chunk must start with a keyframe")
        if not is_replay:
            if self._last_input_sequence is None:
                self.first_input_sequence = int(chunk.sequence)
                self.first_input_pts_ms = float(chunk.start_pts_ms)
            if self._last_input_sequence is not None and chunk.sequence <= self._last_input_sequence:
                raise ValueError("media chunk sequence must increase monotonically")
            if self._last_input_end_pts_ms is not None and chunk.start_pts_ms < self._last_input_end_pts_ms:
                raise ValueError("media chunk PTS must not move backwards")
            self._last_input_sequence = chunk.sequence
            self._last_input_end_pts_ms = float(chunk.end_pts_ms)
        for frames in (chunk.audio, chunk.video):
            previous_pts: float | None = None
            for item in frames:
                pts = float(item.timestamp_ms)
                if previous_pts is not None and pts < previous_pts:
                    raise ValueError("media frame PTS must be monotonic")
                previous_pts = pts

    async def _pace(self, timestamp_ms: float) -> None:
        if self._wall_origin is None:
            self._wall_origin = time.monotonic() - float(timestamp_ms) / 1000.0
        target = self._wall_origin + float(timestamp_ms) / 1000.0
        delay = target - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)

    async def _write_chunk(self, chunk: MediaChunk) -> None:
        if not chunk.video and not chunk.audio:
            return
        if self._container is None:
            if not chunk.video:
                raise ValueError("first media chunk must contain video")
            await self._ensure_container(chunk.video[0])
        events: list[tuple[float, int, str, ProgramVideo | ProgramAudio]] = []
        events.extend((float(item.timestamp_ms), 1, "video", item) for item in chunk.video)
        events.extend((float(item.timestamp_ms), 0, "audio", item) for item in chunk.audio)
        events.sort(key=lambda item: (item[0], item[1]))
        for timestamp_ms, _order, kind, item in events:
            await self._pace(timestamp_ms)
            if kind == "video":
                await self._write_video(item)  # type: ignore[arg-type]
            else:
                await self._write_audio(item)  # type: ignore[arg-type]
            self.last_program_pts_ms = max(float(timestamp_ms), float(self.last_program_pts_ms or 0.0))

    async def _ensure_container(self, item: ProgramVideo | None = None) -> None:
        if self._container is not None:
            return
        if item is None:
            if not self.settings.width or not self.settings.height:
                raise ValueError("video dimensions are required before the first media chunk")
            width = int(self.settings.width)
            height = int(self.settings.height)
        else:
            data = np.asarray(item.data, dtype=np.uint8)
            if data.ndim != 3 or data.shape[2] < 3:
                raise ValueError("video frame must be an HxWx3 array")
            width = int(self.settings.width or item.width or data.shape[1])
            height = int(self.settings.height or item.height or data.shape[0])
        endpoint = urlparse(self.settings.endpoint)
        resolved = validate_resolved_target(
            endpoint.hostname or "",
            endpoint.port or 1935,
            allow_local=self.settings.allow_local,
            allowed_cidrs=list(self.settings.allowed_cidrs),
        )
        if not resolved:
            raise OSError("RTMPS endpoint resolved to no approved address")
        url = _pin_rtmps_url(self.settings, resolved[0])
        options: dict[str, str] = {"tls_verify": "1" if self.settings.tls_verify else "0"}
        if self.settings.ca_file:
            options["ca_file"] = self.settings.ca_file
        if endpoint.hostname:
            options["verifyhost"] = endpoint.hostname
            options["rtmp_tcurl"] = f"{endpoint.scheme}://{endpoint.hostname}:{endpoint.port or 1935}{endpoint.path}"
        if self.settings.tls_verify:
            await asyncio.to_thread(_verify_tls_peer, self.settings.endpoint, self.settings.ca_file, resolved[0])
        self._container = await asyncio.to_thread(_open_av_output, url, options)
        self._video_stream = self._container.add_stream(
            "libx264", rate=Fraction(str(self.settings.fps)).limit_denominator(1000)
        )
        gop = max(1, int(round(float(self.settings.fps) * float(self.settings.gop_seconds))))
        # This publisher is consumed by a live HLS preview. Disable x264's
        # lookahead/reordering so the first IDR and subsequent packets reach
        # MediaMTX immediately instead of accumulating several seconds of
        # encoder delay. max_b_frames is also kept at zero below for FLV.
        self._video_stream.codec_context.options = {
            "preset": "ultrafast",
            "tune": "zerolatency",
            # ``PictureType.I`` requests an intra frame, but does not force
            # every FFmpeg/libx264 build to emit an IDR access unit. RTMPS
            # consumers and MediaMTX HLS startup need an actual decoder-safe
            # IDR with SPS/PPS available at the first packet.
            "forced-idr": "1",
            "x264-params": f"keyint={gop}:min-keyint={gop}:scenecut=0:open-gop=0:repeat-headers=1",
        }
        self._video_stream.width = width
        self._video_stream.height = height
        self._video_stream.pix_fmt = "yuv420p"
        self._video_stream.bit_rate = max(250_000, int(self.settings.video_bitrate_kbps) * 1000)
        self._video_stream.gop_size = gop
        self._video_stream.codec_context.max_b_frames = 0
        self._audio_stream = self._container.add_stream("aac", rate=48_000)
        self._audio_stream.layout = "stereo"
        self._audio_stream.bit_rate = 128_000
        self._video_size = (width, height)
        self._audio_resampler = AudioResampler(format="s16", layout="stereo", rate=48_000)
        self._video_frame_index = 0
        self._audio_pts = 0
        self.state = "publishing"

    async def _write_video(self, item: ProgramVideo) -> None:
        await self._ensure_container(item)
        assert self._container is not None and self._video_stream is not None
        data = np.asarray(item.data, dtype=np.uint8)
        frame_data: Any = data[:, :, :3]
        if self._video_size is not None and (data.shape[1], data.shape[0]) != self._video_size:
            import cv2

            frame_data = cv2.resize(data[:, :, :3], self._video_size, interpolation=cv2.INTER_AREA)
        frame = VideoFrame.from_ndarray(np.ascontiguousarray(frame_data), format="bgr24")
        output_timestamp_ms = float(item.timestamp_ms) + self._output_timestamp_offset_ms
        frame.pts = int(round(output_timestamp_ms * float(self.settings.fps) / 1000.0))
        frame.time_base = Fraction(1, max(1, int(round(float(self.settings.fps)))))
        gop = max(1, int(round(float(self.settings.fps) * float(self.settings.gop_seconds))))
        if self._video_frame_index % gop == 0:
            # PyAV accepts the short FFmpeg picture-type name and this forces
            # a decoder-safe IDR at the beginning of every replay window.
            frame.pict_type = PictureType.I
        for packet in self._video_stream.encode(frame):
            self._container.mux(packet)
            self.bytes_sent += int(getattr(packet, "size", 0) or 0)
        self._video_frame_index += 1
        self.sent_video += 1
        if self.first_media_at is None:
            self.first_media_at = time.time()
        self.last_sent_pts_ms = max(float(item.timestamp_ms), float(self.last_sent_pts_ms or 0.0))

    async def _write_audio(self, item: ProgramAudio) -> None:
        if self._container is None or self._audio_stream is None:
            raise RuntimeError("audio arrived before the first video frame")
        arr = np.asarray(item.data, dtype=np.int16).reshape(-1)
        if not arr.size:
            return
        sample_rate = int(item.sample_rate)
        if sample_rate <= 0:
            raise ValueError("audio sample rate must be positive")
        source = AudioFrame(format="s16", layout="mono", samples=int(arr.size))
        source.planes[0].update(np.ascontiguousarray(arr.astype("<i2", copy=False)).tobytes())
        source.sample_rate = sample_rate
        source.pts = int(round(float(item.timestamp_ms) * sample_rate / 1000.0))
        source.time_base = Fraction(1, sample_rate)
        assert self._audio_resampler is not None
        output_frames = self._audio_resampler.resample(source)
        output_pts = max(self._audio_pts, int(round(float(item.timestamp_ms) * 48_000 / 1000.0)))
        for frame in output_frames:
            frame.pts = output_pts
            frame.time_base = Fraction(1, 48_000)
            for packet in self._audio_stream.encode(frame):
                self._container.mux(packet)
                self.bytes_sent += int(getattr(packet, "size", 0) or 0)
            output_pts += int(frame.samples or 0)
        self._audio_pts = output_pts
        self.sent_audio += 1
        if self.first_media_at is None:
            self.first_media_at = time.time()
        self.last_sent_pts_ms = max(float(item.timestamp_ms), float(self.last_sent_pts_ms or 0.0))

    async def _close_container(self, *, flush: bool) -> None:
        container = self._container
        video_stream = self._video_stream
        audio_stream = self._audio_stream
        resampler = self._audio_resampler
        self._container = None
        self._video_stream = None
        self._audio_stream = None
        self._audio_resampler = None
        if container is None:
            return
        error: Exception | None = None
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                if flush and resampler is not None and audio_stream is not None:
                    output_pts = self._audio_pts
                    for frame in resampler.resample(None):
                        frame.pts = output_pts
                        frame.time_base = Fraction(1, 48_000)
                        for packet in audio_stream.encode(frame):
                            container.mux(packet)
                            self.bytes_sent += int(getattr(packet, "size", 0) or 0)
                        output_pts += int(frame.samples or 0)
                    self._audio_pts = output_pts
                if flush and video_stream is not None:
                    for packet in video_stream.encode(None):
                        container.mux(packet)
                        self.bytes_sent += int(getattr(packet, "size", 0) or 0)
                if flush and audio_stream is not None:
                    for packet in audio_stream.encode(None):
                        container.mux(packet)
                        self.bytes_sent += int(getattr(packet, "size", 0) or 0)
                container.close()
            except Exception as exc:  # noqa: BLE001
                error = exc
                try:
                    container.close()
                except Exception:
                    pass
            finally:
                del container
        # Once the socket is broken, FFmpeg/PyAV may raise a second
        # BrokenPipeError while closing the old container.  Close failures on
        # the non-flushing disconnect path are expected and must not escape
        # into the reconnect loop.  Finalization still propagates its error so
        # a normal EOF cannot be reported as completed after a failed flush.
        if error is not None and flush:
            raise error
