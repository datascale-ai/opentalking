from __future__ import annotations

from pathlib import Path


def test_quicktalk_frontend_uses_unified_speak_endpoint() -> None:
    source = Path("apps/web/src/App.tsx").read_text(encoding="utf-8")

    assert 'model === "quicktalk"' not in source
    assert 'const endpoint = "speak";' in source
    assert "prompt: text" not in source
    assert "text," in source
