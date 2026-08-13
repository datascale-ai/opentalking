from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from opentalking.streaming.chunks import ChunkHub, ChunkQueue, MediaChunk
from opentalking.streaming.destinations.rtmps import RTMPSSettings
from opentalking.streaming.destinations.rtmps_chunked import ChunkedRTMPSPublisher
from opentalking.streaming import rtmps_jobs as rtmps_jobs_module
from opentalking.streaming.rtmps_jobs import ChunkedRTMPSJob, ChunkedRTMPSJobManager
from opentalking.video_creation_jobs import VideoCreationJob, VideoCreationJobManager


class _FinishedPublisher:
    def __init__(self, state: str) -> None:
        self.state = state

    async def wait(self) -> None:
        return


class _ExplodingPublisher(_FinishedPublisher):
    async def wait(self) -> None:
        raise RuntimeError("secret-bearing transport detail")


def _media_chunk(sequence: int) -> MediaChunk:
    return MediaChunk(
        sequence=sequence,
        start_pts_ms=float(sequence * 1000),
        end_pts_ms=float((sequence + 1) * 1000),
        video=(object(),),
        starts_with_keyframe=sequence == 0,
    )


class _BlockingPublisher:
    instances: list["_BlockingPublisher"] = []

    def __init__(self, settings: RTMPSSettings, *, replay_chunks: int = 8) -> None:
        self.settings = settings
        self.replay_chunks = replay_chunks
        self.state = "created"
        self.health = "unknown"
        self.last_error = None
        self.error_code = None
        self.sent_video = 0
        self.sent_audio = 0
        self.bytes_sent = 0
        self.dropped_chunks = 0
        self.last_sent_pts_ms = 0.0
        self.first_media_at = None
        self.finalized_at = None
        self.queue_depth = 0
        self.buffer_duration_ms = 0.0
        self.blocked_ms = 0.0
        self._done = asyncio.Event()
        self.__class__.instances.append(self)

    async def start(self, queue: ChunkQueue) -> None:
        self.queue = queue
        self.state = "publishing"
        self.health = "healthy"

    async def wait(self) -> None:
        await self._done.wait()

    async def stop(self) -> None:
        self.state = "stopped"
        self.health = "degraded"
        self._done.set()


class _StartFailingPublisher(_BlockingPublisher):
    async def start(self, queue: ChunkQueue) -> None:
        self.queue = queue
        raise OSError("transport failed")


class _ReconnectStartFailingPublisher(_BlockingPublisher):
    starts = 0

    async def start(self, queue: ChunkQueue) -> None:
        type(self).starts += 1
        if type(self).starts == 2:
            self.queue = queue
            raise OSError("reconnect transport failed")
        await super().start(queue)


def _job_manager_fixture() -> tuple[ChunkedRTMPSJobManager, VideoCreationJob]:
    settings = SimpleNamespace(
        streaming_allow_local_targets=True,
        streaming_allowed_hosts="",
        streaming_allowed_cidrs="",
        streaming_rtmps_tls_verify=True,
        video_creation_chunk_queue_max_chunks=2,
        streaming_reconnect_max_attempts=1,
        streaming_reconnect_max_delay_sec=0,
    )
    video_jobs = VideoCreationJobManager(settings)
    source = VideoCreationJob(
        job_id="job_source",
        source="tts_text",
        metadata={},
        hub=ChunkHub(max_chunks=2, replay_chunks=2),
        status="generating",
    )
    video_jobs.jobs[source.job_id] = source
    return ChunkedRTMPSJobManager(settings, video_jobs), source


def _create_body(source_id: str = "job_source") -> dict[str, object]:
    return {
        "source": {"type": "video_creation_job", "job_id": source_id},
        "transport": {
            "endpoint": "rtmp://127.0.0.1:1936/live",
            "stream_key": "same-target",
            "username": "publisher",
            "password": "secret-only-in-memory",
        },
    }


def test_rtmps_public_status_never_contains_transport_password() -> None:
    source = VideoCreationJob(
        job_id="job_source",
        source="tts_text",
        metadata={},
        hub=ChunkHub(max_chunks=2, replay_chunks=2),
    )
    secret = "do-not-return-this-password"
    publisher = ChunkedRTMPSPublisher(
        RTMPSSettings(
            endpoint="rtmps://example.test/live",
            stream_key="offline-video",
            username="publisher",
            password=secret,
        )
    )
    job = ChunkedRTMPSJob(
        rtmps_job_id="rtjob_test",
        video_creation_job_id=source.job_id,
        publisher=publisher,
        queue=ChunkQueue(max_chunks=2),
        source_hub=source.hub,
    )

    payload = job.public(source)

    assert secret not in repr(payload)
    assert "password" not in payload
    assert payload["secret_configured"] is True


def test_rtmps_watcher_converts_unexpected_publisher_exception_to_failed() -> None:
    async def run() -> None:
        video_jobs = VideoCreationJobManager(SimpleNamespace(video_creation_chunk_queue_max_chunks=2))
        source = VideoCreationJob(
            job_id="job_source",
            source="tts_text",
            metadata={},
            hub=ChunkHub(max_chunks=2, replay_chunks=2),
        )
        queue = await source.hub.subscribe()
        publisher = _ExplodingPublisher("publishing")
        rtmps_job = ChunkedRTMPSJob(
            rtmps_job_id="rtjob_test",
            video_creation_job_id=source.job_id,
            publisher=publisher,  # type: ignore[arg-type]
            queue=queue,
            source_hub=source.hub,
        )
        manager = ChunkedRTMPSJobManager(SimpleNamespace(), video_jobs)
        video_jobs.jobs[source.job_id] = source

        await manager._watch(rtmps_job)

        assert rtmps_job.status == "failed"
        assert publisher.error_code == "RuntimeError"
        assert publisher.last_error == "RuntimeError"
        assert source.hub.subscriber_count == 0

    asyncio.run(run())


def test_publisher_failure_unblocks_video_producer() -> None:
    async def run() -> None:
        video_jobs = VideoCreationJobManager(SimpleNamespace(video_creation_chunk_queue_max_chunks=1))
        source = VideoCreationJob(
            job_id="job_source",
            source="tts_text",
            metadata={},
            hub=ChunkHub(max_chunks=1, replay_chunks=1),
        )
        queue = await source.hub.subscribe()
        await queue.put(_media_chunk(0))
        publisher = _ExplodingPublisher("publishing")
        rtmps_job = ChunkedRTMPSJob(
            rtmps_job_id="rtjob_test",
            video_creation_job_id=source.job_id,
            publisher=publisher,  # type: ignore[arg-type]
            queue=queue,
            source_hub=source.hub,
        )
        manager = ChunkedRTMPSJobManager(SimpleNamespace(), video_jobs)
        video_jobs.jobs[source.job_id] = source

        blocked_publish = asyncio.create_task(source.hub.publish(_media_chunk(1)))
        await asyncio.sleep(0)
        await asyncio.wait_for(manager._watch(rtmps_job), timeout=0.1)
        await asyncio.wait_for(blocked_publish, timeout=0.1)

        assert rtmps_job.status == "failed"
        assert source.hub.subscriber_count == 0

    asyncio.run(run())


@pytest.mark.parametrize("publisher_state", ["failed", "stopped"])
def test_rtmps_watcher_unsubscribes_after_publisher_finishes(publisher_state: str) -> None:
    async def run() -> None:
        video_jobs = VideoCreationJobManager(SimpleNamespace(video_creation_chunk_queue_max_chunks=2))
        source = VideoCreationJob(
            job_id="job_source",
            source="tts_text",
            metadata={},
            hub=ChunkHub(max_chunks=2, replay_chunks=2),
        )
        queue = await source.hub.subscribe()
        publisher = _FinishedPublisher(publisher_state)
        rtmps_job = ChunkedRTMPSJob(
            rtmps_job_id="rtjob_test",
            video_creation_job_id=source.job_id,
            publisher=publisher,  # type: ignore[arg-type]
            queue=queue,
            source_hub=source.hub,
        )
        manager = ChunkedRTMPSJobManager(SimpleNamespace(), video_jobs)
        video_jobs.jobs[source.job_id] = source

        await manager._watch(rtmps_job)

        assert source.hub.subscriber_count == 0
        assert rtmps_job.status == publisher_state
        assert queue.closed

    asyncio.run(run())


def test_manager_rejects_target_conflict_and_releases_after_stop(monkeypatch) -> None:
    async def run() -> None:
        manager, source = _job_manager_fixture()
        _BlockingPublisher.instances.clear()
        monkeypatch.setattr(rtmps_jobs_module, "ChunkedRTMPSPublisher", _BlockingPublisher)

        first = await manager.create(_create_body())
        with pytest.raises(rtmps_jobs_module.RTMPSTargetConflict):
            await manager.create(_create_body())

        await manager.stop(first.rtmps_job_id)
        assert source.hub.subscriber_count == 0
        assert manager._target_owners == {}

        second = await manager.create(_create_body())
        await manager.stop(second.rtmps_job_id)
        assert manager._target_owners == {}

    asyncio.run(run())


def test_manager_start_failure_releases_target_and_subscription(monkeypatch) -> None:
    async def run() -> None:
        manager, source = _job_manager_fixture()
        monkeypatch.setattr(rtmps_jobs_module, "ChunkedRTMPSPublisher", _StartFailingPublisher)

        with pytest.raises(OSError):
            await manager.create(_create_body())

        assert manager.jobs == {}
        assert manager._target_owners == {}
        assert source.hub.subscriber_count == 0

    asyncio.run(run())


def test_publish_gated_source_starts_only_after_rtmps_subscription(monkeypatch) -> None:
    async def run() -> None:
        settings = SimpleNamespace(
            streaming_allow_local_targets=True,
            streaming_allowed_hosts="",
            streaming_allowed_cidrs="",
            streaming_rtmps_tls_verify=True,
            video_creation_chunk_queue_max_chunks=2,
            streaming_reconnect_max_attempts=1,
            streaming_reconnect_max_delay_sec=0,
        )
        video_jobs = VideoCreationJobManager(settings)
        started = asyncio.Event()
        runner_started = False

        async def runner(sink) -> dict[str, object]:
            nonlocal runner_started
            runner_started = True
            started.set()
            await sink.publish(_media_chunk(0))
            await sink.finish()
            return {}

        source = await video_jobs.submit(
            source="tts_text",
            metadata={},
            runner=runner,
            wait_for_start=True,
        )
        await asyncio.sleep(0)
        assert source.status == "waiting_publisher"
        assert not runner_started

        manager = ChunkedRTMPSJobManager(settings, video_jobs)
        monkeypatch.setattr(rtmps_jobs_module, "ChunkedRTMPSPublisher", _BlockingPublisher)
        job = await manager.create(_create_body(source.job_id))

        await asyncio.wait_for(started.wait(), timeout=0.1)
        await asyncio.wait_for(source.task, timeout=0.1)  # type: ignore[arg-type]
        assert source.first_sequence == 0
        assert source.first_pts_ms == 0.0

        await manager.stop(job.rtmps_job_id)

    asyncio.run(run())


def test_manager_reconnect_failure_releases_new_subscription_and_target(monkeypatch) -> None:
    async def run() -> None:
        manager, source = _job_manager_fixture()
        _ReconnectStartFailingPublisher.starts = 0
        monkeypatch.setattr(rtmps_jobs_module, "ChunkedRTMPSPublisher", _ReconnectStartFailingPublisher)

        job = await manager.create(_create_body())
        await manager.stop(job.rtmps_job_id)

        with pytest.raises(OSError):
            await manager.reconnect(job.rtmps_job_id)

        assert source.hub.subscriber_count == 0
        assert manager._target_owners == {}
        assert job.queue.closed

    asyncio.run(run())
