from __future__ import annotations

from pathlib import Path


def test_frontend_does_not_inject_default_knowledge_base() -> None:
    source = Path("apps/web/src/App.tsx").read_text(encoding="utf-8")

    assert 'byId.set("default"' not in source
    assert 'knowledgeBaseIds: ["default"]' not in source
    assert 'normalizeKnowledgeBaseIds(agentConfig.knowledgeBaseIds, ["default"])' not in source
    assert 'knowledge_base_id: knowledgeBaseIds[0] ?? "default"' not in source


def test_asset_library_allows_deleting_any_listed_knowledge_base() -> None:
    source = Path("apps/web/src/components/AssetLibraryWorkspace.tsx").read_text(encoding="utf-8")

    assert 'selectedKnowledgeBase.id === "default"' not in source
