from __future__ import annotations

import asyncio
import io
import queue
import wave
import importlib
import sys
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
        ("local_indextts", "LocalIndexTTSAdapter"),
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


def test_local_indextts_status_uses_local_model_root(monkeypatch):
    from opentalking.providers.tts.factory import tts_provider_config

    monkeypatch.setenv("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", "/tmp/opentalking-local-audio")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_INDEXTTS_SERVICE_URL", "http://127.0.0.1:19092/synthesize")
    monkeypatch.setattr(
        "opentalking.providers.tts.factory._settings_value",
        lambda _name, default="": default,
    )
    monkeypatch.delenv("OPENTALKING_TTS_LOCAL_INDEXTTS_MODEL", raising=False)
    monkeypatch.delenv("OPENTALKING_TTS_LOCAL_INDEXTTS_MODEL_DIR", raising=False)
    monkeypatch.delenv("OPENTALKING_TTS_LOCAL_INDEXTTS_CFG_PATH", raising=False)
    monkeypatch.delenv("OPENTALKING_TTS_LOCAL_INDEXTTS_PROMPT_AUDIO", raising=False)
    monkeypatch.delenv("OPENTALKING_TTS_LOCAL_INDEXTTS_W2V_BERT_DIR", raising=False)
    monkeypatch.delenv("OPENTALKING_TTS_LOCAL_INDEXTTS_MASKGCT_DIR", raising=False)
    monkeypatch.delenv("OPENTALKING_TTS_LOCAL_INDEXTTS_CAMPPLUS_DIR", raising=False)
    monkeypatch.delenv("OPENTALKING_TTS_LOCAL_INDEXTTS_BIGVGAN_DIR", raising=False)
    monkeypatch.delenv("OPENTALKING_TTS_LOCAL_INDEXTTS_DEVICE", raising=False)

    status = tts_provider_config("local_indextts")

    assert status == {
        "provider": "local_indextts",
        "model": "IndexTeam/IndexTTS-2",
        "model_dir": "/tmp/opentalking-local-audio/IndexTeam__IndexTTS-2",
        "voice": "local-default",
        "device": "auto",
        "key_set": False,
        "service_url": "http://127.0.0.1:19092/synthesize",
        "service_url_set": True,
        "cfg_path": "/tmp/opentalking-local-audio/IndexTeam__IndexTTS-2/config.yaml",
        "prompt_audio_set": False,
        "w2v_bert_dir": "/tmp/opentalking-local-audio/facebook__w2v-bert-2.0",
        "maskgct_dir": "/tmp/opentalking-local-audio/amphion__MaskGCT",
        "campplus_dir": "/tmp/opentalking-local-audio/funasr__campplus",
        "bigvgan_dir": "/tmp/opentalking-local-audio/nvidia__bigvgan_v2_22khz_80band_256x",
    }

def test_indextts_public_provider_routes_to_configured_backend(monkeypatch):
    from opentalking.providers.tts.factory import create_tts_adapter, tts_provider_config

    monkeypatch.setenv("OPENTALKING_TTS_INDEXTTS_BACKEND", "local")
    monkeypatch.setenv("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", "/tmp/opentalking-local-audio")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_INDEXTTS_SERVICE_URL", "http://127.0.0.1:19092/synthesize")

    assert normalize_tts_provider("indextts", default=None) == "indextts"

    local_status = tts_provider_config("indextts")
    assert local_status["provider"] == "indextts"
    assert local_status["backend"] == "local"
    assert local_status["resolved_provider"] == "local_indextts"
    assert local_status["service_url_set"] is True
    assert local_status["model"] == "IndexTeam/IndexTTS-2"

    local_adapter = create_tts_adapter(
        sample_rate=16000,
        chunk_ms=20.0,
        default_voice="indextts-clear-cn",
        tts_provider="indextts",
        tts_model="IndexTeam/IndexTTS-2",
    )
    assert local_adapter.__class__.__name__ == "LocalIndexTTSAdapter"
    assert local_adapter.service_url == "http://127.0.0.1:19092/synthesize"

    monkeypatch.setenv("OPENTALKING_TTS_INDEXTTS_BACKEND", "omnirt")
    monkeypatch.setenv(
        "OPENTALKING_TTS_OMNIRT_INDEXTTS_SERVICE_URL",
        "http://127.0.0.1:9012/v1/text2audio/indextts",
    )

    omnirt_status = tts_provider_config("indextts")
    assert omnirt_status["provider"] == "indextts"
    assert omnirt_status["backend"] == "omnirt"
    assert omnirt_status["resolved_provider"] == "omnirt_indextts"
    assert omnirt_status["streaming_mode"] == "token_window"

    omnirt_adapter = create_tts_adapter(
        sample_rate=16000,
        chunk_ms=20.0,
        default_voice="indextts-clear-cn",
        tts_provider="indextts",
        tts_model="IndexTeam/IndexTTS-2",
    )
    assert omnirt_adapter.__class__.__name__ == "OmniRTIndexTTSAdapter"


def test_tts_enabled_providers_collapse_legacy_indextts_backends(monkeypatch):
    from opentalking.providers.tts.factory import tts_enabled_providers

    monkeypatch.setenv(
        "OPENTALKING_TTS_ENABLED_PROVIDERS",
        "edge,local_indextts,omnirt_indextts,indextts",
    )
    assert tts_enabled_providers() == ["edge", "indextts"]


def test_indextts_normalized_vector_config_is_idempotent():
    from opentalking.providers.tts.indextts_config import normalize_indextts_config

    once = normalize_indextts_config(
        {
            "emotion_mode": "vector",
            "emo_alpha": 1.0,
            "emo_vector": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "use_random": True,
            "streaming_mode": "segment",
            "max_text_tokens_per_segment": 80,
            "quick_streaming_tokens": 4,
        }
    )

    twice = normalize_indextts_config(once)

    assert once["emo_vector"] == [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    assert twice["emo_vector"] == once["emo_vector"]
    assert twice["emo_alpha"] == 1.0
    assert twice["use_random"] is True
    assert twice["streaming_mode"] == "segment"
    assert twice["max_text_tokens_per_segment"] == 80
    assert twice["quick_streaming_tokens"] == 4



def test_indextts_vector_config_keeps_official_mixed_strengths_without_pre_scaling():
    from opentalking.providers.tts.indextts_config import normalize_indextts_config

    config = normalize_indextts_config(
        {
            "emotion_mode": "vector",
            "emo_alpha": 1.0,
            "emo_vector": [0.75, 0.0, 0.0, 0.0, 0.0, 0.0, 0.35, 0.0],
        }
    )

    assert config["emo_vector"] == [0.75, 0.0, 0.0, 0.0, 0.0, 0.0, 0.35, 0.0]


def test_indextts_adapters_keep_pre_normalized_emotion_config():
    from opentalking.providers.tts.local_indextts.adapter import LocalIndexTTSAdapter
    from opentalking.providers.tts.omnirt_indextts.adapter import OmniRTIndexTTSAdapter

    normalized_config = {
        "emo_alpha": 0.9,
        "emo_vector": [0.0, 0.0, 0.8, 0.0, 0.0, 0.0, 0.0, 0.0],
        "use_random": False,
    }

    local = LocalIndexTTSAdapter(indextts_config=normalized_config)
    omnirt = OmniRTIndexTTSAdapter(
        service_url="http://127.0.0.1:9012/v1/text2audio/indextts",
        indextts_config=normalized_config,
    )

    assert local.indextts_config == normalized_config
    assert omnirt.indextts_config == normalized_config



def test_local_indextts_resolves_bundled_system_voice_prompt(tmp_path, monkeypatch):
    from opentalking.providers.tts.local_indextts.adapter import LocalIndexTTSAdapter

    monkeypatch.setenv("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", str(tmp_path / "models"))
    adapter = LocalIndexTTSAdapter(service_url="http://127.0.0.1:19092/synthesize")
    prompt = adapter._resolve_voice_prompt("indextts-xiaoxiao-cn")

    assert prompt is not None
    assert str(prompt).endswith("opentalking/assets/voices/system/indextts-xiaoxiao-cn/prompt.wav")


def test_local_indextts_reuses_engine_for_same_runtime_config(monkeypatch, tmp_path):
    from opentalking.providers.tts.local_indextts.adapter import LocalIndexTTSAdapter

    model_dir = tmp_path / "IndexTTS-2"
    model_dir.mkdir()
    cfg_path = model_dir / "config.yaml"
    cfg_path.write_text("model: fake\n", encoding="utf-8")
    prompt_audio = tmp_path / "prompt.wav"
    with wave.open(str(prompt_audio), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(np.zeros(1600, dtype="<i2").tobytes())

    init_calls: list[dict[str, object]] = []
    infer_calls: list[str] = []

    class FakeIndexTTS2:
        def __init__(self, **kwargs):
            init_calls.append(kwargs)

        def infer(self, _prompt: str, text: str, output_path: str, **_kwargs):
            infer_calls.append(text)
            with wave.open(output_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(np.zeros(1600, dtype="<i2").tobytes())

    monkeypatch.setitem(sys.modules, "indextts.infer_v2", SimpleNamespace(IndexTTS2=FakeIndexTTS2))

    first = LocalIndexTTSAdapter(model_dir=str(model_dir), cfg_path=str(cfg_path), prompt_audio=str(prompt_audio))
    second = LocalIndexTTSAdapter(model_dir=str(model_dir), cfg_path=str(cfg_path), prompt_audio=str(prompt_audio))

    assert first._synthesize_in_process("第一句", None)
    assert second._synthesize_in_process("第二句", None)

    assert len(init_calls) == 1
    assert infer_calls == ["第一句", "第二句"]


def test_omnirt_indextts_provider_config_reads_env(monkeypatch):
    from opentalking.providers.tts.factory import tts_provider_config

    monkeypatch.setenv(
        "OPENTALKING_TTS_OMNIRT_INDEXTTS_SERVICE_URL",
        "http://127.0.0.1:9012/v1/text2audio/indextts",
    )
    monkeypatch.setenv("OPENTALKING_TTS_OMNIRT_INDEXTTS_MODEL", "IndexTeam/IndexTTS-2")
    monkeypatch.setenv("OPENTALKING_TTS_OMNIRT_INDEXTTS_STREAMING_MODE", "token_window")
    monkeypatch.setenv("OPENTALKING_TTS_OMNIRT_INDEXTTS_TOKEN_WINDOW_SIZE", "32")
    monkeypatch.setenv("OPENTALKING_TTS_OMNIRT_INDEXTTS_TOKEN_WINDOW_HOP", "96")
    monkeypatch.setenv("OPENTALKING_TTS_OMNIRT_INDEXTTS_TOKEN_WINDOW_CONTEXT", "8")
    monkeypatch.setenv("OPENTALKING_TTS_OMNIRT_INDEXTTS_TOKEN_WINDOW_OVERLAP_MS", "60")

    assert normalize_tts_provider("omnirt_indextts", default=None) == "omnirt_indextts"

    status = tts_provider_config("omnirt_indextts")

    assert status == {
        "provider": "omnirt_indextts",
        "model": "IndexTeam/IndexTTS-2",
        "model_dir": "",
        "voice": "local-default",
        "device": "",
        "key_set": False,
        "service_url": "http://127.0.0.1:9012/v1/text2audio/indextts",
        "service_url_set": True,
        "streaming": True,
        "streaming_mode": "token_window",
        "max_text_tokens_per_segment": 80,
        "quick_streaming_tokens": 4,
        "interval_silence_ms": 0,
        "token_window_size": 32,
        "token_window_hop": 96,
        "token_window_context": 8,
        "token_window_overlap_ms": 60,
    }

    adapter = create_tts_adapter(
        sample_rate=16000,
        chunk_ms=20.0,
        default_voice="local-default",
        tts_provider="omnirt_indextts",
        tts_model="IndexTeam/IndexTTS-2",
    )

    assert adapter.__class__.__name__ == "OmniRTIndexTTSAdapter"
    assert adapter.model == "IndexTeam/IndexTTS-2"
    assert adapter.service_url == "http://127.0.0.1:9012/v1/text2audio/indextts"


def test_build_tts_adapter_routes_omnirt_indextts(monkeypatch):
    monkeypatch.setenv(
        "OPENTALKING_TTS_OMNIRT_INDEXTTS_SERVICE_URL",
        "http://127.0.0.1:9012/v1/text2audio/indextts",
    )

    adapter = build_tts_adapter(
        sample_rate=16000,
        chunk_ms=20.0,
        default_voice="local-default",
        tts_provider="omnirt_indextts",
        tts_model="IndexTeam/IndexTTS-2",
        settings=_settings(normalized_tts_provider="edge"),
    )

    assert adapter.__class__.__name__ == "OmniRTIndexTTSAdapter"
    assert adapter.model == "IndexTeam/IndexTTS-2"
    assert adapter.service_url == "http://127.0.0.1:9012/v1/text2audio/indextts"


def test_omnirt_indextts_provider_config_defaults_to_balanced_token_window(monkeypatch):
    from opentalking.providers.tts.factory import tts_provider_config

    monkeypatch.delenv("OPENTALKING_TTS_OMNIRT_INDEXTTS_TOKEN_WINDOW_SIZE", raising=False)

    status = tts_provider_config("omnirt_indextts")

    assert status["token_window_size"] == 40
    assert status["token_window_hop"] == 96

async def _collect_audio_chunks(stream):
    return [chunk async for chunk in stream]


def test_omnirt_indextts_streams_l16_without_full_body_buffer(monkeypatch):
    from opentalking.providers.tts.omnirt_indextts import adapter as omnirt_adapter
    from opentalking.providers.tts.omnirt_indextts.adapter import OmniRTIndexTTSAdapter

    calls: list[dict[str, object]] = []

    class FakeResponse:
        headers = {
            "content-type": "audio/L16; rate=16000; channels=1",
            "x-audio-sample-rate": "16000",
        }

        def raise_for_status(self):
            return None

        async def aiter_bytes(self):
            yield b"\x01"
            yield b"\x00\x02\x00\x03\x00"

        async def aread(self):
            raise AssertionError("PCM streaming responses must not be fully buffered")

    class FakeStream:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeClient:
        def __init__(self, *, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, url, *, json):
            calls.append({"method": method, "url": url, "json": json})
            return FakeStream()

    monkeypatch.setattr(omnirt_adapter.httpx, "AsyncClient", FakeClient)
    adapter = OmniRTIndexTTSAdapter(
        service_url="http://127.0.0.1:9012/v1/text2audio/indextts",
        default_voice="local-default",
        sample_rate=16000,
        chunk_ms=40.0,
        model="IndexTeam/IndexTTS-2",
        streaming=True,
        streaming_mode="token_window",
        max_text_tokens_per_segment=80,
        quick_streaming_tokens=4,
        interval_silence_ms=0,
        token_window_size=40,
        token_window_hop=96,
        token_window_context=8,
        token_window_overlap_ms=60,
    )

    chunks = asyncio.run(_collect_audio_chunks(adapter.synthesize_stream("你好", voice="local-default")))

    assert calls == [
        {
            "method": "POST",
            "url": "http://127.0.0.1:9012/v1/text2audio/indextts",
            "json": {
                "text": "你好",
                "voice": "local-default",
                "model": "IndexTeam/IndexTTS-2",
                "sample_rate": 16000,
                "streaming": True,
                "streaming_mode": "token_window",
                "max_text_tokens_per_segment": 80,
                "quick_streaming_tokens": 4,
                "interval_silence_ms": 0,
                "token_window_size": 40,
                "token_window_hop": 96,
                "token_window_context": 8,
                "token_window_overlap_ms": 60,
            },
        }
    ]
    assert len(chunks) == 1
    assert chunks[0].sample_rate == 16000
    assert chunks[0].data.tolist() == [1, 2, 3]


def test_local_indextts_in_process_synthesis_uses_indextts2(monkeypatch, tmp_path):
    from opentalking.providers.tts.local_indextts.adapter import LocalIndexTTSAdapter

    prompt = tmp_path / "prompt.wav"
    prompt.write_bytes(b"prompt")
    model_dir = tmp_path / "IndexTTS-2"
    model_dir.mkdir()
    cfg = model_dir / "config.yaml"
    cfg.write_text("test: true\n", encoding="utf-8")
    calls: list[dict[str, object]] = []

    class FakeIndexTTS2:
        def __init__(self, **kwargs):
            calls.append({"init": kwargs})

        def infer(self, spk_audio_prompt, text, output_path, **kwargs):
            calls.append(
                {
                    "spk_audio_prompt": spk_audio_prompt,
                    "text": text,
                    "output_path": output_path,
                    "kwargs": kwargs,
                }
            )
            samples = (np.sin(np.linspace(0, np.pi * 2, 1600)) * 0.25 * 32767).astype("<i2")
            with wave.open(output_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes(samples.tobytes())

    monkeypatch.setitem(
        __import__("sys").modules,
        "indextts.infer_v2",
        SimpleNamespace(IndexTTS2=FakeIndexTTS2),
    )

    adapter = LocalIndexTTSAdapter(
        sample_rate=16000,
        chunk_ms=40.0,
        model="IndexTeam/IndexTTS-2",
        model_dir=str(model_dir),
        cfg_path=str(cfg),
        prompt_audio=str(prompt),
        device="cpu",
    )

    chunks = list(adapter._synthesize_in_process("你好，IndexTTS。"))

    assert calls[0]["init"] == {
        "cfg_path": str(cfg),
        "model_dir": str(model_dir),
        "use_fp16": False,
        "device": "cpu",
        "use_cuda_kernel": False,
        "use_deepspeed": False,
    }
    assert calls[1]["spk_audio_prompt"] == str(prompt)
    assert calls[1]["text"] == "你好，IndexTTS。"
    assert isinstance(chunks[0], AudioChunk)
    assert {chunk.sample_rate for chunk in chunks} == {16000}
    assert sum(chunk.data.size for chunk in chunks) > 0


def test_local_indextts_uses_system_voice_prompt(monkeypatch, tmp_path):
    from opentalking.providers.tts.local_indextts.adapter import LocalIndexTTSAdapter

    default_prompt = tmp_path / "default.wav"
    default_prompt.write_bytes(b"default")
    voice_dir = tmp_path / "voices" / "system" / "indextts-clear-cn"
    voice_dir.mkdir(parents=True)
    voice_prompt = voice_dir / "prompt.wav"
    voice_prompt.write_bytes(b"voice")
    model_dir = tmp_path / "IndexTTS-2"
    model_dir.mkdir()
    cfg = model_dir / "config.yaml"
    cfg.write_text("test: true\n", encoding="utf-8")
    calls: list[dict[str, object]] = []

    class FakeIndexTTS2:
        def __init__(self, **kwargs):
            calls.append({"init": kwargs})

        def infer(self, spk_audio_prompt, text, output_path, **kwargs):
            calls.append(
                {
                    "spk_audio_prompt": spk_audio_prompt,
                    "text": text,
                    "output_path": output_path,
                    "kwargs": kwargs,
                }
            )
            samples = (np.sin(np.linspace(0, np.pi * 2, 1600)) * 0.25 * 32767).astype("<i2")
            with wave.open(output_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes(samples.tobytes())

    monkeypatch.setenv("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", str(tmp_path))
    monkeypatch.setitem(
        __import__("sys").modules,
        "indextts.infer_v2",
        SimpleNamespace(IndexTTS2=FakeIndexTTS2),
    )

    adapter = LocalIndexTTSAdapter(
        sample_rate=16000,
        chunk_ms=40.0,
        model="IndexTeam/IndexTTS-2",
        model_dir=str(model_dir),
        cfg_path=str(cfg),
        prompt_audio=str(default_prompt),
        device="cpu",
    )

    chunks = asyncio.run(_collect_audio_chunks(adapter.synthesize_stream("你好，IndexTTS。", voice="indextts-clear-cn")))

    assert calls[1]["spk_audio_prompt"] == str(voice_prompt)
    assert chunks


def test_local_indextts_resolves_system_prompt_when_voice_matches_default(monkeypatch, tmp_path):
    from opentalking.providers.tts.local_indextts.adapter import LocalIndexTTSAdapter

    voice_dir = tmp_path / "voices" / "system" / "indextts-default"
    voice_dir.mkdir(parents=True)
    voice_prompt = voice_dir / "prompt.wav"
    voice_prompt.write_bytes(b"voice")
    model_dir = tmp_path / "IndexTTS-2"
    model_dir.mkdir()

    monkeypatch.setenv("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", str(tmp_path))

    adapter = LocalIndexTTSAdapter(
        default_voice="indextts-default",
        model_dir=str(model_dir),
        prompt_audio="",
    )

    assert adapter._resolve_voice_prompt("indextts-default") == voice_prompt


def test_local_indextts_rewrites_w2v_bert_feature_extractor_to_local_dir(monkeypatch, tmp_path):
    from opentalking.providers.tts.local_indextts.adapter import LocalIndexTTSAdapter

    model_dir = tmp_path / "IndexTTS-2"
    model_dir.mkdir()
    cfg = model_dir / "config.yaml"
    cfg.write_text("test: true\n", encoding="utf-8")
    prompt = tmp_path / "prompt.wav"
    prompt.write_bytes(b"prompt")
    w2v_dir = tmp_path / "facebook__w2v-bert-2.0"
    w2v_dir.mkdir()
    (w2v_dir / "preprocessor_config.json").write_text("{}", encoding="utf-8")
    calls: list[str] = []

    class FakeFeatureExtractor:
        @classmethod
        def from_pretrained(cls, value):
            calls.append(value)
            return cls()

    class FakeIndexTTS2:
        def __init__(self, **kwargs):
            from indextts.infer_v2 import SeamlessM4TFeatureExtractor

            SeamlessM4TFeatureExtractor.from_pretrained("facebook/w2v-bert-2.0")

    monkeypatch.setitem(
        __import__("sys").modules,
        "indextts.infer_v2",
        SimpleNamespace(IndexTTS2=FakeIndexTTS2, SeamlessM4TFeatureExtractor=FakeFeatureExtractor),
    )

    adapter = LocalIndexTTSAdapter(
        model_dir=str(model_dir),
        cfg_path=str(cfg),
        prompt_audio=str(prompt),
        w2v_bert_dir=str(w2v_dir),
    )
    adapter._load_engine()

    assert calls == [str(w2v_dir)]


def test_local_indextts_rewrites_w2v_bert_semantic_model_to_local_dir(monkeypatch, tmp_path):
    from opentalking.providers.tts.local_indextts.adapter import LocalIndexTTSAdapter

    model_dir = tmp_path / "IndexTTS-2"
    model_dir.mkdir()
    cfg = model_dir / "config.yaml"
    cfg.write_text("test: true\n", encoding="utf-8")
    prompt = tmp_path / "prompt.wav"
    prompt.write_bytes(b"prompt")
    w2v_dir = tmp_path / "facebook__w2v-bert-2.0"
    w2v_dir.mkdir()
    (w2v_dir / "preprocessor_config.json").write_text("{}", encoding="utf-8")
    calls: list[str] = []

    class FakeWav2Vec2BertModel:
        @classmethod
        def from_pretrained(cls, value, *args, **kwargs):
            calls.append(value)
            return cls()

    class FakeIndexTTS2:
        def __init__(self, **kwargs):
            from indextts.utils.maskgct_utils import Wav2Vec2BertModel

            Wav2Vec2BertModel.from_pretrained("facebook/w2v-bert-2.0")

    monkeypatch.setitem(
        __import__("sys").modules,
        "indextts.infer_v2",
        SimpleNamespace(IndexTTS2=FakeIndexTTS2),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "indextts.utils.maskgct_utils",
        SimpleNamespace(Wav2Vec2BertModel=FakeWav2Vec2BertModel),
    )

    adapter = LocalIndexTTSAdapter(
        model_dir=str(model_dir),
        cfg_path=str(cfg),
        prompt_audio=str(prompt),
        w2v_bert_dir=str(w2v_dir),
    )
    adapter._load_engine()

    assert calls == [str(w2v_dir)]


def test_local_indextts_rewrites_hub_assets_to_local_dirs(monkeypatch, tmp_path):
    from opentalking.providers.tts.local_indextts.adapter import LocalIndexTTSAdapter

    model_dir = tmp_path / "IndexTTS-2"
    model_dir.mkdir()
    cfg = model_dir / "config.yaml"
    cfg.write_text("test: true\n", encoding="utf-8")
    prompt = tmp_path / "prompt.wav"
    prompt.write_bytes(b"prompt")
    maskgct_dir = tmp_path / "amphion__MaskGCT"
    semantic_path = maskgct_dir / "semantic_codec" / "model.safetensors"
    semantic_path.parent.mkdir(parents=True)
    semantic_path.write_bytes(b"semantic")
    campplus_dir = tmp_path / "funasr__campplus"
    campplus_path = campplus_dir / "campplus_cn_common.bin"
    campplus_dir.mkdir()
    campplus_path.write_bytes(b"campplus")
    bigvgan_dir = tmp_path / "nvidia__bigvgan_v2_22khz_80band_256x"
    bigvgan_dir.mkdir()
    (bigvgan_dir / "config.json").write_text("{}", encoding="utf-8")
    (bigvgan_dir / "bigvgan_generator.pt").write_bytes(b"bigvgan")
    hub_results: list[str] = []
    bigvgan_calls: list[str] = []

    def fake_hf_hub_download(repo_id, filename, *args, **kwargs):
        if repo_id == "amphion/MaskGCT":
            return str(semantic_path)
        if repo_id == "funasr/campplus":
            return str(campplus_path)
        raise AssertionError(f"unexpected hub download: {repo_id} {filename}")

    class FakeBigVGAN:
        @classmethod
        def from_pretrained(cls, model_id, **kwargs):
            bigvgan_calls.append(model_id)
            return cls()

    class FakeIndexTTS2:
        def __init__(self, **kwargs):
            from indextts.infer_v2 import hf_hub_download
            from indextts.BigVGAN import bigvgan
            from indextts.s2mel.modules.bigvgan import bigvgan as s2mel_bigvgan

            hub_results.append(hf_hub_download("amphion/MaskGCT", filename="semantic_codec/model.safetensors"))
            hub_results.append(hf_hub_download("funasr/campplus", filename="campplus_cn_common.bin"))
            bigvgan.BigVGAN.from_pretrained("nvidia/bigvgan_v2_22khz_80band_256x")
            s2mel_bigvgan.BigVGAN.from_pretrained("nvidia/bigvgan_v2_22khz_80band_256x")

    fake_bigvgan_module = SimpleNamespace(BigVGAN=FakeBigVGAN)
    monkeypatch.setitem(sys.modules, "indextts", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "indextts.BigVGAN", SimpleNamespace(bigvgan=fake_bigvgan_module))
    monkeypatch.setitem(sys.modules, "indextts.s2mel", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "indextts.s2mel.modules", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "indextts.s2mel.modules.bigvgan", SimpleNamespace(bigvgan=fake_bigvgan_module))
    monkeypatch.setitem(
        sys.modules,
        "indextts.infer_v2",
        SimpleNamespace(IndexTTS2=FakeIndexTTS2, hf_hub_download=fake_hf_hub_download),
    )
    monkeypatch.setitem(
        sys.modules,
        "indextts.BigVGAN.bigvgan",
        fake_bigvgan_module,
    )
    monkeypatch.setitem(
        sys.modules,
        "indextts.s2mel.modules.bigvgan.bigvgan",
        fake_bigvgan_module,
    )

    adapter = LocalIndexTTSAdapter(
        model_dir=str(model_dir),
        cfg_path=str(cfg),
        prompt_audio=str(prompt),
        maskgct_dir=str(maskgct_dir),
        campplus_dir=str(campplus_dir),
        bigvgan_dir=str(bigvgan_dir),
    )
    adapter._load_engine()

    assert hub_results == [str(semantic_path), str(campplus_path)]
    assert bigvgan_calls == [str(bigvgan_dir), str(bigvgan_dir)]


def test_local_indextts_torchaudio_save_falls_back_without_torchcodec(tmp_path):
    from opentalking.providers.tts.local_indextts.adapter import LocalIndexTTSAdapter

    calls: list[str] = []

    class FakeTensor:
        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return np.array([[0, 1000, -1000, 0]], dtype=np.int16)

    class FakeTorchaudio:
        @staticmethod
        def save(path, tensor, sample_rate, *args, **kwargs):
            calls.append(path)
            raise RuntimeError("Could not load libtorchcodec")

    module = SimpleNamespace(torchaudio=FakeTorchaudio)
    LocalIndexTTSAdapter._patch_torchaudio_save(module)
    out = tmp_path / "out.wav"

    module.torchaudio.save(str(out), FakeTensor(), 16000)

    assert calls == [str(out)]
    with wave.open(str(out), "rb") as wf:
        assert wf.getframerate() == 16000
        assert wf.getnframes() == 4


def test_local_indextts_sidecar_rewrites_runtime_assets_to_local_dirs(monkeypatch, tmp_path):
    from scripts.local_indextts_service import LocalIndexTTSService

    model_dir = tmp_path / "IndexTTS-2"
    model_dir.mkdir()
    cfg = model_dir / "config.yaml"
    cfg.write_text("test: true\n", encoding="utf-8")
    prompt = tmp_path / "prompt.wav"
    prompt.write_bytes(b"prompt")
    w2v_dir = tmp_path / "facebook__w2v-bert-2.0"
    w2v_dir.mkdir()
    (w2v_dir / "preprocessor_config.json").write_text("{}", encoding="utf-8")
    maskgct_dir = tmp_path / "amphion__MaskGCT-ms"
    semantic_path = maskgct_dir / "semantic_codec" / "model.safetensors"
    semantic_path.parent.mkdir(parents=True)
    semantic_path.write_bytes(b"semantic")
    campplus_dir = tmp_path / "funasr__campplus"
    campplus_path = campplus_dir / "campplus_cn_common.bin"
    campplus_dir.mkdir()
    campplus_path.write_bytes(b"campplus")
    bigvgan_dir = tmp_path / "nvidia__bigvgan_v2_22khz_80band_256x"
    bigvgan_dir.mkdir()
    (bigvgan_dir / "config.json").write_text("{}", encoding="utf-8")
    (bigvgan_dir / "bigvgan_generator.pt").write_bytes(b"bigvgan")

    w2v_calls: list[str] = []
    semantic_calls: list[str] = []
    hub_results: list[str] = []
    bigvgan_calls: list[str] = []

    class FakeFeatureExtractor:
        @classmethod
        def from_pretrained(cls, value, *args, **kwargs):
            w2v_calls.append(value)
            return cls()

    class FakeWav2Vec2BertModel:
        @classmethod
        def from_pretrained(cls, value, *args, **kwargs):
            semantic_calls.append(value)
            return cls()

    def fake_hf_hub_download(repo_id, filename, *args, **kwargs):
        raise AssertionError(f"unexpected hub download: {repo_id} {filename}")

    class FakeBigVGAN:
        @classmethod
        def from_pretrained(cls, model_id, **kwargs):
            bigvgan_calls.append(model_id)
            return cls()

    class FakeIndexTTS2:
        def __init__(self, **kwargs):
            from indextts.infer_v2 import SeamlessM4TFeatureExtractor, hf_hub_download
            from indextts.BigVGAN import bigvgan
            from indextts.s2mel.modules.bigvgan import bigvgan as s2mel_bigvgan
            from indextts.utils.maskgct_utils import Wav2Vec2BertModel

            SeamlessM4TFeatureExtractor.from_pretrained("facebook/w2v-bert-2.0")
            Wav2Vec2BertModel.from_pretrained("facebook/w2v-bert-2.0")
            hub_results.append(hf_hub_download("amphion/MaskGCT", filename="semantic_codec/model.safetensors"))
            hub_results.append(hf_hub_download("funasr/campplus", filename="campplus_cn_common.bin"))
            bigvgan.BigVGAN.from_pretrained("nvidia/bigvgan_v2_22khz_80band_256x")
            s2mel_bigvgan.BigVGAN.from_pretrained("nvidia/bigvgan_v2_22khz_80band_256x")

    fake_bigvgan_module = SimpleNamespace(BigVGAN=FakeBigVGAN)
    fake_bigvgan_package = SimpleNamespace(bigvgan=fake_bigvgan_module)
    fake_s2mel_bigvgan_package = SimpleNamespace(bigvgan=fake_bigvgan_module)

    monkeypatch.setitem(sys.modules, "indextts", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "indextts.infer_v2",
        SimpleNamespace(
            IndexTTS2=FakeIndexTTS2,
            SeamlessM4TFeatureExtractor=FakeFeatureExtractor,
            hf_hub_download=fake_hf_hub_download,
        ),
    )
    monkeypatch.setitem(sys.modules, "indextts.utils", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "indextts.utils.maskgct_utils", SimpleNamespace(Wav2Vec2BertModel=FakeWav2Vec2BertModel))
    monkeypatch.setitem(sys.modules, "indextts.BigVGAN", fake_bigvgan_package)
    monkeypatch.setitem(sys.modules, "indextts.BigVGAN.bigvgan", fake_bigvgan_module)
    monkeypatch.setitem(sys.modules, "indextts.s2mel", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "indextts.s2mel.modules", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "indextts.s2mel.modules.bigvgan", fake_s2mel_bigvgan_package)
    monkeypatch.setitem(sys.modules, "indextts.s2mel.modules.bigvgan.bigvgan", fake_bigvgan_module)

    service = LocalIndexTTSService(
        model_dir=str(model_dir),
        cfg_path=str(cfg),
        prompt_audio=str(prompt),
        w2v_bert_dir=str(w2v_dir),
        maskgct_dir=str(maskgct_dir),
        campplus_dir=str(campplus_dir),
        bigvgan_dir=str(bigvgan_dir),
        device="auto",
        use_fp16=False,
        use_cuda_kernel=False,
        use_deepspeed=False,
    )
    service.model()

    assert w2v_calls == [str(w2v_dir)]
    assert semantic_calls == [str(w2v_dir)]
    assert hub_results == [str(semantic_path), str(campplus_path)]
    assert bigvgan_calls == [str(bigvgan_dir), str(bigvgan_dir)]


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


def test_local_cosyvoice_in_process_reads_runtime_flags(monkeypatch):
    from opentalking.providers.tts.local_cosyvoice import adapter as cosy_adapter

    loaded: dict[str, object] = {}

    class FakeAutoModel:
        def __init__(self, model_dir, **kwargs):
            loaded["model_dir"] = model_dir
            loaded["kwargs"] = kwargs

    monkeypatch.setitem(
        sys.modules,
        "cosyvoice.cli.cosyvoice",
        SimpleNamespace(AutoModel=FakeAutoModel),
    )
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL_DIR", "/models/cosyvoice3")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_DEVICE", "cuda:0")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_FP16", "auto")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_LOAD_TRT", "1")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_LOAD_JIT", "1")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_LOAD_VLLM", "0")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_TRT_CONCURRENT", "2")

    adapter = cosy_adapter.LocalCosyVoiceTTSAdapter(
        model="FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
    )

    assert isinstance(adapter._load_engine(), FakeAutoModel)
    assert loaded["model_dir"] == "/models/cosyvoice3"
    assert loaded["kwargs"] == {
        "load_jit": True,
        "load_trt": True,
        "load_vllm": False,
        "fp16": True,
        "trt_concurrent": 2,
    }


def test_local_cosyvoice_provider_config_reports_runtime_flags(monkeypatch):
    from opentalking.providers.tts.factory import tts_provider_config

    monkeypatch.setenv("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", "/tmp/opentalking-local-audio")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL", "http://127.0.0.1:19090/synthesize")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_DEVICE", "cuda:0")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_FP16", "auto")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_LOAD_TRT", "1")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_TRT_CONCURRENT", "2")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_TOKEN_HOP_LEN", "8")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_TOKEN_MAX_HOP_LEN", "16")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_STREAM_SCALE_FACTOR", "1")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_FLOW_N_TIMESTEPS", "4")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_MAX_TOKEN_TEXT_RATIO", "6")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_MASK_STOP_TOKENS", "1")

    status = tts_provider_config("local_cosyvoice")

    assert status["service_url"] == "http://127.0.0.1:19090/synthesize"
    assert status["device"] == "cuda:0"
    assert status["fp16"] == "auto"
    assert status["load_trt"] is True
    assert status["trt_concurrent"] == 2
    assert status["token_hop_len"] == 8
    assert status["token_max_hop_len"] == 16
    assert status["stream_scale_factor"] == 1
    assert status["flow_n_timesteps"] == 4
    assert status["max_token_text_ratio"] == 6.0
    assert status["mask_stop_tokens"] is True


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

    monkeypatch.setenv("OPENTALKING_STT_DEFAULT_PROVIDER", "funasr")

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

    monkeypatch.setenv("OPENTALKING_STT_DEFAULT_PROVIDER", "sensevoice")
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
    monkeypatch.setenv("OPENTALKING_STT_DEFAULT_PROVIDER", "sensevoice")
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
    monkeypatch.setenv("OPENTALKING_STT_DEFAULT_PROVIDER", "funasr")
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


def test_download_script_default_models_use_verified_12g_set(monkeypatch):
    monkeypatch.delenv("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", raising=False)
    from scripts import download_local_audio_models as downloader

    downloader = importlib.reload(downloader)
    selected = downloader.default_model_keys()

    assert selected == ["sensevoice-small", "fun-cosyvoice3-0.5b-2512"]
    assert set(selected).issubset(downloader.MODELS)
    assert {
        "indextts2",
        "indextts2-w2v-bert",
        "indextts2-maskgct",
        "indextts2-campplus",
        "indextts2-bigvgan",
    }.issubset(downloader.MODELS)
    assert downloader.DEFAULT_ROOT == Path("./models/local-audio")
    assert "/data2" not in Path("scripts/download_local_audio_models.py").read_text(encoding="utf-8")


def test_quicktalk_cuda_extra_declares_gpu_onnxruntime():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "quicktalk-cpu" in pyproject
    assert "quicktalk-cuda" in pyproject
    assert "onnxruntime>=1.24.3" in pyproject
    assert "onnxruntime-gpu>=1.24.0" in pyproject
    assert "imageio-ffmpeg>=0.5" in pyproject

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


def test_quicktalk_onnx_provider_prefers_coreml_for_mps(monkeypatch):
    from opentalking.models.quicktalk import runtime_v2

    monkeypatch.setattr(
        runtime_v2.ort,
        "get_available_providers",
        lambda: ["CoreMLExecutionProvider", "CPUExecutionProvider"],
    )

    assert runtime_v2._onnx_providers_for_device(runtime_v2.torch.device("mps")) == [
        "CoreMLExecutionProvider",
        "CPUExecutionProvider",
    ]


def test_quicktalk_onnx_provider_keeps_cuda_for_cuda_device(monkeypatch):
    from opentalking.models.quicktalk import runtime_v2

    monkeypatch.setattr(
        runtime_v2.ort,
        "get_available_providers",
        lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"],
    )

    assert runtime_v2._onnx_providers_for_device(runtime_v2.torch.device("cuda:2")) == [
        ("CUDAExecutionProvider", {"device_id": 2}),
        "CPUExecutionProvider",
    ]


def test_quicktalk_runtime_uses_imageio_ffmpeg_fallback(monkeypatch):
    import types

    from opentalking.models.quicktalk import runtime_v2

    monkeypatch.delenv("OPENTALKING_FFMPEG_BIN", raising=False)
    monkeypatch.setattr(runtime_v2.shutil, "which", lambda _: None)

    fake_imageio = types.SimpleNamespace(get_ffmpeg_exe=lambda: "/tmp/ffmpeg-imageio")
    monkeypatch.setitem(runtime_v2.sys.modules, "imageio_ffmpeg", fake_imageio)

    assert runtime_v2.ensure_ffmpeg() == "/tmp/ffmpeg-imageio"


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


def test_cosyvoice_service_applies_validated_runtime_tuning(monkeypatch):
    from scripts import local_cosyvoice_service as service_module

    loaded: dict[str, object] = {}

    class FakeScores:
        def __init__(self, values):
            self.values = list(values)

        def __len__(self):
            return len(self.values)

        def __setitem__(self, key, value):
            if isinstance(key, list):
                for item in key:
                    self.values[item] = value
            else:
                self.values[key] = value

        def clone(self):
            return FakeScores(self.values)

    class FakeLLM:
        def __init__(self):
            self.calls = []
            self.sampled_scores = []
            self.stop_token_ids = [3, 4, 5]

        def inference(self, **kwargs):
            self.calls.append(kwargs)
            yield "token"

        def sampling_ids(self, weighted_scores, decoded_tokens, sampling, ignore_eos=True):
            return "original"

        def sampling(self, weighted_scores, decoded_tokens, sampling):
            self.sampled_scores = list(weighted_scores.values)
            return "sampled"

    class FakeModel:
        token_hop_len = 25
        token_max_hop_len = 100
        stream_scale_factor = 2

        def __init__(self):
            self.llm = FakeLLM()
            self.flow = SimpleNamespace(inference_n_timesteps=10)

    class FakeAutoModel:
        fp16 = True
        sample_rate = 24000

        def __init__(self, **kwargs):
            loaded.update(kwargs)
            self.model = FakeModel()

    monkeypatch.setitem(
        sys.modules,
        "cosyvoice.cli.cosyvoice",
        SimpleNamespace(AutoModel=FakeAutoModel),
    )

    service = service_module.CosyVoiceService(
        model_dir="/tmp/model",
        runtime_dir="/tmp/runtime",
        device="cpu",
        prompt_audio="prompt.wav",
        prompt_text="参考文本",
        mode="zero_shot",
        instruction="",
        fp16=True,
        load_trt=True,
        trt_concurrent=2,
        token_hop_len=8,
        token_max_hop_len=16,
        stream_scale_factor=1,
        flow_n_timesteps=4,
        max_token_text_ratio=6.0,
        min_token_text_ratio=1.0,
        mask_stop_tokens=True,
    )
    engine = service.model()

    assert loaded["load_trt"] is True
    assert loaded["trt_concurrent"] == 2
    assert service.health_payload()["streaming"] == {
        "token_hop_len": 8,
        "token_max_hop_len": 16,
        "stream_scale_factor": 1,
    }
    assert service.health_payload()["flow"] == {"inference_n_timesteps": 4}
    assert service.health_payload()["llm_token_ratio"] == {
        "max_token_text_ratio": 6.0,
        "min_token_text_ratio": 1.0,
    }
    assert service.health_payload()["llm_stop_token_patch"] == {"stop_token_count": 3}

    assert list(engine.model.llm.inference(text="你好")) == ["token"]
    assert engine.model.llm.calls[-1]["max_token_text_ratio"] == 6.0
    assert engine.model.llm.calls[-1]["min_token_text_ratio"] == 1.0
    scores = FakeScores([0.0] * 8)
    assert engine.model.llm.sampling_ids(scores, [], 25, ignore_eos=True) == "sampled"
    assert scores.values == [0.0] * 8
    assert engine.model.llm.sampled_scores[3:6] == [-float("inf")] * 3
    assert engine.model.llm.sampling_ids(scores, [], 25, ignore_eos=False) == "original"


def test_cosyvoice_service_resets_streaming_tuning_per_request(monkeypatch):
    from scripts import local_cosyvoice_service as service_module

    class FakeEngine:
        sample_rate = 16000
        token_hop_len = 8
        token_max_hop_len = 16
        stream_scale_factor = 1

        def inference_zero_shot(self, text, prompt_text, prompt_audio, stream=True):
            self.token_hop_len = 99
            yield {"tts_speech": np.zeros(160, dtype=np.float32)}

    engine = FakeEngine()
    service_module.apply_streaming_tuning(
        engine,
        token_hop_len=8,
        token_max_hop_len=16,
        stream_scale_factor=1,
    )
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
    monkeypatch.setattr(service, "model", lambda: engine)

    stream, _sr = service.synthesize_pcm_stream(service_module.SynthesizeRequest(text="你好"))
    assert b"".join(stream)

    assert engine.token_hop_len == 8
    assert engine.token_max_hop_len == 16
    assert engine.stream_scale_factor == 1


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
