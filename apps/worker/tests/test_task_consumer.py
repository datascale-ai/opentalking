from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

import pytest

from apps.api.services import session_service
from opentalking.core.in_memory_redis import InMemoryRedis
from opentalking.core.redis_keys import TASK_QUEUE
from opentalking.core.session_store import get_session_record, session_key
import opentalking.worker.task_consumer as task_consumer
from opentalking.worker.session_runner import SessionRunner
from opentalking.worker.task_consumer import handle_worker_task


class StubRunner:
    def __init__(self) -> None:
        self.prepared = False
        self.interrupted = False
        self.closed = False
        self.spoken: list[str] = []
        self.ready_event = asyncio.Event()
        self.speech_tasks: set[asyncio.Task[None]] = set()

    async def prepare(self) -> None:
        self.prepared = True
        self.ready_event.set()

    def create_speak_task(
        self,
        text: str,
        tts_voice: str | None = None,
        **kwargs: object,
    ) -> asyncio.Task[None]:
        async def _speak() -> None:
            self.spoken.append(text)

        task = asyncio.create_task(_speak())
        self.speech_tasks.add(task)
        task.add_done_callback(self.speech_tasks.discard)
        return task

    async def interrupt(self) -> None:
        self.interrupted = True

    async def close(self) -> None:
        self.closed = True


class UploadedPcmRunner(StubRunner):
    def __init__(self) -> None:
        super().__init__()
        self.uploaded_pcm: list[bytes] = []

    def create_speak_uploaded_pcm_task(
        self,
        pcm_path: str,
        *,
        enqueue_unix: float | None = None,
    ) -> asyncio.Task[None]:
        _ = enqueue_unix
        self.uploaded_pcm.append(Path(pcm_path).read_bytes())

        async def _noop() -> None:
            return None

        task = asyncio.create_task(_noop())
        self.speech_tasks.add(task)
        task.add_done_callback(self.speech_tasks.discard)
        return task


def test_session_runner_create_speak_task_accepts_tts_overrides() -> None:
    runner = object.__new__(SessionRunner)
    runner.speech_tasks = set()
    captured: dict[str, object] = {}

    async def fake_run_speak_task(
        text: str,
        tts_voice: str | None = None,
        tts_provider: str | None = None,
        tts_model: str | None = None,
        enqueue_unix: float | None = None,
    ) -> None:
        captured.update(
            {
                "text": text,
                "tts_voice": tts_voice,
                "tts_provider": tts_provider,
                "tts_model": tts_model,
                "enqueue_unix": enqueue_unix,
            }
        )

    runner._run_speak_task = fake_run_speak_task  # type: ignore[method-assign]

    async def run() -> None:
        task = runner.create_speak_task(
            "hello",
            tts_voice="Cherry",
            tts_provider="dashscope",
            tts_model="qwen3-tts-flash-realtime",
            enqueue_unix=123.0,
        )
        await task

    asyncio.run(run())

    assert captured == {
        "text": "hello",
        "tts_voice": "Cherry",
        "tts_provider": "dashscope",
        "tts_model": "qwen3-tts-flash-realtime",
        "enqueue_unix": 123.0,
    }


def test_speak_flashtalk_uploaded_pcm_queues_redis_pcm_key() -> None:
    async def run() -> None:
        redis = InMemoryRedis()
        sid = "sess_pcm_service"
        pcm = b"\x01\x00\x02\x00"

        await session_service.speak_flashtalk_uploaded_pcm(redis, sid, pcm)

        # interrupt task is queued first, then the actual uploaded-audio task.
        await redis.brpop(TASK_QUEUE, timeout=1)
        res = await redis.brpop(TASK_QUEUE, timeout=1)
        assert res is not None
        _, raw = res
        task = json.loads(raw)
        assert task["cmd"] == "speak_flashtalk_audio"
        assert "pcm_path" not in task
        pcm_key = task["pcm_key"]
        stored = await redis.get(pcm_key)
        assert stored is not None
        assert base64.b64decode(stored) == pcm

    asyncio.run(run())


def test_handle_worker_task_reads_uploaded_pcm_from_redis_key() -> None:
    async def run() -> None:
        sid = "sess_pcm_key"
        pcm = b"\x03\x00\x04\x00"
        redis = InMemoryRedis()
        pcm_key = f"test-pcm:{sid}"
        await redis.set(pcm_key, base64.b64encode(pcm).decode("ascii"), ex=60)
        await redis.hset(session_key(sid), mapping={"session_id": sid, "state": "ready", "model": "flashtalk"})
        runner = UploadedPcmRunner()
        await runner.prepare()

        await handle_worker_task(
            {
                "cmd": "speak_flashtalk_audio",
                "session_id": sid,
                "pcm_key": pcm_key,
                "enqueue_unix": 1.0,
            },
            redis,
            Path("."),
            "cpu",
            {sid: runner},
        )
        await asyncio.sleep(0)

        assert runner.uploaded_pcm == [pcm]
        assert await redis.get(pcm_key) is None

    asyncio.run(run())


@pytest.mark.asyncio
async def test_handle_worker_task_tracks_runner_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = StubRunner()

    def fake_create_runner(*_args, **_kwargs) -> StubRunner:
        return runner

    monkeypatch.setattr("opentalking.worker.task_consumer._create_runner", fake_create_runner)

    redis = InMemoryRedis()
    sid = "sess_test"
    await redis.hset(session_key(sid), mapping={"session_id": sid, "state": "created"})
    runners: dict[str, StubRunner] = {}

    await handle_worker_task(
        {"cmd": "init", "session_id": sid, "avatar_id": "demo-avatar", "model": "wav2lip"},
        redis,
        Path("."),
        "cpu",
        runners,
    )
    assert runner.prepared is True
    rec = await get_session_record(redis, sid)
    assert rec is not None
    assert rec["state"] == "worker_ready"

    await handle_worker_task({"cmd": "speak", "session_id": sid, "text": "hello"}, redis, Path("."), "cpu", runners)
    await asyncio.sleep(0)
    assert runner.spoken == ["hello"]

    await handle_worker_task({"cmd": "interrupt", "session_id": sid}, redis, Path("."), "cpu", runners)
    assert runner.interrupted is True

    await handle_worker_task({"cmd": "close", "session_id": sid}, redis, Path("."), "cpu", runners)
    assert runner.closed is True
    assert sid not in runners
    assert await get_session_record(redis, sid) is not None


@pytest.mark.asyncio
async def test_handle_worker_task_flashtalk_init_marks_worker_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = StubRunner()

    def fake_create_runner(*_args, **_kwargs) -> StubRunner:
        return runner

    monkeypatch.setattr(task_consumer, "_create_runner", fake_create_runner)
    monkeypatch.setattr(task_consumer, "_flashtalk_slot_lock", None)
    monkeypatch.setattr(task_consumer, "_slot_queue_size", 0)
    monkeypatch.setattr(task_consumer, "_queued_tasks", {})

    redis = InMemoryRedis()
    sid = "sess_flashtalk_ready"
    await redis.hset(session_key(sid), mapping={"session_id": sid, "state": "created", "model": "flashtalk"})
    runners: dict[str, StubRunner] = {}

    await handle_worker_task(
        {"cmd": "init", "session_id": sid, "avatar_id": "demo-avatar", "model": "flashtalk"},
        redis,
        Path("."),
        "cpu",
        runners,
    )

    for _ in range(100):
        rec = await get_session_record(redis, sid)
        if rec is not None and rec.get("state") == "worker_ready":
            break
        await asyncio.sleep(0.01)
    else:
        raise AssertionError("FlashTalk init did not publish worker_ready")

    assert runner.prepared is True
    assert runners[sid] is runner

    await handle_worker_task({"cmd": "close", "session_id": sid}, redis, Path("."), "cpu", runners)
    await asyncio.sleep(0.6)
