from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_light2d_frontend_modules_and_app_wiring_exist() -> None:
    expected = [
        ROOT / "apps/web/src/light2d/audio.ts",
        ROOT / "apps/web/src/light2d/config.ts",
        ROOT / "apps/web/src/light2d/avatarSelection.ts",
        ROOT / "apps/web/src/components/Light2dAvatar.tsx",
    ]
    assert all(path.is_file() for path in expected)

    app = (ROOT / "apps/web/src/App.tsx").read_text(encoding="utf-8")
    stage = (ROOT / "apps/web/src/components/SceneStage.tsx").read_text(encoding="utf-8")
    assert "recommendAvatarForModel" in app
    assert "normalizeAvatarModelSelection" in app
    assert 'clientRenderer={!showStart && model === "mock"' in app
    assert "Light2dAvatar" in stage
    assert "onRendererError" in stage
    assert "const handleRendererError = useCallback" in stage
    assert "VideoBackground" in stage
    renderer = (ROOT / "apps/web/src/components/Light2dAvatar.tsx").read_text(encoding="utf-8")
    assert 'window.addEventListener("pointerdown", resumeAudio' in renderer
    assert 'window.addEventListener("keydown", resumeAudio' in renderer
    assert 'window.removeEventListener("pointerdown", resumeAudio' in renderer
    assert 'window.removeEventListener("keydown", resumeAudio' in renderer


def test_light2d_asset_contract_is_complete() -> None:
    avatar_dir = ROOT / "examples/avatars/dogo-light2d"
    manifest = json.loads((avatar_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["id"] == "dogo-light2d"
    assert manifest["model_type"] == "mock"
    renderer = manifest["metadata"]["client_renderer"]
    assert renderer == {
        "type": "light2d",
        "config": "light2d/avatar.json",
        "recommended_for": ["mock"],
    }

    config = json.loads((avatar_dir / renderer["config"]).read_text(encoding="utf-8"))
    sources = [config["layers"]["base"]["source"], config["layers"]["blink"]["source"]]
    sources.extend(layer["source"] for layer in config["layers"]["mouth"].values())
    assert len(sources) == 6
    assert all((avatar_dir / "light2d" / source).is_file() for source in sources)
    assert (avatar_dir / "preview.png").is_file()
    assert (avatar_dir / "reference.png").is_file()


def test_light2d_ui_labels_are_present() -> None:
    selection = (ROOT / "apps/web/src/components/AvatarSelectionStage.tsx").read_text(encoding="utf-8")
    settings = (ROOT / "apps/web/src/components/SettingsPanel.tsx").read_text(encoding="utf-8")
    app = (ROOT / "apps/web/src/App.tsx").read_text(encoding="utf-8")
    assert "免 GPU / 浏览器动画" in selection
    video_creation = (
        ROOT / "apps/web/src/components/VideoCreationWorkspace.tsx"
    ).read_text(encoding="utf-8")
    labels = (ROOT / "apps/web/src/lib/modelLabels.ts").read_text(encoding="utf-8")
    assert 'mock: "轻量模式"' in labels
    assert "modelLabel(" in settings
    assert "modelLabel(" in app
    assert "modelLabel(" in video_creation
    assert "轻量模式（Mock）" not in settings
    assert "轻量模式（Mock）" not in app
    assert "本地自测" not in settings


def test_dogo_is_locked_to_light_mode_in_realtime_and_offline_sources() -> None:
    app = (ROOT / "apps/web/src/App.tsx").read_text(encoding="utf-8")
    settings = (ROOT / "apps/web/src/components/SettingsPanel.tsx").read_text(encoding="utf-8")
    video_creation = (
        ROOT / "apps/web/src/components/VideoCreationWorkspace.tsx"
    ).read_text(encoding="utf-8")
    selection = (ROOT / "apps/web/src/light2d/avatarSelection.ts").read_text(encoding="utf-8")

    assert "normalizeAvatarModelSelection" in app
    assert "canChangeModelForAvatar" in app
    assert "isDogoLight2dAvatar" in settings
    assert "videoCreationStateForAvatar" in video_creation
    assert "videoCreationCompositionForAvatar" in video_creation
    assert "setVideoBackgroundId(null)" in video_creation
    assert 'model: locked ? "mock" : requestedModel' in selection


def test_all_user_visible_model_consumers_use_shared_labels() -> None:
    consumers = {
        "StartOverlay.tsx": "avatar.model_type",
        "AvatarSelectionStage.tsx": "selectedPersona.avatar.model",
        "AssetLibraryWorkspace.tsx": "item.model",
        "VideoCloneWorkspace.tsx": "avatar.model_type",
    }
    components = ROOT / "apps/web/src/components"
    for filename, raw_expression in consumers.items():
        source = (components / filename).read_text(encoding="utf-8")
        assert 'from "../lib/modelLabels"' in source
        assert "modelLabel(" in source
        assert f"{{{raw_expression}}}" not in source
        assert f"${{{raw_expression}}}" not in source
