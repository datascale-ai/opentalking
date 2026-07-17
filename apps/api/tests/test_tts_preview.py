from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from opentalking.core.types.frames import AudioChunk


def test_tts_preview_returns_wav_with_request_overrides(monkeypatch):
    from apps.api.routes import tts_preview

    calls: list[dict[str, object]] = []

    class FakeTTS:
        async def synthesize_stream(self, text: str, voice: str | None = None):
            calls.append({"text": text, "voice": voice})
            yield AudioChunk(
                data=np.array([0, 1000, -1000, 0], dtype=np.int16),
                sample_rate=16000,
                duration_ms=0.25,
            )

        async def aclose(self) -> None:
            calls.append({"closed": True})

    def fake_build_tts_adapter(**kwargs):
        calls.append(kwargs)
        return FakeTTS()

    monkeypatch.setattr(tts_preview, "build_tts_adapter", fake_build_tts_adapter)

    app = FastAPI()
    app.include_router(tts_preview.router)
    client = TestClient(app)

    response = client.post(
        "/tts/preview",
        json={
            "text": "你好，我在调试复刻音色。",
            "voice": "voice-clone-1",
            "tts_provider": "dashscope",
            "tts_model": "qwen3-tts-flash-realtime",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content.startswith(b"RIFF")
    assert calls[0]["default_voice"] == "voice-clone-1"
    assert calls[0]["tts_provider"] == "dashscope"
    assert calls[0]["tts_model"] == "qwen3-tts-flash-realtime"
    assert calls[1] == {"text": "你好，我在调试复刻音色。", "voice": "voice-clone-1"}
    assert calls[-1] == {"closed": True}


def test_tts_preview_duo_dialog_uses_per_role_tts_settings(monkeypatch):
    from apps.api.routes import tts_preview

    calls: list[dict[str, object]] = []

    class FakeTTS:
        def __init__(self, provider: str | None) -> None:
            self.provider = provider

        async def synthesize_stream(self, text: str, voice: str | None = None):
            calls.append({"text": text, "voice": voice, "provider": self.provider})
            value = 1000 if self.provider == "edge" else 2000
            yield AudioChunk(
                data=np.full(4, value, dtype=np.int16),
                sample_rate=16000,
                duration_ms=0.25,
            )

        async def aclose(self) -> None:
            calls.append({"closed": self.provider})

    def fake_build_tts_adapter(**kwargs):
        calls.append(kwargs)
        return FakeTTS(kwargs.get("tts_provider"))

    monkeypatch.setattr(tts_preview, "build_tts_adapter", fake_build_tts_adapter)

    app = FastAPI()
    app.include_router(tts_preview.router)
    client = TestClient(app)

    response = client.post(
        "/tts/preview-duo-dialog",
        json={
            "lines": [
                {"id": "line-1", "role": "male", "text": "男声开场"},
                {"id": "line-2", "role": "female", "text": "女声回应"},
            ],
            "gap_ms": 120,
            "speakers": {
                "male": {
                    "tts_provider": "edge",
                    "voice": "zh-CN-YunxiNeural",
                },
                "female": {
                    "tts_provider": "xiaomi_mimo",
                    "tts_model": "mimo-v2.5-tts",
                    "voice": "冰糖",
                },
            },
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content.startswith(b"RIFF")
    assert calls[0]["tts_provider"] == "edge"
    assert calls[0]["default_voice"] == "zh-CN-YunxiNeural"
    assert calls[1] == {"text": "男声开场", "voice": "zh-CN-YunxiNeural", "provider": "edge"}
    assert calls[3]["tts_provider"] == "xiaomi_mimo"
    assert calls[3]["tts_model"] == "mimo-v2.5-tts"
    assert calls[3]["default_voice"] == "冰糖"
    assert calls[4] == {"text": "女声回应", "voice": "冰糖", "provider": "xiaomi_mimo"}


def test_tts_preview_allows_video_creation_length_text(monkeypatch):
    from apps.api.routes import tts_preview

    calls: list[dict[str, object]] = []

    class FakeTTS:
        async def synthesize_stream(self, text: str, voice: str | None = None):
            calls.append({"text": text, "voice": voice})
            yield AudioChunk(
                data=np.array([0, 1000, -1000, 0], dtype=np.int16),
                sample_rate=16000,
                duration_ms=0.25,
            )

        async def aclose(self) -> None:
            calls.append({"closed": True})

    def fake_build_tts_adapter(**kwargs):
        calls.append(kwargs)
        return FakeTTS()

    monkeypatch.setattr(tts_preview, "build_tts_adapter", fake_build_tts_adapter)

    app = FastAPI()
    app.include_router(tts_preview.router)
    client = TestClient(app)
    text = "测" * 1000

    response = client.post(
        "/tts/preview",
        json={
            "text": text,
            "voice": "indextts-default",
            "tts_provider": "omnirt_indextts",
            "tts_model": "IndexTeam/IndexTTS-2",
        },
    )

    assert response.status_code == 200
    assert calls[1] == {"text": text, "voice": "indextts-default"}



def test_tts_preview_passes_indextts_config(monkeypatch):
    from apps.api.routes import tts_preview

    calls: list[dict[str, object]] = []

    class FakeTTS:
        async def synthesize_stream(self, text: str, voice: str | None = None):
            yield AudioChunk(
                data=np.array([0, 1000, -1000, 0], dtype=np.int16),
                sample_rate=16000,
                duration_ms=0.25,
            )

    def fake_build_tts_adapter(**kwargs):
        calls.append(kwargs)
        return FakeTTS()

    monkeypatch.setattr(tts_preview, "build_tts_adapter", fake_build_tts_adapter)

    app = FastAPI()
    app.include_router(tts_preview.router)
    client = TestClient(app)

    response = client.post(
        "/tts/preview",
        json={
            "text": "你好",
            "voice": "indextts-default",
            "tts_provider": "indextts",
            "tts_model": "IndexTeam/IndexTTS-2",
            "indextts_config": {
                "emotion_mode": "vector",
                "emo_alpha": 0.8,
                "emo_vector": [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                "use_random": True,
                "streaming_mode": "segment",
                "max_text_tokens_per_segment": 80,
                "quick_streaming_tokens": 4,
            },
        },
    )

    assert response.status_code == 200
    assert calls[0]["indextts_config"] == {
        "emo_alpha": 0.8,
        "emo_vector": [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "use_random": True,
        "streaming_mode": "segment",
        "max_text_tokens_per_segment": 80,
        "quick_streaming_tokens": 4,
    }


def test_tts_preview_logs_voice_and_indextts_emotion_config(monkeypatch, caplog):
    from apps.api.routes import tts_preview

    class FakeTTS:
        async def synthesize_stream(self, text: str, voice: str | None = None):
            yield AudioChunk(
                data=np.array([0, 1000, -1000, 0], dtype=np.int16),
                sample_rate=16000,
                duration_ms=0.25,
            )

    def fake_build_tts_adapter(**kwargs):
        return FakeTTS()

    monkeypatch.setattr(tts_preview, "build_tts_adapter", fake_build_tts_adapter)
    caplog.set_level(logging.INFO, logger="apps.api.routes.tts_preview")

    app = FastAPI()
    app.include_router(tts_preview.router)
    client = TestClient(app)

    response = client.post(
        "/tts/preview",
        json={
            "text": "你好",
            "voice": "local-clone1-520238c1",
            "tts_provider": "indextts",
            "tts_model": "IndexTeam/IndexTTS-2",
            "indextts_config": {
                "emotion_mode": "vector",
                "emo_alpha": 0.7,
                "emo_vector": [0.75, 0.0, 0.0, 0.0, 0.0, 0.0, 0.35, 0.0],
            },
        },
    )

    assert response.status_code == 200
    assert "tts preview requested" in caplog.text
    assert "provider=indextts" in caplog.text
    assert "voice_id=local-clone1-520238c1" in caplog.text
    assert "model=IndexTeam/IndexTTS-2" in caplog.text
    assert "indextts_emotion_mode=vector" in caplog.text
    assert "indextts_emo_alpha=0.7" in caplog.text
    assert "indextts_emo_vector=[0.75, 0.0, 0.0, 0.0, 0.0, 0.0, 0.35, 0.0]" in caplog.text


def test_tts_preview_form_passes_indextts_emotion_audio_file(monkeypatch):
    from apps.api.routes import tts_preview

    calls: list[dict[str, object]] = []

    class FakeTTS:
        async def synthesize_stream(self, text: str, voice: str | None = None):
            yield AudioChunk(
                data=np.array([0, 1000, -1000, 0], dtype=np.int16),
                sample_rate=16000,
                duration_ms=0.25,
            )

    def fake_build_tts_adapter(**kwargs):
        config = dict(kwargs["indextts_config"])
        calls.append(
            {
                **kwargs,
                "emotion_audio_bytes": Path(str(config["emo_audio_prompt"])).read_bytes(),
            }
        )
        return FakeTTS()

    monkeypatch.setattr(tts_preview, "build_tts_adapter", fake_build_tts_adapter)

    app = FastAPI()
    app.include_router(tts_preview.router)
    client = TestClient(app)

    response = client.post(
        "/tts/preview",
        data={
            "text": "你好",
            "voice": "indextts-default",
            "tts_provider": "indextts",
            "tts_model": "IndexTeam/IndexTTS-2",
            "indextts_config": json.dumps({"emotion_mode": "audio", "emo_alpha": 0.9}),
        },
        files={"indextts_emotion_audio_file": ("emotion.wav", b"RIFFemotion", "audio/wav")},
    )

    assert response.status_code == 200
    assert calls[0]["indextts_config"]["emo_alpha"] == 0.9
    assert calls[0]["emotion_audio_bytes"] == b"RIFFemotion"



def test_tts_preview_local_cosyvoice_returns_after_enough_preview_audio(monkeypatch):
    from apps.api.routes import tts_preview

    yielded: list[int] = []

    class FakeTTS:
        async def synthesize_stream(self, text: str, voice: str | None = None):
            for i in range(20):
                yielded.append(i)
                yield AudioChunk(
                    data=np.ones(16000, dtype=np.int16),
                    sample_rate=16000,
                    duration_ms=1000.0,
                )

    def fake_build_tts_adapter(**kwargs):
        return FakeTTS()

    monkeypatch.setattr(tts_preview, 'build_tts_adapter', fake_build_tts_adapter)

    app = FastAPI()
    app.include_router(tts_preview.router)
    client = TestClient(app)

    response = client.post(
        '/tts/preview',
        json={
            'text': '你好，我正在测试音色。',
            'voice': 'local-office-serena',
            'tts_provider': 'local_cosyvoice',
            'tts_model': 'FunAudioLLM/Fun-CosyVoice3-0.5B-2512',
        },
    )

    assert response.status_code == 200
    assert response.content.startswith(b'RIFF')
    assert 1 <= len(yielded) < 20

def test_tts_preview_rejects_empty_text():
    from apps.api.routes import tts_preview

    app = FastAPI()
    app.include_router(tts_preview.router)
    client = TestClient(app)

    response = client.post("/tts/preview", json={"text": " "})

    assert response.status_code == 422
    assert "text is required" in response.json()["detail"]

def test_tts_preview_keeps_local_cosyvoice_model_id(monkeypatch):
    from apps.api.routes import tts_preview

    calls: list[dict[str, object]] = []

    class FakeTTS:
        async def synthesize_stream(self, text: str, voice: str | None = None):
            yield AudioChunk(
                data=np.array([0, 1000, -1000, 0], dtype=np.int16),
                sample_rate=16000,
                duration_ms=0.25,
            )

    def fake_build_tts_adapter(**kwargs):
        calls.append(kwargs)
        return FakeTTS()

    monkeypatch.setattr(tts_preview, "build_tts_adapter", fake_build_tts_adapter)

    app = FastAPI()
    app.include_router(tts_preview.router)
    client = TestClient(app)

    response = client.post(
        "/tts/preview",
        json={
            "text": "你好",
            "tts_provider": "local_cosyvoice",
            "tts_model": "iic/CosyVoice-300M",
        },
    )

    assert response.status_code == 200
    assert calls[0]["tts_provider"] == "local_cosyvoice"
    assert calls[0]["tts_model"] == "iic/CosyVoice-300M"



def test_tts_preview_keeps_omnirt_indextts_model_id(monkeypatch):
    from apps.api.routes import tts_preview

    calls: list[dict[str, object]] = []

    class FakeTTS:
        async def synthesize_stream(self, text: str, voice: str | None = None):
            yield AudioChunk(
                data=np.array([0, 1000, -1000, 0], dtype=np.int16),
                sample_rate=16000,
                duration_ms=0.25,
            )

    def fake_build_tts_adapter(**kwargs):
        calls.append(kwargs)
        return FakeTTS()

    monkeypatch.setattr(tts_preview, "build_tts_adapter", fake_build_tts_adapter)

    app = FastAPI()
    app.include_router(tts_preview.router)
    client = TestClient(app)

    response = client.post(
        "/tts/preview",
        json={
            "text": "你好",
            "tts_provider": "omnirt_indextts",
            "tts_model": "IndexTeam/IndexTTS-2",
        },
    )

    assert response.status_code == 200
    assert calls[0]["tts_provider"] == "omnirt_indextts"
    assert calls[0]["tts_model"] == "IndexTeam/IndexTTS-2"


def test_tts_preview_keeps_local_indextts_model_id(monkeypatch):
    from apps.api.routes import tts_preview

    calls: list[dict[str, object]] = []

    class FakeTTS:
        async def synthesize_stream(self, text: str, voice: str | None = None):
            yield AudioChunk(
                data=np.array([0, 1000, -1000, 0], dtype=np.int16),
                sample_rate=16000,
                duration_ms=0.25,
            )

    def fake_build_tts_adapter(**kwargs):
        calls.append(kwargs)
        return FakeTTS()

    monkeypatch.setattr(tts_preview, "build_tts_adapter", fake_build_tts_adapter)

    app = FastAPI()
    app.include_router(tts_preview.router)
    client = TestClient(app)

    response = client.post(
        "/tts/preview",
        json={
            "text": "你好",
            "tts_provider": "local_indextts",
            "tts_model": "IndexTeam/IndexTTS-2",
        },
    )

    assert response.status_code == 200
    assert calls[0]["tts_provider"] == "local_indextts"
    assert calls[0]["tts_model"] == "IndexTeam/IndexTTS-2"
