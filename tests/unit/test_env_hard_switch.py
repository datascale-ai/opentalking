from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from opentalking.core.config import Settings


def test_legacy_dashscope_key_does_not_configure_llm(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENTALKING_LLM_API_KEY", raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-key")

    settings = Settings()

    assert settings.llm_api_key == ""


def test_dashscope_stt_only_uses_provider_specific_api_key(monkeypatch):
    from opentalking.providers.stt.dashscope import adapter

    monkeypatch.delenv("OPENTALKING_STT_API_KEY", raising=False)
    monkeypatch.delenv("OPENTALKING_STT_DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setenv("OPENTALKING_LLM_API_KEY", "llm-key")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-key")
    monkeypatch.setattr(
        "opentalking.core.config.get_settings",
        lambda: SimpleNamespace(stt_api_key="", stt_dashscope_api_key=""),
    )

    assert adapter._dashscope_api_key() == ""

    monkeypatch.setenv("OPENTALKING_STT_API_KEY", "stt-key")
    assert adapter._dashscope_api_key() == ""
    monkeypatch.setenv("OPENTALKING_STT_DASHSCOPE_API_KEY", "stt-dashscope-key")
    assert adapter._dashscope_api_key() == "stt-dashscope-key"


def test_dashscope_tts_only_uses_provider_specific_api_key(monkeypatch):
    from opentalking.providers.tts.cosyvoice_ws import adapter as cosyvoice_ws
    from opentalking.providers.tts.dashscope_qwen.adapter import DashScopeQwenTTSAdapter
    from opentalking.providers.tts.dashscope_sambert import adapter as sambert

    monkeypatch.delenv("OPENTALKING_TTS_API_KEY", raising=False)
    monkeypatch.delenv("OPENTALKING_TTS_DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setenv("OPENTALKING_LLM_API_KEY", "llm-key")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-key")
    monkeypatch.setattr(
        "opentalking.core.config.get_settings",
        lambda: SimpleNamespace(tts_api_key="", tts_dashscope_api_key=""),
    )

    with pytest.raises(RuntimeError, match="OPENTALKING_TTS_DASHSCOPE_API_KEY"):
        DashScopeQwenTTSAdapter()._ensure_api_key()
    with pytest.raises(RuntimeError, match="OPENTALKING_TTS_DASHSCOPE_API_KEY"):
        cosyvoice_ws._ensure_api_key()
    with pytest.raises(RuntimeError, match="OPENTALKING_TTS_DASHSCOPE_API_KEY"):
        sambert._ensure_api_key()

    monkeypatch.setenv("OPENTALKING_TTS_API_KEY", "tts-key")
    with pytest.raises(RuntimeError, match="OPENTALKING_TTS_DASHSCOPE_API_KEY"):
        DashScopeQwenTTSAdapter()._ensure_api_key()
    monkeypatch.setenv("OPENTALKING_TTS_DASHSCOPE_API_KEY", "tts-dashscope-key")
    assert DashScopeQwenTTSAdapter()._ensure_api_key() == "tts-dashscope-key"
    assert cosyvoice_ws._ensure_api_key() == "tts-dashscope-key"
    assert sambert._ensure_api_key() == "tts-dashscope-key"


def test_dashscope_voice_clone_only_uses_provider_specific_api_key(monkeypatch):
    from opentalking.providers.tts.dashscope_qwen import clone

    monkeypatch.delenv("OPENTALKING_TTS_API_KEY", raising=False)
    monkeypatch.delenv("OPENTALKING_TTS_DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setenv("OPENTALKING_LLM_API_KEY", "llm-key")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-key")
    monkeypatch.setattr(
        "opentalking.core.config.get_settings",
        lambda: SimpleNamespace(tts_api_key="", tts_dashscope_api_key=""),
    )

    with pytest.raises(RuntimeError, match="OPENTALKING_TTS_DASHSCOPE_API_KEY"):
        clone._dashscope_api_key()

    monkeypatch.setenv("OPENTALKING_TTS_API_KEY", "legacy-tts-key")
    with pytest.raises(RuntimeError, match="OPENTALKING_TTS_DASHSCOPE_API_KEY"):
        clone._dashscope_api_key()

    monkeypatch.setattr(
        "opentalking.core.config.get_settings",
        lambda: SimpleNamespace(tts_api_key="legacy-settings-key", tts_dashscope_api_key="settings-dashscope-key"),
    )
    assert clone._dashscope_api_key() == "settings-dashscope-key"

    monkeypatch.setenv("OPENTALKING_TTS_DASHSCOPE_API_KEY", "env-dashscope-key")
    assert clone._dashscope_api_key() == "env-dashscope-key"


def test_sensevoice_ignores_dashscope_default_stt_model(monkeypatch):
    from opentalking.providers.stt import factory

    monkeypatch.setenv("OPENTALKING_STT_PROVIDER", "sensevoice")
    monkeypatch.setenv("OPENTALKING_STT_MODEL", "paraformer-realtime-v2")
    monkeypatch.delenv("OPENTALKING_SENSEVOICE_MODEL", raising=False)

    assert factory.stt_status()["model"] == "iic/SenseVoiceSmall"


def test_runtime_status_reports_module_key_state_and_ignored_legacy_env(monkeypatch):
    from apps.api.routes.health import router

    monkeypatch.setenv("DASHSCOPE_API_KEY", "legacy-key")
    monkeypatch.setenv("OPENTALKING_LLM_API_KEY", "llm-key")
    monkeypatch.setenv("OPENTALKING_STT_DASHSCOPE_API_KEY", "stt-key")
    monkeypatch.setenv("OPENTALKING_TTS_DASHSCOPE_API_KEY", "tts-key")

    app = FastAPI()
    app.state.settings = Settings(cors_origins="*")
    app.include_router(router, prefix="/api")

    payload = TestClient(app).get("/api/runtime/status").json()

    assert payload["llm_key_set"] is True
    assert payload["stt_providers"]["dashscope"]["key_set"] is True
    assert payload["tts_providers"]["dashscope"]["key_set"] is True
    assert "DASHSCOPE_API_KEY" in payload["ignored_legacy_env"]
    assert "service_url_set" not in payload["stt_providers"]["dashscope"]


def test_tts_legacy_service_url_does_not_override_dashscope_adapter(monkeypatch):
    from opentalking.providers.tts.dashscope_qwen.adapter import DashScopeQwenTTSAdapter
    from opentalking.providers.tts.factory import build_tts_adapter

    monkeypatch.delenv("OPENTALKING_TTS_MODEL", raising=False)
    monkeypatch.setenv("OPENTALKING_TTS_SERVICE_URL", "wss://legacy-env.example/realtime")
    settings = SimpleNamespace(
        normalized_tts_provider="dashscope",
        tts_voice="Cherry",
        tts_model="settings-qwen-model",
        tts_service_url="wss://settings-tts.example/realtime",
    )

    adapter = build_tts_adapter(sample_rate=16000, chunk_ms=20.0, settings=settings)

    assert isinstance(adapter, DashScopeQwenTTSAdapter)
    assert adapter._model == "settings-qwen-model"
    assert adapter._ws_url == "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"


def test_tts_legacy_service_url_does_not_override_cosyvoice_adapter(monkeypatch):
    from opentalking.providers.tts.cosyvoice_ws.adapter import DashScopeCosyVoiceWsAdapter
    from opentalking.providers.tts.factory import build_tts_adapter

    monkeypatch.delenv("OPENTALKING_TTS_MODEL", raising=False)
    monkeypatch.setenv("OPENTALKING_TTS_SERVICE_URL", "wss://legacy-env.example/realtime")
    settings = SimpleNamespace(
        normalized_tts_provider="cosyvoice",
        tts_voice="longwan",
        tts_model="settings-cosyvoice-model",
        tts_service_url="wss://settings-cosyvoice.example/realtime",
    )

    adapter = build_tts_adapter(sample_rate=16000, chunk_ms=20.0, settings=settings)

    assert isinstance(adapter, DashScopeCosyVoiceWsAdapter)
    assert adapter._model == "settings-cosyvoice-model"
    assert adapter._service_url == ""


def test_stt_default_provider_uses_provider_specific_config(monkeypatch):
    from opentalking.providers.stt import factory

    for key in [
        "OPENTALKING_STT_PROVIDER",
        "OPENTALKING_STT_MODEL",
        "OPENTALKING_STT_API_KEY",
        "OPENTALKING_STT_DEVICE",
        "OPENTALKING_LOCAL_AUDIO_MODEL_ROOT",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENTALKING_STT_DEFAULT_PROVIDER", "sensevoice")
    monkeypatch.setenv("OPENTALKING_STT_SENSEVOICE_MODEL", "iic/SenseVoiceSmall")
    monkeypatch.setenv("OPENTALKING_STT_SENSEVOICE_MODEL_DIR", "/models/stt/sensevoice")
    monkeypatch.setenv("OPENTALKING_STT_SENSEVOICE_DEVICE", "cpu")
    monkeypatch.setenv("OPENTALKING_STT_DASHSCOPE_MODEL", "paraformer-realtime-v2")
    monkeypatch.setenv("OPENTALKING_STT_DASHSCOPE_API_KEY", "stt-api-key")

    factory.clear_stt_adapter_cache()
    status = factory.stt_status()
    adapter = factory.create_stt_adapter()

    assert status["provider"] == "sensevoice"
    assert status["model"] == "iic/SenseVoiceSmall"
    assert status["model_dir"] == "/models/stt/sensevoice"
    assert status["device"] == "cpu"
    assert adapter.model == "iic/SenseVoiceSmall"
    assert adapter.model_dir == "/models/stt/sensevoice"
    assert adapter._runtime_model_name() == "/models/stt/sensevoice"


def test_stt_dashscope_uses_provider_specific_api_key_and_model(monkeypatch):
    from opentalking.providers.stt import factory
    from opentalking.providers.stt.dashscope import adapter

    monkeypatch.delenv("OPENTALKING_STT_PROVIDER", raising=False)
    monkeypatch.delenv("OPENTALKING_STT_MODEL", raising=False)
    monkeypatch.delenv("OPENTALKING_STT_API_KEY", raising=False)
    monkeypatch.setenv("OPENTALKING_STT_DEFAULT_PROVIDER", "dashscope")
    monkeypatch.setenv("OPENTALKING_STT_DASHSCOPE_MODEL", "provider-specific-paraformer")
    monkeypatch.setenv("OPENTALKING_STT_DASHSCOPE_API_KEY", "provider-specific-key")
    monkeypatch.setenv("OPENTALKING_STT_SENSEVOICE_MODEL", "iic/SenseVoiceSmall")

    assert factory.stt_status()["model"] == "provider-specific-paraformer"
    assert adapter._stt_model() == "provider-specific-paraformer"
    assert adapter._dashscope_api_key() == "provider-specific-key"


def test_tts_default_provider_uses_provider_specific_local_config(monkeypatch):
    from opentalking.providers.tts import factory
    from opentalking.providers.tts.local_cosyvoice.adapter import LocalCosyVoiceTTSAdapter

    for key in [
        "OPENTALKING_TTS_PROVIDER",
        "OPENTALKING_TTS_MODEL",
        "OPENTALKING_TTS_SERVICE_URL",
        "OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL",
        "OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL",
        "OPENTALKING_LOCAL_AUDIO_MODEL_ROOT",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENTALKING_TTS_DEFAULT_PROVIDER", "local_cosyvoice")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL", "FunAudioLLM/Fun-CosyVoice3-0.5B-2512")
    monkeypatch.setenv(
        "OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL_DIR",
        "/models/tts/FunAudioLLM__Fun-CosyVoice3-0.5B-2512",
    )
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL", "http://127.0.0.1:19090/synthesize")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_DEVICE", "cuda:0")

    adapter = factory.create_tts_adapter(sample_rate=16000, chunk_ms=20)

    assert isinstance(adapter, LocalCosyVoiceTTSAdapter)
    assert adapter.model == "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"
    assert adapter.model_dir == "/models/tts/FunAudioLLM__Fun-CosyVoice3-0.5B-2512"
    assert adapter.service_url == "http://127.0.0.1:19090/synthesize"
    assert adapter.device == "cuda:0"


def test_tts_dashscope_uses_provider_specific_api_config(monkeypatch):
    from opentalking.providers.tts.dashscope_qwen.adapter import DashScopeQwenTTSAdapter
    from opentalking.providers.tts.factory import create_tts_adapter

    for key in [
        "OPENTALKING_TTS_PROVIDER",
        "OPENTALKING_TTS_MODEL",
        "OPENTALKING_TTS_API_KEY",
        "OPENTALKING_TTS_SERVICE_URL",
        "OPENTALKING_TTS_VOICE",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENTALKING_TTS_DEFAULT_PROVIDER", "dashscope")
    monkeypatch.setenv("OPENTALKING_TTS_DASHSCOPE_MODEL", "provider-qwen-model")
    monkeypatch.setenv("OPENTALKING_TTS_DASHSCOPE_API_KEY", "provider-tts-key")
    monkeypatch.setenv("OPENTALKING_TTS_DASHSCOPE_SERVICE_URL", "wss://provider.example/realtime")
    monkeypatch.setenv("OPENTALKING_TTS_DASHSCOPE_VOICE", "Cherry")

    adapter = create_tts_adapter(sample_rate=16000, chunk_ms=20)

    assert isinstance(adapter, DashScopeQwenTTSAdapter)
    assert adapter._model == "provider-qwen-model"
    assert adapter._ws_url == "wss://provider.example/realtime"
    assert adapter.default_voice == "Cherry"
    assert adapter._ensure_api_key() == "provider-tts-key"


def test_runtime_status_reports_provider_specific_configs(monkeypatch):
    from apps.api.routes.health import router

    monkeypatch.setenv("OPENTALKING_STT_DEFAULT_PROVIDER", "dashscope")
    monkeypatch.setenv("OPENTALKING_STT_ENABLED_PROVIDERS", "sensevoice,dashscope")
    monkeypatch.setenv("OPENTALKING_STT_DASHSCOPE_MODEL", "provider-paraformer")
    monkeypatch.setenv("OPENTALKING_STT_DASHSCOPE_API_KEY", "provider-stt-key")
    monkeypatch.setenv("OPENTALKING_STT_SENSEVOICE_MODEL_DIR", "/models/stt/sensevoice")
    monkeypatch.setenv("OPENTALKING_TTS_DEFAULT_PROVIDER", "local_cosyvoice")
    monkeypatch.setenv("OPENTALKING_TTS_ENABLED_PROVIDERS", "local_cosyvoice,dashscope,edge")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL", "provider-cosyvoice")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL_DIR", "/models/tts/cosyvoice")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL", "http://127.0.0.1:19090/synthesize")
    monkeypatch.setenv("OPENTALKING_TTS_DASHSCOPE_API_KEY", "provider-tts-key")

    app = FastAPI()
    app.state.settings = Settings(cors_origins="*")
    app.include_router(router, prefix="/api")

    payload = TestClient(app).get("/api/runtime/status").json()

    assert payload["stt_provider"] == "dashscope"
    assert payload["stt_default_provider"] == "dashscope"
    assert payload["stt_enabled_providers"] == ["sensevoice", "dashscope"]
    assert payload["stt_model"] == "provider-paraformer"
    assert payload["stt_key_set"] is True
    assert "service_url_set" not in payload["stt_providers"]["dashscope"]
    assert payload["stt_providers"]["sensevoice"]["model_dir"] == "/models/stt/sensevoice"
    assert payload["tts_provider"] == "local_cosyvoice"
    assert payload["tts_default_provider"] == "local_cosyvoice"
    assert payload["tts_enabled_providers"] == ["local_cosyvoice", "dashscope", "edge"]
    assert payload["tts_model"] == "provider-cosyvoice"
    assert payload["tts_service_url_set"] is True
    assert payload["tts_key_set"] is False
    assert payload["tts_providers"]["dashscope"]["key_set"] is True


def test_env_example_does_not_expose_legacy_or_unused_service_urls() -> None:
    text = Path(".env.example").read_text(encoding="utf-8")

    assert "OPENTALKING_STT_DASHSCOPE_SERVICE_URL" not in text
    assert "OPENTALKING_TTS_SERVICE_URL" not in text
    assert "OPENTALKING_LOCAL_COSYVOICE_SERVICE_URL" not in text
    assert "OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL" in text
