from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import socket
import ssl
import time
from dataclasses import dataclass
from fractions import Fraction
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

import av
import numpy as np
from av import AudioFrame, VideoFrame

from ..security import validate_resolved_target, validate_target_url
from ..types import ProgramAudio, ProgramVideo

log = logging.getLogger(__name__)


def _open_av_output(url: str, options: dict[str, str]) -> Any:
    """Open an output container while suppressing libav URL diagnostics.

    MediaMTX auth is assembled into ``url`` only inside the worker.  Some
    libav builds print the full URL (including its query) to stderr on a
    handshake failure, so never let that diagnostic reach service logs.
    """
    with contextlib.redirect_stderr(io.StringIO()):
        return av.open(url, mode="w", format="flv", options=options)


def _verify_tls_peer(endpoint: str, ca_file: str, resolved_ip: str | None = None) -> None:
    """Perform an explicit certificate/hostname check before PyAV opens RTMPS.

    PyAV's output path currently calls ``avio_open`` without forwarding the
    protocol dictionary, so ``tls_verify``/``ca_file`` may be reported as
    unused by FFmpeg.  The preflight keeps the safety property at the
    application boundary; the same options are still passed to FFmpeg for
    versions that do forward them.
    """
    parsed = urlparse(endpoint)
    if parsed.scheme.lower() != "rtmps" or not parsed.hostname:
        return
    context = ssl.create_default_context(cafile=ca_file or None)
    host = parsed.hostname
    port = parsed.port or 443
    with socket.create_connection((resolved_ip or host, port), timeout=10.0) as raw:
        with context.wrap_socket(raw, server_hostname=host):
            return


def _pin_rtmps_url(settings: RTMPSSettings, resolved_ip: str) -> str:
    """Build a URL using the approved address while retaining TLS SNI/verifyhost."""
    endpoint = normalize_rtmps_endpoint(settings.endpoint, allow_local=settings.allow_local)
    parsed = urlparse(endpoint)
    host = resolved_ip
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host
    if parsed.port is not None:
        netloc = f"{host}:{parsed.port}"
    pinned = RTMPSSettings(
        endpoint=urlunparse((parsed.scheme, netloc, parsed.path, "", "", "")),
        stream_key=settings.stream_key,
        username=settings.username,
        password=settings.password,
        allow_local=True,
    )
    return build_rtmps_url(pinned)


@dataclass(frozen=True)
class RTMPSSettings:
    endpoint: str
    stream_key: str
    username: str | None = None
    password: str | None = None
    tls_verify: bool = True
    ca_file: str = ""
    fps: float = 25.0
    video_bitrate_kbps: int = 2500
    gop_seconds: float = 2.0
    allow_local: bool = False
    reconnect_max_attempts: int = 10
    reconnect_max_delay_sec: float = 30.0
    allowed_cidrs: tuple[str, ...] = ()
    allowed_hosts: tuple[str, ...] = ()
    width: int | None = None
    height: int | None = None

    def url(self) -> str:
        return build_rtmps_url(self)


def validate_stream_key(value: str) -> str:
    import re

    key = str(value or "").strip()
    if not key or len(key.encode("utf-8")) > 128 or not re.fullmatch(r"[A-Za-z0-9._-]+", key):
        raise ValueError("stream_key must match [A-Za-z0-9._-]+ and be at most 128 bytes")
    if key == "..":
        raise ValueError("stream_key is invalid")
    return key


def normalize_rtmps_endpoint(endpoint: str, *, allow_local: bool = False, allowed_hosts: set[str] | None = None, allowed_cidrs: list[str] | None = None) -> str:
    parsed = urlparse(endpoint.strip())
    if parsed.scheme.lower() not in {"rtmps", "rtmp"}:
        raise ValueError("RTMPS endpoint must use rtmps://")
    if parsed.query or parsed.fragment or parsed.username or parsed.password or not parsed.hostname:
        raise ValueError("RTMPS endpoint must not contain query, fragment, or URL credentials")
    if not parsed.path or parsed.path == "/" or "//" in parsed.path:
        raise ValueError("RTMPS endpoint must contain a single non-empty application path")
    if parsed.port is not None and not (1 <= parsed.port <= 65535):
        raise ValueError("invalid RTMPS endpoint port")
    return validate_target_url(
        endpoint,
        schemes={"rtmps"} if not allow_local else {"rtmps", "rtmp"},
        allow_local=allow_local,
        allowed_hosts=allowed_hosts,
        allowed_cidrs=allowed_cidrs,
    )


def build_rtmps_url(settings: RTMPSSettings) -> str:
    endpoint = normalize_rtmps_endpoint(settings.endpoint, allow_local=settings.allow_local)
    key = validate_stream_key(settings.stream_key)
    parsed = urlparse(endpoint)
    path = parsed.path.rstrip("/") + "/" + key
    query: list[tuple[str, str]] = []
    # MediaMTX's internal RTMP auth is intentionally constructed only here;
    # callers never submit a secret-bearing URL.
    if settings.username:
        query.append(("user", settings.username))
    if settings.password:
        query.append(("pass", settings.password))
    return urlunparse((parsed.scheme, parsed.netloc, path, "", urlencode(query), ""))


class RTMPSPublisher:
    """Small in-process PyAV FLV/RTMPS publisher.

    The publisher consumes independent Program queues through ``video`` and
    ``audio`` callbacks.  Encoding/muxing is kept behind the callback boundary
    so a slow socket is isolated by :class:`ProgramOutputManager`.
    """

    def __init__(self, settings: RTMPSSettings) -> None:
        self.settings = settings
        self.state = "created"
        self.health = "unknown"
        self._queue: asyncio.Queue[tuple[str, ProgramVideo | ProgramAudio] | None] = asyncio.Queue(maxsize=256)
        self._task: asyncio.Task[None] | None = None
        self._container: Any = None
        self._video_stream: Any = None
        self._audio_stream: Any = None
        self._video_size: tuple[int, int] | None = None
        self._audio_pts = 0
        self._pending_audio: list[ProgramAudio] = []
        self.last_error: str | None = None
        self.sent_video = 0
        self.sent_audio = 0
        self.bytes_sent = 0
        self.last_media_at: float | None = None
        self.last_program_pts_ms: float | None = None
        self.last_sent_pts_ms: float | None = None
        self.last_video_pts_ms: float | None = None
        self.last_audio_pts_ms: float | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        # Validate before task creation; this is a deterministic failure and
        # must not enter reconnect loops.
        normalize_rtmps_endpoint(
            self.settings.endpoint,
            allow_local=self.settings.allow_local,
            allowed_hosts=set(self.settings.allowed_hosts),
            allowed_cidrs=list(self.settings.allowed_cidrs),
        )
        build_rtmps_url(self.settings)
        endpoint_parts = urlparse(self.settings.endpoint)
        validate_resolved_target(
            endpoint_parts.hostname or "",
            endpoint_parts.port or 1935,
            allow_local=self.settings.allow_local,
            allowed_cidrs=list(self.settings.allowed_cidrs),
        )
        self.state = "connecting"
        self.health = "unknown"
        self._task = asyncio.create_task(self._run(), name="rtmps-publisher")

    async def video(self, item: ProgramVideo) -> None:
        await self._put(("video", item))

    async def audio(self, item: ProgramAudio) -> None:
        await self._put(("audio", item))

    async def _put(self, item: tuple[str, ProgramVideo | ProgramAudio]) -> None:
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            # Publisher queue overflow is handled as degraded; drop the oldest
            # item instead of blocking the runner.
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self._queue.put_nowait(item)
            except asyncio.QueueFull:
                self.health = "degraded"

    async def _run(self) -> None:
        attempts = 0
        try:
            while True:
                try:
                    entry = await self._queue.get()
                    if entry is None:
                        break
                    kind, item = entry
                    if kind == "video":
                        await self._write_video(item)  # type: ignore[arg-type]
                    else:
                        await self._write_audio(item)  # type: ignore[arg-type]
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    await self._close_container()
                    if isinstance(exc, ValueError) or attempts >= max(0, self.settings.reconnect_max_attempts):
                        self.state = "failed"
                        self.health = "failed"
                        self.last_error = type(exc).__name__
                        log.warning("RTMPS publisher stopped: %s", type(exc).__name__)
                        break
                    attempts += 1
                    self.state = "reconnecting"
                    self.health = "degraded"
                    self.last_error = type(exc).__name__
                    delay = min(
                        max(0.0, self.settings.reconnect_max_delay_sec),
                        0.25 * (2 ** min(attempts - 1, 8)),
                    )
                    await asyncio.sleep(delay)
                    self.state = "connecting"
        finally:
            await self._close_container()
            if self.state != "failed":
                self.state = "disconnected"

    async def _ensure_container(self, item: ProgramVideo) -> None:
        if self._container is not None:
            return
        width = int(self.settings.width or item.width)
        height = int(self.settings.height or item.height)
        endpoint_host = urlparse(self.settings.endpoint).hostname or ""
        resolved = validate_resolved_target(
            endpoint_host,
            urlparse(self.settings.endpoint).port or 1935,
            allow_local=self.settings.allow_local,
            allowed_cidrs=list(self.settings.allowed_cidrs),
        )
        if not resolved:
            raise OSError("RTMPS endpoint resolved to no approved address")
        resolved_ip = resolved[0]
        url = _pin_rtmps_url(self.settings, resolved_ip)
        parsed = urlparse(self.settings.endpoint)
        options: dict[str, str] = {
            "tls_verify": "1" if self.settings.tls_verify else "0",
        }
        if self.settings.ca_file:
            options["ca_file"] = self.settings.ca_file
        if parsed.hostname:
            # FFmpeg connects to the pinned IP but validates/SNI's the
            # original hostname. This avoids a second uncontrolled DNS lookup
            # in the publisher's normal connection path.
            options["verifyhost"] = parsed.hostname
            options["rtmp_tcurl"] = f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 1935}{parsed.path}"
        if self.settings.tls_verify:
            await asyncio.to_thread(_verify_tls_peer, self.settings.endpoint, self.settings.ca_file, resolved_ip)
        self._container = await asyncio.to_thread(_open_av_output, url, options)
        self._video_stream = self._container.add_stream(
            "libx264", rate=Fraction(str(self.settings.fps)).limit_denominator(1000)
        )
        self._video_stream.width = width
        self._video_stream.height = height
        self._video_stream.pix_fmt = "yuv420p"
        self._video_stream.bit_rate = max(250_000, int(self.settings.video_bitrate_kbps) * 1000)
        self._video_stream.gop_size = max(1, int(round(self.settings.fps * self.settings.gop_seconds)))
        self._video_stream.codec_context.max_b_frames = 0
        self._audio_stream = self._container.add_stream("aac", rate=48_000)
        self._audio_stream.layout = "stereo"
        self._audio_stream.bit_rate = 128_000
        self._video_size = (width, height)
        self.state = "connected"
        pending = self._pending_audio
        self._pending_audio = []
        for audio in pending:
            await self._write_audio(audio)

    async def _write_video(self, item: ProgramVideo) -> None:
        self.last_program_pts_ms = float(item.timestamp_ms)
        await self._ensure_container(item)
        assert self._container is not None and self._video_stream is not None
        data = np.asarray(item.data, dtype=np.uint8)
        frame_data: Any = data
        if self._video_size is not None and (data.shape[1], data.shape[0]) != self._video_size:
            import cv2

            frame_data = cv2.resize(data, self._video_size, interpolation=cv2.INTER_AREA)
        frame = VideoFrame.from_ndarray(frame_data, format="bgr24")
        frame.pts = int(round(item.timestamp_ms * self.settings.fps / 1000.0))
        frame.time_base = Fraction(1, max(1, int(round(self.settings.fps))))
        for packet in self._video_stream.encode(frame):
            self._container.mux(packet)
            self.bytes_sent += int(getattr(packet, "size", 0) or 0)
        self.sent_video += 1
        self.last_media_at = time.monotonic()
        self.last_sent_pts_ms = float(item.timestamp_ms)
        self.last_video_pts_ms = float(item.timestamp_ms)
        if self.sent_audio and self.health != "healthy":
            self.health = "healthy"

    async def _write_audio(self, item: ProgramAudio) -> None:
        self.last_program_pts_ms = max(float(item.timestamp_ms), float(self.last_program_pts_ms or 0.0))
        if self._container is None or self._audio_stream is None:
            # Wait for the first video to establish dimensions/streams.
            if len(self._pending_audio) < 256:
                self._pending_audio.append(item)
            return
        arr = np.asarray(item.data, dtype=np.int16).reshape(-1)
        if not arr.size:
            return
        stereo = np.repeat(arr[:, None], 2, axis=1)
        frame = AudioFrame(format="s16", layout="stereo", samples=arr.size)
        frame.planes[0].update(stereo.astype("<i2", copy=False).tobytes())
        frame.sample_rate = 48_000
        frame.pts = int(round(item.timestamp_ms * 48_000 / 1000.0))
        frame.time_base = Fraction(1, 48_000)
        for packet in self._audio_stream.encode(frame):
            self._container.mux(packet)
            self.bytes_sent += int(getattr(packet, "size", 0) or 0)
        self._audio_pts += arr.size
        self.sent_audio += 1
        self.last_media_at = time.monotonic()
        self.last_sent_pts_ms = float(item.timestamp_ms)
        self.last_audio_pts_ms = float(item.timestamp_ms)
        if self.sent_video and self.health != "healthy":
            self.health = "healthy"

    async def _close_container(self) -> None:
        container = self._container
        self._container = None
        if container is None:
            return
        # PyAV's OutputContainer destructor writes an unraisable exception to
        # stderr and includes ``container.name``.  That name is the assembled
        # RTMPS URL (including MediaMTX auth query credentials), so force the
        # object and its streams to destruct while stderr is redirected.  The
        # application log only records the type below and never the URL.
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                if self._video_stream is not None:
                    for packet in self._video_stream.encode(None):
                        container.mux(packet)
                if self._audio_stream is not None:
                    for packet in self._audio_stream.encode(None):
                        container.mux(packet)
                container.close()
            except Exception:
                log.debug("RTMPS container close failed", exc_info=True)
            finally:
                self._video_stream = None
                self._audio_stream = None
                del container

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        try:
            self._queue.put_nowait(None)
        except asyncio.QueueFull:
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        if self.state != "failed":
            self.state = "disconnected"
