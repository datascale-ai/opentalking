from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_runtime_config_section_is_first_realtime_settings_section() -> None:
    source = (ROOT / "apps/web/src/components/SettingsPanel.tsx").read_text(encoding="utf-8")

    runtime_idx = source.index('title="运行配置"')
    avatar_idx = source.index('title="数字人形象"')
    assert runtime_idx < avatar_idx
    assert "runtimeConfig: RuntimeConfigResponse | null" in source
    assert "onRuntimeConfigApply" in source
    assert "应用配置" in source


def test_runtime_config_inputs_do_not_reveal_keys() -> None:
    settings_source = (ROOT / "apps/web/src/components/SettingsPanel.tsx").read_text(encoding="utf-8")
    api_source = (ROOT / "apps/web/src/lib/api.ts").read_text(encoding="utf-8")

    assert "llmApiKey" in settings_source
    assert "sttApiKey" in settings_source
    assert "ttsApiKey" in settings_source
    assert 'type="password"' in settings_source
    assert 'llmApiKey: ""' in settings_source
    assert 'sttApiKey: ""' in settings_source
    assert 'ttsApiKey: ""' in settings_source
    assert "api_key_set: boolean" in api_source
    assert "api_key: string" not in api_source


def test_app_loads_and_applies_runtime_config() -> None:
    app_source = (ROOT / "apps/web/src/App.tsx").read_text(encoding="utf-8")
    api_source = (ROOT / "apps/web/src/lib/api.ts").read_text(encoding="utf-8")

    assert "loadRuntimeConfig" in api_source
    assert "applyRuntimeConfig" in api_source
    assert "refreshRuntimeConfig" in app_source
    assert "handleApplyRuntimeConfig" in app_source
    assert "setRuntimeConfig(next)" in app_source
    assert "setAsrProvider" in app_source
    assert "setTtsProvider" in app_source
