from __future__ import annotations

import io
import json
import wave

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import apps.api.routes.voices as voices_routes
from opentalking.providers.tts import minimax_voice_clone


def _wav_bytes(seconds: float = 10.0) -> bytes:
    sample_rate = 16000
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * int(sample_rate * seconds))
    return output.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("region", "expected_host"),
    [("global", "api.minimax.io"), ("cn", "api.minimaxi.com")],
)
async def test_clone_minimax_voice_uploads_file_then_clones(region, expected_host):
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/files/upload":
            assert request.headers["Authorization"] == "Bearer test-key"
            body = await request.aread()
            assert b'name="purpose"' in body
            assert b"voice_clone" in body
            assert b'filename="voice-clone.wav"' in body
            return httpx.Response(
                200,
                json={"file": {"file_id": 12345}, "base_resp": {"status_code": 0}},
            )
        assert request.url.path == "/v1/voice_clone"
        payload = json.loads((await request.aread()).decode())
        assert payload == {
            "file_id": 12345,
            "voice_id": "ExampleVoice_01",
            "model": "speech-2.8-hd",
        }
        return httpx.Response(200, json={"base_resp": {"status_code": 0}})

    voice_id = await minimax_voice_clone.clone_minimax_voice(
        wav_bytes=_wav_bytes(),
        voice_id="ExampleVoice_01",
        model="speech-2.8-hd",
        api_key="test-key",
        region=region,
        transport=httpx.MockTransport(handler),
    )

    assert voice_id == "ExampleVoice_01"
    assert len(requests) == 2
    assert all(request.url.host == expected_host for request in requests)


@pytest.mark.asyncio
async def test_clone_minimax_voice_reports_api_rejection():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"base_resp": {"status_code": 1004, "status_msg": "invalid sample"}},
        )

    with pytest.raises(minimax_voice_clone.MiniMaxVoiceCloneError, match="invalid sample"):
        await minimax_voice_clone.clone_minimax_voice(
            wav_bytes=_wav_bytes(),
            voice_id="ExampleVoice_01",
            model="speech-2.8-hd",
            api_key="test-key",
            transport=httpx.MockTransport(handler),
        )


def test_minimax_clone_route_uses_region_and_persists_voice(monkeypatch):
    inserted: dict[str, object] = {}
    called: dict[str, object] = {}

    monkeypatch.setenv("OPENTALKING_TTS_MINIMAX_API_KEY", "test-key")
    monkeypatch.setattr(voices_routes, "init_voice_store", lambda: None)
    monkeypatch.setattr(voices_routes, "list_voices", lambda provider=None: [])
    monkeypatch.setattr(
        voices_routes.bailian_clone,
        "convert_audio_to_wav_24k_mono",
        lambda raw, suffix: _wav_bytes(),
    )

    async def fake_clone(**kwargs):
        called.update(kwargs)
        return "ExampleVoice_01"

    def fake_insert_clone(**kwargs):
        inserted.update(kwargs)
        return 42

    monkeypatch.setattr(voices_routes.minimax_voice_clone, "clone_minimax_voice", fake_clone)
    monkeypatch.setattr(voices_routes, "insert_clone", fake_insert_clone)

    app = FastAPI()
    app.include_router(voices_routes.router)
    response = TestClient(app).post(
        "/voices/clone",
        data={
            "provider": "minimax",
            "target_model": "speech-2.8-hd",
            "display_label": "Support voice",
            "preferred_name": "ExampleVoice_01",
            "region": "cn",
        },
        files={"audio": ("sample.wav", _wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 200, response.text
    assert response.json()["voice_id"] == "ExampleVoice_01"
    assert called["api_key"] == "test-key"
    assert called["region"] == "cn"
    assert called["model"] == "speech-2.8-hd"
    assert inserted == {
        "provider": "minimax",
        "voice_id": "ExampleVoice_01",
        "display_label": "Support voice",
        "target_model": "speech-2.8-hd",
    }
