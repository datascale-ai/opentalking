from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import urlparse

from opentalking.video_creation_jobs import VideoCreationJob, VideoCreationJobManager

from .chunks import ChunkHub, ChunkQueue
from .destinations.rtmps import RTMPSSettings, normalize_rtmps_endpoint, validate_stream_key
from .destinations.rtmps_chunked import ChunkedRTMPSPublisher


class RTMPSTargetConflict(ValueError):
    """A second in-process publisher attempted to claim the same target."""

    code = "target_replaced"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass
class ChunkedRTMPSJob:
    rtmps_job_id: str
    video_creation_job_id: str
    publisher: ChunkedRTMPSPublisher
    queue: ChunkQueue
    source_hub: ChunkHub
    target_key: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    status: str = "waiting_source"
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    def public(self, source_job: VideoCreationJob | None = None) -> dict[str, Any]:
        publisher = self.publisher
        source_public = source_job.public() if source_job is not None else {}
        source_status = str(source_public.get("status") or "")
        if self.status == "waiting_source" and source_status in {"failed", "stopped"}:
            self.status = "failed"
        publisher_state = str(getattr(publisher, "state", "") or "")
        status = self.status
        if status not in {"completed", "stopped", "failed"}:
            if publisher_state == "publishing":
                status = "publishing"
            elif publisher_state in {"connecting", "reconnecting", "finalizing"}:
                status = publisher_state
            elif source_status in {"queued", "generating"}:
                status = "waiting_source" if publisher_state == "created" else "generating"
        connection_state = {
            "created": "created",
            "connecting": "connecting",
            "publishing": "connected",
            "reconnecting": "reconnecting",
            "finalizing": "connected",
            "completed": "disconnected",
            "stopped": "disconnected",
            "failed": "failed",
        }.get(publisher_state, publisher_state or "unknown")
        playback_state = status
        payload: dict[str, Any] = {
            "rtmps_job_id": self.rtmps_job_id,
            "video_creation_job_id": self.video_creation_job_id,
            "status": status,
            "connection_state": connection_state,
            "playback_state": playback_state,
            "transport": "rtmps",
            "secret_configured": True,
            "generated_duration_ms": round(float(source_public.get("generated_duration_ms") or 0.0), 3),
            "published_duration_ms": round(float(publisher.last_sent_pts_ms or 0.0), 3),
            "buffer_duration_ms": round(float(publisher.buffer_duration_ms), 3),
            "first_media_at": publisher.first_media_at,
            "first_input_sequence": getattr(publisher, "first_input_sequence", None),
            "first_input_pts_ms": getattr(publisher, "first_input_pts_ms", None),
            "finalized_at": publisher.finalized_at,
            "sent_video": int(publisher.sent_video),
            "sent_audio": int(publisher.sent_audio),
            "bytes_sent": int(publisher.bytes_sent),
            "dropped_chunks": int(publisher.dropped_chunks),
            "queue_depth": int(publisher.queue_depth),
            "blocked_ms": round(float(publisher.blocked_ms), 3),
            "last_error": publisher.last_error,
            "error_code": publisher.error_code,
            "final_export_id": source_public.get("final_export_id"),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        return {key: value for key, value in payload.items() if value is not None}


class ChunkedRTMPSJobManager:
    def __init__(self, settings: object, video_jobs: VideoCreationJobManager) -> None:
        self.settings = settings
        self.video_jobs = video_jobs
        self.jobs: dict[str, ChunkedRTMPSJob] = {}
        self._target_owners: dict[str, str] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _csv_setting(settings: object, name: str) -> tuple[str, ...]:
        return tuple(
            item.strip()
            for item in str(getattr(settings, name, "") or "").replace(";", ",").split(",")
            if item.strip()
        )

    def _settings_from_body(self, body: Mapping[str, Any]) -> RTMPSSettings:
        transport = body.get("transport")
        if not isinstance(transport, Mapping):
            raise ValueError("transport must be an object")
        endpoint = str(transport.get("endpoint") or "").strip()
        stream_key = str(transport.get("stream_key") or "").strip()
        if not endpoint or not stream_key:
            raise ValueError("transport requires endpoint and stream_key")
        allow_local = bool(getattr(self.settings, "streaming_allow_local_targets", False))
        allowed_hosts = self._csv_setting(self.settings, "streaming_allowed_hosts")
        allowed_cidrs = self._csv_setting(self.settings, "streaming_allowed_cidrs")
        normalize_rtmps_endpoint(
            endpoint,
            allow_local=allow_local,
            allowed_hosts=set(allowed_hosts),
            allowed_cidrs=list(allowed_cidrs),
        )
        validate_stream_key(stream_key)
        profile = body.get("profile") or {}
        if not isinstance(profile, Mapping):
            raise ValueError("profile must be an object")
        allowed_profile = {"width", "height", "fps", "video_bitrate_kbps", "gop_seconds"}
        if any(str(key) not in allowed_profile for key in profile):
            raise ValueError("unsupported profile field")
        tls_verify = bool(transport.get("tls_verify", getattr(self.settings, "streaming_rtmps_tls_verify", True)))
        if not tls_verify and not bool(getattr(self.settings, "streaming_test_auth_bypass", False)):
            raise ValueError("RTMPS TLS verification cannot be disabled")
        return RTMPSSettings(
            endpoint=endpoint,
            stream_key=stream_key,
            username=str(transport.get("username") or "") or None,
            password=str(transport.get("password") or "") or None,
            tls_verify=tls_verify,
            ca_file=str(getattr(self.settings, "streaming_rtmps_ca_file", "") or ""),
            fps=float(profile.get("fps", getattr(self.settings, "streaming_video_fps", 25))),
            video_bitrate_kbps=int(profile.get("video_bitrate_kbps", 2500)),
            # Offline video playback favors a one-second IDR cadence so HLS
            # can begin from the first available media window quickly.
            gop_seconds=float(profile.get("gop_seconds", 1.0)),
            allow_local=allow_local,
            reconnect_max_attempts=int(getattr(self.settings, "streaming_reconnect_max_attempts", 10)),
            reconnect_max_delay_sec=float(getattr(self.settings, "streaming_reconnect_max_delay_sec", 30.0)),
            allowed_cidrs=allowed_cidrs,
            allowed_hosts=allowed_hosts,
            width=int(profile["width"]) if "width" in profile else None,
            height=int(profile["height"]) if "height" in profile else None,
        )

    @staticmethod
    def _target_key(settings: RTMPSSettings) -> str:
        """Return a secret-free identity for one ingest target."""

        parsed = urlparse(settings.endpoint)
        host = (parsed.hostname or "").rstrip(".").lower()
        port = parsed.port or 1935
        path = parsed.path.rstrip("/")
        return f"{parsed.scheme.lower()}://{host}:{port}{path}/{settings.stream_key}"

    async def _claim_target(self, target_key: str, job_id: str) -> None:
        async with self._lock:
            owner_id = self._target_owners.get(target_key)
            if owner_id and owner_id != job_id:
                owner = self.jobs.get(owner_id)
                # A claimed target is also a reservation while a job is
                # being assembled.  Treat a missing job as occupied instead
                # of allowing a second create() call to win during the
                # subscribe/start await points.
                if owner is None:
                    raise RTMPSTargetConflict()
                owner_state = str(getattr(owner.publisher, "state", "") or "") if owner else ""
                owner_status = str(getattr(owner, "status", "") or "") if owner else ""
                if owner_status not in {"completed", "stopped", "failed"} and owner_state not in {
                    "completed",
                    "stopped",
                    "failed",
                }:
                    raise RTMPSTargetConflict()
                self._target_owners.pop(target_key, None)
            self._target_owners[target_key] = job_id

    async def _release_target(self, job: ChunkedRTMPSJob) -> None:
        if not job.target_key:
            return
        async with self._lock:
            if self._target_owners.get(job.target_key) == job.rtmps_job_id:
                self._target_owners.pop(job.target_key, None)

    async def create(self, body: Mapping[str, Any]) -> ChunkedRTMPSJob:
        source = body.get("source")
        if not isinstance(source, Mapping) or str(source.get("type") or "") != "video_creation_job":
            raise ValueError("source.type must be video_creation_job")
        source_id = str(source.get("job_id") or "").strip()
        source_job = self.video_jobs.get(source_id)
        if source_job is None:
            raise KeyError(source_id)
        if source_job.status in {"failed", "stopped"}:
            raise ValueError("source video creation job is not publishable")
        settings = self._settings_from_body(body)
        target_key = self._target_key(settings)
        job_id = f"rtjob_{uuid.uuid4().hex[:16]}"
        await self._claim_target(target_key, job_id)
        publisher = ChunkedRTMPSPublisher(
            settings,
            replay_chunks=max(2, int(getattr(self.settings, "video_creation_chunk_queue_max_chunks", 8))),
        )
        queue: ChunkQueue | None = None
        job: ChunkedRTMPSJob | None = None
        try:
            queue = await source_job.hub.subscribe()
            job = ChunkedRTMPSJob(
                rtmps_job_id=job_id,
                video_creation_job_id=source_id,
                publisher=publisher,
                queue=queue,
                source_hub=source_job.hub,
                target_key=target_key,
            )
            async with self._lock:
                self.jobs[job.rtmps_job_id] = job
            await publisher.start(queue)
            # Publish-mode source jobs are gated until this queue and the
            # publisher task are installed. This guarantees that the first
            # generated chunk is sequence 0 / PTS 0 for this RTMPS job.
            await self.video_jobs.start(source_id)
        except Exception:
            # A failed RTMPS start must not leave a gated source waiting
            # forever; let it finish its MP4 archive without this publisher.
            try:
                await self.video_jobs.start(source_id)
            except KeyError:
                pass
            if queue is not None:
                await source_job.hub.unsubscribe(queue)
            async with self._lock:
                self.jobs.pop(job_id, None)
                if self._target_owners.get(target_key) == job_id:
                    self._target_owners.pop(target_key, None)
            raise
        assert job is not None
        job.status = "connecting"
        job.task = asyncio.create_task(self._watch(job), name=f"rtmps-job-{job.rtmps_job_id}")
        return job

    async def _watch(self, job: ChunkedRTMPSJob) -> None:
        # Capture the subscription before waiting.  ``reconnect()`` replaces
        # job.queue while the old watcher is being stopped; cleanup must
        # unsubscribe the queue owned by this watcher, not the replacement.
        queue = job.queue
        try:
            await job.publisher.wait()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            # A publisher task must never leave the job in ``connecting`` or
            # ``publishing`` after an unexpected muxer/socket exception.  Do
            # not copy the exception text: lower layers may include a URL or
            # an upstream response containing credentials.
            job.publisher.state = "failed"
            job.publisher.health = "failed"
            job.publisher.error_code = type(exc).__name__
            job.publisher.last_error = type(exc).__name__
        finally:
            await job.source_hub.unsubscribe(queue)
            await self._release_target(job)
            job.updated_at = time.time()
        if job.publisher.state == "completed":
            job.status = "completed"
        elif job.publisher.state == "stopped":
            job.status = "stopped"
        elif job.publisher.state == "failed":
            job.status = "failed"
        job.updated_at = time.time()

    def get(self, job_id: str) -> ChunkedRTMPSJob | None:
        return self.jobs.get(job_id)

    def public(self, job: ChunkedRTMPSJob) -> dict[str, Any]:
        source_job = self.video_jobs.get(job.video_creation_job_id)
        return job.public(source_job)

    async def stop(self, job_id: str) -> ChunkedRTMPSJob:
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        await job.publisher.stop()
        if job.task is not None and job.task is not asyncio.current_task():
            try:
                await job.task
            except asyncio.CancelledError:
                pass
        job.status = "stopped"
        job.updated_at = time.time()
        return job

    async def reconnect(self, job_id: str) -> ChunkedRTMPSJob:
        old = self.jobs.get(job_id)
        if old is None:
            raise KeyError(job_id)
        source_job = self.video_jobs.get(old.video_creation_job_id)
        if source_job is None:
            raise KeyError(old.video_creation_job_id)
        await old.publisher.stop()
        if old.task is not None and old.task is not asyncio.current_task():
            try:
                await old.task
            except asyncio.CancelledError:
                pass
        target_key = self._target_key(old.publisher.settings)
        await self._claim_target(target_key, old.rtmps_job_id)
        publisher = ChunkedRTMPSPublisher(old.publisher.settings, replay_chunks=old.publisher.replay_chunks)
        queue: ChunkQueue | None = None
        try:
            queue = await source_job.hub.subscribe()
            await publisher.start(queue)
        except Exception:
            if queue is not None:
                await source_job.hub.unsubscribe(queue)
            async with self._lock:
                if self._target_owners.get(target_key) == old.rtmps_job_id:
                    self._target_owners.pop(target_key, None)
            raise
        assert queue is not None
        old.queue = queue
        old.source_hub = source_job.hub
        old.target_key = target_key
        old.publisher = publisher
        old.status = "reconnecting"
        old.task = asyncio.create_task(self._watch(old), name=f"rtmps-job-{old.rtmps_job_id}")
        return old

    async def delete(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        await self.stop(job_id)
        async with self._lock:
            self.jobs.pop(job_id, None)

    async def close(self) -> None:
        for job_id in tuple(self.jobs):
            try:
                await self.delete(job_id)
            except KeyError:
                pass
