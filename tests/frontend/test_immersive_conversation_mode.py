from __future__ import annotations

from pathlib import Path


def test_scene_stage_component_exists_and_handles_background_layers() -> None:
    source = Path("apps/web/src/components/SceneStage.tsx").read_text(encoding="utf-8")

    assert "export function SceneStage" in source
    assert "SceneBackgroundAsset" in source
    assert "SceneComposition" in source
    assert "scene-background-layer" in source
    assert "VideoBackground" in source
    assert "subtitle_style" in source


def test_scene_stage_applies_avatar_anchor_positioning() -> None:
    source = Path("apps/web/src/components/SceneStage.tsx").read_text(encoding="utf-8")

    assert "scene?.avatar_anchor" in source
    assert "AVATAR_ANCHOR_OBJECT_POSITIONS" in source
    assert 'bottom: "object-[center_bottom]"' in source
    assert 'left: "object-[left_center]"' in source
    assert 'right: "object-[right_center]"' in source
    assert "${avatarFit} ${avatarObjectPosition}" in source
    assert "AVATAR_ANCHOR_TRANSFORM_ORIGINS" in source
    assert "transformOrigin: avatarTransformOrigin" in source
    assert 'bottom: "items-end justify-center"' in source
    assert 'left: "items-center justify-start"' in source
    assert 'right: "items-center justify-end"' in source


def test_scene_stage_masks_transparent_avatar_video_with_preview_alpha() -> None:
    source = Path("apps/web/src/components/SceneStage.tsx").read_text(encoding="utf-8")

    assert "avatarMaskUrl?: string | null;" in source
    assert "WebkitMaskImage" in source
    assert "maskImage" in source
    assert "maskMode" in source
    assert "avatarMaskStyle" in source


def test_scene_stage_accepts_immersive_avatar_adjustments() -> None:
    source = Path("apps/web/src/components/SceneStage.tsx").read_text(encoding="utf-8")

    assert "avatarAdjust?: {" in source
    assert "x: number;" in source
    assert "y: number;" in source
    assert "scale: number;" in source
    assert "translate(${avatarAdjust.x}px, ${avatarAdjust.y}px) scale" in source


def test_app_uses_scene_stage_for_realtime_stage() -> None:
    source = Path("apps/web/src/App.tsx").read_text(encoding="utf-8")

    assert 'import { SceneStage } from "./components/SceneStage";' in source
    assert "selectedScene" in source
    assert "sceneBackgrounds" in source
    assert "<SceneStage" in source
    assert "selectedAvatarMaskUrl" in source
    assert "avatarMaskUrl={showStart ? null : selectedAvatarMaskUrl}" in source


def test_app_keeps_webrtc_remote_stream_identity_for_async_tracks() -> None:
    source = Path("apps/web/src/App.tsx").read_text(encoding="utf-8")

    assert "cloneMediaStream" not in source
    assert "setRemoteStream(remoteStream)" in source
    assert "setRemoteStream(playback.remoteStream)" in source


def test_video_background_falls_back_to_muted_playback_when_autoplay_blocks_audio() -> None:
    source = Path("apps/web/src/components/VideoBackground.tsx").read_text(encoding="utf-8")

    assert "export function playWithMutedFallback" in source
    assert "video.muted = true" in source
    assert "video.play().catch" in source


def test_app_replays_remote_video_with_muted_fallback_when_view_changes() -> None:
    source = Path("apps/web/src/App.tsx").read_text(encoding="utf-8")

    assert 'import { playWithMutedFallback } from "./components/VideoBackground";' in source
    effect_start = source.index("const video = videoRef.current;")
    effect_end = source.index("}, [conversationViewMode, remoteStream, workflow]);", effect_start)
    playback_effect = source[effect_start:effect_end]
    assert "playWithMutedFallback(video)" in playback_effect


def test_immersive_conversation_component_focuses_stage_and_input() -> None:
    source = Path("apps/web/src/components/ImmersiveConversation.tsx").read_text(encoding="utf-8")

    assert "export function ImmersiveConversation" in source
    assert "SceneStage" in source
    assert "ChatInput" in source
    assert "onExit" in source
    assert 'event.key === "Escape"' in source
    assert "bottom-3" in source
    assert "返回工作台" in source


def test_topbar_exposes_realtime_view_mode_toggle() -> None:
    source = Path("apps/web/src/components/TopBar.tsx").read_text(encoding="utf-8")

    assert 'export type ConversationViewMode = "studio" | "immersive";' in source
    assert "onConversationViewModeChange" in source
    assert "沉浸" in source


def test_topbar_hides_main_module_navigation_in_immersive_chrome() -> None:
    source = Path("apps/web/src/components/TopBar.tsx").read_text(encoding="utf-8")

    nav_label = source.index('aria-label="工作台模块"')
    nav_start = source.rindex("<nav", 0, nav_label)
    nav_end = source.index("</nav>", nav_label)
    nav_block = source[nav_start:nav_end]
    assert "immersiveChrome" in nav_block
    assert '? "hidden"' in nav_block


def test_topbar_immersive_chrome_does_not_stay_open_from_button_focus() -> None:
    source = Path("apps/web/src/components/TopBar.tsx").read_text(encoding="utf-8")

    header_start = source.index("<header")
    header_end = source.index(">", header_start)
    header_block = source[header_start:header_end]
    assert "focus-within:translate-y-0" not in header_block


def test_app_switches_between_studio_and_immersive_realtime_views() -> None:
    source = Path("apps/web/src/App.tsx").read_text(encoding="utf-8")

    assert "conversationViewMode" in source
    assert "immersiveActive" in source
    assert 'conversationViewMode === "immersive"' in source


def test_app_exits_immersive_realtime_view_with_escape() -> None:
    source = Path("apps/web/src/App.tsx").read_text(encoding="utf-8")

    assert 'event.key !== "Escape"' in source
    assert 'setConversationViewMode("studio")' in source


def test_app_offers_immersive_avatar_adjustment_controls() -> None:
    source = Path("apps/web/src/App.tsx").read_text(encoding="utf-8")

    assert "immersiveAvatarAdjust" in source
    assert "avatarAdjust={immersiveActive ? immersiveAvatarAdjust : undefined}" in source
    assert "画面微调" in source
    assert "水平" in source
    assert "垂直" in source
    assert "缩放" in source
    assert "重置" in source


def test_immersive_avatar_adjustment_controls_have_wide_ranges() -> None:
    source = Path("apps/web/src/App.tsx").read_text(encoding="utf-8")

    x_label = source.index("<span>水平</span>")
    y_label = source.index("<span>垂直</span>")
    scale_label = source.index("<span>缩放</span>")
    x_block = source[x_label:source.index('value={immersiveAvatarAdjust.x}', x_label)]
    y_block = source[y_label:source.index('value={immersiveAvatarAdjust.y}', y_label)]
    scale_block = source[scale_label:source.index('value={immersiveAvatarAdjust.scale}', scale_label)]

    assert 'min="-480"' in x_block
    assert 'max="480"' in x_block
    assert 'min="-320"' in y_block
    assert 'max="320"' in y_block
    assert 'min="0.4"' in scale_block
    assert 'max="2.2"' in scale_block


def test_immersive_avatar_adjustment_panel_uses_opaque_background() -> None:
    source = Path("apps/web/src/App.tsx").read_text(encoding="utf-8")

    panel_start = source.index('className="w-64 rounded-l-xl')
    panel_end = source.index('画面微调', panel_start)
    panel_block = source[panel_start:panel_end]
    assert "bg-slate-950 " in panel_block
    assert "bg-slate-950/" not in panel_block
    assert "backdrop-blur" not in panel_block


def test_app_gates_persisted_immersive_mode_while_start_is_visible() -> None:
    source = Path("apps/web/src/App.tsx").read_text(encoding="utf-8")

    assert 'const effectiveConversationViewMode = showStart ? "studio" : conversationViewMode;' in source
    assert 'effectiveConversationViewMode === "immersive"' in source
