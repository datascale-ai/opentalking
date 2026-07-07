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
    assert "VIDEO_CREATION_OUTPUT_RESOLUTION_OPTIONS" in source
    assert "computeVideoCreationMaxResolution" in source
    assert "computeVideoCreationOutputSize" in source
    assert "resolutionLabel" in source
    assert "selectedOutputResolution" in source
    assert "videoOutputResolution" in source
    assert "selectedVideoOutputSize" in source
    assert "if (!videoBackgroundId) return null;" not in source
    assert "maxSelectableOutputResolution" in source
    assert "options.includes(maxSelectableOutputResolution)" in source
    assert "outputResolutionOptionLabel" in source
    assert "\u539f\u5206\u8fa8\u7387" in source
    assert "\u8f93\u51fa\u5206\u8fa8\u7387" not in source
    assert "\u6700\u7ec8\u8f93\u51fa\u5c3a\u5bf8" not in source
    assert "\u5141\u8bb8\u8303\u56f4\uff1a480p -" not in source
    assert "DUO_DIALOG_1080P_AVATAR_IDS" not in source
    assert "\u56fe\u7247\u751f\u6210\u53c2\u8003\u89c6\u9891" in source
    assert "\u53c2\u8003\u89c6\u9891\u65f6\u957f" in source
    assert 'setModel("flashtalk")' in source
    assert 'audioSource: "reference_video"' in source
    assert "durationSec: referenceDurationSec" in source
