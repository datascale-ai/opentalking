from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import numpy as np
import pytest


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    from opentalking.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_tts_minimax_status_reads_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from opentalking.providers.tts import factory

    monkeypatch.setenv("OPENTALKING_TTS_DEFAULT_PROVIDER", "minimax")
    monkeypatch.setenv("OPENTALKING_TTS_MINIMAX_BASE_URL", "https://api.minimax.io/v1")
    monkeypatch.setenv("OPENTALKING_TTS_MINIMAX_API_KEY", "test-key")
    monkeypatch.setenv("OPENTALKING_TTS_MINIMAX_MODEL", "speech-2.8-hd")
    monkeypatch.setenv("OPENTALKING_TTS_MINIMAX_VOICE", "male-qn-qingse")

    status = factory.tts_status()

    assert status["provider"] == "minimax"
    assert status["model"] == "speech-2.8-hd"
    assert status["voice"] == "male-qn-qingse"
    assert status["key_set"] is True
    assert status["service_url_set"] is True


def test_tts_minimax_posts_t2a_v2_and_reads_hex_pcm(monkeypatch: pytest.MonkeyPatch) -> None:
    import opentalking.providers.tts.minimax.adapter as adapter_mod
    from opentalking.providers.tts.factory import build_tts_adapter

    captured: list[httpx.Request] = []
    pcm = np.array([0, 1200, -1200, 0], dtype="<i2")

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        payload = json.loads(request.content.decode("utf-8"))
        assert payload == {
            "model": "speech-2.8-hd",
            "text": "Hello from MiniMax.",
            "stream": False,
            "output_format": "hex",
            "voice_setting": {"voice_id": "male-qn-qingse"},
            "audio_setting": {
                "sample_rate": 16000,
                "bitrate": 128000,
                "format": "pcm",
                "channel": 1,
            },
        }
        return httpx.Response(
            200,
            json={"data": {"audio": pcm.tobytes().hex(), "status": 2}, "base_resp": {"status_code": 0}},
        )

    transport = httpx.MockTransport(handler)

    class PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(adapter_mod.httpx, "AsyncClient", PatchedAsyncClient)
    monkeypatch.setenv("OPENTALKING_TTS_DEFAULT_PROVIDER", "minimax")
    monkeypatch.setenv("OPENTALKING_TTS_MINIMAX_BASE_URL", "https://api.minimax.io/v1")
    monkeypatch.setenv("OPENTALKING_TTS_MINIMAX_API_KEY", "test-key")
    monkeypatch.setenv("OPENTALKING_TTS_MINIMAX_MODEL", "speech-2.8-hd")
    monkeypatch.setenv("OPENTALKING_TTS_MINIMAX_VOICE", "male-qn-qingse")
    monkeypatch.setenv("OPENTALKING_TTS_MINIMAX_AUDIO_FORMAT", "pcm")

    tts = build_tts_adapter(sample_rate=16000, chunk_ms=20.0, tts_provider="minimax")
    chunks = asyncio.run(_collect_tts_chunks(tts, "Hello from MiniMax."))

    assert chunks
    assert any(np.array_equal(chunk.data, pcm) for chunk in chunks)
    assert str(captured[0].url) == "https://api.minimax.io/v1/t2a_v2"
    assert captured[0].headers["authorization"] == "Bearer test-key"


def test_tts_minimax_region_selects_cn_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    from opentalking.providers.tts.factory import create_tts_adapter

    monkeypatch.delenv("OPENTALKING_TTS_MINIMAX_BASE_URL", raising=False)
    monkeypatch.setenv("OPENTALKING_TTS_MINIMAX_REGION", "cn_zh")
    monkeypatch.setenv("OPENTALKING_TTS_MINIMAX_API_KEY", "test-key")

    tts = create_tts_adapter(sample_rate=16000, chunk_ms=20.0, tts_provider="minimax")

    assert tts.base_url == "https://api.minimaxi.com/v1"


def test_tts_minimax_settings_load_yaml(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from opentalking.core.config import Settings

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
tts:
  minimax_region: cn_zh
  minimax_api_key: yaml-key
  minimax_model: speech-2.8-turbo
  minimax_voice: test-voice
  minimax_audio_format: flac
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENTALKING_CONFIG_FILE", str(config_path))
    for name in (
        "OPENTALKING_TTS_MINIMAX_REGION",
        "OPENTALKING_TTS_MINIMAX_API_KEY",
        "OPENTALKING_TTS_MINIMAX_MODEL",
        "OPENTALKING_TTS_MINIMAX_VOICE",
        "OPENTALKING_TTS_MINIMAX_AUDIO_FORMAT",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.tts_minimax_region == "cn_zh"
    assert settings.tts_minimax_api_key == "yaml-key"
    assert settings.tts_minimax_model == "speech-2.8-turbo"
    assert settings.tts_minimax_voice == "test-voice"
    assert settings.tts_minimax_audio_format == "flac"


def test_tts_minimax_runtime_config_uses_cn_region_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.routes import runtime_config

    monkeypatch.delenv("OPENTALKING_TTS_MINIMAX_BASE_URL", raising=False)
    monkeypatch.delenv("OPENTALKING_TTS_MINIMAX_REGION", raising=False)
    settings = SimpleNamespace(
        tts_minimax_base_url="",
        tts_minimax_region="cn_zh",
        tts_minimax_model="speech-2.8-hd",
        tts_minimax_voice="male-qn-qingse",
        tts_minimax_api_key="test-key",
    )

    payload = runtime_config._current_tts_payload("minimax", settings, {})

    assert payload["base_url"] == "https://api.minimaxi.com/v1"


async def _collect_tts_chunks(tts, text: str):
    return [chunk async for chunk in tts.synthesize_stream(text)]
