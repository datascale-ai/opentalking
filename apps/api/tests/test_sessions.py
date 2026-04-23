from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import apps.unified.main as unified_main
import opentalking.worker.task_consumer as task_consumer
from opentalking.core.session_store import set_session_state


class FakeRunner:
    def __init__(self, *, session_id: str, redis) -> None:
        self.session_id = session_id
        self.redis = redis
        self.ready_event = asyncio.Event()
        self.speech_tasks: set[asyncio.Task[None]] = set()
        self._speak_lock = asyncio.Lock()
        self._closed = False
        self.started_texts: list[str] = []
        self.finished_texts: list[str] = []
        self.cancelled_texts: list[str] = []
        self.speaking_started = asyncio.Event()
        self.allow_finish = asyncio.Event()

    async def prepare(self) -> None:
        self.ready_event.set()

    async def handle_webrtc_offer(self, sdp: str, type_: str) -> dict[str, str]:
        await self.ready_event.wait()
        return {"sdp": sdp, "type": type_}

    def create_speak_task(
        self,
        text: str,
        tts_voice: str | None = None,
        **kwargs: object,
    ) -> asyncio.Task[None]:
        task = asyncio.create_task(self._run_speak_task(text, tts_voice))
        self.speech_tasks.add(task)
        task.add_done_callback(self.speech_tasks.discard)
        return task

    async def _run_speak_task(self, text: str, tts_voice: str | None = None) -> None:
        try:
            async with self._speak_lock:
                if self._closed:
                    return
                self.started_texts.append(text)
                self.speaking_started.set()
                await set_session_state(self.redis, self.session_id, "speaking")
                await self.allow_finish.wait()
                self.finished_texts.append(text)
                if not self._closed:
                    await set_session_state(self.redis, self.session_id, "ready")
        except asyncio.CancelledError:
            self.cancelled_texts.append(text)
            raise

    async def interrupt(self) -> None:
        tasks = [task for task in self.speech_tasks if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if not self._closed:
            await set_session_state(self.redis, self.session_id, "ready")

    async def close(self) -> None:
        self._closed = True
        await self.interrupt()
        await set_session_state(self.redis, self.session_id, "closed")


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met before timeout")


@pytest.fixture
def unified_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    created_runners: dict[str, FakeRunner] = {}

    def fake_create_runner(task, redis, avatars_root: Path, device: str) -> FakeRunner:
        runner = FakeRunner(session_id=str(task["session_id"]), redis=redis)
        created_runners[runner.session_id] = runner
        return runner

    monkeypatch.setattr(task_consumer, "_create_runner", fake_create_runner)
    with TestClient(unified_main.create_app()) as client:
        client.created_runners = created_runners  # type: ignore[attr-defined]
        yield client


def test_create_session_rejects_avatar_model_mismatch() -> None:
    with TestClient(unified_main.create_app()) as client:
        response = client.post(
            "/sessions",
            json={"avatar_id": "demo-avatar", "model": "musetalk"},
        )

    assert response.status_code == 400
    assert "requires model" in response.json()["detail"]


def test_delete_session_closes_runner_and_marks_closed(unified_client: TestClient) -> None:
    create_response = unified_client.post(
        "/sessions",
        json={"avatar_id": "demo-avatar", "model": "wav2lip"},
    )
    session_id = create_response.json()["session_id"]

    response = unified_client.delete(f"/sessions/{session_id}")
    assert response.status_code == 200

    _wait_until(lambda: unified_client.get(f"/sessions/{session_id}").json()["state"] == "closed")
    runner = unified_client.created_runners[session_id]  # type: ignore[attr-defined]
    assert runner._closed is True


def test_interrupt_cancels_active_speech_and_restores_ready(unified_client: TestClient) -> None:
    create_response = unified_client.post(
        "/sessions",
        json={"avatar_id": "demo-avatar", "model": "wav2lip"},
    )
    session_id = create_response.json()["session_id"]
    runner = unified_client.created_runners[session_id]  # type: ignore[attr-defined]

    speak_response = unified_client.post(f"/sessions/{session_id}/speak", json={"text": "hello"})
    assert speak_response.status_code == 200

    _wait_until(lambda: runner.speaking_started.is_set())

    interrupt_response = unified_client.post(f"/sessions/{session_id}/interrupt")
    assert interrupt_response.status_code == 200

    _wait_until(lambda: "hello" in runner.cancelled_texts)
    _wait_until(lambda: unified_client.get(f"/sessions/{session_id}").json()["state"] == "ready")


def test_close_cancels_running_and_queued_speech_tasks(unified_client: TestClient) -> None:
    create_response = unified_client.post(
        "/sessions",
        json={"avatar_id": "demo-avatar", "model": "wav2lip"},
    )
    session_id = create_response.json()["session_id"]
    runner = unified_client.created_runners[session_id]  # type: ignore[attr-defined]

    unified_client.post(f"/sessions/{session_id}/speak", json={"text": "first"})
    unified_client.post(f"/sessions/{session_id}/speak", json={"text": "second"})
    _wait_until(lambda: runner.speaking_started.is_set())

    close_response = unified_client.delete(f"/sessions/{session_id}")
    assert close_response.status_code == 200

    _wait_until(lambda: set(runner.cancelled_texts) == {"first", "second"})
    _wait_until(lambda: unified_client.get(f"/sessions/{session_id}").json()["state"] == "closed")
