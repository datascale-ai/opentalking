from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_frontend_api_defines_multi_knowledge_base_types() -> None:
    source = (ROOT / "apps/web/src/lib/api.ts").read_text(encoding="utf-8")

    assert "export type KnowledgeBaseSummary" in source
    assert "export type KnowledgeBasesResponse" in source
    assert "knowledge_bases?: (string | KnowledgeBaseSummary)[]" in source
    assert "knowledge_base_summaries" in source
    assert "knowledge_bases" in source
    assert "export type AvatarKnowledgeBasesResponse" in source


def test_app_migrates_stored_single_knowledge_base_id_to_plural_shape() -> None:
    source = (ROOT / "apps/web/src/App.tsx").read_text(encoding="utf-8")

    assert "knowledgeBaseIds" in source
    assert "knowledgeBaseId" in source
    assert "readStoredAgentConfig" in source
    assert "knowledge_base_ids" in source
    assert "knowledge_base_id" in source
    assert "Array.isArray(parsed.knowledgeBaseIds)" in source
    assert "parsed.knowledgeBaseId" in source


def test_app_clears_stale_subtitle_state_on_context_reset() -> None:
    source = (ROOT / "apps/web/src/App.tsx").read_text(encoding="utf-8")

    assert "setCurrentSubtitle(\"\")" in source
    assert "subtitleAccRef.current = \"\"" in source
    assert "subtitleMediaReadyRef.current = false" in source
    assert "subtitleFallbackTimerRef.current = null" in source
    assert "streamingAssistantMsgIdRef.current = null" in source
    assert "pendingAssistantMsgIdRef.current = null" in source
    assert "setIsSpeaking(false)" in source

    start_idx = source.index("const handleStart = useCallback")
    start_clear_idx = source.index("clearSubtitleState();", start_idx)
    previous_session_idx = source.index("const previousSessionId", start_idx)
    assert start_clear_idx < previous_session_idx

    avatar_idx = source.index("const handleAvatarChange = useCallback")
    avatar_clear_idx = source.index("clearSubtitleState();", avatar_idx)
    avatar_set_idx = source.index("setAvatarId(normalized.avatarId)", avatar_idx)
    assert avatar_clear_idx < avatar_set_idx

    model_idx = source.index("const handleModelChange = useCallback")
    model_clear_idx = source.index("clearSubtitleState();", model_idx)
    model_set_idx = source.index("setModel(newModel)", model_idx)
    assert model_clear_idx < model_set_idx


def test_settings_panel_supports_knowledge_base_selection() -> None:
    source = (ROOT / "apps/web/src/components/SettingsPanel.tsx").read_text(encoding="utf-8")

    assert "knowledgeBaseIds" in source
    assert "selected knowledge bases" not in source.lower()
    assert "可用知识库" not in source

    knowledge_idx = source.index('title="知识库"')
    model_idx = source.index('title="驱动模型"')
    knowledge_block = source[knowledge_idx:model_idx]
    assert "{knowledgeBases.length} 个知识库" in knowledge_block
    assert "onManageKnowledgeBases" in knowledge_block
    assert "selectedKnowledgeBaseSet.has(knowledgeBase.id)" in knowledge_block
    assert "disabled={!knowledgeBaseReady}" in knowledge_block
    assert "已选" in knowledge_block
    assert "可用知识库" not in knowledge_block


def test_settings_panel_places_knowledge_between_avatar_and_model() -> None:
    source = (ROOT / "apps/web/src/components/SettingsPanel.tsx").read_text(encoding="utf-8")

    avatar_idx = source.index('title="数字人形象"')
    knowledge_idx = source.index('title="知识库"')
    model_idx = source.index('title="驱动模型"')
    assert avatar_idx < knowledge_idx < model_idx
    assert "knowledgeBases: KnowledgeBaseSummary[]" in source
    assert "agentConfig: AgentConfig" in source
    assert "onAgentConfigChange" in source
    assert "onManageKnowledgeBases" in source
    manage_idx = source.index("管理")
    total_count_idx = source.index("{knowledgeBases.length} 个知识库")
    assert manage_idx < total_count_idx
    manage_button_start_idx = source.index("onClick={onManageKnowledgeBases}")
    manage_button_block = source[manage_button_start_idx:manage_idx]
    assert "border" not in manage_button_block
    assert "bg-white" not in manage_button_block
    assert "{agentConfig.knowledgeBaseIds.length} 个已选" not in source
    assert "可用知识库" not in source
    assert "启用知识库" not in source
    assert "已就绪" in source
    assert "准备中" in source
    assert "knowledgeBaseReady" in source
    assert "disabled={!knowledgeBaseReady}" in source
    assert "knowledgeDocuments" not in source


def test_realtime_knowledge_selection_can_sync_to_live_session() -> None:
    app_source = (ROOT / "apps/web/src/App.tsx").read_text(encoding="utf-8")
    settings_source = (ROOT / "apps/web/src/components/SettingsPanel.tsx").read_text(encoding="utf-8")
    api_source = (ROOT / "apps/web/src/lib/api.ts").read_text(encoding="utf-8")

    assert "SessionKnowledgeBasesRequest" in api_source
    assert "SessionKnowledgeBasesResponse" in api_source
    assert "/knowledge-bases`" in app_source
    assert "syncSessionKnowledgeBases" in app_source
    assert "knowledgeSyncChainRef" in app_source
    assert "sessionIdRef.current !== sid" in app_source
    assert "void syncSessionKnowledgeBases(normalized.knowledgeBaseIds)" in app_source
    assert "disabled={configLocked || !knowledgeBaseReady}" not in settings_source
    assert "disabled={!knowledgeBaseReady}" in settings_source


def test_realtime_settings_panel_does_not_manage_knowledge_documents() -> None:
    settings_source = (ROOT / "apps/web/src/components/SettingsPanel.tsx").read_text(encoding="utf-8")
    app_source = (ROOT / "apps/web/src/App.tsx").read_text(encoding="utf-8")

    assert "knowledgeDocuments" not in settings_source
    assert "onKnowledgeUpload" not in settings_source
    assert "上传文档" not in settings_source
    assert "refreshKnowledgeDocuments" not in app_source
    assert "handleKnowledgeUpload" not in app_source
    assert 'if (workflow === "realtime") void refreshKnowledgeBases();' in app_source
    assert "knowledgeUploading" not in app_source
