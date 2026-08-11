from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from fractions import Fraction
from urllib.parse import urljoin, urlparse

import httpx
import numpy as np
from aiortc import RTCBundlePolicy, RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamTrack
from aiortc.rtcrtpsender import RTCRtpSender
from av import AudioFrame, VideoFrame

from ..security import validate_resolved_target, validate_target_url
from ..types import ProgramAudio, ProgramVideo

log = logging.getLogger(__name__)


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
        width, height = self._size
        if width and height and (data.shape[1], data.shape[0]) != (width, height):
            import cv2

            data = cv2.resize(data, (width, height), interpolation=cv2.INTER_AREA)
        frame = VideoFrame.from_ndarray(data, format="bgr24")
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
        self.last_media_at: float | None = None

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
        verify: bool | str = self.settings.ca_file if self.settings.tls_verify and self.settings.ca_file else self.settings.tls_verify
        headers = {
            "Authorization": f"Bearer {self.settings.bearer_token}",
            "Content-Type": "application/sdp",
            "Accept": "application/sdp",
        }
        async with httpx.AsyncClient(verify=verify, follow_redirects=False, trust_env=False, timeout=15.0) as client:
            target = endpoint
            for redirect_count in range(max(0, self.settings.max_redirects) + 1):
                response = await client.post(target, headers=headers, content=local.sdp.encode("utf-8"))
                if response.status_code not in {307, 308}:
                    break
                location = response.headers.get("location")
                if not location or redirect_count >= max(0, self.settings.max_redirects):
                    raise RuntimeError("WHIP redirect policy rejected")
                target = urljoin(target, location)
                validate_target_url(
                    target,
                    schemes={"https"},
                    allow_local=self.settings.allow_local,
                    allowed_hosts=set(self.settings.allowed_hosts),
                    allowed_cidrs=list(self.settings.allowed_cidrs),
                )
            else:  # pragma: no cover - loop always breaks or raises
                raise RuntimeError("WHIP redirect policy rejected")
        if response.status_code != 201:
            raise RuntimeError(f"WHIP publish rejected ({response.status_code})")
        if "sdp" not in response.headers.get("content-type", "").lower():
            raise RuntimeError("WHIP response is not application/sdp")
        answer_sdp = response.text
        if not answer_sdp.strip() or answer_sdp.count("m=") != local.sdp.count("m="):
            raise RuntimeError("WHIP answer media sections do not match offer")
        if "a=sendonly" in answer_sdp and "a=recvonly" not in answer_sdp:
            raise RuntimeError("WHIP answer has incompatible direction")
        location = response.headers.get("location")
        if not location:
            raise RuntimeError("WHIP response is missing Location")
        resource = urljoin(target, location)
        validate_target_url(
            resource,
            schemes={"https"},
            allow_local=self.settings.allow_local,
            allowed_hosts=set(self.settings.allowed_hosts),
            allowed_cidrs=list(self.settings.allowed_cidrs),
        )
        self.resource_url = resource
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=answer_sdp, type="answer"))
        self.state = "connected"

    async def video(self, item: ProgramVideo) -> None:
        await self.video_track.put(item)
        self.sent_video += 1
        self.last_media_at = time.monotonic()
        if self.sent_audio:
            self.health = "healthy"

    async def audio(self, item: ProgramAudio) -> None:
        await self.audio_track.put(item)
        self.sent_audio += 1
        self.last_media_at = time.monotonic()
        if self.sent_video:
            self.health = "healthy"

    async def stop(self) -> None:
        resource = self.resource_url
        token = self.settings.bearer_token
        self.resource_url = None
        if resource and token:
            try:
                verify: bool | str = self.settings.ca_file if self.settings.tls_verify and self.settings.ca_file else self.settings.tls_verify
                async with httpx.AsyncClient(verify=verify, follow_redirects=False, trust_env=False, timeout=10.0) as client:
                    await client.delete(resource, headers={"Authorization": f"Bearer {token}"})
            except Exception:
                log.debug("WHIP resource DELETE failed", exc_info=True)
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
