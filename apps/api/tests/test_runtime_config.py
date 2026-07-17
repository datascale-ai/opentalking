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
                "OPENTALKING_LLM_API_KEY=llm-secret",
                "OPENTALKING_STT_DEFAULT_PROVIDER=openai_compatible",
                "OPENTALKING_STT_OPENAI_BASE_URL=https://asr.example.test/v1",
                "OPENTALKING_STT_OPENAI_MODEL=whisper-1",
                "OPENTALKING_STT_OPENAI_API_KEY=stt-secret",
                "OPENTALKING_TTS_DEFAULT_PROVIDER=openai_compatible",
                "OPENTALKING_TTS_OPENAI_BASE_URL=https://tts.example.test/v1",
                "OPENTALKING_TTS_OPENAI_MODEL=gpt-4o-mini-tts",
                "OPENTALKING_TTS_OPENAI_API_KEY=tts-secret",
                "OPENTALKING_MEMORY_MEM0_LLM_PROVIDER=openai",
                "OPENTALKING_MEMORY_MEM0_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1",
                "OPENTALKING_MEMORY_MEM0_LLM_MODEL=qwen-flash",
                "OPENTALKING_MEMORY_MEM0_LLM_API_KEY=mem0-llm-secret",
                "OPENTALKING_MEMORY_MEM0_EMBEDDER_PROVIDER=openai",
                "OPENTALKING_MEMORY_MEM0_EMBEDDER_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1",
                "OPENTALKING_MEMORY_MEM0_EMBEDDER_MODEL=text-embedding-v4",
                "OPENTALKING_MEMORY_MEM0_EMBEDDER_API_KEY=mem0-embedder-secret",
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
    assert payload["mem0"]["llm"]["provider"] == "openai"
    assert payload["mem0"]["llm"]["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert payload["mem0"]["llm"]["model"] == "qwen-flash"
    assert payload["mem0"]["llm"]["api_key_set"] is True
    assert payload["mem0"]["embedder"]["provider"] == "openai"
    assert payload["mem0"]["embedder"]["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert payload["mem0"]["embedder"]["model"] == "text-embedding-v4"
    assert payload["mem0"]["embedder"]["api_key_set"] is True
    assert "llm-secret" not in str(payload)
    assert "stt-secret" not in str(payload)
    assert "tts-secret" not in str(payload)
    assert "mem0-llm-secret" not in str(payload)
    assert "mem0-embedder-secret" not in str(payload)


async def test_runtime_config_get_expands_mem0_base_url_references(monkeypatch, tmp_path) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "OPENTALKING_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1",
                "OPENTALKING_MEMORY_MEM0_LLM_BASE_URL=${OPENTALKING_LLM_BASE_URL}",
                "OPENTALKING_MEMORY_MEM0_EMBEDDER_BASE_URL=${OPENTALKING_LLM_BASE_URL}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = await runtime_config.get_runtime_config(_request(monkeypatch, tmp_path))

    assert payload["mem0"]["llm"]["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert payload["mem0"]["embedder"]["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert "${OPENTALKING_LLM_BASE_URL}" not in str(payload)


async def test_runtime_config_apply_persists_llm_stt_tts_and_keeps_blank_keys(monkeypatch, tmp_path) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "OPENTALKING_LLM_API_KEY=existing-llm",
                "OPENTALKING_STT_OPENAI_API_KEY=existing-stt",
                "OPENTALKING_TTS_OPENAI_API_KEY=existing-tts",
                "OPENTALKING_MEMORY_MEM0_LLM_API_KEY=existing-mem0-llm",
                "OPENTALKING_MEMORY_MEM0_EMBEDDER_API_KEY=existing-mem0-embedder",
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
            mem0_llm_provider="openai",
            mem0_llm_base_url="https://mem0-llm.example.test/v1/",
            mem0_llm_model="qwen-flash",
            mem0_llm_api_key="",
            mem0_embedder_provider="openai",
            mem0_embedder_base_url="https://mem0-embed.example.test/v1/",
            mem0_embedder_model="text-embedding-v4",
            mem0_embedder_api_key="",
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
    assert payload["mem0"]["llm"]["provider"] == "openai"
    assert payload["mem0"]["llm"]["base_url"] == "https://mem0-llm.example.test/v1"
    assert payload["mem0"]["llm"]["model"] == "qwen-flash"
    assert payload["mem0"]["llm"]["api_key_set"] is True
    assert payload["mem0"]["embedder"]["provider"] == "openai"
    assert payload["mem0"]["embedder"]["base_url"] == "https://mem0-embed.example.test/v1"
    assert payload["mem0"]["embedder"]["model"] == "text-embedding-v4"
    assert payload["mem0"]["embedder"]["api_key_set"] is True
    assert "existing-llm" not in str(payload)
    assert "existing-stt" not in str(payload)
    assert "existing-tts" not in str(payload)
    assert "existing-mem0-llm" not in str(payload)
    assert "existing-mem0-embedder" not in str(payload)
    assert os.environ["OPENTALKING_LLM_API_KEY"] == "existing-llm"
    assert os.environ["OPENTALKING_STT_OPENAI_API_KEY"] == "existing-stt"
    assert os.environ["OPENTALKING_TTS_OPENAI_API_KEY"] == "existing-tts"
    assert os.environ["OPENTALKING_MEMORY_MEM0_LLM_API_KEY"] == "existing-mem0-llm"
    assert os.environ["OPENTALKING_MEMORY_MEM0_EMBEDDER_API_KEY"] == "existing-mem0-embedder"


async def test_runtime_config_apply_updates_mem0_keys_and_refreshes_memory_provider(monkeypatch, tmp_path) -> None:
    refreshed = False

    async def fake_close_cached_memory_provider() -> None:
        nonlocal refreshed
        refreshed = True

    monkeypatch.setattr(runtime_config, "close_cached_memory_provider", fake_close_cached_memory_provider, raising=False)

    payload = await runtime_config.apply_runtime_config(
        runtime_config.RuntimeConfigPayload(
            mem0_llm_provider="openai",
            mem0_llm_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1/",
            mem0_llm_model="qwen-flash",
            mem0_llm_api_key="new-mem0-llm",
            mem0_embedder_provider="openai",
            mem0_embedder_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1/",
            mem0_embedder_model="text-embedding-v4",
            mem0_embedder_api_key="new-mem0-embedder",
            sync_dashscope_api_key=False,
        ),
        _request(monkeypatch, tmp_path),
    )

    assert refreshed is True
    assert payload["mem0"]["llm"]["api_key_set"] is True
    assert payload["mem0"]["embedder"]["api_key_set"] is True
    assert "new-mem0-llm" not in str(payload)
    assert "new-mem0-embedder" not in str(payload)
    assert os.environ["OPENTALKING_MEMORY_MEM0_LLM_API_KEY"] == "new-mem0-llm"
    assert os.environ["OPENTALKING_MEMORY_MEM0_EMBEDDER_API_KEY"] == "new-mem0-embedder"
    assert os.environ.get("DASHSCOPE_API_KEY") != "new-mem0-llm"


async def test_runtime_config_apply_discards_stale_wechat_memory_registry(monkeypatch, tmp_path) -> None:
    async def fake_close_cached_memory_provider() -> None:
        return None

    request = _request(monkeypatch, tmp_path)
    request.app.state.wechat_import_registry = object()
    monkeypatch.setattr(runtime_config, "close_cached_memory_provider", fake_close_cached_memory_provider, raising=False)

    await runtime_config.apply_runtime_config(
        runtime_config.RuntimeConfigPayload(mem0_llm_api_key="new-mem0-llm"),
        request,
    )

    assert not hasattr(request.app.state, "wechat_import_registry")


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
