from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from .destinations.rtmps import (
    RTMPSPublisher,
    RTMPSSettings,
    normalize_rtmps_endpoint,
    validate_stream_key,
)
from .destinations.whip import WHIPPublisher, WHIPSettings
from .security import validate_target_url
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
        public = {
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
        # Non-sensitive media progress helps the UI distinguish a completed
        # handshake from an output that is actually carrying A/V. Never expose
        # endpoint, credentials, SDP, or third-party response bodies here.
        for key in ("sent_video", "sent_audio", "bytes_sent"):
            value = getattr(self.publisher, key, None)
            if isinstance(value, (int, float)):
                public[key] = int(value)
        return public


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
        self._action_idempotency: dict[str, tuple[str, str]] = {}
        self._monitors: dict[str, asyncio.Task[None]] = {}
        self._connect_tasks: dict[str, asyncio.Task[Any]] = {}
        self._media_announced: set[str] = set()
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
        if "width" in profile and (not 160 <= int(profile["width"]) <= 3840 or int(profile["width"]) % 2):
            raise ValueError("profile.width is out of range")
        if "height" in profile and (not 120 <= int(profile["height"]) <= 2160 or int(profile["height"]) % 2):
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
        program_fps = float(getattr(getattr(self.program, "clock", None), "fps", 25.0))
        if abs(float(profile.get("fps", program_fps)) - program_fps) > 0.01:
            raise ValueError("profile.fps must match the active ProgramClock fps")
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
        publisher: RTMPSPublisher | WHIPPublisher
        if kind == "rtmps":
            endpoint = str(transport.get("endpoint") or "").strip()
            stream_key = str(transport.get("stream_key") or "").strip()
            if not endpoint or not stream_key:
                raise ValueError("rtmps transport requires endpoint and stream_key")
            # Reject deterministic transport errors during the API request;
            # an async publisher task must not be the first place a caller
            # learns that its endpoint or stream name is malformed.
            normalize_rtmps_endpoint(
                endpoint,
                allow_local=allow_local,
                allowed_hosts=set(allowed_hosts),
                allowed_cidrs=list(allowed_cidrs),
            )
            validate_stream_key(stream_key)
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
                    width=int(profile["width"]) if "width" in profile else None,
                    height=int(profile["height"]) if "height" in profile else None,
                )
            )
            return kind, endpoint, publisher, bool(stream_key or transport.get("password"))
        endpoint = str(transport.get("endpoint") or "").strip()
        token = str(transport.get("bearer_token") or "").strip()
        if not endpoint or not token:
            raise ValueError("whip transport requires endpoint and bearer_token")
        validate_target_url(
            endpoint,
            schemes={"https"},
            allow_local=allow_local,
            allowed_hosts=set(allowed_hosts),
            allowed_cidrs=list(allowed_cidrs),
        )
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
                width=int(profile["width"]) if "width" in profile else None,
                height=int(profile["height"]) if "height" in profile else None,
            )
        )
        return kind, endpoint, publisher, True

    async def create(self, body: Mapping[str, Any], *, idempotency_key: str | None = None) -> OutputRecord:
        async with self._lock:
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
            if len(self.outputs) >= int(getattr(self.settings, "streaming_max_outputs_per_session", 4)):
                raise ValueError("maximum outputs per session reached")
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
            self.request_connect(record.output_id)
        return record

    def _reserve_action_idempotency(
        self,
        output_id: str,
        action: str,
        idempotency_key: str | None,
    ) -> OutputRecord | None:
        if not idempotency_key:
            return None
        key = idempotency_key.strip()
        if not key:
            return None
        scoped = f"{action}:{output_id}:{key}"
        payload_hash = hashlib.sha256(f"{action}:{output_id}".encode("utf-8")).hexdigest()
        previous = self._action_idempotency.get(scoped)
        if previous is not None:
            previous_hash, previous_id = previous
            if previous_hash != payload_hash:
                raise ValueError("Idempotency-Key was already used with a different payload")
            existing = self.outputs.get(previous_id)
            if existing is not None:
                return existing
        self._action_idempotency[scoped] = (payload_hash, output_id)
        return None

    def request_connect(self, output_id: str, *, idempotency_key: str | None = None) -> OutputRecord:
        """Queue a publisher handshake without blocking the HTTP request."""
        record = self.outputs.get(output_id)
        if record is None:
            raise KeyError(output_id)
        duplicate = self._reserve_action_idempotency(output_id, "connect", idempotency_key)
        if duplicate is not None:
            return duplicate
        current = self._connect_tasks.get(output_id)
        if current is not None and not current.done():
            return record
        if record.connection_state == OutputConnectionState.CONNECTED:
            return record
        task = asyncio.create_task(self.connect(output_id), name=f"output-connect-{output_id}")
        self._connect_tasks[output_id] = task

        def _done(done: asyncio.Task[OutputRecord], key: str = output_id) -> None:
            if self._connect_tasks.get(key) is done:
                self._connect_tasks.pop(key, None)
            if not done.cancelled():
                try:
                    done.exception()
                except Exception:
                    log.debug("output connect task failed", exc_info=True)

        task.add_done_callback(_done)
        return record

    def _request_lifecycle(
        self,
        output_id: str,
        action: str,
        *,
        idempotency_key: str | None = None,
    ) -> OutputRecord:
        record = self.outputs.get(output_id)
        if record is None:
            raise KeyError(output_id)
        duplicate = self._reserve_action_idempotency(output_id, action, idempotency_key)
        if duplicate is not None:
            return duplicate
        current = self._connect_tasks.get(output_id)
        if current is not None and not current.done():
            return record
        if action == "disconnect" and record.connection_state in {
            OutputConnectionState.DISCONNECTED,
            OutputConnectionState.CREATED,
        }:
            return record
        task = asyncio.create_task(
            self.disconnect(output_id) if action == "disconnect" else self.reconnect(output_id),
            name=f"output-{action}-{output_id}",
        )
        self._connect_tasks[output_id] = task

        def _done(done: asyncio.Task[Any], key: str = output_id) -> None:
            if self._connect_tasks.get(key) is done:
                self._connect_tasks.pop(key, None)
            if not done.cancelled():
                try:
                    done.exception()
                except Exception:
                    log.debug("output lifecycle task failed", exc_info=True)

        task.add_done_callback(_done)
        return record

    def request_disconnect(self, output_id: str, *, idempotency_key: str | None = None) -> OutputRecord:
        return self._request_lifecycle(output_id, "disconnect", idempotency_key=idempotency_key)

    def request_reconnect(self, output_id: str, *, idempotency_key: str | None = None) -> OutputRecord:
        return self._request_lifecycle(output_id, "reconnect", idempotency_key=idempotency_key)

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
            # Attach the branch only after the protocol publisher has
            # completed its handshake.  A failed WHIP/RTMPS connect must not
            # leave a silent branch consuming Program frames.
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
        pending = self._connect_tasks.pop(output_id, None)
        if pending is not None and not pending.done() and pending is not asyncio.current_task():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        record.connection_state = OutputConnectionState.DISCONNECTING
        await self._emit_state(record)
        self.program.remove_branch(output_id)
        monitor = self._monitors.pop(output_id, None)
        if monitor is not None:
            monitor.cancel()
        self._media_announced.discard(output_id)
        await record.publisher.stop()
        record.connection_state = OutputConnectionState.DISCONNECTED
        record.health = OutputHealth.UNKNOWN
        await self._emit_state(record)
        return record

    async def reconnect(self, output_id: str) -> OutputRecord:
        await self.disconnect(output_id)
        # `reconnect()` may itself be running from `_connect_tasks`; release
        # that marker before scheduling the fresh handshake, otherwise
        # request_connect() would mistake this task for an existing connect.
        current = asyncio.current_task()
        if self._connect_tasks.get(output_id) is current:
            self._connect_tasks.pop(output_id, None)
        return self.request_connect(output_id)

    async def delete(self, output_id: str, *, idempotency_key: str | None = None) -> None:
        if idempotency_key:
            key = idempotency_key.strip()
            if key:
                scoped = f"delete:{output_id}:{key}"
                payload_hash = hashlib.sha256(f"delete:{output_id}".encode("utf-8")).hexdigest()
                previous = self._action_idempotency.get(scoped)
                if previous is not None:
                    previous_hash, _previous_id = previous
                    if previous_hash != payload_hash:
                        raise ValueError("Idempotency-Key was already used with a different payload")
                    # A successful delete is terminal. Treat retries as a
                    # successful no-op even though the record is gone.
                    if output_id not in self.outputs:
                        return
                self._action_idempotency[scoped] = (payload_hash, output_id)
        if output_id in self.outputs:
            await self.disconnect(output_id)
            self.outputs.pop(output_id, None)

    async def close(self) -> None:
        pending = list(self._connect_tasks.values())
        self._connect_tasks.clear()
        for task in pending:
            if not task.done():
                task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
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
                    self.program.remove_branch(record.output_id)
                    changed = True
                if publisher_health == OutputHealth.HEALTHY.value and record.health != OutputHealth.HEALTHY:
                    record.health = OutputHealth.HEALTHY
                    changed = True
                if changed:
                    await self._emit_state(record, reason=record.last_error)
                if (
                    publisher_health == OutputHealth.HEALTHY.value
                    and record.output_id not in self._media_announced
                ):
                    self._media_announced.add(record.output_id)
                    if self.redis is not None:
                        try:
                            await publish_event(
                                self.redis,
                                self.session_id,
                                "output.media_started",
                                {"session_id": self.session_id, "output_id": record.output_id},
                            )
                        except Exception:
                            log.debug("failed to publish output media event", exc_info=True)
        except asyncio.CancelledError:
            return

    def get(self, output_id: str) -> OutputRecord | None:
        return self.outputs.get(output_id)

    def public(self) -> list[dict[str, Any]]:
        return [record.public() for record in self.outputs.values()]
