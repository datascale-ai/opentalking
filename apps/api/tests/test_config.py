from __future__ import annotations

from pathlib import Path

import pytest

import apps.api.main as api_main
import apps.unified.main as unified_main
from opentalking.core.config import Settings


@pytest.mark.parametrize(
    ("cors_origins", "expected"),
    [
        ("*", ["*"]),
        ("http://a.test,http://b.test", ["http://a.test", "http://b.test"]),
        (["http://a.test", "http://b.test"], ["http://a.test", "http://b.test"]),
    ],
)
def test_create_app_accepts_supported_cors_formats(
    monkeypatch: pytest.MonkeyPatch,
    cors_origins: str | list[str],
    expected: list[str],
) -> None:
    settings = Settings(cors_origins=cors_origins)
    monkeypatch.setattr(api_main, "get_settings", lambda: settings)
    monkeypatch.setattr(unified_main, "get_settings", lambda: settings)

    api_app = api_main.create_app()
    unified_app = unified_main.create_app()

    assert api_app.user_middleware[0].kwargs["allow_origins"] == expected
    assert unified_app.user_middleware[0].kwargs["allow_origins"] == expected


def test_wav2lip_preload_defaults_on() -> None:
    settings = Settings()

    assert settings.wav2lip_preload is True


def test_unprefixed_omnirt_endpoint_is_read_from_dotenv(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OMNIRT_ENDPOINT", raising=False)
    monkeypatch.delenv("OPENTALKING_OMNIRT_ENDPOINT", raising=False)
    (tmp_path / ".env").write_text(
        "OMNIRT_ENDPOINT=http://127.0.0.1:9000\n"
        "OMNIRT_AUDIO2VIDEO_PATH_TEMPLATE=/v1/audio2video/{model}\n",
        encoding="utf-8",
    )

    settings = Settings()

    assert settings.omnirt_endpoint == "http://127.0.0.1:9000"
    assert settings.omnirt_audio2video_path_template == "/v1/audio2video/{model}"


def test_prefixed_omnirt_endpoint_takes_precedence_over_unprefixed_dotenv(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENTALKING_OMNIRT_ENDPOINT", "http://10.0.0.2:9000")
    monkeypatch.delenv("OMNIRT_ENDPOINT", raising=False)
    (tmp_path / ".env").write_text(
        "OMNIRT_ENDPOINT=http://127.0.0.1:9000\n",
        encoding="utf-8",
    )

    settings = Settings()

    assert settings.omnirt_endpoint == "http://10.0.0.2:9000"



def test_export_settings_defaults_and_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("OPENTALKING_EXPORTS_DIR", "/tmp/opentalking-exports")
    monkeypatch.setenv("OPENTALKING_EXPORT_MAX_BYTES", "2048")

    settings = Settings(_env_file=None)

    assert settings.exports_dir == "/tmp/opentalking-exports"
    assert settings.export_max_bytes == 2048


def test_export_settings_have_safe_defaults(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("OPENTALKING_EXPORTS_DIR", raising=False)
    monkeypatch.delenv("OPENTALKING_EXPORT_MAX_BYTES", raising=False)
    monkeypatch.chdir(tmp_path)

    settings = Settings(_env_file=None)

    assert settings.exports_dir == "./data/exports"
    assert settings.export_max_bytes == 1024 * 1024 * 1024


def test_agent_lightrag_settings_read_prefixed_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENTALKING_AGENT_LIGHTRAG_QUERY_MODE", "mix")
    monkeypatch.setenv("OPENTALKING_AGENT_LIGHTRAG_EMBEDDING_MODEL", "text-embedding-v3")
    monkeypatch.setenv("OPENTALKING_AGENT_LIGHTRAG_EMBEDDING_DIM", "1536")
    monkeypatch.setenv("OPENTALKING_AGENT_LIGHTRAG_CHUNK_FALLBACK_ENABLED", "false")

    settings = Settings(_env_file=None)

    assert settings.agent_lightrag_query_mode == "mix"
    assert settings.agent_lightrag_embedding_model == "text-embedding-v3"
    assert settings.agent_lightrag_embedding_dim == 1536
    assert settings.agent_lightrag_chunk_fallback_enabled is False


def test_agent_lightrag_chunk_fallback_defaults_to_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENTALKING_AGENT_LIGHTRAG_CHUNK_FALLBACK_ENABLED", raising=False)

    settings = Settings(_env_file=None)

    assert settings.agent_lightrag_chunk_fallback_enabled is False


def test_agent_lightrag_chunk_fallback_can_be_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENTALKING_AGENT_LIGHTRAG_CHUNK_FALLBACK_ENABLED", "true")

    settings = Settings(_env_file=None)

    assert settings.agent_lightrag_chunk_fallback_enabled is True


def test_local_cosyvoice_runtime_settings_read_prefixed_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_FP16", "auto")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_LOAD_TRT", "true")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_TRT_CONCURRENT", "2")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_TOKEN_HOP_LEN", "8")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_TOKEN_MAX_HOP_LEN", "16")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_STREAM_SCALE_FACTOR", "1")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_FLOW_N_TIMESTEPS", "4")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_MAX_TOKEN_TEXT_RATIO", "6")
    monkeypatch.setenv("OPENTALKING_TTS_LOCAL_COSYVOICE_MASK_STOP_TOKENS", "true")

    settings = Settings(_env_file=None)

    assert settings.tts_local_cosyvoice_fp16 == "auto"
    assert settings.tts_local_cosyvoice_load_trt is True
    assert settings.tts_local_cosyvoice_trt_concurrent == 2
    assert settings.tts_local_cosyvoice_token_hop_len == 8
    assert settings.tts_local_cosyvoice_token_max_hop_len == 16
    assert settings.tts_local_cosyvoice_stream_scale_factor == 1
    assert settings.tts_local_cosyvoice_flow_n_timesteps == 4
    assert settings.tts_local_cosyvoice_max_token_text_ratio == 6.0
    assert settings.tts_local_cosyvoice_mask_stop_tokens is True


def _active_env_names(contents: str) -> set[str]:
    names: set[str] = set()
    for raw_line in contents.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _value = line.split("=", 1)
        names.add(name)
    return names


def test_env_examples_expose_only_user_facing_memory_settings() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    examples = [
        repo_root / ".env.example",
        repo_root / "scripts/quickstart/env.example",
    ]
    required_names = {
        "OPENTALKING_MEMORY_SUMMARY_ENABLED",
        "OPENTALKING_MEMORY_SUMMARY_TURN_WINDOW",
        "OPENTALKING_MEMORY_SUMMARY_MAX_ITEMS",
        "OPENTALKING_MEMORY_MEM0_LLM_PROVIDER",
        "OPENTALKING_MEMORY_MEM0_LLM_BASE_URL",
        "OPENTALKING_MEMORY_MEM0_LLM_API_KEY",
        "OPENTALKING_MEMORY_MEM0_LLM_MODEL",
        "OPENTALKING_MEMORY_MEM0_EMBEDDER_PROVIDER",
        "OPENTALKING_MEMORY_MEM0_EMBEDDER_BASE_URL",
        "OPENTALKING_MEMORY_MEM0_EMBEDDER_API_KEY",
        "OPENTALKING_MEMORY_MEM0_EMBEDDER_MODEL",
    }
    hidden_names = {
        "OPENTALKING_MEMORY_PROVIDER",
        "OPENTALKING_MEMORY_ENABLED",
        "OPENTALKING_MEMORY_DEFAULT_PROFILE_ID",
        "OPENTALKING_MEMORY_DEFAULT_LIBRARY_ID",
        "OPENTALKING_MEMORY_SQLITE_PATH",
        "OPENTALKING_MEMORY_RECALL_LIMIT",
        "OPENTALKING_MEMORY_RECALL_MIN_SCORE",
        "OPENTALKING_MEMORY_RECALL_TIMEOUT_MS",
        "OPENTALKING_MEMORY_RECALL_BACKEND",
        "OPENTALKING_MEMORY_WRITE_MODE",
        "OPENTALKING_MEMORY_DECISION_MODE",
        "OPENTALKING_MEMORY_DECISION_TIMEOUT_MS",
        "OPENTALKING_MEMORY_SMART_WRITE_ENABLED",
        "OPENTALKING_MEMORY_MEM0_CONFIG",
    }

    for example in examples:
        contents = example.read_text(encoding="utf-8")
        missing = sorted(name for name in required_names if name not in contents)
        exposed = sorted(name for name in hidden_names if name in contents)
        assert not missing, f"{example} is missing user-facing memory settings: {missing}"
        assert not exposed, f"{example} exposes internal memory settings: {exposed}"


def test_root_env_example_keeps_memory_summary_enabled_by_default() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    contents = (repo_root / ".env.example").read_text(encoding="utf-8")
    values = {}
    for raw_line in contents.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name] = value

    assert values["OPENTALKING_MEMORY_SUMMARY_ENABLED"] == "true"
    assert values["OPENTALKING_MEMORY_SUMMARY_TURN_WINDOW"] == "8"
    assert values["OPENTALKING_MEMORY_SUMMARY_MAX_ITEMS"] == "3"


def test_memory_engine_defaults_are_smart_but_session_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [
        "OPENTALKING_MEMORY_PROVIDER",
        "OPENTALKING_MEMORY_ENABLED",
        "OPENTALKING_MEMORY_RECALL_BACKEND",
        "OPENTALKING_MEMORY_WRITE_MODE",
        "OPENTALKING_MEMORY_DECISION_MODE",
        "OPENTALKING_MEMORY_DECISION_TIMEOUT_MS",
        "OPENTALKING_MEMORY_RECALL_TIMEOUT_MS",
        "OPENTALKING_MEMORY_SMART_WRITE_ENABLED",
        "OPENTALKING_MEMORY_SUMMARY_ENABLED",
        "OPENTALKING_MEMORY_SUMMARY_TURN_WINDOW",
        "OPENTALKING_MEMORY_SUMMARY_MAX_ITEMS",
    ]:
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.memory_provider == "mem0"
    assert settings.memory_enabled is False
    assert settings.memory_recall_backend == "hybrid"
    assert settings.memory_write_mode == "hybrid"
    assert settings.memory_decision_mode == "hybrid"
    assert settings.memory_decision_timeout_ms == 2000
    assert settings.memory_recall_timeout_ms == 2000
    assert settings.memory_smart_write_enabled is True
    assert settings.memory_summary_enabled is True
    assert settings.memory_summary_turn_window == 8
    assert settings.memory_summary_max_items == 3


def test_memory_engine_settings_read_prefixed_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENTALKING_MEMORY_RECALL_BACKEND", "mem0")
    monkeypatch.setenv("OPENTALKING_MEMORY_WRITE_MODE", "mem0")
    monkeypatch.setenv("OPENTALKING_MEMORY_DECISION_MODE", "hybrid")
    monkeypatch.setenv("OPENTALKING_MEMORY_DECISION_TIMEOUT_MS", "1200")
    monkeypatch.setenv("OPENTALKING_MEMORY_SMART_WRITE_ENABLED", "false")
    monkeypatch.setenv("OPENTALKING_MEMORY_SUMMARY_ENABLED", "true")
    monkeypatch.setenv("OPENTALKING_MEMORY_SUMMARY_TURN_WINDOW", "4")
    monkeypatch.setenv("OPENTALKING_MEMORY_SUMMARY_MAX_ITEMS", "2")

    settings = Settings(_env_file=None)

    assert settings.memory_recall_backend == "mem0"
    assert settings.memory_write_mode == "mem0"
    assert settings.memory_decision_mode == "hybrid"
    assert settings.memory_decision_timeout_ms == 1200
    assert settings.memory_smart_write_enabled is False
    assert settings.memory_summary_enabled is True
    assert settings.memory_summary_turn_window == 4
    assert settings.memory_summary_max_items == 2


def test_light2d_video_creation_limits_have_defaults_and_env_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENTALKING_VIDEO_CREATION_LIGHT2D_MAX_DURATION_SEC", raising=False)
    monkeypatch.delenv("OPENTALKING_VIDEO_CREATION_LIGHT2D_MAX_TEXT_CHARS", raising=False)
    defaults = Settings(_env_file=None)
    assert defaults.video_creation_light2d_max_duration_sec == 300
    assert defaults.video_creation_light2d_max_text_chars == 1000

    monkeypatch.setenv("OPENTALKING_VIDEO_CREATION_LIGHT2D_MAX_DURATION_SEC", "12")
    monkeypatch.setenv("OPENTALKING_VIDEO_CREATION_LIGHT2D_MAX_TEXT_CHARS", "42")
    overridden = Settings(_env_file=None)
    assert overridden.video_creation_light2d_max_duration_sec == 12
    assert overridden.video_creation_light2d_max_text_chars == 42
