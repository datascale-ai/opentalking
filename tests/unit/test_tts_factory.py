from __future__ import annotations

from types import SimpleNamespace
import asyncio
import base64
import sys
import threading
import time
import types

import numpy as np

from opentalking.providers.tts.factory import build_tts_adapter, create_tts_adapter
from opentalking.providers.tts.dashscope_qwen.adapter import _qwen_cantonese_voice_override, _qwen_language_type
from opentalking.providers.tts.qwen_tts_voices import normalize_optional_qwen_voice


def _settings(**overrides):
    defaults = {
        "normalized_tts_provider": "edge",
        "tts_voice": "zh-CN-XiaoxiaoNeural",
        "ffmpeg_bin": "ffmpeg",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_build_tts_adapter_uses_edge_provider():
    adapter = build_tts_adapter(
        sample_rate=16000,
        chunk_ms=20.0,
        settings=_settings(normalized_tts_provider="edge"),
    )
    assert adapter.__class__.__name__ == "EdgeTTSAdapter"


def test_build_tts_adapter_auto_falls_back_without_reference():
    adapter = build_tts_adapter(
        sample_rate=16000,
        chunk_ms=20.0,
        settings=_settings(normalized_tts_provider="auto"),
    )
    assert adapter.__class__.__name__ == "EdgeTTSAdapter"


def test_build_tts_adapter_uses_request_provider_override():
    adapter = build_tts_adapter(
        sample_rate=16000,
        chunk_ms=20.0,
        settings=_settings(normalized_tts_provider="edge", tts_voice="zh-CN-XiaoxiaoNeural"),
        default_voice="Cherry",
        tts_provider="dashscope",
        tts_model="qwen3-tts-flash-realtime",
    )

    assert adapter.__class__.__name__ == "DashScopeQwenTTSAdapter"
    assert adapter.default_voice == "Cherry"
    assert adapter._model == "qwen3-tts-flash-realtime"


def test_create_tts_adapter_builds_elevenlabs_for_request_override(monkeypatch):
    monkeypatch.setenv("OPENTALKING_TTS_ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setenv("OPENTALKING_TTS_ELEVENLABS_VOICE_ID", "env-voice")

    adapter = create_tts_adapter(
        sample_rate=16000,
        chunk_ms=20.0,
        default_voice="request-voice",
        tts_provider="elevenlabs",
    )

    assert adapter.__class__.__name__ == "ElevenLabsTTSAdapter"
    assert adapter.default_voice == "request-voice"


def test_qwen_tts_normalizes_cantonese_voice_aliases():
    assert normalize_optional_qwen_voice("kiki") == "Kiki"
    assert normalize_optional_qwen_voice("rocky") == "Rocky"


def test_qwen_tts_cantonese_env_uses_chinese_language_type(monkeypatch):
    monkeypatch.setenv("OPENTALKING_QWEN_TTS_LANGUAGE", "cantonese")

    assert _qwen_language_type() == "Chinese"
    assert _qwen_cantonese_voice_override() == "Kiki"


def test_qwen_tts_cantonese_voice_override_can_select_rocky(monkeypatch):
    monkeypatch.setenv("OPENTALKING_QWEN_TTS_DIALECT", "yue")
    monkeypatch.setenv("OPENTALKING_QWEN_TTS_CANTONESE_VOICE", "rocky")

    assert _qwen_cantonese_voice_override() == "Rocky"


def test_qwen_tts_one_shot_keeps_callback_alive(monkeypatch):
    from opentalking.providers.tts.dashscope_qwen.adapter import DashScopeQwenTTSAdapter

    pcm = np.array([1000] * 960, dtype=np.int16).tobytes()

    class FakeCallback:
        pass

    class FakeClient:
        def __init__(self, *, callback, **_kwargs):
            self.callback = callback
            self.ready = False

        def connect(self):
            return None

        def update_session(self, **_kwargs):
            def mark_ready():
                time.sleep(0.05)
                self.ready = True
                self.callback.on_event({"type": "session.updated"})

            threading.Thread(target=mark_ready, daemon=True).start()

        def append_text(self, _text):
            return None

        def commit(self):
            if self.ready:
                self.callback.on_event({"type": "response.audio.delta", "delta": base64.b64encode(pcm).decode()})
                self.callback.on_event({"type": "response.done"})

        def finish(self):
            return None

        def close(self):
            return None

    audio_format = SimpleNamespace(PCM_24000HZ_MONO_16BIT="pcm")
    realtime = types.ModuleType("dashscope.audio.qwen_tts_realtime")
    realtime.AudioFormat = audio_format
    realtime.QwenTtsRealtime = FakeClient
    realtime.QwenTtsRealtimeCallback = FakeCallback
    fake_audio = types.ModuleType("dashscope.audio")
    fake_dashscope = types.ModuleType("dashscope")
    fake_dashscope.api_key = None
    fake_dashscope.audio = fake_audio
    monkeypatch.setitem(sys.modules, "dashscope", fake_dashscope)
    monkeypatch.setitem(sys.modules, "dashscope.audio", fake_audio)
    monkeypatch.setitem(sys.modules, "dashscope.audio.qwen_tts_realtime", realtime)
    monkeypatch.setenv("OPENTALKING_TTS_DASHSCOPE_API_KEY", "test-key")

    async def collect():
        adapter = DashScopeQwenTTSAdapter(reuse_ws=False)
        return [chunk async for chunk in adapter.synthesize_stream("你好")]

    chunks = asyncio.run(asyncio.wait_for(collect(), timeout=0.5))
    assert chunks
