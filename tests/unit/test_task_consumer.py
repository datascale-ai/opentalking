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
import opentalking.runtime.task_consumer as task_consumer
from opentalking.pipeline.session.runner import SessionRunner
from opentalking.runtime.task_consumer import handle_worker_task


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


class ChatCapableRunner(StubRunner):
    def __init__(self) -> None:
        super().__init__()
        self.chat_calls: list[dict[str, object]] = []

    def create_chat_task(
        self,
        prompt: str,
        tts_voice: str | None = None,
        **kwargs: object,
    ) -> asyncio.Task[None]:
        async def _chat() -> None:
            self.chat_calls.append({"prompt": prompt, "tts_voice": tts_voice, **kwargs})

        task = asyncio.create_task(_chat())
        self.speech_tasks.add(task)
        task.add_done_callback(self.speech_tasks.discard)
        return task


def test_create_runner_passes_wav2lip_postprocess_mode_to_unified_local_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeFlashTalkRunner:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    class FakeLocalAudio2VideoClient:
        def __init__(self, adapter: object, *, device: str) -> None:
            self.adapter = adapter
            self.device = device

    monkeypatch.setattr("opentalking.runtime.task_consumer.FlashTalkRunner", FakeFlashTalkRunner)
    monkeypatch.setattr("opentalking.runtime.task_consumer.LocalAudio2VideoClient", FakeLocalAudio2VideoClient)
    monkeypatch.setattr("opentalking.runtime.task_consumer.get_adapter", lambda model: object())
    monkeypatch.setattr(
        task_consumer,
        "resolve_model_backend",
        lambda *_args, **_kwargs: type("Backend", (), {"backend": "local"})(),
    )

    runner = task_consumer._create_runner(
        {
            "session_id": "sess_wav2lip",
            "avatar_id": "singer",
            "model": "wav2lip",
            "wav2lip_postprocess_mode": "basic",
        },
        InMemoryRedis(),
        Path("examples/avatars"),
        "cpu",
    )

    assert isinstance(runner, FakeFlashTalkRunner)
    assert captured["wav2lip_postprocess_mode"] == "basic"
    assert captured["model_type"] == "wav2lip"


def test_create_runner_uses_model_specific_device_for_local_quicktalk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeFlashTalkRunner:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    class FakeLocalAudio2VideoClient:
        def __init__(self, adapter: object, *, device: str) -> None:
            self.adapter = adapter
            self.device = device

    monkeypatch.setenv("OPENTALKING_QUICKTALK_DEVICE", "cuda:3")
    monkeypatch.setenv("OPENTALKING_TORCH_DEVICE", "cpu")
    monkeypatch.setattr("opentalking.runtime.task_consumer.FlashTalkRunner", FakeFlashTalkRunner)
    monkeypatch.setattr("opentalking.runtime.task_consumer.LocalAudio2VideoClient", FakeLocalAudio2VideoClient)
    monkeypatch.setattr("opentalking.runtime.task_consumer.get_adapter", lambda model: object())
    monkeypatch.setattr(
        task_consumer,
        "resolve_model_backend",
        lambda *_args, **_kwargs: type("Backend", (), {"backend": "local"})(),
    )

    runner = task_consumer._create_runner(
        {
            "session_id": "sess_quicktalk",
            "avatar_id": "singer",
            "model": "quicktalk",
        },
        InMemoryRedis(),
        Path("examples/avatars"),
        "cpu",
    )

    assert isinstance(runner, FakeFlashTalkRunner)
    assert captured["audio2video_client"].device == "cuda:3"


def test_create_runner_wraps_omnirt_ws_client_in_audio2video_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeFlashTalkRunner:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    class FakeAudio2VideoClient:
        def __init__(self, ws_client: object) -> None:
            self.ws_client = ws_client

    class FakeWSClient:
        def __init__(self, ws_url: str, *, extra_headers: dict[str, str] | None = None) -> None:
            self.ws_url = ws_url
            self.extra_headers = extra_headers or {}

    monkeypatch.setattr("opentalking.runtime.task_consumer.FlashTalkRunner", FakeFlashTalkRunner)
    monkeypatch.setattr("opentalking.runtime.task_consumer.OmniRTAudio2VideoClient", FakeAudio2VideoClient)
    monkeypatch.setattr("opentalking.runtime.task_consumer.FlashTalkWSClient", FakeWSClient)
    monkeypatch.setattr(
        task_consumer,
        "resolve_model_backend",
        lambda *_args, **_kwargs: type("Backend", (), {"backend": "omnirt", "ws_url": None})(),
    )
    monkeypatch.setattr(
        "opentalking.providers.synthesis.omnirt.resolve_synthesis_ws_url",
        lambda model, _settings: f"ws://omnirt.test/v1/audio2video/{model}",
    )
    monkeypatch.setattr(
        "opentalking.providers.synthesis.omnirt.auth_headers",
        lambda _settings: {"Authorization": "Bearer test"},
    )

    runner = task_consumer._create_runner(
        {
            "session_id": "sess_wav2lip",
            "avatar_id": "singer",
            "model": "wav2lip",
        },
        InMemoryRedis(),
        Path("examples/avatars"),
        "cpu",
    )

    assert isinstance(runner, FakeFlashTalkRunner)
    audio2video_client = captured["audio2video_client"]
    assert isinstance(audio2video_client, FakeAudio2VideoClient)
    assert isinstance(audio2video_client.ws_client, FakeWSClient)
    assert audio2video_client.ws_client.ws_url == "ws://omnirt.test/v1/audio2video/wav2lip"
    assert audio2video_client.ws_client.extra_headers == {"Authorization": "Bearer test"}
    assert "flashtalk_client" not in captured


def test_create_runner_wraps_musetalk_omnirt_in_audio2video_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeFlashTalkRunner:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    class FakeAudio2VideoClient:
        def __init__(self, ws_client: object) -> None:
            self.ws_client = ws_client

    class FakeWSClient:
        def __init__(self, ws_url: str, *, extra_headers: dict[str, str] | None = None) -> None:
            self.ws_url = ws_url
            self.extra_headers = extra_headers or {}

    monkeypatch.setattr("opentalking.runtime.task_consumer.FlashTalkRunner", FakeFlashTalkRunner)
    monkeypatch.setattr("opentalking.runtime.task_consumer.OmniRTAudio2VideoClient", FakeAudio2VideoClient)
    monkeypatch.setattr("opentalking.runtime.task_consumer.FlashTalkWSClient", FakeWSClient)
    monkeypatch.setattr(
        task_consumer,
        "resolve_model_backend",
        lambda *_args, **_kwargs: type("Backend", (), {"backend": "omnirt", "ws_url": None})(),
    )
    monkeypatch.setattr(
        "opentalking.providers.synthesis.omnirt.resolve_synthesis_ws_url",
        lambda model, _settings: f"ws://omnirt.test/v1/audio2video/{model}",
    )

    runner = task_consumer._create_runner(
        {"session_id": "sess_musetalk", "avatar_id": "singer", "model": "musetalk"},
        InMemoryRedis(),
        Path("examples/avatars"),
        "cpu",
    )

    assert isinstance(runner, FakeFlashTalkRunner)
    assert captured["model_type"] == "musetalk"
    assert captured["audio2video_client"].ws_client.ws_url == "ws://omnirt.test/v1/audio2video/musetalk"


def test_create_runner_wraps_local_musetalk_adapter_in_audio2video_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeFlashTalkRunner:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    class FakeLocalAudio2VideoClient:
        def __init__(self, adapter: object, *, device: str) -> None:
            self.adapter = adapter
            self.device = device

    fake_adapter = object()

    monkeypatch.setenv("OPENTALKING_MUSETALK_DEVICE", "cuda:7")
    monkeypatch.setenv("OPENTALKING_TORCH_DEVICE", "cpu")
    monkeypatch.setattr("opentalking.runtime.task_consumer.FlashTalkRunner", FakeFlashTalkRunner)
    monkeypatch.setattr("opentalking.runtime.task_consumer.LocalAudio2VideoClient", FakeLocalAudio2VideoClient)
    monkeypatch.setattr("opentalking.runtime.task_consumer.get_adapter", lambda model: fake_adapter)
    monkeypatch.setattr(
        task_consumer,
        "resolve_model_backend",
        lambda *_args, **_kwargs: type("Backend", (), {"backend": "local", "ws_url": None})(),
    )

    runner = task_consumer._create_runner(
        {"session_id": "sess_musetalk", "avatar_id": "singer", "model": "musetalk"},
        InMemoryRedis(),
        Path("examples/avatars"),
        "cpu",
    )

    assert isinstance(runner, FakeFlashTalkRunner)
    audio2video_client = captured["audio2video_client"]
    assert isinstance(audio2video_client, FakeLocalAudio2VideoClient)
    assert audio2video_client.adapter is fake_adapter
    assert audio2video_client.device == "cuda:7"
    assert captured["model_type"] == "musetalk"


def test_create_runner_wraps_local_wav2lip_adapter_in_audio2video_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeFlashTalkRunner:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    class FakeLocalAudio2VideoClient:
        def __init__(self, adapter: object, *, device: str) -> None:
            self.adapter = adapter
            self.device = device

    fake_adapter = object()

    monkeypatch.setenv("OPENTALKING_WAV2LIP_DEVICE", "cuda:5")
    monkeypatch.setattr("opentalking.runtime.task_consumer.FlashTalkRunner", FakeFlashTalkRunner)
    monkeypatch.setattr("opentalking.runtime.task_consumer.LocalAudio2VideoClient", FakeLocalAudio2VideoClient)
    monkeypatch.setattr("opentalking.runtime.task_consumer.get_adapter", lambda model: fake_adapter)
    monkeypatch.setattr(
        task_consumer,
        "resolve_model_backend",
        lambda *_args, **_kwargs: type("Backend", (), {"backend": "local", "ws_url": None})(),
    )

    runner = task_consumer._create_runner(
        {
            "session_id": "sess_wav2lip",
            "avatar_id": "singer",
            "model": "wav2lip",
            "wav2lip_postprocess_mode": "basic",
        },
        InMemoryRedis(),
        Path("examples/avatars"),
        "cpu",
    )

    assert isinstance(runner, FakeFlashTalkRunner)
    audio2video_client = captured["audio2video_client"]
    assert isinstance(audio2video_client, FakeLocalAudio2VideoClient)
    assert audio2video_client.adapter is fake_adapter
    assert audio2video_client.device == "cuda:5"
    assert captured["model_type"] == "wav2lip"


def test_create_runner_wraps_local_quicktalk_adapter_in_audio2video_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeFlashTalkRunner:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    class FakeLocalAudio2VideoClient:
        def __init__(self, adapter: object, *, device: str) -> None:
            self.adapter = adapter
            self.device = device

    fake_adapter = object()

    monkeypatch.setenv("OPENTALKING_QUICKTALK_DEVICE", "cuda:3")
    monkeypatch.setenv("OPENTALKING_TORCH_DEVICE", "cpu")
    monkeypatch.setattr("opentalking.runtime.task_consumer.FlashTalkRunner", FakeFlashTalkRunner)
    monkeypatch.setattr("opentalking.runtime.task_consumer.LocalAudio2VideoClient", FakeLocalAudio2VideoClient)
    monkeypatch.setattr("opentalking.runtime.task_consumer.get_adapter", lambda model: fake_adapter)
    monkeypatch.setattr(
        task_consumer,
        "resolve_model_backend",
        lambda *_args, **_kwargs: type("Backend", (), {"backend": "local", "ws_url": None})(),
    )

    runner = task_consumer._create_runner(
        {
            "session_id": "sess_quicktalk",
            "avatar_id": "singer",
            "model": "quicktalk",
        },
        InMemoryRedis(),
        Path("examples/avatars"),
        "cpu",
    )

    assert isinstance(runner, FakeFlashTalkRunner)
    audio2video_client = captured["audio2video_client"]
    assert isinstance(audio2video_client, FakeLocalAudio2VideoClient)
    assert audio2video_client.adapter is fake_adapter
    assert audio2video_client.device == "cuda:3"
    assert captured["model_type"] == "quicktalk"


def test_session_runner_configures_wav2lip_adapter_postprocess_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeAdapter:
        mode: str | None = None

        def set_wav2lip_postprocess_mode(self, mode: str | None) -> None:
            self.mode = mode

    adapter = FakeAdapter()
    monkeypatch.setattr("opentalking.pipeline.session.runner.get_adapter", lambda _model: adapter)

    runner = SessionRunner(
        session_id="sess_wav2lip",
        avatar_id="singer",
        model_type="wav2lip",
        avatars_root=Path("examples/avatars"),
        redis=InMemoryRedis(),
        wav2lip_postprocess_mode="basic",
    )

    assert runner.adapter is adapter
    assert adapter.mode == "basic"


def test_session_runner_prepare_passes_avatar_state_to_adapter_warmup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeManifest:
        fps = 25
        sample_rate = 16000

    class FakeAdapter:
        warmed_state: object | None = None

        def load_model(self, device: str) -> None:
            self.device = device

        def load_avatar(self, avatar_path: str) -> object:
            self.avatar_path = avatar_path
            return type("FakeState", (), {"manifest": FakeManifest()})()

        def warmup(self, avatar_state: object | None = None) -> None:
            self.warmed_state = avatar_state

        def idle_frame(self, avatar_state: object, frame_idx: int) -> object:
            raise AssertionError("idle cache is disabled in this test")

    class FakeWebRTCSession:
        def __init__(self, *, fps: float, sample_rate: int, mode: str) -> None:
            self.fps = fps
            self.sample_rate = sample_rate
            self.mode = mode

    adapter = FakeAdapter()
    monkeypatch.setattr("opentalking.pipeline.session.runner.get_adapter", lambda _model: adapter)
    monkeypatch.setattr("opentalking.pipeline.session.runner.WebRTCSession", FakeWebRTCSession)
    monkeypatch.setenv("OPENTALKING_TTS_PREWARM_ON_PREPARE", "0")
    monkeypatch.setenv("OPENTALKING_IDLE_CACHE_FRAMES", "0")

    runner = SessionRunner(
        session_id="sess_warmup",
        avatar_id="singer",
        model_type="wav2lip",
        avatars_root=Path("examples/avatars"),
        redis=InMemoryRedis(),
    )

    async def run() -> None:
        await runner.prepare()

    asyncio.run(run())

    assert adapter.warmed_state is runner.avatar_state


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


def test_session_runner_llm_helpers_import_provider_dependencies() -> None:
    runner = object.__new__(SessionRunner)
    runner._llm_client = None
    runner._llm_base_url = "https://llm.example/v1"
    runner._llm_api_key = "test-key"
    runner._llm_model = "test-model"
    runner._conversation = None
    runner._llm_system_prompt = "system prompt"

    client = runner._ensure_llm_client()
    conversation = runner._ensure_conversation()

    assert client.base_url == "https://llm.example/v1"
    assert client.api_key == "test-key"
    assert client.model == "test-model"
    assert conversation.get_messages()[0]["content"].startswith("system prompt")


def test_session_runner_splits_first_complete_long_sentence_at_soft_punctuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENTALKING_CHAT_FIRST_SENT_MIN_CHARS", "6")
    monkeypatch.setenv("OPENTALKING_CHAT_FIRST_SENT_MAX_CHARS", "20")

    splitter = SessionRunner._build_first_sentence_splitter()

    parts = splitter("这是一个完整但比较长的回答，我们先讲结论，然后再补充细节。")

    assert parts == ["这是一个完整但比较长的回答，", "我们先讲结论，然后再补充细节。"]


def test_session_runner_forces_first_complete_long_sentence_split_at_max_chars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENTALKING_CHAT_FIRST_SENT_MIN_CHARS", "6")
    monkeypatch.setenv("OPENTALKING_CHAT_FIRST_SENT_MAX_CHARS", "10")

    splitter = SessionRunner._build_first_sentence_splitter()

    parts = splitter("这是一个没有软标点但很长的回答。")

    assert parts == ["这是一个没有软标点但", "很长的回答。"]


@pytest.mark.asyncio
async def test_session_runner_prewarm_tts_consumes_first_audio_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeManifest:
        sample_rate = 16000

    class FakeTTS:
        async def synthesize_stream(self, text: str):
            calls.append({"text": text})
            yield object()
            raise AssertionError("prewarm should stop after the first audio chunk")

    runner = object.__new__(SessionRunner)
    runner.avatar_state = type("FakeState", (), {"manifest": FakeManifest()})()
    runner._tts_settings = object()
    runner._tts_prewarm_text = "预热"
    runner._speech_chunk_ms = lambda: 123.0  # type: ignore[method-assign]

    def fake_build_tts_adapter(**kwargs: object) -> FakeTTS:
        calls.append(kwargs)
        return FakeTTS()

    monkeypatch.setattr("opentalking.pipeline.session.runner.build_tts_adapter", fake_build_tts_adapter)

    await runner._prewarm_tts()

    assert calls == [
        {
            "sample_rate": 16000,
            "chunk_ms": 123.0,
            "settings": runner._tts_settings,
            "default_voice": None,
            "tts_provider": None,
            "tts_model": None,
        },
        {"text": "预热"},
    ]


@pytest.mark.asyncio
async def test_handle_worker_task_routes_text_speak_through_chat_when_available() -> None:
    sid = "sess_local_chat"
    redis = InMemoryRedis()
    await redis.hset(
        session_key(sid),
        mapping={"session_id": sid, "state": "ready", "model": "wav2lip"},
    )
    runner = ChatCapableRunner()
    await runner.prepare()

    await handle_worker_task(
        {
            "cmd": "speak",
            "session_id": sid,
            "text": "你好",
            "tts_voice": "Cherry",
            "tts_provider": "dashscope",
            "tts_model": "qwen3-tts-flash-realtime",
            "enqueue_unix": 123.0,
        },
        redis,
        Path("."),
        "cpu",
        {sid: runner},
    )
    await asyncio.sleep(0)

    assert runner.spoken == []
    assert runner.chat_calls == [
        {
            "prompt": "你好",
            "tts_voice": "Cherry",
            "tts_provider": "dashscope",
            "tts_model": "qwen3-tts-flash-realtime",
            "enqueue_unix": 123.0,
        }
    ]


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

    monkeypatch.setattr("opentalking.runtime.task_consumer._create_runner", fake_create_runner)

    redis = InMemoryRedis()
    sid = "sess_test"
    await redis.hset(session_key(sid), mapping={"session_id": sid, "state": "created"})
    runners: dict[str, StubRunner] = {}

    await handle_worker_task(
        {"cmd": "init", "session_id": sid, "avatar_id": "singer", "model": "wav2lip"},
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
        {"cmd": "init", "session_id": sid, "avatar_id": "singer", "model": "flashtalk"},
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
