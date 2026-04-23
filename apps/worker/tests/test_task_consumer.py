from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from opentalking.core.in_memory_redis import InMemoryRedis
from opentalking.core.session_store import get_session_record, session_key
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

    await handle_worker_task({"cmd": "speak", "session_id": sid, "text": "hello"}, redis, Path("."), "cpu", runners)
    await asyncio.sleep(0)
    assert runner.spoken == ["hello"]

    await handle_worker_task({"cmd": "interrupt", "session_id": sid}, redis, Path("."), "cpu", runners)
    assert runner.interrupted is True

    await handle_worker_task({"cmd": "close", "session_id": sid}, redis, Path("."), "cpu", runners)
    assert runner.closed is True
    assert sid not in runners
    assert await get_session_record(redis, sid) is not None
