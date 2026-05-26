from __future__ import annotations

import io
import queue
import wave
import importlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from opentalking.core.types.frames import AudioChunk
from opentalking.providers.tts.factory import build_tts_adapter, create_tts_adapter
from opentalking.providers.tts.providers import normalize_tts_provider


def _settings(**overrides):
    defaults = {
        "normalized_tts_provider": "edge",
        "tts_voice": "zh-CN-XiaoxiaoNeural",
        "ffmpeg_bin": "ffmpeg",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.mark.parametrize(
    ("provider", "expected_cls"),
    [
        ("local_cosyvoice", "LocalCosyVoiceTTSAdapter"),
        ("local_qwen3_tts", "LocalQwen3TTSAdapter"),
    ],
)
def test_local_tts_providers_are_supported(provider: str, expected_cls: str, monkeypatch):
    monkeypatch.setenv("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", "/tmp/opentalking-local-audio")

    assert normalize_tts_provider(provider, default=None) == provider

    adapter = create_tts_adapter(
        sample_rate=16000,
        chunk_ms=20.0,
        default_voice="local-voice",
        tts_provider=provider,
        tts_model="test-model",
    )

    assert adapter.__class__.__name__ == expected_cls
    assert adapter.default_voice == "local-voice"
    assert adapter.model == "test-model"


def test_build_tts_adapter_uses_settings_local_provider(monkeypatch):
    monkeypatch.setenv("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", "/tmp/opentalking-local-audio")

    adapter = build_tts_adapter(
        sample_rate=16000,
        chunk_ms=20.0,
        settings=_settings(normalized_tts_provider="local_cosyvoice"),
        tts_model="FunAudioLLM/CosyVoice2-0.5B",
    )

    assert adapter.__class__.__name__ == "LocalCosyVoiceTTSAdapter"
    assert adapter.model == "FunAudioLLM/CosyVoice2-0.5B"


def test_local_tts_defaults_use_downloadable_model_ids(monkeypatch):
    from opentalking.providers.tts.local_cosyvoice.adapter import LocalCosyVoiceTTSAdapter
    from opentalking.providers.tts.local_qwen3_tts.adapter import LocalQwen3TTSAdapter

    for key in [
        "OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL",
        "OPENTALKING_LOCAL_QWEN3_TTS_MODEL",
    ]:
        monkeypatch.delenv(key, raising=False)

    assert LocalCosyVoiceTTSAdapter().model == "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"
    assert LocalQwen3TTSAdapter().model == "Qwen/Qwen3-TTS-12Hz-0.6B-Base"


def test_local_cosyvoice3_uses_automodel(monkeypatch):
    from opentalking.core import config as core_config
    from opentalking.providers.tts.local_cosyvoice import adapter as cosy_adapter

    loaded: dict[str, object] = {}

    class FakeAutoModel:
        def __init__(self, model_dir, **kwargs):
            loaded["model_dir"] = model_dir
            loaded["kwargs"] = kwargs

    monkeypatch.setitem(
        __import__("sys").modules,
        "cosyvoice.cli.cosyvoice",
        SimpleNamespace(AutoModel=FakeAutoModel),
    )
    monkeypatch.delenv("OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL_DIR", raising=False)
    monkeypatch.delenv("OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL_DIR", raising=False)
    monkeypatch.setattr(
        core_config,
        "get_settings",
        lambda: SimpleNamespace(
            tts_tts_local_cosyvoice_model_dir="",
            tts_local_cosyvoice_model_dir="",
            local_audio_model_root="",
        ),
    )
    monkeypatch.setattr(cosy_adapter, "_resolve_model_path", lambda model: f"/models/{model}")

    engine = cosy_adapter.LocalCosyVoiceTTSAdapter(
        model="FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
    )._load_engine()

    assert isinstance(engine, FakeAutoModel)
    assert loaded["model_dir"] == "/models/FunAudioLLM/Fun-CosyVoice3-0.5B-2512"


def test_local_tts_adapters_read_settings_when_env_is_absent(monkeypatch):
    from opentalking.core import config as core_config
    from opentalking.providers.tts.local_cosyvoice.adapter import LocalCosyVoiceTTSAdapter
    from opentalking.providers.tts.local_qwen3_tts.adapter import LocalQwen3TTSAdapter

    for key in [
        "OPENTALKING_LOCAL_AUDIO_MODEL_ROOT",
        "OPENTALKING_LOCAL_AUDIO_DEVICE",
        "OPENTALKING_LOCAL_TTS_DEVICE",
        "OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL",
        "OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL",
        "OPENTALKING_LOCAL_QWEN3_TTS_MODEL",
        "OPENTALKING_LOCAL_QWEN3_TTS_SERVICE_URL",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        core_config,
        "get_settings",
        lambda: SimpleNamespace(
            local_audio_model_root="/settings/local-audio",
            local_audio_device="cpu",
            tts_local_cosyvoice_model="settings/CosyVoice",
            tts_local_cosyvoice_service_url="http://127.0.0.1:19090/cosy",
            local_qwen3_tts_model="settings/Qwen3-TTS",
            local_qwen3_tts_service_url="http://127.0.0.1:19091/qwen3",
        ),
    )

    cosy = LocalCosyVoiceTTSAdapter()
    qwen3 = LocalQwen3TTSAdapter()

    assert cosy.model == "settings/CosyVoice"
    assert cosy.service_url == "http://127.0.0.1:19090/cosy"
    assert cosy.device == "cpu"
    assert qwen3.model == "settings/Qwen3-TTS"
    assert qwen3.service_url == "http://127.0.0.1:19091/qwen3"


def test_tts_local_cosyvoice_service_url_map_routes_by_model(monkeypatch):
    from opentalking.providers.tts.local_cosyvoice.adapter import LocalCosyVoiceTTSAdapter

    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL", "FunAudioLLM/Fun-CosyVoice3-0.5B-2512")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL", "http://127.0.0.1:19090/synthesize")
    monkeypatch.setenv(
        "OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URLS",
        "FunAudioLLM/Fun-CosyVoice3-0.5B-2512=http://127.0.0.1:19090/synthesize,"
        "iic/CosyVoice-300M=http://127.0.0.1:19091/synthesize",
    )

    default_adapter = LocalCosyVoiceTTSAdapter(model="FunAudioLLM/Fun-CosyVoice3-0.5B-2512")
    experiment_adapter = LocalCosyVoiceTTSAdapter(model="iic/CosyVoice-300M")
    alias_adapter = LocalCosyVoiceTTSAdapter(model="iic__CosyVoice-300M")

    assert default_adapter.service_url == "http://127.0.0.1:19090/synthesize"
    assert experiment_adapter.service_url == "http://127.0.0.1:19091/synthesize"
    assert alias_adapter.service_url == "http://127.0.0.1:19091/synthesize"

    with pytest.raises(RuntimeError, match="No local CosyVoice service URL configured"):
        LocalCosyVoiceTTSAdapter(model="unknown/CosyVoice")


def test_stt_factory_routes_local_providers(monkeypatch):
    from opentalking.providers.stt import factory

    calls: list[tuple[str, object]] = []

    class FakeAdapter:
        def transcribe_wav(self, path):
            calls.append(("wav", path))
            return "本地识别文本", 12.5

        def transcribe_pcm_queue(self, chunk_queue, *, sample_rate: int = 16000):
            calls.append(("pcm", sample_rate))
            while chunk_queue.get() is not None:
                pass
            return "流式识别文本", 34.5

    monkeypatch.setenv("OPENTALKING_STT_PROVIDER", "funasr")

    monkeypatch.setattr(factory, "create_stt_adapter", lambda provider=None: FakeAdapter())

    text, elapsed = factory.transcribe_wav_path_sync("/tmp/test.wav")
    assert text == "本地识别文本"
    assert elapsed == 12.5
    assert calls[-1] == ("wav", "/tmp/test.wav")

    q: queue.Queue[bytes | None] = queue.Queue()
    q.put(b"\0\0")
    q.put(None)
    assert factory.transcribe_pcm_chunk_queue_sync(q) == ("流式识别文本", 34.5)
    assert calls[-1] == ("pcm", 16000)


def test_stt_factory_request_provider_override_routes_dashscope(monkeypatch):
    from opentalking.providers.stt import factory

    wav_calls: list[Path] = []
    pcm_calls: list[object] = []

    def fake_recognize_wav(path):
        wav_calls.append(path)
        return "API识别文本", 22.0

    def fake_transcribe_pcm(chunk_queue):
        pcm_calls.append(chunk_queue)
        while chunk_queue.get() is not None:
            pass
        return "API流式文本", 33.0

    monkeypatch.setenv("OPENTALKING_STT_PROVIDER", "sensevoice")
    monkeypatch.setattr(
        "opentalking.providers.stt.dashscope.adapter._recognize_wav_sync",
        fake_recognize_wav,
    )
    monkeypatch.setattr(
        "opentalking.providers.stt.dashscope.adapter.transcribe_pcm_chunk_queue_sync",
        fake_transcribe_pcm,
    )

    assert factory.transcribe_wav_path_sync("/tmp/api.wav", provider="dashscope") == ("API识别文本", 22.0)
    assert wav_calls == [Path("/tmp/api.wav")]

    q: queue.Queue[bytes | None] = queue.Queue()
    q.put(b"\0\0")
    q.put(None)
    assert factory.transcribe_pcm_chunk_queue_sync(q, provider="dashscope") == ("API流式文本", 33.0)
    assert pcm_calls == [q]


def test_stt_factory_reuses_local_adapter_for_same_runtime(monkeypatch):
    from opentalking.providers.stt import factory

    factory.clear_stt_adapter_cache()
    monkeypatch.setenv("OPENTALKING_STT_PROVIDER", "sensevoice")
    monkeypatch.setenv("OPENTALKING_STT_MODEL", "iic/SenseVoiceSmall")
    monkeypatch.setenv("OPENTALKING_LOCAL_AUDIO_DEVICE", "cpu")
    monkeypatch.setenv("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", "/tmp/opentalking-local-audio")

    first = factory.create_stt_adapter("sensevoice")
    second = factory.create_stt_adapter("sensevoice")

    assert first is second
    assert first.model == "iic/SenseVoiceSmall"
    assert first.device == "cpu"


def test_local_funasr_runtime_disables_update_check(monkeypatch):
    from opentalking.providers.stt import factory

    loaded: dict[str, object] = {}

    class FakeAutoModel:
        def __init__(self, model, **kwargs):
            loaded["model"] = model
            loaded["kwargs"] = kwargs

    monkeypatch.setitem(
        __import__("sys").modules,
        "funasr",
        SimpleNamespace(AutoModel=FakeAutoModel),
    )

    runtime = factory.LocalFunASRSTTAdapter(
        provider="sensevoice",
        model="iic/SenseVoiceSmall",
        model_dir="/models/sensevoice",
        device="cpu",
    )._load_runtime()

    assert isinstance(runtime, FakeAutoModel)
    assert loaded["model"] == "/models/sensevoice"
    assert loaded["kwargs"] == {"device": "cpu", "disable_update": True}


def test_stt_prewarm_skips_api_provider(monkeypatch):
    from opentalking.providers.stt import factory

    monkeypatch.setenv("OPENTALKING_STT_DEFAULT_PROVIDER", "dashscope")
    monkeypatch.setattr(
        factory,
        "create_stt_adapter",
        lambda provider=None: pytest.fail("API STT provider must not be prewarmed"),
    )

    assert factory.prewarm_stt_adapter() is False


def test_stt_prewarm_loads_local_adapter(monkeypatch):
    from opentalking.providers.stt import factory

    calls: list[str] = []

    class FakeAdapter:
        def _load_runtime(self):
            calls.append("loaded")
            return object()

    monkeypatch.setenv("OPENTALKING_STT_DEFAULT_PROVIDER", "sensevoice")
    monkeypatch.setattr(factory, "create_stt_adapter", lambda provider=None: FakeAdapter())

    assert factory.prewarm_stt_adapter() is True
    assert calls == ["loaded"]


def test_stt_extract_text_removes_sensevoice_tags():
    from opentalking.providers.stt.factory import _extract_text

    result = [{"text": "<|zh|><|NEUTRAL|><|Speech|><|withitn|>开饭时间早上9点。"}]

    assert _extract_text(result) == "开饭时间早上9点。"


def test_stt_device_prefers_local_audio_env_over_default_settings(monkeypatch):
    from opentalking.core import config as core_config
    from opentalking.providers.stt.factory import LocalFunASRSTTAdapter

    monkeypatch.delenv("OPENTALKING_STT_DEVICE", raising=False)
    monkeypatch.setenv("OPENTALKING_LOCAL_AUDIO_DEVICE", "cpu")
    monkeypatch.setenv("OPENTALKING_STT_PROVIDER", "funasr")
    monkeypatch.setattr(
        core_config,
        "get_settings",
        lambda: SimpleNamespace(
            stt_device="auto",
            local_audio_device="auto",
            stt_model="paraformer-realtime-v2",
        ),
    )

    assert LocalFunASRSTTAdapter(provider="funasr").device == "cpu"


def test_download_script_default_models_use_verified_12g_set():
    from scripts import download_local_audio_models as downloader

    selected = downloader.default_model_keys()

    assert selected == ["sensevoice-small", "fun-cosyvoice3-0.5b-2512"]
    assert set(downloader.MODELS) == set(selected)
    assert downloader.DEFAULT_ROOT == Path("./models/local-audio")
    assert "/data2" not in Path("scripts/download_local_audio_models.py").read_text(encoding="utf-8")


def test_quicktalk_cuda_extra_declares_gpu_onnxruntime():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "quicktalk-cpu" in pyproject
    assert "quicktalk-cuda" in pyproject
    assert "onnxruntime>=1.24.3" in pyproject
    assert "onnxruntime-gpu>=1.24.0" in pyproject

    base_deps = pyproject.split("dependencies = [", 1)[1].split("]", 1)[0]
    models_extra = pyproject.split("models = [", 1)[1].split("]", 1)[0]
    assert "onnxruntime" not in base_deps
    assert "onnxruntime" not in models_extra


def test_onnxruntime_extras_declare_uv_conflicts():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "conflicts = [" in pyproject
    assert '{ extra = "quicktalk-cpu" }' in pyproject
    assert '{ extra = "quicktalk-cuda" }' in pyproject
    assert '{ extra = "local-cosyvoice-service" }' in pyproject
    assert '{ extra = "demo" }' in pyproject


def test_download_script_excludes_experimental_model_candidates():
    from scripts import download_local_audio_models as downloader

    assert "cosyvoice-300m" not in downloader.MODELS
    assert "qwen3-tts-0.6b" not in downloader.MODELS
    assert "funasr-nano-2512" not in downloader.MODELS


def test_qwen3_service_dependencies_are_declared():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "local-qwen3-tts-service" in pyproject
    assert "qwen-tts>=0.1.1" in pyproject
    assert "transformers==4.57.3" in pyproject


def test_qwen3_service_script_exposes_http_contract():
    service = Path("scripts/local_qwen3_tts_service.py").read_text(encoding="utf-8")

    assert "@app.post(\"/synthesize\")" in service
    assert "OPENTALKING_LOCAL_QWEN3_TTS_MODEL_DIR" in service
    assert "OPENTALKING_LOCAL_QWEN3_TTS_REF_AUDIO" in service
    assert "local-qwen3-tts-service" in service


def test_cosyvoice_service_dependencies_are_declared():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "local-cosyvoice-service" in pyproject
    assert "fastapi>=0.109" in pyproject
    assert "uvicorn[standard]>=0.27" in pyproject
    assert "openai-whisper>=20240930" in pyproject
    assert "openai-whisper==20231117" not in pyproject
    assert "matcha-tts" not in pyproject


def test_cosyvoice_service_script_exposes_http_contract():
    service = Path("scripts/local_cosyvoice_service.py").read_text(encoding="utf-8")

    assert "@app.post(\"/synthesize\")" in service
    assert "OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL_DIR" in service
    assert "OPENTALKING_TTS_LOCAL_COSYVOICE_PROMPT_AUDIO" in service
    assert "inference_zero_shot" in service
    assert "audio/L16" in service


def test_cosyvoice_zero_shot_prompt_text_gets_endofprompt_prefix(monkeypatch):
    from scripts import local_cosyvoice_service as service_module

    seen: dict[str, str] = {}

    class FakeEngine:
        sample_rate = 24000

        def inference_zero_shot(self, text, prompt_text, prompt_wav, stream=False):
            seen["prompt_text"] = prompt_text
            yield {"tts_speech": np.zeros((1, 80), dtype=np.float32)}

    class FakeAutoModel:
        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setitem(
        __import__("sys").modules,
        "cosyvoice.cli.cosyvoice",
        SimpleNamespace(AutoModel=FakeAutoModel),
    )
    monkeypatch.setattr(service_module, "AutoModel", FakeAutoModel, raising=False)
    monkeypatch.setattr(service_module.CosyVoiceService, "model", lambda self: FakeEngine())

    service = service_module.CosyVoiceService(
        model_dir="/tmp/model",
        runtime_dir="/tmp/runtime",
        device="cpu",
        prompt_audio="/tmp/prompt.wav",
        prompt_text="开饭时间早上9点至下午5点。",
        mode="zero_shot",
        instruction="You are a helpful assistant.<|endofprompt|>",
        fp16=False,
    )

    req = service_module.SynthesizeRequest(text="你好")
    service.synthesize_wav(req)

    assert "<|endofprompt|>" in seen["prompt_text"]
    assert seen["prompt_text"].endswith("开饭时间早上9点至下午5点。")


def test_cosyvoice_synthesize_route_uses_model_streaming_pcm(monkeypatch):
    from fastapi.testclient import TestClient
    from scripts import local_cosyvoice_service as service_module

    seen: dict[str, object] = {}

    class FakeEngine:
        sample_rate = 24000

        def inference_zero_shot(self, text, prompt_text, prompt_wav, stream=False):
            seen["stream"] = stream
            seen["prompt_text"] = prompt_text
            yield {"tts_speech": np.full((1, 240), 0.25, dtype=np.float32)}
            yield {"tts_speech": np.full((1, 120), -0.25, dtype=np.float32)}

    monkeypatch.setattr(service_module.CosyVoiceService, "model", lambda self: FakeEngine())

    service = service_module.CosyVoiceService(
        model_dir="/tmp/model",
        runtime_dir="/tmp/runtime",
        device="cpu",
        prompt_audio="/tmp/prompt.wav",
        prompt_text="开饭时间早上9点至下午5点。",
        mode="zero_shot",
        instruction="You are a helpful assistant.<|endofprompt|>",
        fp16=False,
    )

    resp = TestClient(service_module.create_app(service)).post(
        "/synthesize",
        json={"text": "你好", "sample_rate": 16000},
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("audio/L16")
    assert resp.headers["x-audio-sample-rate"] == "16000"
    assert seen["stream"] is True
    assert "<|endofprompt|>" in seen["prompt_text"]
    assert len(resp.content) > 0


def test_cosyvoice_service_request_prompt_overrides_default(monkeypatch):
    from fastapi.testclient import TestClient
    from scripts import local_cosyvoice_service as service_module

    seen: dict[str, object] = {}

    class FakeEngine:
        sample_rate = 24000

        def inference_zero_shot(self, text, prompt_text, prompt_wav, stream=False):
            seen["prompt_text"] = prompt_text
            seen["prompt_wav"] = prompt_wav
            seen["stream"] = stream
            yield {"tts_speech": np.zeros((1, 120), dtype=np.float32)}

    monkeypatch.setattr(service_module.CosyVoiceService, "model", lambda self: FakeEngine())

    service = service_module.CosyVoiceService(
        model_dir="/tmp/model",
        runtime_dir="/tmp/runtime",
        device="cpu",
        prompt_audio="/tmp/default.wav",
        prompt_text="默认文本",
        mode="zero_shot",
        instruction="You are a helpful assistant.<|endofprompt|>",
        fp16=False,
    )

    resp = TestClient(service_module.create_app(service)).post(
        "/synthesize",
        json={
            "text": "你好",
            "sample_rate": 16000,
            "prompt_audio": "/tmp/local-voice.wav",
            "prompt_text": "这是本地复刻音色文本。",
        },
    )

    assert resp.status_code == 200
    assert seen["stream"] is True
    assert seen["prompt_wav"] == "/tmp/local-voice.wav"
    assert str(seen["prompt_text"]).endswith("这是本地复刻音色文本。")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module_name", "class_name", "service_env"),
    [
        (
            "opentalking.providers.tts.local_cosyvoice.adapter",
            "LocalCosyVoiceTTSAdapter",
            "OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL",
        ),
        (
            "opentalking.providers.tts.local_qwen3_tts.adapter",
            "LocalQwen3TTSAdapter",
            "OPENTALKING_LOCAL_QWEN3_TTS_SERVICE_URL",
        ),
    ],
)
async def test_local_tts_service_wav_response_uses_content_type_decoder(
    module_name: str,
    class_name: str,
    service_env: str,
    monkeypatch,
):
    module = importlib.import_module(module_name)
    monkeypatch.setenv(service_env, "http://127.0.0.1:19090/synthesize")
    calls: list[tuple[bytes, str | None]] = []
    wav_buf = io.BytesIO()
    with wave.open(wav_buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(np.zeros(240, dtype="<i2").tobytes())
    wav_body = wav_buf.getvalue()

    async def fake_stream_decode_audio_to_pcm_chunks(
        audio_iter,
        target_sr: int,
        chunk_ms: float,
        *,
        input_format: str | None = None,
    ):
        body = bytearray()
        async for part in audio_iter:
            body.extend(part)
        calls.append((bytes(body), input_format))
        yield AudioChunk(
            data=np.zeros(160, dtype=np.int16),
            sample_rate=target_sr,
            duration_ms=chunk_ms,
        )

    async def fail_mp3_decoder(*args, **kwargs):
        raise AssertionError("WAV service responses must not use the MP3-only decoder")

    class FakeResponse:
        headers = {"content-type": "audio/wav"}

        def raise_for_status(self) -> None:
            return None

        async def aread(self):
            return wav_body

        async def aiter_bytes(self):
            yield wav_body

    class FakeStream:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, url, json):
            return FakeStream()

    monkeypatch.setattr(module.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(
        module,
        "_stream_decode_audio_to_pcm_chunks",
        fake_stream_decode_audio_to_pcm_chunks,
        raising=False,
    )
    monkeypatch.setattr(module, "_stream_decode_mp3_to_pcm_chunks", fail_mp3_decoder, raising=False)

    cls = getattr(module, class_name)
    adapter = cls(sample_rate=16000, chunk_ms=10.0, model="test-model")

    chunks = [chunk async for chunk in adapter.synthesize_stream("你好")]

    assert len(chunks) == 1
    if class_name == "LocalCosyVoiceTTSAdapter":
        assert chunks[0].sample_rate == 16000
        assert calls == []
    else:
        assert calls == [(wav_body, "wav")]


@pytest.mark.asyncio
async def test_local_cosyvoice_service_pcm_response_streams_without_full_body(monkeypatch):
    module = importlib.import_module("opentalking.providers.tts.local_cosyvoice.adapter")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL", "http://127.0.0.1:19090/synthesize")
    pcm_body = np.arange(320, dtype="<i2").tobytes()
    first = pcm_body[:321]
    second = pcm_body[321:]

    class FakeResponse:
        headers = {
            "content-type": "audio/L16; rate=16000; channels=1",
            "x-audio-sample-rate": "16000",
        }

        def raise_for_status(self) -> None:
            return None

        async def aread(self):
            raise AssertionError("PCM streaming responses must not be fully buffered")

        async def aiter_bytes(self):
            yield first
            yield second

    class FakeStream:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, url, json):
            return FakeStream()

    monkeypatch.setattr(module.httpx, "AsyncClient", FakeClient)

    adapter = module.LocalCosyVoiceTTSAdapter(sample_rate=16000, chunk_ms=10.0, model="test-model")

    chunks = [chunk async for chunk in adapter.synthesize_stream("你好")]

    assert len(chunks) == 2
    assert chunks[0].sample_rate == 16000
    assert chunks[0].duration_ms == 10.0
    np.testing.assert_array_equal(chunks[0].data, np.arange(160, dtype=np.int16))
    np.testing.assert_array_equal(chunks[1].data, np.arange(160, 320, dtype=np.int16))


@pytest.mark.asyncio
async def test_local_cosyvoice_service_payload_includes_system_voice_mode(tmp_path, monkeypatch):
    module = importlib.import_module("opentalking.providers.tts.local_cosyvoice.adapter")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL", "http://127.0.0.1:19090/synthesize")
    monkeypatch.setenv("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", str(tmp_path))
    voice_dir = tmp_path / "voices" / "system" / "local-cross-lingual"
    voice_dir.mkdir(parents=True)
    (voice_dir / "prompt.wav").write_bytes(b"RIFFtest")
    (voice_dir / "prompt.txt").write_text("", encoding="utf-8")
    (voice_dir / "meta.json").write_text('{"mode":"cross_lingual"}', encoding="utf-8")
    seen: dict[str, object] = {}

    class FakeResponse:
        headers = {
            "content-type": "audio/L16; rate=16000; channels=1",
            "x-audio-sample-rate": "16000",
        }

        def raise_for_status(self) -> None:
            return None

        async def aiter_bytes(self):
            yield np.zeros(160, dtype="<i2").tobytes()

    class FakeStream:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, url, json):
            seen.update(json)
            return FakeStream()

    monkeypatch.setattr(module.httpx, "AsyncClient", FakeClient)

    adapter = module.LocalCosyVoiceTTSAdapter(sample_rate=16000, chunk_ms=10.0, model="test-model")
    chunks = [chunk async for chunk in adapter.synthesize_stream("你好", voice="local-cross-lingual")]

    assert chunks
    assert seen["prompt_audio"] == str(voice_dir / "prompt.wav")
    assert seen["mode"] == "cross_lingual"
    assert "prompt_text" not in seen


@pytest.mark.asyncio
async def test_local_cosyvoice_service_payload_includes_local_voice_prompt(tmp_path, monkeypatch):
    module = importlib.import_module("opentalking.providers.tts.local_cosyvoice.adapter")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL", "http://127.0.0.1:19090/synthesize")
    monkeypatch.setenv("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", str(tmp_path))
    voice_dir = tmp_path / "voices" / "clones" / "local-test-voice"
    voice_dir.mkdir(parents=True)
    (voice_dir / "prompt.wav").write_bytes(b"RIFFtest")
    (voice_dir / "prompt.txt").write_text("这是一段本地音色参考文本。", encoding="utf-8")
    seen: dict[str, object] = {}

    class FakeResponse:
        headers = {
            "content-type": "audio/L16; rate=16000; channels=1",
            "x-audio-sample-rate": "16000",
        }

        def raise_for_status(self) -> None:
            return None

        async def aiter_bytes(self):
            yield np.zeros(160, dtype="<i2").tobytes()

    class FakeStream:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, url, json):
            seen.update(json)
            return FakeStream()

    monkeypatch.setattr(module.httpx, "AsyncClient", FakeClient)

    adapter = module.LocalCosyVoiceTTSAdapter(sample_rate=16000, chunk_ms=10.0, model="test-model")
    chunks = [chunk async for chunk in adapter.synthesize_stream("你好", voice="local-test-voice")]

    assert chunks
    assert seen["voice"] == "local-test-voice"
    assert seen["prompt_audio"] == str(voice_dir / "prompt.wav")
    assert seen["prompt_text"] == "这是一段本地音色参考文本。"


def test_local_cosyvoice_service_prewarm_loads_model_and_runs_short_synthesis(monkeypatch):
    from scripts import local_cosyvoice_service as service_module

    calls: list[str] = []

    class FakeEngine:
        sample_rate = 16000

        def inference_zero_shot(self, text, prompt_text, prompt_audio, stream=True):
            calls.append(f"synth:{text}:{stream}")
            yield {"tts_speech": np.zeros(160, dtype=np.float32)}

    service = service_module.CosyVoiceService(
        model_dir="model",
        runtime_dir="runtime",
        device="cpu",
        prompt_audio="prompt.wav",
        prompt_text="参考文本",
        mode="zero_shot",
        instruction="",
        fp16=False,
    )
    monkeypatch.setattr(service, "model", lambda: calls.append("model") or FakeEngine())

    service.prewarm(text="你好")

    assert calls == ["model", "synth:你好:True"]
