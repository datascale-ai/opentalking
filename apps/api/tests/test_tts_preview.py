from __future__ import annotations

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
