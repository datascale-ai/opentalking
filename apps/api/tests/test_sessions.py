from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import numpy as np
import httpx
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import apps.api.main as api_main
import apps.api.routes.health as health_routes
import apps.api.routes.sessions as sessions_routes
from apps.api.schemas.session import CreateSessionRequest
import apps.unified.main as unified_main
import opentalking.runtime.task_consumer as task_consumer
from opentalking.core.in_memory_redis import InMemoryRedis
from opentalking.core.model_config import clear_model_config_cache
from opentalking.core.redis_keys import FLASHTALK_QUEUE_STATUS
from opentalking.core.session_store import session_key, set_session_state
from opentalking.pipeline.recording.recording import append_flashtalk_frames


def test_normalize_voice_for_speak_accepts_elevenlabs_voice_id() -> None:
    voice, provider, model = sessions_routes._normalize_voice_for_speak(
        voice="eleven-voice-id",
        tts_provider="elevenlabs",
        tts_model=None,
    )

    assert voice == "eleven-voice-id"
    assert provider == "elevenlabs"
    assert model is None


@pytest.mark.parametrize("tts_provider", ["indextts", "local_indextts", "omnirt_indextts"])
def test_normalize_voice_for_speak_keeps_indextts_voice_ids(tts_provider: str) -> None:
    voice, provider, model = sessions_routes._normalize_voice_for_speak(
        voice="indextts-clear-cn",
        tts_provider=tts_provider,
        tts_model="IndexTeam/IndexTTS-2",
    )

    assert voice == "indextts-clear-cn"
    assert provider == tts_provider
    assert model == "IndexTeam/IndexTTS-2"


@pytest.mark.parametrize(
    "model",
    ["fasterliveportrait", "quicktalk", "musetalk", "wav2lip"],
)
def test_audio_renderer_models_are_flashtalk_compatible_for_audio_upload(model: str) -> None:
    assert sessions_routes._is_flashtalk_compatible_model(model) is True


@pytest.mark.parametrize("model", ["flashtalk", "flashhead"])
def test_only_flashtalk_slot_models_use_flashtalk_slot(model: str) -> None:
    assert sessions_routes._uses_flashtalk_slot_model(model) is True

@pytest.mark.parametrize("model", ["fasterliveportrait", "quicktalk", "musetalk", "wav2lip"])
def test_other_audio_renderers_do_not_use_flashtalk_slot(model: str) -> None:
    assert sessions_routes._uses_flashtalk_slot_model(model) is False


@pytest.mark.parametrize(
    "model",
    ["flashtalk", "flashhead", "fasterliveportrait", "quicktalk", "musetalk", "wav2lip"],
)
def test_audio_renderer_offline_bundle_enqueue_accepts_session(
    monkeypatch: pytest.MonkeyPatch,
    model: str,
) -> None:
    sid = f"sess_{model}_offline"
    pcm = np.array([1, -2, 3, -4], dtype=np.int16)

    async def fake_decode_audio_file_to_pcm_i16(_upload_path: Path) -> np.ndarray:
        return pcm

    queued: list[dict[str, str]] = []

    async def fake_enqueue(
        _redis: object,
        session_id: str,
        *,
        pcm_path: str,
        job_id: str,
    ) -> None:
        queued.append({"session_id": session_id, "pcm_path": pcm_path, "job_id": job_id})

    monkeypatch.setattr(sessions_routes, "decode_audio_file_to_pcm_i16", fake_decode_audio_file_to_pcm_i16)
    monkeypatch.setattr(
        sessions_routes.session_service,
        "enqueue_flashtalk_offline_bundle",
        fake_enqueue,
    )

    class FakeUpload:
        filename = "speech.wav"

        async def read(self) -> bytes:
            return b"fake-audio"

    async def run() -> dict[str, str]:
        redis = InMemoryRedis()
        await redis.hset(
            session_key(sid),
            mapping={
                "session_id": sid,
                "avatar_id": f"{model}-avatar",
                "model": model,
                "state": "worker_ready",
            },
        )
        app = FastAPI()
        app.state.redis = redis
        request = Request({"type": "http", "app": app})
        return await sessions_routes.flashtalk_offline_bundle_enqueue(sid, request, FakeUpload())  # type: ignore[arg-type]

    payload = asyncio.run(run())
    assert payload["session_id"] == sid
    assert payload["status"] == "queued"
    assert len(queued) == 1
    assert queued[0]["session_id"] == sid
    assert queued[0]["job_id"] == payload["job_id"]
    pcm_path = Path(queued[0]["pcm_path"])
    try:
        assert pcm_path.read_bytes() == pcm.tobytes()
    finally:
        pcm_path.unlink(missing_ok=True)


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
        self.fasterliveportrait_config_updates: list[dict[str, float]] = []
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

    async def update_fasterliveportrait_runtime_config(self, config: dict[str, float]) -> dict[str, object]:
        self.fasterliveportrait_config_updates.append(config)
        return {"type": "config_ok", "updated": config}

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
def unified_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    created_runners: dict[str, FakeRunner] = {}

    def fake_create_runner(task, redis, avatars_root: Path, device: str) -> FakeRunner:
        runner = FakeRunner(session_id=str(task["session_id"]), redis=redis)
        created_runners[runner.session_id] = runner
        return runner

    monkeypatch.setattr(task_consumer, "_create_runner", fake_create_runner)
    monkeypatch.delenv("OMNIRT_ENDPOINT", raising=False)
    monkeypatch.delenv("OPENTALKING_OMNIRT_ENDPOINT", raising=False)
    monkeypatch.delenv("OPENTALKING_CONFIG_FILE", raising=False)
    monkeypatch.delenv("CONFIG_FILE", raising=False)
    monkeypatch.chdir(tmp_path)
    avatars_dir = Path(__file__).resolve().parents[3] / "examples" / "avatars"
    monkeypatch.setenv("OPENTALKING_AVATARS_DIR", str(avatars_dir))
    monkeypatch.setenv("OPENTALKING_FLASHTALK_WS_URL", "ws://127.0.0.1:8765")
    monkeypatch.setenv("OPENTALKING_STT_DEFAULT_PROVIDER", "sensevoice")
    monkeypatch.setenv("OPENTALKING_STT_PREWARM_ON_STARTUP", "0")
    monkeypatch.setenv("OPENTALKING_TTS_DEFAULT_PROVIDER", "edge")
    unified_main.get_settings.cache_clear()
    try:
        with TestClient(unified_main.create_app()) as client:
            client.created_runners = created_runners  # type: ignore[attr-defined]
            yield client
    finally:
        unified_main.get_settings.cache_clear()


def test_create_session_avatar_model_decoupled_within_supported(
    monkeypatch: pytest.MonkeyPatch,
    unified_client: TestClient,
) -> None:
    """Avatar and model are decoupled — any (avatar, supported_model) is accepted.

    Runtime model availability lives in /models and the synthesis availability helper.
    """
    monkeypatch.setattr(task_consumer, "slot_is_occupied", lambda: True)
    pairs = [
        ("singer", "flashtalk"),  # wav2lip avatar + portrait-only model
        ("anime-handsome-guy", "flashtalk"),
        ("ancient-beauty", "flashtalk"),
        ("laozi", "flashtalk"),
        ("office-woman", "flashtalk"),
        ("anchor", "flashtalk"),
        ("anchor", "mock"),
        ("singer", "mock"),
        ("anime-handsome-guy", "mock"),
        ("ancient-beauty", "mock"),
        ("laozi", "mock"),
        ("office-woman", "mock"),
    ]
    for avatar_id, model in pairs:
        response = unified_client.post(
            "/sessions",
            json={"avatar_id": avatar_id, "model": model},
        )
        assert response.status_code != 400, (
            f"avatar={avatar_id} + model={model} returned 400: {response.json()}"
        )


def test_create_session_rejects_unconnected_model() -> None:
    """Picking a model not connected on this deployment yields 400 with a clear hint."""
    with TestClient(unified_main.create_app()) as client:
        for unsupported in ("musetalk",):
            response = client.post(
                "/sessions",
                json={"avatar_id": "anchor", "model": unsupported},
            )
            assert response.status_code == 400, response.json()
            detail = response.json()["detail"]
            assert unsupported in detail
            assert "not yet supported" in detail


def test_create_session_accepts_local_wav2lip_adapter(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_file = tmp_path / "opentalking.yaml"
    config_file.write_text(
        """
models:
  wav2lip:
    backend: local
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENTALKING_CONFIG_FILE", str(config_file))
    monkeypatch.setattr(
        "opentalking.models.wav2lip.adapter.Wav2LipAdapter.runtime_available",
        staticmethod(lambda: True),
    )

    def fake_create_runner(task, redis, avatars_root: Path, device: str) -> FakeRunner:
        del avatars_root, device
        return FakeRunner(session_id=str(task["session_id"]), redis=redis)

    monkeypatch.setattr(task_consumer, "_create_runner", fake_create_runner)
    clear_model_config_cache()

    with TestClient(unified_main.create_app()) as client:
        response = client.post(
            "/sessions",
            json={
                "avatar_id": "anchor",
                "model": "wav2lip",
                "stt_provider": "sensevoice",
                "tts_provider": "edge",
            },
        )

    assert response.status_code == 200, response.json()
    assert response.json()["status"] in {"created", "initializing"}
    clear_model_config_cache()


def test_chat_endpoint_removed_from_unified_sessions() -> None:
    route_paths = {
        getattr(route, "path", None)
        for route in sessions_routes.router.routes
    }

    assert "/sessions/{session_id}/chat" not in route_paths


def test_create_session_passes_fasterliveportrait_config_to_task(
    monkeypatch: pytest.MonkeyPatch,
    unified_client: TestClient,
) -> None:
    calls: list[dict[str, object]] = []

    async def fake_create_session(*_args: object, **kwargs: object) -> str:
        calls.append(kwargs)
        return "sess_fasterliveportrait_config"

    monkeypatch.setattr(sessions_routes.session_service, "create_session", fake_create_session)

    async def fake_connected_model_ids(_settings: object) -> set[str]:
        return {"fasterliveportrait"}

    monkeypatch.setattr(
        "opentalking.providers.synthesis.availability.connected_model_ids",
        fake_connected_model_ids,
    )
    monkeypatch.setattr(task_consumer, "slot_is_occupied", lambda: True)

    response = unified_client.post(
        "/sessions",
        json={
            "avatar_id": "singer",
            "model": "fasterliveportrait",
            "fasterliveportrait_config": {
                "mouth_open_multiplier": 1.8,
                "pose_motion_multiplier": 0.2,
                "yaw_multiplier": 0.7,
                "animation_region": "all",
                "flag_pasteback": True,
                "flag_lip_retargeting": False,
                "width": 999,
            },
        },
    )

    assert response.status_code == 200
    assert calls[0]["fasterliveportrait_config"] == {
        "mouth_open_multiplier": 1.8,
        "pose_motion_multiplier": 0.2,
        "yaw_multiplier": 0.7,
        "animation_region": "all",
        "flag_pasteback": True,
        "flag_lip_retargeting": False,
    }


@pytest.mark.parametrize(
    "model",
    ["flashtalk", "flashhead", "fasterliveportrait", "quicktalk", "musetalk", "wav2lip"],
)
def test_create_session_passes_agent_config_to_service_for_audio_renderer_models(
    monkeypatch: pytest.MonkeyPatch,
    model: str,
) -> None:
    calls: list[dict[str, object]] = []

    async def fake_create_session(*args: object, **kwargs: object) -> str:
        calls.append(kwargs)
        sid = f"sess_agent_config_{model}"
        redis = args[0]
        await redis.hset(
            session_key(sid),
            mapping={
                "session_id": sid,
                "avatar_id": kwargs["avatar_id"],
                "model": kwargs["model"],
                "state": "worker_ready",
            },
        )
        return sid

    monkeypatch.setattr(sessions_routes.session_service, "create_session", fake_create_session)

    async def fake_connected_model_ids(_settings: object) -> set[str]:
        return {model}

    monkeypatch.setattr(
        "opentalking.providers.synthesis.availability.connected_model_ids",
        fake_connected_model_ids,
    )

    avatars_dir = Path(__file__).resolve().parents[3] / "examples" / "avatars"
    app = FastAPI()
    app.state.redis = InMemoryRedis()
    app.state.settings = SimpleNamespace(
        avatars_dir=str(avatars_dir),
        normalized_stt_default_provider="sensevoice",
        normalized_stt_provider="sensevoice",
        normalized_tts_default_provider="edge",
        normalized_tts_provider="edge",
        omnirt_endpoint="",
    )
    request = Request({"type": "http", "app": app})

    response = asyncio.run(
        sessions_routes.create_session(
            CreateSessionRequest(
                avatar_id="singer",
                model=model,
                user_id="client_test",
                agent_enabled=True,
                memory_enabled=True,
                knowledge_enabled=True,
                knowledge_base_id="kb_agent",
            ),
            request,
        )
    )

    assert response.status == "created"
    assert calls[0]["model"] == model
    assert calls[0]["user_id"] == "client_test"
    assert calls[0]["agent_enabled"] is True
    assert calls[0]["memory_enabled"] is True
    assert calls[0]["knowledge_enabled"] is True
    assert calls[0]["knowledge_base_id"] == "kb_agent"


def test_create_session_passes_multiple_knowledge_bases_to_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    async def fake_create_session(*args: object, **kwargs: object) -> str:
        calls.append(kwargs)
        sid = "sess_multi_kb"
        redis = args[0]
        await redis.hset(
            session_key(sid),
            mapping={
                "session_id": sid,
                "avatar_id": kwargs["avatar_id"],
                "model": kwargs["model"],
                "state": "worker_ready",
            },
        )
        return sid

    monkeypatch.setattr(sessions_routes.session_service, "create_session", fake_create_session)
    monkeypatch.setattr(task_consumer, "slot_is_occupied", lambda: False)

    avatars_dir = Path(__file__).resolve().parents[3] / "examples" / "avatars"
    app = FastAPI()
    app.state.redis = InMemoryRedis()
    app.state.settings = SimpleNamespace(
        avatars_dir=str(avatars_dir),
        normalized_stt_default_provider="sensevoice",
        normalized_stt_provider="sensevoice",
        normalized_tts_default_provider="edge",
        normalized_tts_provider="edge",
        omnirt_endpoint="",
    )
    request = Request({"type": "http", "app": app})

    response = asyncio.run(
        sessions_routes.create_session(
            CreateSessionRequest(
                avatar_id="singer",
                model="mock",
                knowledge_base_ids=["kb_a", "kb_b"],
                knowledge_enabled=True,
            ),
            request,
        )
    )

    assert response.status == "created"
    assert calls[0]["knowledge_base_ids"] == ["kb_a", "kb_b"]
    assert calls[0]["knowledge_base_id"] == "kb_a"


def test_update_session_knowledge_bases_tracks_live_single_multi_and_cleared_selection() -> None:
    class RunnerWithAgentConfig:
        def __init__(self) -> None:
            self.agent_config = SimpleNamespace(
                user_id="client_test",
                agent_enabled=True,
                memory_enabled=False,
                knowledge_enabled=False,
                knowledge_base_id=None,
                knowledge_base_ids=[],
            )

    async def run() -> dict[str, object]:
        redis = InMemoryRedis()
        sid = "sess_live_kb"
        await redis.hset(
            session_key(sid),
            mapping={
                "session_id": sid,
                "avatar_id": "singer",
                "model": "mock",
                "state": "worker_ready",
                "agent_enabled": "1",
                "memory_enabled": "0",
                "knowledge_enabled": "0",
                "knowledge_base_id": "",
                "knowledge_base_ids": "[]",
            },
        )
        runner = RunnerWithAgentConfig()
        app = FastAPI()
        app.state.redis = redis
        app.state.session_runners = {sid: runner}
        request = Request({"type": "http", "app": app})

        observed: list[dict[str, object]] = []
        for selected in (
            ["kb_a"],
            ["kb_a", "kb_b", "kb_a"],
            ["kb_b"],
            [],
        ):
            response = await sessions_routes.update_session_knowledge_bases(
                sid,
                sessions_routes.SessionKnowledgeBasesRequest(knowledge_base_ids=selected),
                request,
            )
            observed.append(
                {
                    "response": response.model_dump(),
                    "record": await redis.hgetall(session_key(sid)),
                    "runner_knowledge_enabled": runner.agent_config.knowledge_enabled,
                    "runner_knowledge_base_id": runner.agent_config.knowledge_base_id,
                    "runner_knowledge_base_ids": list(runner.agent_config.knowledge_base_ids),
                }
            )
        return {
            "observed": observed,
        }

    result = asyncio.run(run())
    observed = result["observed"]

    assert observed[0]["response"] == {
        "session_id": "sess_live_kb",
        "knowledge_base_ids": ["kb_a"],
    }
    assert observed[0]["record"]["knowledge_base_id"] == "kb_a"  # type: ignore[index]
    assert observed[0]["record"]["knowledge_base_ids"] == '["kb_a"]'  # type: ignore[index]
    assert observed[0]["runner_knowledge_enabled"] is True
    assert observed[0]["runner_knowledge_base_id"] == "kb_a"
    assert observed[0]["runner_knowledge_base_ids"] == ["kb_a"]

    assert observed[1]["response"] == {
        "session_id": "sess_live_kb",
        "knowledge_base_ids": ["kb_a", "kb_b"],
    }
    assert observed[1]["record"]["knowledge_base_id"] == "kb_a"  # type: ignore[index]
    assert observed[1]["record"]["knowledge_base_ids"] == '["kb_a", "kb_b"]'  # type: ignore[index]
    assert observed[1]["runner_knowledge_enabled"] is True
    assert observed[1]["runner_knowledge_base_id"] == "kb_a"
    assert observed[1]["runner_knowledge_base_ids"] == ["kb_a", "kb_b"]

    assert observed[2]["response"] == {
        "session_id": "sess_live_kb",
        "knowledge_base_ids": ["kb_b"],
    }
    assert observed[2]["record"]["knowledge_base_id"] == "kb_b"  # type: ignore[index]
    assert observed[2]["record"]["knowledge_base_ids"] == '["kb_b"]'  # type: ignore[index]
    assert observed[2]["runner_knowledge_enabled"] is True
    assert observed[2]["runner_knowledge_base_id"] == "kb_b"
    assert observed[2]["runner_knowledge_base_ids"] == ["kb_b"]

    assert observed[3]["response"] == {
        "session_id": "sess_live_kb",
        "knowledge_base_ids": [],
    }
    assert observed[3]["record"]["knowledge_enabled"] == "0"  # type: ignore[index]
    assert observed[3]["record"]["knowledge_base_id"] == ""  # type: ignore[index]
    assert observed[3]["record"]["knowledge_base_ids"] == "[]"  # type: ignore[index]
    assert observed[3]["runner_knowledge_enabled"] is False
    assert observed[3]["runner_knowledge_base_id"] is None
    assert observed[3]["runner_knowledge_base_ids"] == []


def test_update_session_knowledge_bases_can_clear_selection_without_defaulting() -> None:
    async def run() -> dict[str, str]:
        redis = InMemoryRedis()
        sid = "sess_clear_kb"
        await redis.hset(
            session_key(sid),
            mapping={
                "session_id": sid,
                "avatar_id": "singer",
                "model": "mock",
                "state": "worker_ready",
                "agent_enabled": "1",
                "memory_enabled": "0",
                "knowledge_enabled": "1",
                "knowledge_base_id": "kb_old",
                "knowledge_base_ids": '["kb_old"]',
            },
        )
        app = FastAPI()
        app.state.redis = redis
        app.state.session_runners = {}
        request = Request({"type": "http", "app": app})

        await sessions_routes.update_session_knowledge_bases(
            sid,
            sessions_routes.SessionKnowledgeBasesRequest(knowledge_base_ids=[]),
            request,
        )
        return await redis.hgetall(session_key(sid))

    record = asyncio.run(run())

    assert record["knowledge_enabled"] == "0"
    assert record["knowledge_base_id"] == ""
    assert record["knowledge_base_ids"] == "[]"


def test_agent_session_config_defaults_to_no_knowledge_base() -> None:
    body = CreateSessionRequest(
        avatar_id="singer",
        model="flashtalk",
        user_id="client_test",
    )

    (
        agent_user_id,
        agent_enabled,
        memory_enabled,
        knowledge_enabled,
        knowledge_base_id,
        knowledge_base_ids,
    ) = sessions_routes._normalize_agent_session_config(body)

    assert agent_user_id == "client_test"
    assert agent_enabled is True
    assert memory_enabled is False
    assert knowledge_enabled is True
    assert knowledge_base_id is None
    assert knowledge_base_ids == []


def test_create_session_expands_persona_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    async def fake_create_session(*args: object, **kwargs: object) -> str:
        calls.append(kwargs)
        sid = "sess_persona"
        redis = args[0]
        await redis.hset(
            session_key(sid),
            mapping={
                "session_id": sid,
                "avatar_id": kwargs["avatar_id"],
                "model": kwargs["model"],
                "state": "worker_ready",
            },
        )
        return sid

    async def fake_connected_model_ids(_settings: object) -> set[str]:
        return {"mock"}

    persona_dir = tmp_path / "personas" / "customer-support-zh"
    (persona_dir / "prompts").mkdir(parents=True)
    (persona_dir / "prompts" / "system.md").write_text("你是客服数字人。", encoding="utf-8")
    (persona_dir / "persona.json").write_text(
        """
{
  "schema_version": "0.1",
  "id": "customer-support-zh",
  "name": "客服",
  "description": "客服 Persona",
  "locale": "zh-CN",
  "avatar": {"id": "singer", "model": "mock"},
  "voice": {"provider": "edge", "voice_id": "zh-CN-XiaoxiaoNeural"},
  "agent": {
    "system_prompt": "prompts/system.md",
    "memory_enabled": true,
    "knowledge_enabled": true,
    "knowledge_base_ids": ["kb_persona"]
  },
  "runtime": {"stt_provider": "sensevoice", "tts_provider": "edge"},
  "safety": {"authorized_avatar": true, "authorized_voice": true, "content_label_required": true}
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(sessions_routes.session_service, "create_session", fake_create_session)
    monkeypatch.setattr(
        "opentalking.providers.synthesis.availability.connected_model_ids",
        fake_connected_model_ids,
    )

    avatars_dir = Path(__file__).resolve().parents[3] / "examples" / "avatars"
    app = FastAPI()
    app.state.redis = InMemoryRedis()
    app.state.settings = SimpleNamespace(
        avatars_dir=str(avatars_dir),
        persona_root=str(tmp_path / "personas"),
        normalized_stt_default_provider="sensevoice",
        normalized_stt_provider="sensevoice",
        normalized_tts_default_provider="edge",
        normalized_tts_provider="edge",
        omnirt_endpoint="",
    )
    request = Request({"type": "http", "app": app})

    response = asyncio.run(
        sessions_routes.create_session(
            CreateSessionRequest(persona_id="customer-support-zh", user_id="client_test"),
            request,
        )
    )

    assert response.status == "created"
    assert calls[0]["persona_id"] == "customer-support-zh"
    assert calls[0]["avatar_id"] == "singer"
    assert calls[0]["model"] == "mock"
    assert calls[0]["tts_provider"] == "edge"
    assert calls[0]["stt_provider"] == "sensevoice"
    assert calls[0]["tts_voice"] == "zh-CN-XiaoxiaoNeural"
    assert calls[0]["llm_system_prompt"] == "你是客服数字人。"
    assert calls[0]["memory_enabled"] is True
    assert calls[0]["knowledge_base_ids"] == ["kb_persona"]


def test_create_session_keeps_persona_prompt_above_explicit_llm_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    async def fake_create_session(*args: object, **kwargs: object) -> str:
        calls.append(kwargs)
        sid = "sess_persona_override"
        redis = args[0]
        await redis.hset(
            session_key(sid),
            mapping={
                "session_id": sid,
                "avatar_id": kwargs["avatar_id"],
                "model": kwargs["model"],
                "state": "worker_ready",
            },
        )
        return sid

    async def fake_connected_model_ids(_settings: object) -> set[str]:
        return {"mock", "flashtalk"}

    persona_dir = tmp_path / "personas" / "support"
    persona_dir.mkdir(parents=True)
    (persona_dir / "persona.json").write_text(
        """
{
  "schema_version": "0.1",
  "id": "support",
  "name": "客服",
  "description": "客服 Persona",
  "locale": "zh-CN",
  "avatar": {"id": "singer", "model": "mock"},
  "voice": {"provider": "edge", "voice_id": "zh-CN-XiaoxiaoNeural"},
  "agent": {"persona_prompt": "persona.md", "memory_enabled": true, "knowledge_enabled": true, "knowledge_base_ids": ["kb_persona"]},
  "runtime": {"stt_provider": "sensevoice", "tts_provider": "edge"},
  "safety": {"authorized_avatar": true, "authorized_voice": true, "content_label_required": true}
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (persona_dir / "persona.md").write_text("# Persona\nPersona prompt from package.\n", encoding="utf-8")

    monkeypatch.setattr(sessions_routes.session_service, "create_session", fake_create_session)
    monkeypatch.setattr(
        "opentalking.providers.synthesis.availability.connected_model_ids",
        fake_connected_model_ids,
    )

    avatars_dir = Path(__file__).resolve().parents[3] / "examples" / "avatars"
    app = FastAPI()
    app.state.redis = InMemoryRedis()
    app.state.settings = SimpleNamespace(
        avatars_dir=str(avatars_dir),
        persona_root=str(tmp_path / "personas"),
        normalized_stt_default_provider="sensevoice",
        normalized_stt_provider="sensevoice",
        normalized_tts_default_provider="edge",
        normalized_tts_provider="edge",
        omnirt_endpoint="",
    )
    request = Request({"type": "http", "app": app})

    response = asyncio.run(
        sessions_routes.create_session(
            CreateSessionRequest(
                persona_id="support",
                avatar_id="anchor",
                model="flashtalk",
                llm_system_prompt="显式提示词",
                knowledge_base_ids=["kb_override"],
                memory_enabled=False,
                user_id="client_test",
            ),
            request,
        )
    )

    assert response.status == "created"
    assert calls[0]["avatar_id"] == "anchor"
    assert calls[0]["model"] == "flashtalk"
    assert calls[0]["llm_system_prompt"] == "# Persona\nPersona prompt from package."
    assert calls[0]["knowledge_base_ids"] == ["kb_override"]
    assert calls[0]["memory_enabled"] is False


def test_create_session_passes_indextts_voice_and_model_to_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    async def fake_create_session(*args: object, **kwargs: object) -> str:
        calls.append(kwargs)
        sid = "sess_indextts_voice"
        redis = args[0]
        await redis.hset(
            session_key(sid),
            mapping={
                "session_id": sid,
                "avatar_id": kwargs["avatar_id"],
                "model": kwargs["model"],
                "state": "worker_ready",
            },
        )
        return sid

    async def fake_connected_model_ids(_settings: object) -> set[str]:
        return {"flashtalk"}

    monkeypatch.setattr(sessions_routes.session_service, "create_session", fake_create_session)
    monkeypatch.setattr(
        "opentalking.providers.synthesis.availability.connected_model_ids",
        fake_connected_model_ids,
    )

    avatars_dir = Path(__file__).resolve().parents[3] / "examples" / "avatars"
    app = FastAPI()
    app.state.redis = InMemoryRedis()
    app.state.settings = SimpleNamespace(
        avatars_dir=str(avatars_dir),
        normalized_stt_default_provider="sensevoice",
        normalized_stt_provider="sensevoice",
        normalized_tts_default_provider="indextts",
        normalized_tts_provider="indextts",
        omnirt_endpoint="",
    )
    request = Request({"type": "http", "app": app})

    response = asyncio.run(
        sessions_routes.create_session(
            CreateSessionRequest(
                avatar_id="anchor",
                model="flashtalk",
                tts_provider="indextts",
                tts_voice="indextts-clone-cn",
                tts_model="IndexTeam/IndexTTS-2",
                stt_provider="sensevoice",
            ),
            request,
        )
    )

    assert response.status == "created"
    assert calls[0]["tts_provider"] == "indextts"
    assert calls[0]["tts_voice"] == "indextts-clone-cn"
    assert calls[0]["tts_model"] == "IndexTeam/IndexTTS-2"



def test_speak_audio_passes_request_level_stt_provider(
    unified_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str | None] = []

    async def fake_transcribe_upload_path(upload_path: Path, *, stt_provider: str | None = None) -> str:
        del upload_path
        seen.append(stt_provider)
        return "上传识别文本"

    monkeypatch.setattr(sessions_routes, "_transcribe_upload_path", fake_transcribe_upload_path)

    create_response = unified_client.post(
        "/sessions",
        json={"avatar_id": "singer", "model": "flashtalk", "stt_provider": "sensevoice"},
    )
    session_id = create_response.json()["session_id"]
    response = unified_client.post(
        f"/sessions/{session_id}/speak_audio",
        data={
            "stt_provider": "dashscope",
            "tts_provider": "edge",
        },
        files={"file": ("speech.webm", b"fake-audio", "audio/webm")},
    )

    assert response.status_code == 200, response.json()
    assert response.json()["text"] == "上传识别文本"
    assert seen == ["dashscope"]


def test_update_fasterliveportrait_config_for_active_session(
    unified_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_connected_model_ids(_settings: object) -> set[str]:
        return {"fasterliveportrait"}

    monkeypatch.setattr(
        "opentalking.providers.synthesis.availability.connected_model_ids",
        fake_connected_model_ids,
    )

    create_response = unified_client.post(
        "/sessions",
        json={"avatar_id": "singer", "model": "fasterliveportrait"},
    )
    session_id = create_response.json()["session_id"]

    response = unified_client.post(
        f"/sessions/{session_id}/fasterliveportrait-config",
        json={
            "mouth_open_multiplier": 1.7,
            "pose_motion_multiplier": 0.2,
            "yaw_multiplier": 0.75,
            "animation_region": "lip",
            "flag_pasteback": True,
            "flag_lip_retargeting": False,
            "width": 999,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": session_id,
        "status": "updated",
        "updated": {
            "mouth_open_multiplier": 1.7,
            "pose_motion_multiplier": 0.2,
            "yaw_multiplier": 0.75,
            "animation_region": "lip",
            "flag_pasteback": True,
            "flag_lip_retargeting": False,
        },
    }
    runner = unified_client.created_runners[session_id]  # type: ignore[attr-defined]
    assert runner.fasterliveportrait_config_updates == [
        {
            "mouth_open_multiplier": 1.7,
            "pose_motion_multiplier": 0.2,
            "yaw_multiplier": 0.75,
            "animation_region": "lip",
            "flag_pasteback": True,
            "flag_lip_retargeting": False,
        }
    ]


@pytest.mark.parametrize("tts_provider", ["dashscope", "cosyvoice", "sambert"])
def test_create_session_accepts_bailian_tts_providers(
    unified_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tts_provider: str,
) -> None:
    monkeypatch.setenv("OPENTALKING_TTS_DASHSCOPE_API_KEY", "test-tts-key")
    response = unified_client.post(
        "/sessions",
        json={
            "avatar_id": "singer",
            "model": "flashtalk",
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


def test_unified_prewarm_model_can_override_avatar_manifest_model() -> None:
    source = Path(unified_main.__file__).read_text(encoding="utf-8")

    assert "OPENTALKING_PREWARM_MODEL" in source
    assert "prewarm_model or bundle.manifest.model_type" in source


def test_unified_quicktalk_create_waits_for_runner_ready() -> None:
    source = Path(sessions_routes.__file__).read_text(encoding="utf-8")

    assert 'if body.model == "quicktalk":' not in source


def test_split_flashtalk_create_returns_queued_until_worker_ready(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    avatar_id = "anchor"
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
        flashtalk_ws_url="ws://127.0.0.1:8765",
        omnirt_endpoint="",
        flashhead_ws_url="",
    )
    app.include_router(sessions_routes.router)

    with TestClient(app) as client:
        response = client.post(
            "/sessions",
            json={"avatar_id": avatar_id, "model": "flashtalk", "stt_provider": "sensevoice"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "queued"


def test_split_flashtalk_create_returns_created_when_worker_ready(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    avatar_id = "anchor"
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
        flashtalk_ws_url="ws://127.0.0.1:8765",
        omnirt_endpoint="",
        flashhead_ws_url="",
    )
    app.include_router(sessions_routes.router)

    with TestClient(app) as client:
        response = client.post(
            "/sessions",
            json={"avatar_id": avatar_id, "model": "flashtalk", "stt_provider": "sensevoice"},
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
        json={"avatar_id": "singer", "model": "flashtalk"},
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
        json={"avatar_id": "singer", "model": "flashtalk"},
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
    from opentalking.runtime.server import create_app as create_worker_app

    session_id = "sess_worker_dl"
    append_flashtalk_frames(
        session_id,
        [np.full((10, 12, 3), 32, dtype=np.uint8)],
        start_index=0,
        fps=25.0,
    )

    with TestClient(create_worker_app()) as client:
        response = client.get(f"/sessions/{session_id}/flashtalk-recording")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("video/mp4")
    assert len(response.content) > 0


def test_interrupt_cancels_active_speech_and_restores_ready(unified_client: TestClient) -> None:
    create_response = unified_client.post(
        "/sessions",
        json={"avatar_id": "singer", "model": "flashtalk"},
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
        json={"avatar_id": "singer", "model": "flashtalk"},
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



def test_create_session_loads_persona_md_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    async def fake_create_session(*args: object, **kwargs: object) -> str:
        calls.append(kwargs)
        sid = "sess_persona_md"
        redis = args[0]
        await redis.hset(
            session_key(sid),
            mapping={
                "session_id": sid,
                "avatar_id": kwargs["avatar_id"],
                "model": kwargs["model"],
                "state": "worker_ready",
            },
        )
        return sid

    async def fake_connected_model_ids(_settings: object) -> set[str]:
        return {"mock"}

    persona_dir = tmp_path / "personas" / "friend-li"
    persona_dir.mkdir(parents=True)
    (persona_dir / "persona.md").write_text("# Persona\n你是小李，说话温柔。", encoding="utf-8")
    (persona_dir / "persona.json").write_text(
        """
{
  "schema_version": "0.1",
  "id": "friend-li",
  "name": "小李",
  "description": "微信导入生成的 Persona",
  "locale": "zh-CN",
  "avatar": {"id": "singer", "model": "mock"},
  "agent": {"persona_prompt": "persona.md", "memory_enabled": true, "knowledge_enabled": false},
  "safety": {"authorized_avatar": true, "authorized_voice": false, "content_label_required": true}
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sessions_routes.session_service, "create_session", fake_create_session)
    monkeypatch.setattr(
        "opentalking.providers.synthesis.availability.connected_model_ids",
        fake_connected_model_ids,
    )

    avatars_dir = Path(__file__).resolve().parents[3] / "examples" / "avatars"
    app = FastAPI()
    app.state.redis = InMemoryRedis()
    app.state.settings = SimpleNamespace(
        avatars_dir=str(avatars_dir),
        persona_root=str(tmp_path / "personas"),
        normalized_stt_default_provider="sensevoice",
        normalized_stt_provider="sensevoice",
        normalized_tts_default_provider="edge",
        normalized_tts_provider="edge",
        omnirt_endpoint="",
    )
    request = Request({"type": "http", "app": app})

    response = asyncio.run(
        sessions_routes.create_session(
            CreateSessionRequest(persona_id="friend-li", user_id="client_test"),
            request,
        )
    )

    assert response.status == "created"
    assert calls[0]["llm_system_prompt"] == "# Persona\n你是小李，说话温柔。"
