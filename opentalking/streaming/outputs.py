from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from .destinations.rtmps import RTMPSPublisher, RTMPSSettings
from .destinations.whip import WHIPPublisher, WHIPSettings
from .state import OutputConnectionState, OutputHealth
from opentalking.runtime.bus import publish_event

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_payload(value: Mapping[str, Any]) -> str:
    # The digest is used only for idempotency/conflict checks.  Never retain
    # this normalized body because it contains credentials.
    redacted = dict(value)
    transport = dict(redacted.get("transport") or {})
    for key in ("stream_key", "username", "password", "bearer_token"):
        if key in transport:
            transport[key] = "<secret>"
    redacted["transport"] = transport
    return hashlib.sha256(json.dumps(redacted, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass
class OutputRecord:
    output_id: str
    session_id: str
    type: str
    name: str
    auto_connect: bool
    publisher: RTMPSPublisher | WHIPPublisher
    payload_hash: str
    secret_configured: bool
    connection_state: OutputConnectionState = OutputConnectionState.CREATED
    health: OutputHealth = OutputHealth.UNKNOWN
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    last_error: str | None = None
    attempts: int = 0

    def public(self) -> dict[str, Any]:
        publisher_state = getattr(self.publisher, "state", self.connection_state.value)
        publisher_health = getattr(self.publisher, "health", self.health.value)
        if publisher_state == "failed":
            self.connection_state = OutputConnectionState.FAILED
        elif publisher_state == "connected":
            self.connection_state = OutputConnectionState.CONNECTED
        if publisher_health in {item.value for item in OutputHealth}:
            self.health = OutputHealth(publisher_health)
        self.last_error = getattr(self.publisher, "last_error", None) or self.last_error
        self.updated_at = _now()
        return {
            "output_id": self.output_id,
            "session_id": self.session_id,
            "type": self.type,
            "name": self.name,
            "connection_state": self.connection_state.value,
            "health": self.health.value,
            "secret_configured": self.secret_configured,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "attempts": self.attempts,
            **({"last_error": self.last_error} if self.last_error else {}),
        }


class SessionOutputController:
    """Own output secrets and publisher instances for one in-process Session."""

    def __init__(self, *, session_id: str, program: Any, settings: Any, redis: Any | None = None) -> None:
        if program is None:
            raise RuntimeError("streaming program is not enabled for this session")
        self.session_id = session_id
        self.program = program
        self.settings = settings
        self.redis = redis
        self.outputs: dict[str, OutputRecord] = {}
        self._idempotency: dict[str, tuple[str, str]] = {}
        self._monitors: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    async def _emit_state(self, record: OutputRecord, reason: str | None = None) -> None:
        if self.redis is None:
            return
        data: dict[str, Any] = {
            "session_id": self.session_id,
            "output_id": record.output_id,
            "connection_state": record.connection_state.value,
            "health": record.health.value,
        }
        if reason:
            data["reason"] = reason
        try:
            await publish_event(self.redis, self.session_id, "output.state_changed", data)
        except Exception:
            log.debug("failed to publish output state event", exc_info=True)

    @staticmethod
    def _profile(body: Mapping[str, Any]) -> dict[str, Any]:
        raw = body.get("profile") or {}
        if not isinstance(raw, Mapping):
            raise ValueError("profile must be an object")
        allowed = {"width", "height", "fps", "video_bitrate_kbps", "gop_seconds"}
        if any(str(key) not in allowed for key in raw):
            raise ValueError("unsupported profile field")
        profile = dict(raw)
        fps = float(profile.get("fps", 25.0))
        if not 15 <= fps <= 30:
            raise ValueError("profile.fps must be between 15 and 30")
        if "width" in profile and not 160 <= int(profile["width"]) <= 3840:
            raise ValueError("profile.width is out of range")
        if "height" in profile and not 120 <= int(profile["height"]) <= 2160:
            raise ValueError("profile.height is out of range")
        return profile

    def _publisher(self, body: Mapping[str, Any]) -> tuple[str, str, Any, bool]:
        kind = str(body.get("type") or "").strip().lower()
        if kind not in {"rtmps", "whip"}:
            raise ValueError("type must be rtmps or whip")
        transport = body.get("transport") or {}
        if not isinstance(transport, Mapping):
            raise ValueError("transport must be an object")
        profile = self._profile(body)
        allow_local = bool(getattr(self.settings, "streaming_allow_local_targets", False))
        allowed_cidrs = tuple(
            item.strip()
            for item in str(getattr(self.settings, "streaming_allowed_cidrs", "") or "").replace(";", ",").split(",")
            if item.strip()
        )
        allowed_hosts = tuple(
            item.strip()
            for item in str(getattr(self.settings, "streaming_allowed_hosts", "") or "").replace(";", ",").split(",")
            if item.strip()
        )
        if kind == "rtmps":
            endpoint = str(transport.get("endpoint") or "").strip()
            stream_key = str(transport.get("stream_key") or "").strip()
            if not endpoint or not stream_key:
                raise ValueError("rtmps transport requires endpoint and stream_key")
            tls_verify = bool(transport.get("tls_verify", getattr(self.settings, "streaming_rtmps_tls_verify", True)))
            if not tls_verify and not bool(getattr(self.settings, "streaming_test_auth_bypass", False)):
                raise ValueError("RTMPS TLS verification cannot be disabled")
            publisher = RTMPSPublisher(
                RTMPSSettings(
                    endpoint=endpoint,
                    stream_key=stream_key,
                    username=str(transport.get("username") or "") or None,
                    password=str(transport.get("password") or "") or None,
                    tls_verify=tls_verify,
                    ca_file=str(getattr(self.settings, "streaming_rtmps_ca_file", "") or ""),
                    fps=float(profile.get("fps", getattr(self.settings, "streaming_video_fps", 25))),
                    video_bitrate_kbps=int(profile.get("video_bitrate_kbps", 2500)),
                    gop_seconds=float(profile.get("gop_seconds", 2.0)),
                    allow_local=allow_local,
                    reconnect_max_attempts=int(getattr(self.settings, "streaming_reconnect_max_attempts", 10)),
                    reconnect_max_delay_sec=float(getattr(self.settings, "streaming_reconnect_max_delay_sec", 30.0)),
                    allowed_cidrs=allowed_cidrs,
                    allowed_hosts=allowed_hosts,
                )
            )
            return kind, endpoint, publisher, bool(stream_key or transport.get("password"))
        endpoint = str(transport.get("endpoint") or "").strip()
        token = str(transport.get("bearer_token") or "").strip()
        if not endpoint or not token:
            raise ValueError("whip transport requires endpoint and bearer_token")
        tls_verify = bool(transport.get("tls_verify", getattr(self.settings, "streaming_whip_tls_verify", True)))
        if not tls_verify and not bool(getattr(self.settings, "streaming_test_auth_bypass", False)):
            raise ValueError("WHIP TLS verification cannot be disabled")
        publisher = WHIPPublisher(
            WHIPSettings(
                endpoint=endpoint,
                bearer_token=token,
                tls_verify=tls_verify,
                ca_file=str(getattr(self.settings, "streaming_whip_ca_file", "") or ""),
                fps=float(profile.get("fps", getattr(self.settings, "streaming_video_fps", 25))),
                ice_servers=str(getattr(self.settings, "streaming_whip_ice_servers", "") or ""),
                allow_local=allow_local,
                max_redirects=int(getattr(self.settings, "streaming_whip_max_redirects", 2)),
                allowed_cidrs=allowed_cidrs,
                allowed_hosts=allowed_hosts,
            )
        )
        return kind, endpoint, publisher, True

    async def create(self, body: Mapping[str, Any], *, idempotency_key: str | None = None) -> OutputRecord:
        async with self._lock:
            if len(self.outputs) >= int(getattr(self.settings, "streaming_max_outputs_per_session", 4)):
                raise ValueError("maximum outputs per session reached")
            body_hash = _hash_payload(body)
            # A caller may retry with the same key; do not create a second
            # publisher.  The key is kept only in this process, never Redis.
            if idempotency_key:
                key = idempotency_key.strip()
                previous = self._idempotency.get(key)
                if previous is not None:
                    previous_hash, previous_id = previous
                    if previous_hash != body_hash:
                        raise ValueError("Idempotency-Key was already used with a different payload")
                    existing = self.outputs.get(previous_id)
                    if existing is not None:
                        return existing
            kind, _endpoint, publisher, secret_configured = self._publisher(body)
            record = OutputRecord(
                output_id=f"out_{uuid.uuid4().hex[:12]}",
                session_id=self.session_id,
                type=kind,
                name=str(body.get("name") or kind).strip()[:120],
                auto_connect=bool(body.get("auto_connect", False)),
                publisher=publisher,
                payload_hash=body_hash,
                secret_configured=secret_configured,
            )
            self.outputs[record.output_id] = record
            if idempotency_key:
                self._idempotency[idempotency_key.strip()] = (body_hash, record.output_id)
        if record.auto_connect:
            await self.connect(record.output_id)
        return record

    async def connect(self, output_id: str) -> OutputRecord:
        record = self.outputs.get(output_id)
        if record is None:
            raise KeyError(output_id)
        if record.connection_state == OutputConnectionState.CONNECTED:
            return record
        record.connection_state = OutputConnectionState.CONNECTING
        record.attempts += 1
        await self._emit_state(record)
        try:
            await record.publisher.start()
            self.program.add_branch(
                output_id,
                video_callback=record.publisher.video,
                audio_callback=record.publisher.audio,
            )
            record.connection_state = OutputConnectionState.CONNECTED
            record.health = OutputHealth.UNKNOWN
            await self._emit_state(record)
            previous = self._monitors.pop(output_id, None)
            if previous is not None:
                previous.cancel()
            self._monitors[output_id] = asyncio.create_task(
                self._monitor(record), name=f"output-monitor-{output_id}"
            )
        except Exception as exc:
            record.connection_state = OutputConnectionState.FAILED
            record.health = OutputHealth.FAILED
            record.last_error = type(exc).__name__
            await self._emit_state(record, reason=record.last_error)
            await record.publisher.stop()
            raise
        return record

    async def disconnect(self, output_id: str) -> OutputRecord:
        record = self.outputs.get(output_id)
        if record is None:
            raise KeyError(output_id)
        self.program.remove_branch(output_id)
        monitor = self._monitors.pop(output_id, None)
        if monitor is not None:
            monitor.cancel()
        await record.publisher.stop()
        record.connection_state = OutputConnectionState.DISCONNECTED
        record.health = OutputHealth.UNKNOWN
        await self._emit_state(record)
        return record

    async def reconnect(self, output_id: str) -> OutputRecord:
        await self.disconnect(output_id)
        return await self.connect(output_id)

    async def delete(self, output_id: str) -> None:
        if output_id in self.outputs:
            await self.disconnect(output_id)
            self.outputs.pop(output_id, None)

    async def close(self) -> None:
        for output_id in list(self.outputs):
            try:
                await self.delete(output_id)
            except Exception:
                log.warning("failed to close output %s", output_id, exc_info=True)

    async def _monitor(self, record: OutputRecord) -> None:
        try:
            while record.output_id in self.outputs:
                await asyncio.sleep(0.5)
                publisher_state = getattr(record.publisher, "state", "")
                publisher_health = getattr(record.publisher, "health", "")
                changed = False
                if publisher_state == "failed" and record.connection_state != OutputConnectionState.FAILED:
                    record.connection_state = OutputConnectionState.FAILED
                    record.health = OutputHealth.FAILED
                    record.last_error = getattr(record.publisher, "last_error", None)
                    changed = True
                if publisher_health == OutputHealth.HEALTHY.value and record.health != OutputHealth.HEALTHY:
                    record.health = OutputHealth.HEALTHY
                    changed = True
                if changed:
                    await self._emit_state(record, reason=record.last_error)
        except asyncio.CancelledError:
            return

    def get(self, output_id: str) -> OutputRecord | None:
        return self.outputs.get(output_id)

    def public(self) -> list[dict[str, Any]]:
        return [record.public() for record in self.outputs.values()]
