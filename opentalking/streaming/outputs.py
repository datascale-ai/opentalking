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
from opentalking.core.redis_keys import (
    streaming_output_index_key,
    streaming_output_key,
    streaming_receipt_key,
)

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_payload(value: Mapping[str, Any]) -> str:
    # The digest is used only for idempotency/conflict checks. Never retain
    # this normalized body because it contains credentials. Secret values are
    # represented by one-way digests (rather than one shared placeholder), so
    # changing a password/token with the same idempotency key is a conflict.
    redacted = dict(value)
    transport = dict(redacted.get("transport") or {})
    for key in ("stream_key", "username", "password", "bearer_token"):
        if key in transport:
            raw = str(transport.get(key) or "")
            transport[key] = f"sha256:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"
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
    queue_depth: int = 0
    dropped_frames: int = 0
    last_program_pts_ms: float | None = None
    last_sent_pts_ms: float | None = None
    program_to_output_lag_ms: float | None = None
    av_drift_ms: float | None = None
    _last_emitted_state: tuple[str, str] | None = field(default=None, init=False, repr=False)

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
        public["queue_depth"] = int(self.queue_depth)
        public["dropped_frames"] = int(self.dropped_frames)
        for key in ("last_program_pts_ms", "last_sent_pts_ms", "program_to_output_lag_ms", "av_drift_ms"):
            value = getattr(self, key)
            if value is not None:
                public[key] = round(float(value), 3)
        return public


@dataclass
class StaleOutputSnapshot:
    """A persisted output without its secret-bearing in-memory publisher."""

    output_id: str
    session_id: str
    type: str
    name: str
    auto_connect: bool
    payload_hash: str
    created_at: str
    updated_at: str
    attempts: int
    last_error: str | None = "stale_worker_state"
    connection_state: OutputConnectionState = OutputConnectionState.FAILED
    health: OutputHealth = OutputHealth.FAILED

    def public(self) -> dict[str, Any]:
        return {
            "output_id": self.output_id,
            "session_id": self.session_id,
            "type": self.type,
            "name": self.name,
            "connection_state": self.connection_state.value,
            "health": self.health.value,
            "secret_configured": False,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "attempts": self.attempts,
            "last_error": self.last_error,
        }


class SessionOutputController:
    """Own output secrets and publisher instances for one in-process Session."""

    def __init__(
        self,
        *,
        session_id: str,
        program: Any,
        settings: Any,
        redis: Any | None = None,
        worker_boot_id: str | None = None,
        allow_snapshot_only: bool = False,
    ) -> None:
        if program is None and not allow_snapshot_only:
            raise RuntimeError("streaming program is not enabled for this session")
        self.session_id = session_id
        self.program = program
        self.settings = settings
        self.redis = redis
        self.worker_boot_id = worker_boot_id or uuid.uuid4().hex
        self.outputs: dict[str, OutputRecord] = {}
        self._stale: dict[str, StaleOutputSnapshot] = {}
        self._idempotency: dict[str, tuple[str, str]] = {}
        self._action_idempotency: dict[str, tuple[str, str]] = {}
        self._monitors: dict[str, asyncio.Task[None]] = {}
        self._connect_tasks: dict[str, asyncio.Task[Any]] = {}
        self._media_announced: set[str] = set()
        self._lock = asyncio.Lock()
        self._loaded_snapshots = False
        self._snapshot_lock = asyncio.Lock()

    def _snapshot_ttl(self) -> int:
        return max(60, int(getattr(self.settings, "streaming_snapshot_ttl_sec", 3600) or 3600))

    async def _persist_record(self, record: OutputRecord) -> None:
        """Persist only a public, secret-free snapshot and owner epoch."""
        if self.redis is None:
            return
        public = record.public()
        snapshot_key = streaming_output_key(self.session_id, record.output_id)
        mapping = {
            "output_id": record.output_id,
            "session_id": self.session_id,
            "type": record.type,
            "name": record.name,
            "auto_connect": "1" if record.auto_connect else "0",
            "payload_hash": record.payload_hash,
            "secret_configured": "1" if record.secret_configured else "0",
            "connection_state": str(public.get("connection_state") or record.connection_state.value),
            "health": str(public.get("health") or record.health.value),
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "attempts": str(record.attempts),
            "last_error": str(public.get("last_error") or ""),
            "worker_boot_id": self.worker_boot_id,
        }
        for key in ("sent_video", "sent_audio", "bytes_sent"):
            if key in public:
                mapping[key] = str(public[key])
        for key in ("queue_depth", "dropped_frames", "last_program_pts_ms", "last_sent_pts_ms", "program_to_output_lag_ms", "av_drift_ms"):
            if key in public:
                mapping[key] = str(public[key])
        ttl = self._snapshot_ttl()
        await self.redis.hset(snapshot_key, mapping=mapping)
        await self.redis.expire(snapshot_key, ttl)
        index_key = streaming_output_index_key(self.session_id)
        await self.redis.hset(index_key, key=record.output_id, value=snapshot_key)
        await self.redis.expire(index_key, ttl)

    async def _delete_snapshot(self, output_id: str) -> None:
        if self.redis is None:
            return
        await self.redis.delete(streaming_output_key(self.session_id, output_id))
        hdel = getattr(self.redis, "hdel", None)
        if callable(hdel):
            await hdel(streaming_output_index_key(self.session_id), output_id)

    @staticmethod
    def _field(fields: Mapping[str, Any], key: str, default: str = "") -> str:
        value = fields.get(key, default)
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    async def load_stale_state(self) -> None:
        """Restore secret-free snapshots and fail closed when their owner is gone.

        Publisher instances are intentionally never restored. A snapshot that
        has no matching in-memory publisher is therefore exposed as failed
        (or disconnected when it was explicitly stopped) and cannot be
        reconnected without submitting a new secret-bearing create request.
        """
        if self._loaded_snapshots or self.redis is None:
            return
        async with self._snapshot_lock:
            if self._loaded_snapshots:
                return
            index = await self.redis.hgetall(streaming_output_index_key(self.session_id))
            for raw_id, raw_key in index.items():
                output_id = self._field({"id": raw_id}, "id")
                snapshot_key = self._field({"key": raw_key}, "key")
                if not output_id or not snapshot_key:
                    continue
                fields = await self.redis.hgetall(snapshot_key)
                if not fields or output_id in self.outputs:
                    continue
                state_raw = self._field(fields, "connection_state", "failed")
                try:
                    state = OutputConnectionState(state_raw)
                except ValueError:
                    state = OutputConnectionState.FAILED
                health_raw = self._field(fields, "health", "failed")
                try:
                    health = OutputHealth(health_raw)
                except ValueError:
                    health = OutputHealth.FAILED
                # A missing publisher is always stale. Preserve an explicitly
                # disconnected terminal state, but never claim old media is
                # still healthy or expose its old secret flag.
                if state not in {OutputConnectionState.DISCONNECTED, OutputConnectionState.FAILED}:
                    state = OutputConnectionState.FAILED
                    health = OutputHealth.FAILED
                elif state == OutputConnectionState.FAILED:
                    health = OutputHealth.FAILED
                else:
                    health = OutputHealth.UNKNOWN
                stale = StaleOutputSnapshot(
                    output_id=output_id,
                    session_id=self.session_id,
                    type=self._field(fields, "type", "unknown"),
                    name=self._field(fields, "name", "streaming output"),
                    auto_connect=self._field(fields, "auto_connect") == "1",
                    payload_hash=self._field(fields, "payload_hash"),
                    created_at=self._field(fields, "created_at", _now()),
                    updated_at=_now(),
                    attempts=int(self._field(fields, "attempts", "0") or 0),
                    last_error=("stale_worker_state" if state == OutputConnectionState.FAILED else None),
                    connection_state=state,
                    health=health,
                )
                self._stale[output_id] = stale
                await self.redis.hset(
                    snapshot_key,
                    mapping={
                        "connection_state": state.value,
                        "health": health.value,
                        "secret_configured": "0",
                        "last_error": stale.last_error or "",
                        "updated_at": stale.updated_at,
                        "worker_boot_id": self.worker_boot_id,
                    },
                )
                await self.redis.expire(snapshot_key, self._snapshot_ttl())
            self._loaded_snapshots = True

    async def _emit_state(self, record: OutputRecord, reason: str | None = None) -> None:
        previous = record._last_emitted_state
        data: dict[str, Any] = {
            "session_id": self.session_id,
            "output_id": record.output_id,
            "connection_state": record.connection_state.value,
            "health": record.health.value,
                    "attempt": record.attempts,
        }
        if previous is not None:
            data["previous_connection_state"] = previous[0]
            data["previous_health"] = previous[1]
        if reason:
            data["reason"] = reason
        record._last_emitted_state = (record.connection_state.value, record.health.value)
        await self._persist_record(record)
        if self.redis is None:
            return
        try:
            await publish_event(self.redis, self.session_id, "output.state_changed", data)
            if record.connection_state == OutputConnectionState.RECONNECTING:
                await publish_event(
                    self.redis,
                    self.session_id,
                    "output.reconnecting",
                    {
                        "session_id": self.session_id,
                        "output_id": record.output_id,
                        "attempt": record.attempts,
                        "reason": reason or "destination_reconnecting",
                    },
                )
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
                candidate_policy=str(getattr(self.settings, "streaming_whip_candidate_policy", "allowlist") or "allowlist"),
                allowed_cidrs=allowed_cidrs,
                allowed_hosts=allowed_hosts,
                width=int(profile["width"]) if "width" in profile else None,
                height=int(profile["height"]) if "height" in profile else None,
            )
        )
        return kind, endpoint, publisher, True

    async def create(self, body: Mapping[str, Any], *, idempotency_key: str | None = None) -> OutputRecord:
        await self.load_stale_state()
        async with self._lock:
            body_hash = _hash_payload(body)
            key = (idempotency_key or "").strip()
            receipt_key = streaming_receipt_key(self.session_id, "create", key) if key else None
            candidate_id = f"out_{uuid.uuid4().hex[:12]}"
            if key:
                previous = self._idempotency.get(key)
                if previous is not None:
                    previous_hash, previous_id = previous
                    if previous_hash != body_hash:
                        raise ValueError("Idempotency-Key was already used with a different payload")
                    existing = self.outputs.get(previous_id)
                    if existing is not None:
                        return existing
                    if previous_id in self._stale:
                        raise ValueError("stale_worker_state")
                if self.redis is not None and receipt_key is not None:
                    pending = json.dumps(
                        {
                            "action": "create",
                            "status": "pending",
                            "payload_hash": body_hash,
                            "output_id": candidate_id,
                            "owner_epoch": self.worker_boot_id,
                        },
                        separators=(",", ":"),
                    )
                    reserved = await self.redis.set(
                        receipt_key,
                        pending,
                        ex=self._snapshot_ttl(),
                        nx=True,
                    )
                    if not reserved:
                        raw = await self.redis.get(receipt_key)
                        if isinstance(raw, bytes):
                            raw = raw.decode("utf-8", errors="replace")
                        try:
                            previous_receipt = json.loads(str(raw or "{}"))
                        except json.JSONDecodeError:
                            previous_receipt = {}
                        if previous_receipt.get("payload_hash") != body_hash:
                            raise ValueError("Idempotency-Key was already used with a different payload")
                        previous_id = str(previous_receipt.get("output_id") or "")
                        existing = self.outputs.get(previous_id)
                        if existing is not None:
                            self._idempotency[key] = (body_hash, previous_id)
                            return existing
                        if previous_id in self._stale or previous_receipt.get("status") in {"dispatched", "terminal"}:
                            raise ValueError("stale_worker_state")
                        raise ValueError("command_in_progress")
            if len(self.outputs) >= int(getattr(self.settings, "streaming_max_outputs_per_session", 4)):
                raise ValueError("maximum outputs per session reached")
            try:
                kind, _endpoint, publisher, secret_configured = self._publisher(body)
            except Exception:
                if self.redis is not None and receipt_key is not None:
                    await self.redis.set(
                        receipt_key,
                        json.dumps(
                            {"action": "create", "status": "failed", "payload_hash": body_hash},
                            separators=(",", ":"),
                        ),
                        ex=self._snapshot_ttl(),
                    )
                raise
            record = OutputRecord(
                output_id=candidate_id,
                session_id=self.session_id,
                type=kind,
                name=str(body.get("name") or kind).strip()[:120],
                auto_connect=bool(body.get("auto_connect", False)),
                publisher=publisher,
                payload_hash=body_hash,
                secret_configured=secret_configured,
            )
            self.outputs[record.output_id] = record
            if key:
                self._idempotency[key] = (body_hash, record.output_id)
            await self._persist_record(record)
            if self.redis is not None and receipt_key is not None:
                await self.redis.set(
                    receipt_key,
                    json.dumps(
                        {
                            "action": "create",
                            "status": "dispatched",
                            "payload_hash": body_hash,
                            "output_id": record.output_id,
                            "owner_epoch": self.worker_boot_id,
                        },
                        separators=(",", ":"),
                    ),
                    ex=self._snapshot_ttl(),
                )
        if record.auto_connect:
            self.request_connect(record.output_id)
        return record

    async def reserve_action_idempotency(
        self,
        output_id: str,
        action: str,
        idempotency_key: str | None,
    ) -> bool:
        """Atomically reserve a non-secret lifecycle command across workers.

        Returns ``True`` when the key was already accepted and the caller
        should return the current snapshot without scheduling another task.
        """
        await self.load_stale_state()
        key = (idempotency_key or "").strip()
        if not key:
            return False
        scoped = f"{action}:{output_id}:{key}"
        payload_hash = hashlib.sha256(f"{action}:{output_id}".encode("utf-8")).hexdigest()
        previous = self._action_idempotency.get(scoped)
        if previous is not None:
            if previous[0] != payload_hash:
                raise ValueError("Idempotency-Key was already used with a different payload")
            return True
        receipt_key = streaming_receipt_key(self.session_id, scoped, key)
        if self.redis is not None:
            value = json.dumps(
                {
                    "action": action,
                    "output_id": output_id,
                    "status": "pending",
                    "payload_hash": payload_hash,
                    "owner_epoch": self.worker_boot_id,
                },
                separators=(",", ":"),
            )
            reserved = await self.redis.set(receipt_key, value, ex=self._snapshot_ttl(), nx=True)
            if not reserved:
                raw = await self.redis.get(receipt_key)
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                try:
                    previous_receipt = json.loads(str(raw or "{}"))
                except json.JSONDecodeError:
                    previous_receipt = {}
                if previous_receipt.get("payload_hash") != payload_hash:
                    raise ValueError("Idempotency-Key was already used with a different payload")
                self._action_idempotency[scoped] = (payload_hash, output_id)
                return True
        if output_id not in self.outputs and output_id not in self._stale:
            raise KeyError(output_id)
        self._action_idempotency[scoped] = (payload_hash, output_id)
        return False

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
            # RTMPS starts its worker before the first Program tick (the
            # first video creates the PyAV container/handshake), whereas
            # WHIP completes its SDP/ICE handshake in ``start``. Reflect the
            # publisher's actual lifecycle instead of claiming connected
            # merely because a background task was created.
            publisher_state = str(getattr(record.publisher, "state", "connecting"))
            record.connection_state = (
                OutputConnectionState.CONNECTED
                if publisher_state == OutputConnectionState.CONNECTED.value
                else OutputConnectionState.CONNECTING
            )
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
        await self.load_stale_state()
        if idempotency_key and await self.reserve_action_idempotency(output_id, "delete", idempotency_key):
            # A successful delete is terminal. Treat retries as a successful
            # no-op even though the in-memory record may already be gone.
            if output_id not in self.outputs and output_id not in self._stale:
                return
        if output_id in self.outputs:
            await self.disconnect(output_id)
            self.outputs.pop(output_id, None)
        self._stale.pop(output_id, None)
        await self._delete_snapshot(output_id)

    async def close(self) -> None:
        pending = list(self._connect_tasks.values())
        self._connect_tasks.clear()
        for task in pending:
            if not task.done():
                task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for output_id in list(dict.fromkeys([*self.outputs, *self._stale])):
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
                state_map = {
                    "connecting": OutputConnectionState.CONNECTING,
                    "connected": OutputConnectionState.CONNECTED,
                    "reconnecting": OutputConnectionState.RECONNECTING,
                    "disconnected": OutputConnectionState.DISCONNECTED,
                    "failed": OutputConnectionState.FAILED,
                }
                mapped_state = state_map.get(str(publisher_state))
                if mapped_state is not None and mapped_state != record.connection_state:
                    record.connection_state = mapped_state
                    changed = True
                if publisher_health in {item.value for item in OutputHealth} and record.health.value != publisher_health:
                    record.health = OutputHealth(publisher_health)
                    changed = True
                if publisher_state == "failed":
                    if record.connection_state != OutputConnectionState.FAILED:
                        record.connection_state = OutputConnectionState.FAILED
                        changed = True
                    record.health = OutputHealth.FAILED
                    record.last_error = getattr(record.publisher, "last_error", None)
                    self.program.remove_branch(record.output_id)
                    changed = True
                branch_metrics: dict[str, Any] = getattr(self.program, "branch_metrics", lambda _name: {})(record.output_id)
                record.queue_depth = int(
                    branch_metrics.get("video_queue_depth", 0) + branch_metrics.get("audio_queue_depth", 0)
                )
                record.dropped_frames = int(
                    branch_metrics.get("dropped_video", 0) + branch_metrics.get("dropped_audio", 0)
                )
                program_pts = getattr(record.publisher, "last_program_pts_ms", None)
                sent_pts = getattr(record.publisher, "last_sent_pts_ms", None)
                if isinstance(program_pts, (int, float)):
                    record.last_program_pts_ms = float(program_pts)
                if isinstance(sent_pts, (int, float)):
                    record.last_sent_pts_ms = float(sent_pts)
                if record.last_program_pts_ms is not None and record.last_sent_pts_ms is not None:
                    record.program_to_output_lag_ms = max(
                        0.0, record.last_program_pts_ms - record.last_sent_pts_ms
                    )
                video_pts = getattr(record.publisher, "last_video_pts_ms", None)
                audio_pts = getattr(record.publisher, "last_audio_pts_ms", None)
                if isinstance(video_pts, (int, float)) and isinstance(audio_pts, (int, float)):
                    record.av_drift_ms = abs(float(video_pts) - float(audio_pts))
                if changed:
                    await self._emit_state(record, reason=record.last_error)
                else:
                    await self._persist_record(record)
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
        return self.outputs.get(output_id) or self._stale.get(output_id)  # type: ignore[return-value]

    def public(self) -> list[dict[str, Any]]:
        return [record.public() for record in self.outputs.values()] + [
            record.public() for output_id, record in self._stale.items() if output_id not in self.outputs
        ]
