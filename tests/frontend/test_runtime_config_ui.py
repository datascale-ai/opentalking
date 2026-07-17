from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_runtime_config_is_top_level_workspace_before_connection_status() -> None:
    topbar_source = (ROOT / "apps/web/src/components/TopBar.tsx").read_text(encoding="utf-8")
    app_source = (ROOT / "apps/web/src/App.tsx").read_text(encoding="utf-8")
    settings_source = (ROOT / "apps/web/src/components/SettingsPanel.tsx").read_text(encoding="utf-8")

    runtime_idx = topbar_source.index("API 配置")
    status_idx = topbar_source.index("DOT_LABELS[connection]")
    assert runtime_idx < status_idx
    assert '"runtimeConfig"' in topbar_source
    assert "runtimeConfigReady" in topbar_source
    assert 'className={`h-8 rounded-lg border px-3 text-xs font-semibold transition' in topbar_source
    assert "API配置（已配置）" in topbar_source
    assert "API配置（未配置）" in topbar_source
    assert "border-emerald-200 bg-emerald-50 text-emerald-700" in topbar_source
    assert "border-amber-200 bg-amber-50 text-amber-700" in topbar_source
    assert 'workflow === "runtimeConfig"' in app_source
    assert 'title="运行配置"' not in settings_source


def test_runtime_config_inputs_do_not_reveal_keys() -> None:
    settings_source = (ROOT / "apps/web/src/components/RuntimeConfigWorkspace.tsx").read_text(encoding="utf-8")
    api_source = (ROOT / "apps/web/src/lib/api.ts").read_text(encoding="utf-8")

    assert "llmApiKey" in settings_source
    assert "sttApiKey" in settings_source
    assert "ttsApiKey" in settings_source
    assert "mem0LlmApiKey" in settings_source
    assert "mem0EmbedderApiKey" in settings_source
    assert 'type="password"' in settings_source
    assert 'llmApiKey: ""' in settings_source
    assert 'sttApiKey: ""' in settings_source
    assert 'ttsApiKey: ""' in settings_source
    assert 'mem0LlmApiKey: ""' in settings_source
    assert 'mem0EmbedderApiKey: ""' in settings_source
    assert "api_key_set: boolean" in api_source
    assert "api_key: string" not in api_source


def test_runtime_config_page_exposes_mem0_llm_and_embedder_settings() -> None:
    source = (ROOT / "apps/web/src/components/RuntimeConfigWorkspace.tsx").read_text(encoding="utf-8")
    api_source = (ROOT / "apps/web/src/lib/api.ts").read_text(encoding="utf-8")

    assert "Mem0 LLM" in source
    assert "Mem0 Embedding" in source
    assert "mem0_llm_provider" in api_source
    assert "mem0_embedder_provider" in api_source
    assert "mem0: RuntimeConfigMem0" in api_source


def test_runtime_config_tts_hides_voice_and_marks_edge_as_no_setup() -> None:
    source = (ROOT / "apps/web/src/components/RuntimeConfigWorkspace.tsx").read_text(encoding="utf-8")

    assert 'const runtimeTtsNeedsSetup = runtimeForm.ttsProvider !== "edge";' in source
    assert "runtimeConfigSyncedRef" in source
    assert "preferDashscopeWhenEdge" in source
    assert "{runtimeTtsNeedsSetup ? (" in source
    assert 'label: "Edge（无需配置）"' in source
    assert 'runtimeTtsNeedsSetup ? (runtimeTtsKeySet ? "Key 已设置" : "Key 未设置") : "无需配置"' in source
    assert "TTS 音色请在实时对话里选择" in source
    assert "Edge 无需配置" not in source
    assert "<span className=\"mb-1 block text-xs font-medium text-slate-500\">Voice</span>" not in source
    assert "同时保存为通用百炼 Key" in source
    assert "供百炼语音识别、语音合成及旧版配置读取" in source
    assert "若不同服务使用不同 Key，请关闭" in source


def test_runtime_config_llm_defaults_to_qwen_flash() -> None:
    source = (ROOT / "apps/web/src/components/RuntimeConfigWorkspace.tsx").read_text(encoding="utf-8")

    assert 'model: "qwen-flash"' in source
    assert 'model: "qwen-turbo"' not in source


def test_runtime_config_page_uses_bottom_actions_without_header_card() -> None:
    source = (ROOT / "apps/web/src/components/RuntimeConfigWorkspace.tsx").read_text(encoding="utf-8")

    assert "<p className=\"text-xs font-medium text-slate-500\">运行配置</p>" not in source
    assert "<h1 className=\"mt-1 text-lg font-semibold text-slate-950\">API 配置</h1>" not in source
    assert 'className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm shadow-slate-200/70' not in source
    tts_section_idx = source.index("<h2 className=\"text-sm font-semibold text-slate-900\">TTS</h2>")
    model_idx = source.index(">Model</span>", tts_section_idx)
    key_idx = source.index(">API Key</span>", tts_section_idx)
    actions_idx = source.rindex("{runtimeConfigLoading ? \"读取中\" : \"刷新\"}")
    apply_idx = source.rindex("{runtimeConfigApplying ? \"应用中...\" : \"应用配置\"}")
    assert "mt-3 flex flex-wrap items-center justify-end gap-2 border-t border-slate-100 pt-3" in source
    assert model_idx < key_idx < actions_idx < apply_idx


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
    assert "runtimeConfigTtsReady" in app_source
