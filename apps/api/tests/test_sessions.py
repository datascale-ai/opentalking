from __future__ import annotations

import asyncio
import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import numpy as np
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

import apps.api.main as api_main
import apps.api.routes.health as health_routes
import apps.api.routes.sessions as sessions_routes
import apps.unified.main as unified_main
import opentalking.worker.task_consumer as task_consumer
from opentalking.core.in_memory_redis import InMemoryRedis
from opentalking.core.redis_keys import FLASHTALK_QUEUE_STATUS
from opentalking.core.session_store import set_session_state
from opentalking.worker.flashtalk_recording import (
    append_flashtalk_av_chunk,
    append_flashtalk_frames,
    export_flashtalk_recording,
)
from opentalking.worker.flashtalk_runner import FlashTalkRunner


def _media_stream_types(path: Path) -> set[str]:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "json",
            str(path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    data = json.loads(proc.stdout.decode("utf-8"))
    return {str(stream.get("codec_type")) for stream in data.get("streams", [])}


def test_normalize_voice_for_speak_accepts_elevenlabs_voice_id() -> None:
    voice, provider, model = sessions_routes._normalize_voice_for_speak(
        voice="eleven-voice-id",
        tts_provider="elevenlabs",
        tts_model=None,
    )

    assert voice == "eleven-voice-id"
    assert provider == "elevenlabs"
    assert model is None


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


@pytest.mark.parametrize("tts_provider", ["dashscope", "cosyvoice", "sambert"])
def test_create_session_accepts_bailian_tts_providers(
    unified_client: TestClient,
    tts_provider: str,
) -> None:
    response = unified_client.post(
        "/sessions",
        json={
            "avatar_id": "demo-avatar",
            "model": "wav2lip",
            "tts_provider": tts_provider,
        },
    )

    assert response.status_code == 200


def test_queue_status_reads_shared_redis_state() -> None:
    redis = InMemoryRedis()
    asyncio.run(
        redis.hset(
            FLASHTALK_QUEUE_STATUS,
            mapping={"slot_occupied": "1", "queue_size": "2"},
        )
    )

    app = FastAPI()
    app.state.redis = redis
    app.include_router(health_routes.router)

    with TestClient(app) as client:
        response = client.get("/queue/status")

    assert response.status_code == 200
    assert response.json() == {"slot_occupied": True, "queue_size": 2}


def test_split_flashtalk_create_returns_queued_until_worker_ready(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    avatar_id = "flashtalk-demo"
    (tmp_path / avatar_id).mkdir()

    async def never_ready(*_args: object, **_kwargs: object) -> bool:
        return False

    monkeypatch.setattr(sessions_routes, "_wait_for_session_worker_ready", never_ready)
    monkeypatch.setattr(
        sessions_routes,
        "load_avatar_bundle",
        lambda *_args, **_kwargs: SimpleNamespace(manifest=SimpleNamespace(model_type="flashtalk")),
    )

    app = FastAPI()
    app.state.redis = InMemoryRedis()
    app.state.settings = SimpleNamespace(
        avatars_dir=str(tmp_path),
        normalized_flashtalk_mode="remote",
    )
    app.include_router(sessions_routes.router)

    with TestClient(app) as client:
        response = client.post(
            "/sessions",
            json={"avatar_id": avatar_id, "model": "flashtalk"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "queued"


def test_split_flashtalk_create_returns_created_when_worker_ready(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    avatar_id = "flashtalk-demo"
    sid = "sess_worker_ready"
    (tmp_path / avatar_id).mkdir()

    monkeypatch.setattr(
        sessions_routes,
        "load_avatar_bundle",
        lambda *_args, **_kwargs: SimpleNamespace(manifest=SimpleNamespace(model_type="flashtalk")),
    )

    async def fake_create_session(*_args: object, **_kwargs: object) -> str:
        await set_session_state(redis, sid, "worker_ready")
        return sid

    monkeypatch.setattr(sessions_routes.session_service, "create_session", fake_create_session)

    app = FastAPI()
    redis = InMemoryRedis()
    app.state.redis = redis
    app.state.settings = SimpleNamespace(
        avatars_dir=str(tmp_path),
        normalized_flashtalk_mode="remote",
    )
    app.include_router(sessions_routes.router)

    with TestClient(app) as client:
        response = client.post(
            "/sessions",
            json={"avatar_id": avatar_id, "model": "flashtalk"},
        )

    assert response.status_code == 200
    assert response.json() == {"session_id": sid, "status": "created"}


def test_customize_prompt_rejects_avatar_path_traversal(tmp_path: Path) -> None:
    avatars_root = tmp_path / "avatars"
    avatars_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    app = FastAPI()
    app.state.redis = InMemoryRedis()
    app.state.settings = SimpleNamespace(avatars_dir=str(avatars_root))
    app.include_router(sessions_routes.router)

    with TestClient(app) as client:
        response = client.post(
            "/sessions/customize/prompt",
            json={"avatar_id": "../outside", "llm_system_prompt": "x"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid avatar_id"


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


def test_download_flashtalk_recording_returns_file(
    unified_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OPENTALKING_FLASHTALK_RECORDINGS_DIR", str(tmp_path))
    create_response = unified_client.post(
        "/sessions",
        json={"avatar_id": "demo-avatar", "model": "wav2lip"},
    )
    session_id = create_response.json()["session_id"]
    append_flashtalk_frames(
        session_id,
        [np.full((12, 16, 3), 64, dtype=np.uint8)],
        start_index=0,
        fps=25.0,
    )

    response = unified_client.get(f"/sessions/{session_id}/flashtalk-recording")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("video/mp4")
    assert len(response.content) > 0


def test_api_mode_proxies_flashtalk_recording_from_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "sess_proxy_test"
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        assert request.method == "GET"
        assert request.url.path == f"/sessions/{session_id}/flashtalk-recording"
        return httpx.Response(
            200,
            content=b"fake-mp4",
            headers={"content-type": "video/mp4"},
        )

    transport = httpx.MockTransport(handler)

    class PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args: object, **kwargs: object) -> None:  # noqa: ANN401
            kwargs["transport"] = transport
            kwargs["base_url"] = "http://worker.test"
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(sessions_routes.httpx, "AsyncClient", PatchedAsyncClient)

    async def fake_get_session(_r, _sid: str) -> dict[str, str]:
        return {"session_id": session_id, "state": "ready"}

    monkeypatch.setattr("apps.api.services.session_service.get_session", fake_get_session)

    def boom_export(_sid: str) -> Path:
        raise FileNotFoundError("no local frames")

    monkeypatch.setattr(sessions_routes, "export_flashtalk_recording", boom_export)

    with TestClient(api_main.create_app()) as client:
        client.app.state.settings.worker_url = "http://worker.test"  # type: ignore[attr-defined]
        response = client.get(f"/sessions/{session_id}/flashtalk-recording")

    assert response.status_code == 200
    assert response.content == b"fake-mp4"
    assert len(captured) == 1


def test_api_mode_worker_recording_404_is_returned_before_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "sess_proxy_404"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/sessions/{session_id}/flashtalk-recording"
        return httpx.Response(404, content=b"missing")

    transport = httpx.MockTransport(handler)

    class PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args: object, **kwargs: object) -> None:  # noqa: ANN401
            kwargs["transport"] = transport
            kwargs["base_url"] = "http://worker.test"
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(sessions_routes.httpx, "AsyncClient", PatchedAsyncClient)

    async def fake_get_session(_r, _sid: str) -> dict[str, str]:
        return {"session_id": session_id, "state": "ready"}

    monkeypatch.setattr("apps.api.services.session_service.get_session", fake_get_session)

    def boom_export(_sid: str) -> Path:
        raise FileNotFoundError("no local frames")

    monkeypatch.setattr(sessions_routes, "export_flashtalk_recording", boom_export)

    with TestClient(api_main.create_app()) as client:
        client.app.state.settings.worker_url = "http://worker.test"  # type: ignore[attr-defined]
        response = client.get(f"/sessions/{session_id}/flashtalk-recording")

    assert response.status_code == 404
    assert response.json()["detail"] == "recording not ready"


def test_worker_flashtalk_recording_endpoint_exports_mp4(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OPENTALKING_FLASHTALK_RECORDINGS_DIR", str(tmp_path))
    from opentalking.worker.server import create_app as create_worker_app

    session_id = "sess_worker_dl"
    append_flashtalk_av_chunk(
        session_id,
        [np.full((10, 12, 3), 32 + i, dtype=np.uint8) for i in range(5)],
        np.linspace(-12000, 12000, 3200, dtype=np.int16),
        start_index=0,
        fps=25.0,
    )

    with TestClient(create_worker_app()) as client:
        response = client.get(f"/sessions/{session_id}/flashtalk-recording")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("video/mp4")
    assert len(response.content) > 0
    saved = tmp_path / session_id / "flashtalk_capture.mp4"
    assert _media_stream_types(saved) == {"video", "audio"}


def test_flashtalk_runner_appends_recording_frames_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OPENTALKING_FLASHTALK_RECORDINGS_DIR", str(tmp_path))

    async def run() -> None:
        redis = InMemoryRedis()
        session_id = "sess_runner_recording"
        await redis.hset(
            f"opentalking:session:{session_id}",
            mapping={"session_id": session_id, "model": "flashtalk"},
        )
        await sessions_routes.apply_flashtalk_recording_start(redis, session_id)

        runner = object.__new__(FlashTalkRunner)
        runner.session_id = session_id
        runner.redis = redis
        runner.flashtalk = SimpleNamespace(fps=25.0)
        runner._recording_epoch = 0
        runner._recording_frame_idx = 0

        frame = SimpleNamespace(data=np.full((10, 12, 3), 96, dtype=np.uint8))
        pcm = np.linspace(-8000, 8000, 1600, dtype=np.int16)
        await runner._record_flashtalk_av_chunk([frame, frame], pcm)
        await sessions_routes.apply_flashtalk_recording_stop(redis, session_id)

        path = export_flashtalk_recording(session_id)
        assert path.is_file()
        assert path.stat().st_size > 0
        assert _media_stream_types(path) == {"video", "audio"}

    asyncio.run(run())


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
