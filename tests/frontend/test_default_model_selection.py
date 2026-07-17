from __future__ import annotations

from pathlib import Path


def test_frontend_prefers_backend_default_model_before_avatar_model() -> None:
    source = Path("apps/web/src/App.tsx").read_text(encoding="utf-8")
    assert "default_model?: string" in source
    assert "defaultModel?: string | null" in source

    default_idx = source.index("if (defaultModel && available.has(defaultModel)")
    current_idx = source.index("if (available.has(currentModel) && connected.has(currentModel))")
    avatar_idx = source.index("const avatarModel = initialAvatar?.model_type")
    assert default_idx < current_idx
    assert default_idx < avatar_idx

    assert "mo.default_model" in source



def test_frontend_keeps_persona_selected_when_model_changes() -> None:
    source = Path("apps/web/src/App.tsx").read_text(encoding="utf-8")
    start = source.index("  const handleModelChange = useCallback((newModel: string) => {")
    end = source.index("\n\n  useEffect(() => {\n    const handlePageHide", start)
    block = source[start:end]
    assert 'setSelectedPersonaId("")' not in block
    assert 'window.localStorage.removeItem(SELECTED_PERSONA_STORAGE_KEY)' not in block
    assert 'clearSubtitleState();' in block
    assert 'setModel(newModel);' in block
