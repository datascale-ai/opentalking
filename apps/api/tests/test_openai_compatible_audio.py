from __future__ import annotations

import asyncio
import base64
import io
import json
import queue
import wave
from pathlib import Path

import httpx
import numpy as np
import pytest


def _wav_bytes() -> bytes:
    pcm = np.array([0, 1200, -1200, 0], dtype="<i2")
    out = io.BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(pcm.tobytes())
    return out.getvalue()


def test_tts_openai_compatible_status_reads_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from opentalking.providers.tts import factory

    monkeypatch.setenv("OPENTALKING_TTS_DEFAULT_PROVIDER", "openai_compatible")
    monkeypatch.setenv("OPENTALKING_TTS_OPENAI_BASE_URL", "https://api.example.test/v1")
    monkeypatch.setenv("OPENTALKING_TTS_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENTALKING_TTS_OPENAI_MODEL", "voice-test-tts")
    monkeypatch.setenv("OPENTALKING_TTS_OPENAI_VOICE", "neutral-test")
    monkeypatch.setenv("OPENTALKING_TTS_OPENAI_PROTOCOL", "audio_speech")

    status = factory.tts_status()

    assert status["provider"] == "openai_compatible"
    assert status["model"] == "voice-test-tts"
    assert status["voice"] == "neutral-test"
    assert status["key_set"] is True
    assert status["service_url_set"] is True


def test_tts_openai_compatible_posts_audio_speech(monkeypatch: pytest.MonkeyPatch) -> None:
    import opentalking.providers.tts.openai_compatible.adapter as adapter_mod
    from opentalking.providers.tts.factory import build_tts_adapter

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        payload = json.loads(request.content.decode("utf-8"))
        assert payload == {
            "model": "voice-test-tts",
            "input": "你好，开始测试。",
            "voice": "neutral-test",
            "response_format": "wav",
        }
        return httpx.Response(200, content=_wav_bytes(), headers={"Content-Type": "audio/wav"})

    transport = httpx.MockTransport(handler)

    class PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(adapter_mod.httpx, "AsyncClient", PatchedAsyncClient)
    monkeypatch.setenv("OPENTALKING_TTS_DEFAULT_PROVIDER", "openai_compatible")
    monkeypatch.setenv("OPENTALKING_TTS_OPENAI_BASE_URL", "https://api.example.test/v1")
    monkeypatch.setenv("OPENTALKING_TTS_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENTALKING_TTS_OPENAI_MODEL", "voice-test-tts")
    monkeypatch.setenv("OPENTALKING_TTS_OPENAI_VOICE", "neutral-test")
    monkeypatch.setenv("OPENTALKING_TTS_OPENAI_PROTOCOL", "audio_speech")

    tts = build_tts_adapter(
        sample_rate=16000,
        chunk_ms=20.0,
        tts_provider="openai_compatible",
    )
    chunks = asyncio.run(_collect_tts_chunks(tts, "你好，开始测试。"))

    assert chunks
    assert str(captured[0].url) == "https://api.example.test/v1/audio/speech"
    assert captured[0].headers["authorization"] == "Bearer test-key"


def test_tts_openai_compatible_chat_completions_posts_audio_request(monkeypatch: pytest.MonkeyPatch) -> None:
    import opentalking.providers.tts.openai_compatible.adapter as adapter_mod
    from opentalking.providers.tts.openai_compatible.adapter import OpenAICompatibleTTSAdapter

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        payload = json.loads(request.content.decode("utf-8"))
        assert payload == {
            "model": "mimo-v2.5-tts",
            "messages": [
                {"role": "user", "content": "自然朗读。"},
                {"role": "assistant", "content": "你好，开始测试。"},
            ],
            "audio": {"format": "wav", "voice": "mimo_default"},
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"audio": {"data": base64.b64encode(_wav_bytes()).decode("ascii")}}}]},
        )

    transport = httpx.MockTransport(handler)

    class PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(adapter_mod.httpx, "AsyncClient", PatchedAsyncClient)
    tts = OpenAICompatibleTTSAdapter(
        api_key="test-key",
        base_url="https://token-plan-cn.xiaomimimo.com/v1",
        model="mimo-v2.5-tts",
        default_voice="mimo_default",
        response_format="wav",
        protocol="chat_completions",
        prompt="自然朗读。",
        sample_rate=16000,
        chunk_ms=20.0,
    )

    chunks = asyncio.run(_collect_tts_chunks(tts, "你好，开始测试。"))

    assert chunks
    assert str(captured[0].url) == "https://token-plan-cn.xiaomimimo.com/v1/chat/completions"
    assert captured[0].headers["authorization"] == "Bearer test-key"


def test_tts_xiaomi_mimo_profile_posts_chat_completions_voiceclone(monkeypatch: pytest.MonkeyPatch) -> None:
    import opentalking.providers.tts.openai_compatible.adapter as adapter_mod
    from opentalking.providers.tts.factory import build_tts_adapter

    captured: list[httpx.Request] = []
    data_uri = "data:audio/wav;base64," + base64.b64encode(_wav_bytes()).decode("ascii")

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        payload = json.loads(request.content.decode("utf-8"))
        assert payload == {
            "model": "mimo-v2.5-tts-voiceclone",
            "messages": [
                {"role": "user", "content": "自然、清晰、口语化的普通话。"},
                {"role": "assistant", "content": "你好，开始测试。"},
            ],
            "audio": {"format": "wav", "voice": data_uri},
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"audio": {"data": base64.b64encode(_wav_bytes()).decode("ascii")}}}]},
        )

    transport = httpx.MockTransport(handler)

    class PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(adapter_mod.httpx, "AsyncClient", PatchedAsyncClient)
    monkeypatch.setenv("OPENTALKING_TTS_DEFAULT_PROVIDER", "xiaomi_mimo")
    monkeypatch.setenv("OPENTALKING_TTS_XIAOMI_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")
    monkeypatch.setenv("OPENTALKING_TTS_XIAOMI_API_KEY", "test-key")
    monkeypatch.setenv("OPENTALKING_TTS_XIAOMI_MODEL", "mimo-v2.5-tts")
    monkeypatch.setenv("OPENTALKING_TTS_XIAOMI_VOICE", "mimo_default")
    monkeypatch.setenv("OPENTALKING_TTS_XIAOMI_PROTOCOL", "chat_completions")
    monkeypatch.setenv("OPENTALKING_TTS_XIAOMI_RESPONSE_FORMAT", "wav")

    tts = build_tts_adapter(
        sample_rate=16000,
        chunk_ms=20.0,
        default_voice=data_uri,
        tts_provider="xiaomi_mimo",
        tts_model="mimo-v2.5-tts-voiceclone",
    )
    chunks = asyncio.run(_collect_tts_chunks(tts, "你好，开始测试。"))

    assert chunks
    assert str(captured[0].url) == "https://token-plan-cn.xiaomimimo.com/v1/chat/completions"
    assert captured[0].headers["authorization"] == "Bearer test-key"


def test_tts_xiaomi_mimo_profile_does_not_use_generic_openai_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from opentalking.core.config import get_settings
    from opentalking.providers.tts import factory

    monkeypatch.chdir(Path.cwd() / "apps" / "api" / "tests")
    get_settings.cache_clear()
    monkeypatch.setenv("OPENTALKING_TTS_DEFAULT_PROVIDER", "xiaomi_mimo")
    monkeypatch.setenv("OPENTALKING_TTS_OPENAI_BASE_URL", "https://api.example.test/v1")
    monkeypatch.setenv("OPENTALKING_TTS_OPENAI_API_KEY", "generic-key")
    monkeypatch.delenv("OPENTALKING_TTS_XIAOMI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENTALKING_TTS_XIAOMI_API_KEY", raising=False)
    monkeypatch.delenv("OPENTALKING_TTS_XIAOMI_MIMO_BASE_URL", raising=False)
    monkeypatch.delenv("OPENTALKING_TTS_XIAOMI_MIMO_API_KEY", raising=False)

    status = factory.tts_status()

    assert status["provider"] == "xiaomi_mimo"
    assert status["key_set"] is False
    assert status["service_url_set"] is False


async def _collect_tts_chunks(tts, text: str):
    return [chunk async for chunk in tts.synthesize_stream(text)]


def test_stt_openai_compatible_status_reads_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from opentalking.providers.stt import factory

    monkeypatch.setenv("OPENTALKING_STT_DEFAULT_PROVIDER", "openai_compatible")
    monkeypatch.setenv("OPENTALKING_STT_OPENAI_BASE_URL", "https://api.example.test/v1")
    monkeypatch.setenv("OPENTALKING_STT_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENTALKING_STT_OPENAI_MODEL", "whisper-compatible")
    monkeypatch.setenv("OPENTALKING_STT_OPENAI_PROTOCOL", "audio_transcriptions")

    status = factory.stt_status()

    assert status["provider"] == "openai_compatible"
    assert status["model"] == "whisper-compatible"
    assert status["model_dir"] == ""
    assert status["key_set"] is True
    assert status["service_url_set"] is True


def test_stt_openai_compatible_posts_audio_transcriptions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import opentalking.providers.stt.openai_compatible.adapter as adapter_mod
    from opentalking.providers.stt.factory import transcribe_wav_path_sync

    wav_path = tmp_path / "speech.wav"
    wav_path.write_bytes(_wav_bytes())
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        body = request.content
        assert b"whisper-compatible" in body
        assert b"speech.wav" in body
        return httpx.Response(200, json={"text": "你好，测试完成。"})

    transport = httpx.MockTransport(handler)

    class PatchedClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(adapter_mod.httpx, "Client", PatchedClient)
    monkeypatch.setenv("OPENTALKING_STT_DEFAULT_PROVIDER", "openai_compatible")
    monkeypatch.setenv("OPENTALKING_STT_OPENAI_BASE_URL", "https://api.example.test/v1")
    monkeypatch.setenv("OPENTALKING_STT_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENTALKING_STT_OPENAI_MODEL", "whisper-compatible")
    monkeypatch.setenv("OPENTALKING_STT_OPENAI_PROTOCOL", "audio_transcriptions")
    factory = __import__("opentalking.providers.stt.factory", fromlist=["clear_stt_adapter_cache"])
    factory.clear_stt_adapter_cache()

    text, elapsed_ms = transcribe_wav_path_sync(wav_path)

    assert text == "你好，测试完成。"
    assert elapsed_ms >= 0
    assert str(captured[0].url) == "https://api.example.test/v1/audio/transcriptions"
    assert captured[0].headers["authorization"] == "Bearer test-key"


def test_stt_openai_compatible_chat_completions_posts_data_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import opentalking.providers.stt.openai_compatible.adapter as adapter_mod
    from opentalking.providers.stt.openai_compatible.adapter import OpenAICompatibleSTTAdapter

    wav_path = tmp_path / "speech.wav"
    wav_path.write_bytes(_wav_bytes())
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        payload = json.loads(request.content.decode("utf-8"))
        audio = payload["messages"][0]["content"][0]["input_audio"]
        assert payload["model"] == "mimo-v2.5-asr"
        assert audio["format"] == "wav"
        assert audio["data"].startswith("data:audio/wav;base64,")
        return httpx.Response(200, json={"choices": [{"message": {"content": "你好，测试完成。"}}]})

    transport = httpx.MockTransport(handler)

    class PatchedClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(adapter_mod.httpx, "Client", PatchedClient)
    adapter = OpenAICompatibleSTTAdapter(
        api_key="test-key",
        base_url="https://token-plan-cn.xiaomimimo.com/v1",
        model="mimo-v2.5-asr",
        protocol="chat_completions",
        audio_format="wav",
    )

    text, elapsed_ms = adapter.transcribe_wav(wav_path)

    assert text == "你好，测试完成。"
    assert elapsed_ms >= 0
    assert str(captured[0].url) == "https://token-plan-cn.xiaomimimo.com/v1/chat/completions"
    assert captured[0].headers["authorization"] == "Bearer test-key"


def test_stt_xiaomi_mimo_status_reads_profile_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from opentalking.providers.stt import factory

    monkeypatch.setenv("OPENTALKING_STT_DEFAULT_PROVIDER", "xiaomi_mimo")
    monkeypatch.setenv("OPENTALKING_STT_OPENAI_BASE_URL", "https://api.example.test/v1")
    monkeypatch.setenv("OPENTALKING_STT_OPENAI_API_KEY", "generic-key")
    monkeypatch.setenv("OPENTALKING_STT_OPENAI_MODEL", "whisper-compatible")
    monkeypatch.setenv("OPENTALKING_STT_XIAOMI_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")
    monkeypatch.setenv("OPENTALKING_STT_XIAOMI_API_KEY", "xiaomi-key")
    monkeypatch.setenv("OPENTALKING_STT_XIAOMI_MODEL", "mimo-v2.5-asr")
    monkeypatch.setenv("OPENTALKING_STT_XIAOMI_PROTOCOL", "chat_completions")

    status = factory.stt_status()

    assert status["provider"] == "xiaomi_mimo"
    assert status["profile"] == "xiaomi_mimo"
    assert status["model"] == "mimo-v2.5-asr"
    assert status["model_dir"] == ""
    assert status["key_set"] is True
    assert status["service_url_set"] is True


def test_stt_xiaomi_mimo_profile_posts_chat_completions_data_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import opentalking.providers.stt.openai_compatible.adapter as adapter_mod
    from opentalking.providers.stt.factory import clear_stt_adapter_cache, transcribe_wav_path_sync

    wav_path = tmp_path / "speech.wav"
    wav_path.write_bytes(_wav_bytes())
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        payload = json.loads(request.content.decode("utf-8"))
        audio = payload["messages"][0]["content"][0]["input_audio"]
        assert payload["model"] == "mimo-v2.5-asr"
        assert audio["format"] == "wav"
        assert audio["data"].startswith("data:audio/wav;base64,")
        return httpx.Response(200, json={"choices": [{"message": {"content": "小米识别完成。"}}]})

    transport = httpx.MockTransport(handler)

    class PatchedClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(adapter_mod.httpx, "Client", PatchedClient)
    monkeypatch.setenv("OPENTALKING_STT_DEFAULT_PROVIDER", "xiaomi_mimo")
    monkeypatch.setenv("OPENTALKING_STT_XIAOMI_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")
    monkeypatch.setenv("OPENTALKING_STT_XIAOMI_API_KEY", "xiaomi-key")
    monkeypatch.setenv("OPENTALKING_STT_XIAOMI_MODEL", "mimo-v2.5-asr")
    monkeypatch.setenv("OPENTALKING_STT_XIAOMI_PROTOCOL", "chat_completions")
    monkeypatch.setenv("OPENTALKING_STT_XIAOMI_AUDIO_FORMAT", "wav")
    clear_stt_adapter_cache()

    text, elapsed_ms = transcribe_wav_path_sync(wav_path)

    assert text == "小米识别完成。"
    assert elapsed_ms >= 0
    assert str(captured[0].url) == "https://token-plan-cn.xiaomimimo.com/v1/chat/completions"
    assert captured[0].headers["authorization"] == "Bearer xiaomi-key"


def test_stt_openai_compatible_transcribes_pcm_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    from opentalking.providers.stt.openai_compatible.adapter import OpenAICompatibleSTTAdapter

    seen: list[Path] = []
    adapter = OpenAICompatibleSTTAdapter(
        api_key="test-key",
        base_url="https://token-plan-cn.xiaomimimo.com/v1",
        model="mimo-v2.5-asr",
    )

    def fake_transcribe_wav(wav_path: str | Path):
        path = Path(wav_path)
        seen.append(path)
        assert path.read_bytes().startswith(b"RIFF")
        return "队列识别完成。", 12.0

    monkeypatch.setattr(adapter, "transcribe_wav", fake_transcribe_wav)
    q: queue.Queue[bytes | None] = queue.Queue()
    q.put(np.array([0, 1000, -1000], dtype="<i2").tobytes())
    q.put(None)

    text, elapsed_ms = adapter.transcribe_pcm_queue(q, sample_rate=16000)

    assert text == "队列识别完成。"
    assert elapsed_ms == 12.0
    assert seen
