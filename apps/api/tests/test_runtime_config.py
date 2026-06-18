from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from apps.api.routes import runtime_config
from opentalking.core.config import get_settings


def _clear_runtime_env(monkeypatch) -> None:
    for key in runtime_config._RUNTIME_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _request(monkeypatch, tmp_path) -> SimpleNamespace:
    _clear_runtime_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runtime_config, "_ENV_PATH", tmp_path / ".env")
    get_settings.cache_clear()
    app = SimpleNamespace()
    app.state = SimpleNamespace()
    app.state.settings = get_settings()
    app.state.session_runners = {}
    return SimpleNamespace(app=app)


async def test_runtime_config_get_masks_secret_values(monkeypatch, tmp_path) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "OPENTALKING_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1",
                "OPENTALKING_LLM_MODEL=qwen-turbo",
                "OPENTALKING_LLM_API_KEY=sk-llm-secret",
                "OPENTALKING_STT_DEFAULT_PROVIDER=openai_compatible",
                "OPENTALKING_STT_OPENAI_BASE_URL=https://asr.example.test/v1",
                "OPENTALKING_STT_OPENAI_MODEL=whisper-1",
                "OPENTALKING_STT_OPENAI_API_KEY=sk-stt-secret",
                "OPENTALKING_TTS_DEFAULT_PROVIDER=openai_compatible",
                "OPENTALKING_TTS_OPENAI_BASE_URL=https://tts.example.test/v1",
                "OPENTALKING_TTS_OPENAI_MODEL=gpt-4o-mini-tts",
                "OPENTALKING_TTS_OPENAI_API_KEY=sk-tts-secret",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = await runtime_config.get_runtime_config(_request(monkeypatch, tmp_path))

    assert payload["llm"]["api_key_set"] is True
    assert payload["stt"]["provider"] == "openai_compatible"
    assert payload["stt"]["base_url"] == "https://asr.example.test/v1"
    assert payload["stt"]["model"] == "whisper-1"
    assert payload["stt"]["api_key_set"] is True
    assert payload["tts"]["provider"] == "openai_compatible"
    assert payload["tts"]["base_url"] == "https://tts.example.test/v1"
    assert payload["tts"]["model"] == "gpt-4o-mini-tts"
    assert payload["tts"]["api_key_set"] is True
    assert "sk-llm-secret" not in str(payload)
    assert "sk-stt-secret" not in str(payload)
    assert "sk-tts-secret" not in str(payload)


async def test_runtime_config_apply_persists_llm_stt_tts_and_keeps_blank_keys(monkeypatch, tmp_path) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "OPENTALKING_LLM_API_KEY=sk-existing-llm",
                "OPENTALKING_STT_OPENAI_API_KEY=sk-existing-stt",
                "OPENTALKING_TTS_OPENAI_API_KEY=sk-existing-tts",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = await runtime_config.apply_runtime_config(
        runtime_config.RuntimeConfigPayload(
            llm_base_url="https://llm.example.test/v1/",
            llm_model="qwen-plus",
            llm_api_key="",
            stt_provider="openai_compatible",
            stt_base_url="https://asr.example.test/v1/",
            stt_model="whisper-large-v3",
            stt_api_key="",
            tts_provider="openai_compatible",
            tts_base_url="https://tts.example.test/v1/",
            tts_model="gpt-4o-mini-tts",
            tts_voice="alloy",
            tts_api_key="",
        ),
        _request(monkeypatch, tmp_path),
    )

    assert payload["applied"] is True
    assert payload["llm"]["base_url"] == "https://llm.example.test/v1"
    assert payload["llm"]["model"] == "qwen-plus"
    assert payload["llm"]["api_key_set"] is True
    assert payload["stt"]["provider"] == "openai_compatible"
    assert payload["stt"]["base_url"] == "https://asr.example.test/v1"
    assert payload["stt"]["model"] == "whisper-large-v3"
    assert payload["stt"]["api_key_set"] is True
    assert payload["tts"]["provider"] == "openai_compatible"
    assert payload["tts"]["base_url"] == "https://tts.example.test/v1"
    assert payload["tts"]["model"] == "gpt-4o-mini-tts"
    assert payload["tts"]["voice"] == "alloy"
    assert payload["tts"]["api_key_set"] is True
    assert "sk-existing-llm" not in str(payload)
    assert "sk-existing-stt" not in str(payload)
    assert "sk-existing-tts" not in str(payload)
    assert os.environ["OPENTALKING_LLM_API_KEY"] == "sk-existing-llm"
    assert os.environ["OPENTALKING_STT_OPENAI_API_KEY"] == "sk-existing-stt"
    assert os.environ["OPENTALKING_TTS_OPENAI_API_KEY"] == "sk-existing-tts"


async def test_runtime_config_apply_rejects_unknown_provider(monkeypatch, tmp_path) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await runtime_config.apply_runtime_config(
            runtime_config.RuntimeConfigPayload(
                stt_provider="not-a-provider",
                tts_provider="openai_compatible",
            ),
            _request(monkeypatch, tmp_path),
        )

    assert exc_info.value.status_code == 400
