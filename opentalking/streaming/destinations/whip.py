from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from fractions import Fraction
from urllib.parse import urljoin, urlparse
from typing import Any

import httpx
import numpy as np
from aiortc import RTCBundlePolicy, RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamTrack
from aiortc.rtcrtpsender import RTCRtpSender
from av import AudioFrame, VideoFrame

from ..security import validate_resolved_target, validate_target_url
from ..types import ProgramAudio, ProgramVideo
from ..whip_sdp import WhipSdpError, validate_answer_sdp, validate_offer_sdp

log = logging.getLogger(__name__)

# A WHEP reader can join an already-running WHIP publisher.  aiortc's H.264
# encoder emits SPS/PPS with a forced keyframe, but MediaMTX does not need to
# forward every reader's PLI back to every publisher.  Requesting a keyframe
# periodically keeps late readers decodable without relying on that relay
# detail.
VIDEO_KEYFRAME_INTERVAL_SEC = 2.0


class _PinnedNetworkBackend:
    """Delegate httpcore network I/O to one already-approved destination IP.

    The HTTP request URL remains on the original hostname, so httpcore keeps
    the hostname in the Host header and TLS SNI while the TCP connect cannot
    silently resolve a different address after policy validation.
    """

    def __init__(self, delegate: Any, address: str) -> None:
        self._delegate = delegate
        self._address = address

    async def connect_tcp(self, host: str, port: int, **kwargs: Any) -> Any:
        del host
        return await self._delegate.connect_tcp(self._address, port, **kwargs)

    async def connect_unix_socket(self, *args: Any, **kwargs: Any) -> Any:
        return await self._delegate.connect_unix_socket(*args, **kwargs)

    async def sleep(self, seconds: float) -> None:
        await self._delegate.sleep(seconds)


def _pinned_transport(*, verify: bool | str, address: str) -> httpx.AsyncHTTPTransport:
    transport = httpx.AsyncHTTPTransport(verify=verify, trust_env=False)
    pool = getattr(transport, "_pool", None)
    if pool is None:
        raise RuntimeError("httpx transport does not expose a connection pool")
    delegate = getattr(pool, "_network_backend", None)
    if delegate is None:
        raise RuntimeError("httpx transport does not expose a network backend")
    pool._network_backend = _PinnedNetworkBackend(delegate, address)
    return transport


@dataclass(frozen=True)
class WHIPSettings:
    endpoint: str
    bearer_token: str
    tls_verify: bool = True
    ca_file: str = ""
    fps: float = 25.0
    ice_servers: str = ""
    allow_local: bool = False
    max_redirects: int = 2
    candidate_policy: str = "allowlist"
    allowed_cidrs: tuple[str, ...] = ()
    allowed_hosts: tuple[str, ...] = ()
    width: int | None = None
    height: int | None = None


class _VideoTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, fps: float, width: int | None = None, height: int | None = None) -> None:
        super().__init__()
        self._queue: asyncio.Queue[ProgramVideo | None] = asyncio.Queue(maxsize=128)
        self._fps = fps
        self._size = (width, height)

    async def put(self, item: ProgramVideo) -> None:
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self._queue.put_nowait(item)
            except asyncio.QueueFull:
                pass

    async def recv(self) -> VideoFrame:
        item = await self._queue.get()
        if item is None:
            raise asyncio.CancelledError
        data = np.asarray(item.data, dtype=np.uint8)
        frame_data: Any = data
        width, height = self._size
        if width and height and (data.shape[1], data.shape[0]) != (width, height):
            import cv2

            frame_data = cv2.resize(data, (width, height), interpolation=cv2.INTER_AREA)
        frame = VideoFrame.from_ndarray(frame_data, format="bgr24")
        frame.pts = int(round(item.timestamp_ms * self._fps / 1000.0))
        frame.time_base = Fraction(1, max(1, int(round(self._fps))))
        return frame


class _AudioTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self) -> None:
        super().__init__()
        self._queue: asyncio.Queue[ProgramAudio | None] = asyncio.Queue(maxsize=256)

    async def put(self, item: ProgramAudio) -> None:
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self._queue.put_nowait(item)
            except asyncio.QueueFull:
                pass

    async def recv(self) -> AudioFrame:
        item = await self._queue.get()
        if item is None:
            raise asyncio.CancelledError
        data = np.asarray(item.data, dtype=np.int16).reshape(-1)
        frame = AudioFrame(format="s16", layout="mono", samples=int(data.size))
        frame.planes[0].update(data.astype("<i2", copy=False).tobytes())
        frame.sample_rate = int(item.sample_rate)
        frame.pts = int(round(item.timestamp_ms * item.sample_rate / 1000.0))
        frame.time_base = Fraction(1, max(1, item.sample_rate))
        return frame


class WHIPPublisher:
    """WHIP offerer using a dedicated aiortc PeerConnection and tracks."""

    def __init__(self, settings: WHIPSettings) -> None:
        self.settings = settings
        self.state = "created"
        self.health = "unknown"
        self.last_error: str | None = None
        self.resource_url: str | None = None
        self.pc: RTCPeerConnection | None = None
        self.video_track = _VideoTrack(settings.fps, settings.width, settings.height)
        self.audio_track = _AudioTrack()
        self.sent_video = 0
        self.sent_audio = 0
        self.bytes_sent = 0
        self.last_media_at: float | None = None
        self.last_program_pts_ms: float | None = None
        self.last_sent_pts_ms: float | None = None
        self.last_video_pts_ms: float | None = None
        self.last_audio_pts_ms: float | None = None
        self._health_task: asyncio.Task[None] | None = None
        self._last_keyframe_request_at = 0.0

    async def _request_pinned(
        self,
        method: str,
        target: str,
        *,
        headers: dict[str, str],
        content: bytes | None = None,
        verify: bool | str,
    ) -> httpx.Response:
        parsed = urlparse(
            validate_target_url(
                target,
                schemes={"https"},
                allow_local=self.settings.allow_local,
                allowed_hosts=set(self.settings.allowed_hosts),
                allowed_cidrs=list(self.settings.allowed_cidrs),
            )
        )
        resolved = validate_resolved_target(
            parsed.hostname or "",
            parsed.port or 443,
            allow_local=self.settings.allow_local,
            allowed_cidrs=list(self.settings.allowed_cidrs),
        )
        if not resolved:
            raise RuntimeError("WHIP endpoint resolved to no approved address")
        transport = _pinned_transport(verify=verify, address=resolved[0])
        try:
            async with httpx.AsyncClient(
                transport=transport,
                follow_redirects=False,
                trust_env=False,
                timeout=15.0,
            ) as client:
                response = await client.request(method, target, headers=headers, content=content)
                await response.aread()
                return response
        finally:
            await transport.aclose()

    async def start(self) -> None:
        if self.pc is not None:
            return
        endpoint = validate_target_url(
            self.settings.endpoint,
            schemes={"https"},
            allow_local=self.settings.allow_local,
            allowed_hosts=set(self.settings.allowed_hosts),
            allowed_cidrs=list(self.settings.allowed_cidrs),
        )
        endpoint_parts = urlparse(endpoint)
        initial_origin = (
            endpoint_parts.scheme.lower(),
            (endpoint_parts.hostname or "").lower().rstrip("."),
            endpoint_parts.port or 443,
        )
        validate_resolved_target(
            endpoint_parts.hostname or "",
            endpoint_parts.port or 443,
            allow_local=self.settings.allow_local,
            allowed_cidrs=list(self.settings.allowed_cidrs),
        )
        if not self.settings.bearer_token:
            raise ValueError("WHIP bearer_token is required")
        self.state = "connecting"
        ice_servers = [
            RTCIceServer(urls=url.strip())
            for url in self.settings.ice_servers.replace(";", ",").split(",")
            if url.strip()
        ]
        if self.settings.candidate_policy.strip().lower() == "relay" and not ice_servers:
            raise ValueError("WHIP relay candidate policy requires a configured ICE relay")
        self.pc = RTCPeerConnection(
            RTCConfiguration(iceServers=ice_servers, bundlePolicy=RTCBundlePolicy.MAX_BUNDLE)
        )
        video_transceiver = self.pc.addTransceiver(self.video_track, direction="sendonly")
        audio_transceiver = self.pc.addTransceiver(self.audio_track, direction="sendonly")
        video_codecs = [
            codec for codec in RTCRtpSender.getCapabilities("video").codecs
            if codec.name.upper() == "H264"
        ]
        if video_codecs:
            video_transceiver.setCodecPreferences(video_codecs)
        audio_codecs = [
            codec for codec in RTCRtpSender.getCapabilities("audio").codecs
            if codec.name.lower() == "opus"
        ]
        if audio_codecs:
            audio_transceiver.setCodecPreferences(audio_codecs)
        for transceiver in self.pc.getTransceivers():
            transceiver.direction = "sendonly"
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)
        for _ in range(100):
            if self.pc.iceGatheringState == "complete":
                break
            await asyncio.sleep(0.05)
        local = self.pc.localDescription
        if local is None or not local.sdp:
            raise RuntimeError("WHIP offer is empty")
        try:
            validate_offer_sdp(
                local.sdp,
                allow_private_candidates=self.settings.allow_local,
                candidate_policy=self.settings.candidate_policy,
                allowed_cidrs=self.settings.allowed_cidrs,
            )
        except WhipSdpError as exc:
            raise RuntimeError(str(exc)) from exc
        verify: bool | str = self.settings.ca_file if self.settings.tls_verify and self.settings.ca_file else self.settings.tls_verify
        headers = {
            "Authorization": f"Bearer {self.settings.bearer_token}",
            "Content-Type": "application/sdp",
            "Accept": "application/sdp",
        }
        target = endpoint
        for redirect_count in range(max(0, self.settings.max_redirects) + 1):
            response = await self._request_pinned(
                "POST",
                target,
                headers=headers,
                content=local.sdp.encode("utf-8"),
                verify=verify,
            )
            if response.status_code not in {307, 308}:
                break
            location = response.headers.get("location")
            if not location or redirect_count >= max(0, self.settings.max_redirects):
                raise RuntimeError("WHIP redirect policy rejected")
            target = urljoin(target, location)
            target_parts = urlparse(
                validate_target_url(
                    target,
                    schemes={"https"},
                    allow_local=self.settings.allow_local,
                    allowed_hosts=set(self.settings.allowed_hosts),
                    allowed_cidrs=list(self.settings.allowed_cidrs),
                )
            )
            target_origin = (
                target_parts.scheme.lower(),
                (target_parts.hostname or "").lower().rstrip("."),
                target_parts.port or 443,
            )
            if target_origin != initial_origin and not self.settings.allowed_hosts:
                raise RuntimeError("WHIP redirect origin is not approved")
        else:  # pragma: no cover - loop always breaks or raises
            raise RuntimeError("WHIP redirect policy rejected")
        if response.status_code != 201:
            raise RuntimeError(f"WHIP publish rejected ({response.status_code})")
        if "sdp" not in response.headers.get("content-type", "").lower():
            raise RuntimeError("WHIP response is not application/sdp")
        answer_sdp = response.text
        location = response.headers.get("location")
        if not location:
            raise RuntimeError("WHIP response is missing Location")
        resource = urljoin(target, location)
        resource = validate_target_url(
            resource,
            schemes={"https"},
            allow_local=self.settings.allow_local,
            allowed_hosts=set(self.settings.allowed_hosts),
            allowed_cidrs=list(self.settings.allowed_cidrs),
        )
        resource_parts = urlparse(resource)
        resource_origin = (
            resource_parts.scheme.lower(),
            (resource_parts.hostname or "").lower().rstrip("."),
            resource_parts.port or 443,
        )
        if resource_origin != initial_origin and not self.settings.allowed_hosts:
            raise RuntimeError("WHIP resource origin is not approved")
        validate_resolved_target(
            resource_parts.hostname or "",
            resource_parts.port or 443,
            allow_local=self.settings.allow_local,
            allowed_cidrs=list(self.settings.allowed_cidrs),
        )
        self.resource_url = resource
        try:
            validate_answer_sdp(local.sdp, answer_sdp)
            await self.pc.setRemoteDescription(RTCSessionDescription(sdp=answer_sdp, type="answer"))
        except Exception as exc:
            # A 201 may have created a server-side resource already. Delete
            # only after Location passed the same egress/origin validation.
            await self._delete_resource(resource)
            self.resource_url = None
            await self.pc.close()
            self.pc = None
            raise RuntimeError(str(exc)) from exc
        self._request_video_keyframe()
        self.state = "connected"
        self._health_task = asyncio.create_task(self._monitor_connection(), name="whip-health")

    def _request_video_keyframe(self) -> None:
        """Ask the aiortc video sender for an IDR carrying SPS/PPS.

        aiortc does not expose this as a public sender API.  Keep the small
        compatibility guard here so a future aiortc release without the
        private helper degrades to its normal encoder behavior.
        """
        pc = self.pc
        if pc is None:
            return
        for sender in pc.getSenders():
            if getattr(sender, "kind", "") != "video":
                continue
            request = getattr(sender, "_send_keyframe", None)
            if callable(request):
                request()
            break

    async def video(self, item: ProgramVideo) -> None:
        await self.video_track.put(item)
        self.sent_video += 1
        self.last_media_at = time.monotonic()
        self.last_program_pts_ms = float(item.timestamp_ms)
        self.last_sent_pts_ms = float(item.timestamp_ms)
        self.last_video_pts_ms = float(item.timestamp_ms)

    async def audio(self, item: ProgramAudio) -> None:
        await self.audio_track.put(item)
        self.sent_audio += 1
        self.last_media_at = time.monotonic()
        self.last_program_pts_ms = max(float(item.timestamp_ms), float(self.last_program_pts_ms or 0.0))
        self.last_sent_pts_ms = float(item.timestamp_ms)
        self.last_audio_pts_ms = float(item.timestamp_ms)

    async def _monitor_connection(self) -> None:
        try:
            while self.pc is not None:
                await asyncio.sleep(0.5)
                pc = self.pc
                if pc is None:
                    return
                now = time.monotonic()
                if now - self._last_keyframe_request_at >= VIDEO_KEYFRAME_INTERVAL_SEC:
                    self._request_video_keyframe()
                    self._last_keyframe_request_at = now
                if pc.connectionState in {"failed", "closed", "disconnected"}:
                    self.state = "failed" if pc.connectionState == "failed" else "disconnected"
                    self.health = "failed" if pc.connectionState == "failed" else "degraded"
                    return
                try:
                    report = await pc.getStats()
                except Exception:
                    continue
                outbound = [
                    stat for stat in report.values()
                    if getattr(stat, "type", "") == "outbound-rtp"
                    and int(getattr(stat, "packetsSent", 0) or 0) > 0
                ]
                self.bytes_sent = sum(
                    int(getattr(stat, "bytesSent", 0) or 0)
                    for stat in report.values()
                    if getattr(stat, "type", "") == "outbound-rtp"
                )
                if len(outbound) >= 2:
                    self.health = "healthy"
        except asyncio.CancelledError:
            return

    async def stop(self) -> None:
        if self._health_task is not None:
            self._health_task.cancel()
            self._health_task = None
        resource = self.resource_url
        token = self.settings.bearer_token
        self.resource_url = None
        if resource and token:
            await self._delete_resource(resource)
        if self.pc is not None:
            await self.pc.close()
            self.pc = None
        self.state = "disconnected"
        for queue in (self.video_track._queue, self.audio_track._queue):
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

    async def _delete_resource(self, resource: str) -> None:
        token = self.settings.bearer_token
        if not token:
            return
        try:
            verify: bool | str = self.settings.ca_file if self.settings.tls_verify and self.settings.ca_file else self.settings.tls_verify
            response = await self._request_pinned(
                "DELETE",
                resource,
                headers={"Authorization": f"Bearer {token}"},
                verify=verify,
            )
            if response.status_code not in {200, 202, 204, 404}:
                log.warning("WHIP resource DELETE returned status=%s", response.status_code)
        except Exception:
            log.debug("WHIP resource DELETE failed", exc_info=True)
