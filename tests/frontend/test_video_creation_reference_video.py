from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SOURCE = ROOT / "apps" / "web" / "src" / "lib" / "api.ts"
WORKSPACE_SOURCE = ROOT / "apps" / "web" / "src" / "components" / "VideoCreationWorkspace.tsx"


def test_video_creation_api_accepts_reference_video_duration() -> None:
    source = API_SOURCE.read_text(encoding="utf-8")

    assert '"reference_video"' in source
    assert "durationSec?: number;" in source
    assert 'form.set("duration_sec", String(input.durationSec));' in source


def test_video_creation_workspace_exposes_reference_video_mode() -> None:
    source = WORKSPACE_SOURCE.read_text(encoding="utf-8")

    assert "type VideoCreationMode" in source
    assert "REFERENCE_DURATION_OPTIONS" in source
    assert "图片生成参考视频" in source
    assert "参考视频时长" in source
    assert 'setModel("flashtalk")' in source
    assert 'audioSource: "reference_video"' in source
    assert "durationSec: referenceDurationSec" in source
