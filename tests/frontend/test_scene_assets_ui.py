from __future__ import annotations

from pathlib import Path


def test_api_exposes_scene_asset_types_and_helpers() -> None:
    source = Path("apps/web/src/lib/api.ts").read_text(encoding="utf-8")

    assert "export type SceneBackgroundAsset" in source
    assert "export type SceneComposition" in source
    assert "uploadSceneBackground" in source
    assert 'apiPostForm<SceneBackgroundAsset>("/scene-assets/backgrounds", form)' in source
    assert 'apiPost<SceneComposition>("/scene-assets/compositions", input)' in source


def test_asset_library_has_scene_assets_tab() -> None:
    source = Path("apps/web/src/components/AssetLibraryWorkspace.tsx").read_text(encoding="utf-8")

    assert 'type AssetTab = "exports" | "knowledge" | "memory" | "scenes" | "voices"' in source
    assert '{ id: "scenes", label: "场景资产" }' in source
    assert "renderScenesTab" in source
    assert "背景资产" in source
    assert "场景组合" in source
    assert "uploadSceneBackground" in source
    assert "createSceneComposition" in source


def test_app_passes_avatars_to_asset_library_workspace() -> None:
    source = Path("apps/web/src/App.tsx").read_text(encoding="utf-8")

    asset_library_mount = source.split('workflow === "assetLibrary" ? (', 1)[1].split(
        ') : workflow === "videoCreation" ? (',
        1,
    )[0]
    assert "<AssetLibraryWorkspace" in asset_library_mount
    assert "avatars={avatars}" in asset_library_mount


def test_app_wires_scene_selection_and_background_updates_to_asset_library_workspace() -> None:
    source = Path("apps/web/src/App.tsx").read_text(encoding="utf-8")

    asset_library_mount = source.split('workflow === "assetLibrary" ? (', 1)[1].split(
        ') : workflow === "videoCreation" ? (',
        1,
    )[0]
    assert "selectedSceneIdsByAvatar={selectedSceneIdsByAvatar}" in asset_library_mount
    assert "onSceneSelect={handleSceneSelect}" in asset_library_mount
    assert "onSceneBackgroundsChange={setSceneBackgrounds}" in asset_library_mount


def test_realtime_stage_uses_avatar_default_scene_without_cross_avatar_leakage() -> None:
    source = Path("apps/web/src/App.tsx").read_text(encoding="utf-8")

    selected_scene_block = source.split("const selectedScene = useMemo(", 1)[1].split(
        "const dismissToast",
        1,
    )[0]
    assert "selectedSceneIdsByAvatar[avatarId]" in selected_scene_block
    assert "scene.avatar_id === avatarId" in selected_scene_block
    assert "matchingScenes.length === 1 ? matchingScenes[0] : null" in selected_scene_block
    assert "[avatarId, sceneCompositions, selectedSceneIdsByAvatar]" in selected_scene_block


def test_asset_library_scene_cards_can_select_created_scene_and_sync_backgrounds() -> None:
    source = Path("apps/web/src/components/AssetLibraryWorkspace.tsx").read_text(encoding="utf-8")

    assert "selectedSceneIdsByAvatar?: Record<string, string>;" in source
    assert "onSceneSelect?: (scene: SceneComposition) => void;" in source
    assert "onSceneClear?: (avatarId: string) => void;" in source
    assert "onSceneBackgroundsChange?: (backgrounds: SceneBackgroundAsset[]) => void;" in source
    assert "onSceneSelect?.(created)" in source
    assert "onSceneBackgroundsChange?.(nextBackgrounds)" in source
    assert "onSceneSelect?.(scene)" in source
    assert "selectedSceneIdsByAvatar[scene.avatar_id] === scene.id" in source
    assert "设为默认" in source
    assert "当前默认" in source
    assert "取消默认" in source


def test_asset_library_groups_scene_compositions_by_avatar() -> None:
    source = Path("apps/web/src/components/AssetLibraryWorkspace.tsx").read_text(encoding="utf-8")

    assert "sceneGroups" in source
    assert "avatarById" in source
    assert "sceneCompositions.filter((scene) => scene.avatar_id === avatar.id)" in source


def test_scene_delete_actions_use_error_handled_handlers() -> None:
    source = Path("apps/web/src/components/AssetLibraryWorkspace.tsx").read_text(encoding="utf-8")

    assert "const handleDeleteSceneBackground = useCallback(async (background: SceneBackgroundAsset)" in source
    assert "const handleDeleteSceneComposition = useCallback(async (scene: SceneComposition)" in source
    assert "delete scene background failed" in source
    assert "delete scene composition failed" in source
    assert "err instanceof ApiError ? err.detail : null" in source
    assert "onNotify?.(detail ? `删除失败：${detail}` : \"删除失败，请稍后重试。\", \"error\")" in source
    assert "await loadScenes()" in source
    assert ".then(loadScenes)" not in source


def test_scene_ui_omits_matting_readiness_copy() -> None:
    asset_source = Path("apps/web/src/components/AssetLibraryWorkspace.tsx").read_text(encoding="utf-8")
    avatar_source = Path("apps/web/src/components/AvatarSelectionStage.tsx").read_text(encoding="utf-8")
    api_source = Path("apps/web/src/lib/api.ts").read_text(encoding="utf-8")

    assert 'matting_status: "unknown" | "opaque" | "transparent_ready";' in api_source
    assert "已抠像/透明数字人" not in asset_source
    assert "抠像状态未知" not in asset_source
    assert "未抠像" not in asset_source
    assert 'avatar?.matting_status === "unknown"' not in asset_source
    assert "matting_status" not in avatar_source
