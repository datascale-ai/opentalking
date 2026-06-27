from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_realtime_settings_memory_matches_knowledge_library_pattern() -> None:
    source = (ROOT / "apps/web/src/components/SettingsPanel.tsx").read_text(encoding="utf-8")

    knowledge_idx = source.index('title="知识库"')
    memory_idx = source.index('title="记忆库"')
    model_idx = source.index('title="驱动模型"')
    assert knowledge_idx < memory_idx < model_idx
    assert "memoryLibraries: MemoryLibrary[]" in source
    assert "onManageMemoryLibraries" in source
    assert "{memoryLibraries.length} 个记忆库" in source
    assert "memoryLibraryReady" in source
    assert "disabled={configLocked || !memoryLibraryReady}" in source
    assert "onClick={onManageMemoryLibraries}" in source


def test_realtime_settings_memory_does_not_render_editing_tools() -> None:
    settings_source = (ROOT / "apps/web/src/components/SettingsPanel.tsx").read_text(encoding="utf-8")
    app_source = (ROOT / "apps/web/src/App.tsx").read_text(encoding="utf-8")

    assert "memoryPanel" not in settings_source
    assert "导入聊天记录" not in settings_source
    assert "新建记忆库名称" not in settings_source
    assert "记忆条目" not in settings_source
    assert "handleMemoryImport" not in app_source
    assert "handleMemoryDelete" not in app_source
    assert 'if (workflow === "realtime") void refreshMemoryLibraries();' in app_source


def test_asset_library_exposes_memory_tab_and_management_panel() -> None:
    source = (ROOT / "apps/web/src/components/AssetLibraryWorkspace.tsx").read_text(encoding="utf-8")

    assert 'type AssetTab = "exports" | "knowledge" | "memory" | "scenes" | "voices"' in source
    assert '{ id: "memory", label: "记忆库" }' in source
    assert "renderMemoryTab" in source
    assert "<MemoryPanel" in source
    assert 'mode="manage"' in source
    assert "profileId={profileId}" in source
    assert "onLibrariesChange={onMemoryLibrariesChange}" in source
    assert "memoryLibraries.length} 个记忆库" in source

    app_source = (ROOT / "apps/web/src/App.tsx").read_text(encoding="utf-8")
    assert "profileId={MEMORY_PROFILE_ID}" in app_source


def test_memory_panel_supports_select_and_manage_modes() -> None:
    source = (ROOT / "apps/web/src/components/MemoryPanel.tsx").read_text(encoding="utf-8")

    assert 'mode?: "select" | "manage"' in source
    assert 'const isManageMode = mode === "manage"' in source
    assert "管理记忆库" in source
    assert "WeChatMemoryImportPanel" in source
    assert "importMemoryTurns" not in source
    assert "记忆条目" in source
    assert 'if (!isManageMode) return' in source


def test_memory_panel_exposes_weflow_upload_without_api_fetch() -> None:
    panel_source = (ROOT / "apps/web/src/components/MemoryPanel.tsx").read_text(encoding="utf-8")
    import_source = (ROOT / "apps/web/src/components/WeChatMemoryImportPanel.tsx").read_text(encoding="utf-8")
    api_source = (ROOT / "apps/web/src/lib/api.ts").read_text(encoding="utf-8")
    types_source = (ROOT / "apps/web/src/types.ts").read_text(encoding="utf-8")

    assert '<WeChatMemoryImportPanel' in panel_source
    assert 'accept=".json,.csv,.txt,.html,.htm,.zip"' in import_source
    assert "uploadWeChatImport" in import_source
    assert "selectWeChatImportSpeaker" in import_source
    assert "commitWeChatImportJob" in import_source
    assert "source_url" not in import_source
    assert "sourceUrl" not in api_source
    assert "WeChatImportJob" in types_source
    assert "WeChatImportCommitResult" in types_source
