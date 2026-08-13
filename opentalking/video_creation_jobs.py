from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping

from opentalking.streaming.chunks import ChunkHub, MediaChunk


VideoJobRunner = Callable[["VideoJobChunkSink"], Awaitable[dict[str, Any]]]


@dataclass
class VideoCreationJob:
    job_id: str
    source: str
    metadata: dict[str, Any]
    hub: ChunkHub
    status: str = "queued"
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_detail: str | None = None
    generated_duration_ms: float = 0.0
    first_media_at: float | None = None
    finalized_at: float | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    task: asyncio.Task[None] | None = field(default=None, repr=False)
    # Publish-mode jobs use this gate so the RTMPS subscriber can be installed
    # before the renderer emits its first MediaChunk.
    start_event: asyncio.Event | None = field(default=None, repr=False)
    first_sequence: int | None = None
    first_pts_ms: float | None = None

    def public(self) -> dict[str, Any]:
        result = self.result or {}
        export_video = result.get("export_video") if isinstance(result, Mapping) else None
        payload: dict[str, Any] = {
            "job_id": self.job_id,
            "status": self.status,
            "source": self.source,
            "generated_duration_ms": round(float(self.generated_duration_ms), 3),
            "buffer_duration_ms": 0.0,
            "first_media_at": self.first_media_at,
            "first_sequence": self.first_sequence,
            "first_pts_ms": self.first_pts_ms,
            "finalized_at": self.finalized_at,
            "final_export_id": export_video.get("id") if isinstance(export_video, Mapping) else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if isinstance(export_video, Mapping):
            payload["export_video"] = dict(export_video)
        if self.error_code:
            payload["error_code"] = self.error_code
        return payload


class VideoJobChunkSink:
    """Updates source-job progress while broadcasting chunks to subscribers."""

    def __init__(self, job: VideoCreationJob) -> None:
        self.job = job

    async def publish(self, chunk: MediaChunk) -> None:
        self.job.generated_duration_ms = max(self.job.generated_duration_ms, float(chunk.end_pts_ms))
        if self.job.first_sequence is None:
            self.job.first_sequence = int(chunk.sequence)
            self.job.first_pts_ms = float(chunk.start_pts_ms)
        if self.job.first_media_at is None and (chunk.video or chunk.audio):
            self.job.first_media_at = time.time()
        self.job.updated_at = time.time()
        await self.job.hub.publish(chunk)

    async def finish(self) -> None:
        self.job.updated_at = time.time()
        await self.job.hub.finish()

    async def fail(self, code: str, detail: str = "") -> None:
        self.job.error_code = str(code)
        self.job.updated_at = time.time()
        await self.job.hub.fail(code, detail)


class VideoCreationJobManager:
    """In-process async manager used by unified and single-worker API modes."""

    def __init__(self, settings: object) -> None:
        self.settings = settings
        self.jobs: dict[str, VideoCreationJob] = {}
        self._lock = asyncio.Lock()

    def _max_chunks(self) -> int:
        raw = getattr(self.settings, "video_creation_chunk_queue_max_chunks", 8)
        try:
            return max(2, int(raw))
        except (TypeError, ValueError):
            return 8

    def _subscriber_put_timeout_sec(self) -> float:
        raw = getattr(self.settings, "video_creation_chunk_publish_timeout_sec", 5.0)
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            return 5.0

    async def submit(
        self,
        *,
        source: str,
        metadata: Mapping[str, Any] | None,
        runner: VideoJobRunner,
        wait_for_start: bool = False,
    ) -> VideoCreationJob:
        job_id = f"job_{uuid.uuid4().hex[:16]}"
        job = VideoCreationJob(
            job_id=job_id,
            source=str(source),
            metadata=dict(metadata or {}),
            hub=ChunkHub(
                max_chunks=self._max_chunks(),
                replay_chunks=self._max_chunks(),
                subscriber_put_timeout_sec=self._subscriber_put_timeout_sec(),
            ),
            start_event=asyncio.Event() if wait_for_start else None,
        )
        async with self._lock:
            self.jobs[job_id] = job
        job.task = asyncio.create_task(self._run(job, runner), name=f"video-creation-{job_id}")
        return job

    async def _run(self, job: VideoCreationJob, runner: VideoJobRunner) -> None:
        if job.start_event is not None:
            job.status = "waiting_publisher"
            job.updated_at = time.time()
            await job.start_event.wait()
        job.status = "generating"
        job.updated_at = time.time()
        sink = VideoJobChunkSink(job)
        try:
            result = await runner(sink)
            job.result = result
            job.finalized_at = time.time()
            job.status = "completed"
            job.updated_at = job.finalized_at
            # A well-behaved service closes its sink only after muxing and
            # registering the final MP4. Keep this guard for runner
            # implementations that fail to do so, but never expose a
            # duplicate secret-bearing object.
            if not job.hub.closed:
                await sink.finish()
        except asyncio.CancelledError:
            job.status = "stopped"
            job.error_code = "stopped"
            job.updated_at = time.time()
            if not job.hub.closed:
                await job.hub.fail("stopped")
            raise
        except Exception as exc:  # noqa: BLE001
            job.status = "failed"
            job.error_code = job.error_code or type(exc).__name__
            job.error_detail = "video creation failed"
            job.updated_at = time.time()
            if not job.hub.closed:
                await job.hub.fail(job.error_code, job.error_detail)

    async def start(self, job_id: str) -> VideoCreationJob:
        """Release a publish-gated job after its subscriber is ready."""

        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.start_event is not None:
            job.start_event.set()
        return job

    def get(self, job_id: str) -> VideoCreationJob | None:
        return self.jobs.get(job_id)

    async def stop(self, job_id: str) -> VideoCreationJob:
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.task is not None and not job.task.done():
            job.task.cancel()
            try:
                await job.task
            except asyncio.CancelledError:
                pass
        elif job.status not in {"completed", "failed", "stopped"}:
            job.status = "stopped"
        return job

    async def delete(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.task is not None and not job.task.done():
            await self.stop(job_id)
        async with self._lock:
            self.jobs.pop(job_id, None)

    async def close(self) -> None:
        jobs = tuple(self.jobs)
        for job_id in jobs:
            job = self.jobs.get(job_id)
            if job is not None and job.task is not None and not job.task.done():
                await self.stop(job_id)
