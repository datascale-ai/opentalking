from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SOURCE = ROOT / "apps" / "web" / "src" / "lib" / "api.ts"
WORKSPACE_SOURCE = ROOT / "apps" / "web" / "src" / "components" / "VideoCreationWorkspace.tsx"


def test_video_creation_api_sends_structured_duo_dialog_payload() -> None:
    source = API_SOURCE.read_text(encoding="utf-8")

    assert '"duo_dialog"' in source
    assert 'export type PersonMode = "single" | "double";' in source
    assert "person_mode: PersonMode;" in source
    assert "updateAvatarPersonMode" not in source
    assert "export type DuoDialogLine" in source
    assert "export type DuoDialogRequest" in source
    assert "duoDialog?: DuoDialogRequest;" in source
    assert 'form.set("duo_dialog", JSON.stringify(input.duoDialog));' in source
    assert "duo_dialog: DuoDialogCapability | null;" in source


def test_video_creation_workspace_discovers_duo_dialog_capability_and_submits_it() -> None:
    source = WORKSPACE_SOURCE.read_text(encoding="utf-8")

    assert "双人对话设置" in source
    assert "PERSON_MODE_OPTIONS" in source
    assert "pendingSourceAssetFile" in source
    assert "handleUploadPersonModeSelect" in source
    assert 'form.set("person_mode", nextMode);' in source
    assert "PERSON_MODE_OPTIONS.map" in source
    assert "handlePersonModeChange" not in source
    assert "updateAvatarPersonMode" not in source
    assert "单人" in source
    assert "双人" in source
    assert "左侧" in source
    assert "右侧" in source
    assert "口播合成" in source
    assert 'selectedAvatar?.person_mode === "double"' in source
    assert 'id: "duo_dialog"' in source
    assert 'id: "voice_clone"' not in source[source.index("const AUDIO_SOURCE_OPTIONS") : source.index("const REFERENCE_DURATION_OPTIONS")]
    assert 'audioSource: "duo_dialog"' in source
    assert "duoDialog:" in source
    assert "speakers:" in source
    assert "duoDialogSpeakers" in source
    assert "requestDuoDialogPreview" in source
    assert "setDuoDialogLines" in source
    assert "onDragStart" in source
    assert "onDragOver" in source
    assert "dropDuoDialogLine" in source
    assert "zh-CN-YunxiNeural" in source
    assert "zh-CN-XiaoxiaoNeural" in source
    assert "试听对话" in source
    assert "<option value=\"left\">左侧</option>" in source
    assert "<option value=\"right\">右侧</option>" in source
    upload_choice_block = source[source.index("pendingSourceAssetFile ?") : source.index("{avatars.map")]
    assert "PERSON_MODE_OPTIONS.map" in upload_choice_block
    assert "onClick={() => void handleUploadPersonModeSelect(option.id)}" in upload_choice_block
    duo_block = source[source.index("双人对话设置") : source.index("<span>口播文本</span>")]
    assert "试听口播" not in duo_block
    assert "custom-视频创作-生成双人眨眼视频-1-20260703-155817-381" not in source
    assert "custom-视频创作-生成双人眨眼视频-20260703-155851-393" not in source
