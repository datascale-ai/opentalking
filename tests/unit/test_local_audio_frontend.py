from __future__ import annotations

from pathlib import Path


WEB = Path("apps/web/src")


def test_frontend_lists_local_tts_models_and_labels():
    constants = (WEB / "constants" / "ttsBailian.ts").read_text(encoding="utf-8")
    settings = (WEB / "components" / "SettingsPanel.tsx").read_text(encoding="utf-8")
    workspace = (WEB / "components" / "VideoCreationWorkspace.tsx").read_text(encoding="utf-8")
    clone = (WEB / "components" / "BailianVoiceClone.tsx").read_text(encoding="utf-8")
    app = (WEB / "App.tsx").read_text(encoding="utf-8")

    assert "local_cosyvoice" in constants
    assert "indextts" in constants
    assert "local_f5_tts" in constants
    assert "Local CosyVoice" in settings
    assert "IndexTTS" in settings
    assert "Local IndexTTS" in settings
    assert "Local F5-TTS" in settings
    assert "OmniRT IndexTTS" not in settings
    assert "Local IndexTTS" in workspace
    assert "Local F5-TTS" in workspace
    assert "OmniRT IndexTTS" not in workspace
    assert "Local IndexTTS" in clone
    assert "Local F5-TTS" in clone
    assert "OmniRT IndexTTS" not in clone
    assert "本地模型" in constants
    assert "local_cosyvoice" in app
    assert "indextts" in app
    assert "FunAudioLLM/Fun-CosyVoice3-0.5B-2512" in constants
    assert "IndexTeam/IndexTTS-2" in constants
    assert "SWivid/F5-TTS/F5TTS_v1_Base" in constants
    assert "LOCAL_F5_TTS_MODEL_OPTIONS" in app
    assert "local_f5_tts" in app[app.index("function normalizeTtsProvider"):app.index("if (normalized === \"local_indextts\"")]
    assert "if (p === \"local_f5_tts\") return \"local_f5_tts\"" in app
    assert 'ttsProvider === "local_f5_tts"' in app[app.index("const sharedSystemPrompt"):app.index("targetModel: sharedSystemPrompt")]
    assert "iic/CosyVoice-300M" not in constants
    assert "local_qwen3_tts" not in settings

def test_single_model_tts_provider_opens_voice_picker_first():
    settings = (WEB / "components" / "SettingsPanel.tsx").read_text(encoding="utf-8")

    assert "providerHasSingleModel" in settings
    assert 'setVoiceView(providerHasSingleModel(provider) ? "voices" : "models")' in settings
    assert (
        'voiceView === "voices" && ttsProvider !== "edge" && ttsProvider !== "openai_compatible"'
        in settings
    )
    assert "选择音色 ·" in settings
    assert "const qwenModelColumnOptions" in settings
    assert "const providerOptions" in settings
    assert "hasChildren: true," in settings[settings.index("const providerOptions"):settings.index("const selectedProvider")]
    assert "hasChildren: p !== ttsProvider" not in settings
    assert "provider === \"local_f5_tts\"" in settings[settings.index("providerHasSingleModel"):settings.index("handleProviderSelect")]
    assert settings.index("const qwenModelColumnOptions") < settings.index("const providerOptions")


def test_frontend_shows_local_asr_status_copy():
    settings = (WEB / "components" / "SettingsPanel.tsx").read_text(encoding="utf-8")
    app = (WEB / "App.tsx").read_text(encoding="utf-8")

    assert "STT" in settings
    assert "SenseVoiceSmall" in settings
    assert "Local FunASR" not in settings
    assert "Local sherpa-onnx" not in settings
    assert "OPENTALKING_STT_DEFAULT_PROVIDER" in settings
    assert "asrProvider" in app
    assert "asrModel" in app


def test_frontend_exposes_api_stt_provider_selection():
    settings = (WEB / "components" / "SettingsPanel.tsx").read_text(encoding="utf-8")
    chat_input = (WEB / "components" / "ChatInput.tsx").read_text(encoding="utf-8")
    app = (WEB / "App.tsx").read_text(encoding="utf-8")

    assert "API 语音识别" in settings
    assert "百炼 API" in settings
    assert "onAsrProviderChange" in settings
    assert "stt_provider" in chat_input
    assert "fd.append(\"stt_provider\"" in app


def test_realtime_indextts_clone_voice_and_model_are_sent_to_session_and_speak():
    app = (WEB / "App.tsx").read_text(encoding="utf-8")
    chat_input = (WEB / "components" / "ChatInput.tsx").read_text(encoding="utf-8")

    apply_block = app[app.index("const applyClonedVoice"):app.index("const bailianModels")]
    assert "setTtsProvider(application.provider)" in apply_block
    assert "setQwenModel(application.model)" in apply_block
    assert "setQwenVoice(application.voice)" in apply_block

    create_start = app.index("const created = await apiPost<CreateSessionResponse>")
    create_block = app[create_start:app.index("wav2lip_postprocess_mode", create_start)]
    assert "tts_provider: ttsProvider" in create_block
    assert "tts_voice: isEdgeTts(ttsProvider)" in create_block
    assert "selectedTtsVoice" in create_block
    assert "resolveSelectableTtsVoice(ttsProvider, qwenVoice, bailianVoices)" in app
    assert "tts_model: ttsModelSelectable(ttsProvider) ? qwenModel : undefined" in create_block

    speak_start = app.index("const payload = {")
    speak_block = app[speak_start:app.index("void apiPost(`/sessions/${sessionId}/${endpoint}`", speak_start)]
    assert "voice:" in speak_block
    assert "selectedTtsVoice" in speak_block
    assert "tts_model: ttsModelSelectable(ttsProvider) ? qwenModel : undefined" in speak_block

    stream_start = chat_input.index("ws.send(")
    stream_meta = chat_input[stream_start:chat_input.index("stt_provider: sttProvider", stream_start)]
    assert 'qwenVoice ?? ""' in stream_meta
    assert 'tts_model: !isEdgeTts(ttsProvider) ? qwenModel ?? "" : ""' in stream_meta


def test_voice_clone_recorder_has_error_copy_and_upload_fallback():
    clone = (WEB / "components" / "BailianVoiceClone.tsx").read_text(encoding="utf-8")

    assert "navigator.mediaDevices" in clone
    assert "麦克风不可用" in clone
    assert "请改用上传音频" in clone
    assert "麦克风权限被拒绝" in clone
    assert "type=\"file\"" in clone
    assert "accept=\"audio/*,.webm,.mp3,.wav,.m4a,.aac,.flac,.ogg\"" in clone
    assert "handleAudioFileChange" in clone


def test_video_clone_camera_failures_show_actionable_copy():
    clone = (WEB / "components" / "VideoCloneWorkspace.tsx").read_text(encoding="utf-8")

    assert "videoCloneStartErrorMessage" in clone
    assert "摄像头权限被拒绝" in clone
    assert "未检测到可用摄像头" in clone
    assert "当前浏览器或访问地址不支持摄像头" in clone
    assert "请使用本机 http://127.0.0.1" in clone
    assert "NotSupportedError" in clone
    assert 'onNotify?.(detail, "error")' in clone
    assert "无法启动摄像头或视频克隆服务" not in clone


def test_video_clone_exposes_reference_controls_and_return_to_avatar_selection():
    clone = (WEB / "components" / "VideoCloneWorkspace.tsx").read_text(encoding="utf-8")
    settings = (WEB / "components" / "SettingsPanel.tsx").read_text(encoding="utf-8")
    app = (WEB / "App.tsx").read_text(encoding="utf-8")

    for key in (
        "flag_stitching",
        "flag_pasteback",
        "flag_relative_motion",
        "flag_normalize_lip",
        "flag_lip_retargeting",
    ):
        assert key in settings
        assert key in app
        assert key in clone
    assert "拼回原图" in clone
    assert "更换形象" in clone
    assert "handleReturnToAvatarSelection" in clone
    return_block = clone[clone.index("const handleReturnToAvatarSelection"):clone.index("const handleUploadPreview")]
    assert "stop()" in return_block
    assert "setOutputUrl(null)" in return_block
    assert "sourcePanelRef.current?.scrollIntoView" in return_block


def test_video_clone_upload_preview_uses_full_frame_and_not_camera_mirror():
    clone = (WEB / "components" / "VideoCloneWorkspace.tsx").read_text(encoding="utf-8")

    assert 'uploadVideoUrl ? "object-contain" : "object-cover"' in clone
    assert "mirror && !uploadVideoUrl" in clone
    preview_block = clone[clone.index("<video ref={videoRef}"):clone.index("/>", clone.index("<video ref={videoRef}"))]
    assert "object-contain" in preview_block
    assert "object-cover" in preview_block
    send_frame_block = clone[clone.index("const sendFrame"):clone.index("canvas.toBlob")]
    assert "mirror && !uploadVideoUrl" in send_frame_block


def test_video_clone_runtime_controls_send_config_update():
    clone = (WEB / "components" / "VideoCloneWorkspace.tsx").read_text(encoding="utf-8")

    assert "sendRuntimeConfigUpdate" in clone
    assert 'type: "config_update"' in clone
    assert "handleConfigChange" in clone
    assert "sendRuntimeConfigUpdate(normalizedConfig)" in clone
    assert "handleCropDrivingChange" in clone
    assert 'sendRuntimeConfigUpdate({ flag_crop_driving_video: checked })' in clone


def test_video_clone_allows_uploading_source_avatar():
    clone = (WEB / "components" / "VideoCloneWorkspace.tsx").read_text(encoding="utf-8")
    app = (WEB / "App.tsx").read_text(encoding="utf-8")

    assert "上传 source 形象" in clone
    assert "handleSourceUpload" in clone
    assert 'apiPostForm<AvatarSummary>("/avatars/custom", form)' in clone
    assert 'form.set("base_avatar_id", selectedAvatar.id)' in clone
    assert 'form.set("model", "fasterliveportrait")' in clone
    assert "onAvatarUploaded(created)" in clone
    assert "handleVideoCloneAvatarUploaded" in app
    assert "onAvatarUploaded={handleVideoCloneAvatarUploaded}" in app


def test_custom_avatar_upload_can_request_background_removal():
    app = (WEB / "App.tsx").read_text(encoding="utf-8")
    stage = (WEB / "components" / "AvatarSelectionStage.tsx").read_text(encoding="utf-8")

    assert "上传时抠除背景" in stage
    assert "customRemoveBackground" in stage
    assert "customUploadState" in stage
    assert "正在抠除背景..." in stage
    assert "抠图完成" in stage
    assert "createdCustomAvatar" in stage
    assert "buildApiUrl(`/avatars/${encodeURIComponent(createdCustomAvatar.id)}/preview`)" in stage
    assert "removeBackground: customRemoveBackground" in stage
    assert "await onCustomAvatarCreate" in stage
    assert 'fd.set("remove_background", options?.removeBackground ? "true" : "false")' in app
    assert "return created" in app
    assert "创建失败：" in app
    assert "e instanceof ApiError ? e.detail : null" in app
    toast = (WEB / "components" / "ToastStack.tsx").read_text(encoding="utf-8")
    assert "whitespace-pre-line break-words" in toast
    assert "tone !== \"error\"" in app
    assert "pauseToast" in app
    assert "resumeToast" in app
    assert "onMouseEnter={() => onPause(toast.id)}" in toast
    assert "onMouseLeave={() => onResume(toast.id)}" in toast


def test_video_clone_lip_retargeting_disables_relative_motion():
    clone = (WEB / "components" / "VideoCloneWorkspace.tsx").read_text(encoding="utf-8")

    assert "normalizeVideoCloneConfigChange" in clone
    assert "flag_lip_retargeting" in clone
    assert "flag_relative_motion: false" in clone
    assert "handleConfigChange({ ...config, [control.key]: event.target.checked })" in clone


def test_frontend_does_not_seed_local_default_voice():
    constants = (WEB / "constants" / "ttsBailian.ts").read_text(encoding="utf-8")

    assert "local-default" not in constants


def test_local_cosyvoice_clone_submits_prompt_text():
    clone = (WEB / "components" / "BailianVoiceClone.tsx").read_text(encoding="utf-8")

    assert "fd.append(\"prompt_text\"" in clone
    assert "setPromptText" in clone
    assert "<textarea" in clone


def test_frontend_hides_other_local_audio_experiments():
    constants = (WEB / "constants" / "ttsBailian.ts").read_text(encoding="utf-8")
    settings = (WEB / "components" / "SettingsPanel.tsx").read_text(encoding="utf-8")

    assert "iic/CosyVoice-300M" not in constants
    assert "CosyVoice 300M" not in constants
    assert "本地实验" not in constants
    assert "Qwen3-TTS" not in settings
    assert "FunASR" not in settings
    assert "sherpa-onnx" not in settings


def test_frontend_locks_stt_provider_after_session_start():
    settings = (WEB / "components" / "SettingsPanel.tsx").read_text(encoding="utf-8")
    app = (WEB / "App.tsx").read_text(encoding="utf-8")

    assert "configLocked" in settings
    assert "disabled={configLocked}" in settings
    assert "当前数字人运行中，停止后可修改语音识别配置。" in settings
    assert "activeAsrProvider" in app
    assert "sttProvider={activeAsrProvider}" in app


def test_frontend_shows_provider_specific_stt_model_names():
    settings = (WEB / "components" / "SettingsPanel.tsx").read_text(encoding="utf-8")
    app = (WEB / "App.tsx").read_text(encoding="utf-8")

    assert "ASR_PROVIDER_MODELS" in settings
    assert "paraformer-realtime-v2" in settings
    assert "selectedAsrModel" in settings
    assert "STT_MODEL_BY_PROVIDER" in app


def test_frontend_blocks_session_start_when_selected_api_audio_key_is_missing():
    app = (WEB / "App.tsx").read_text(encoding="utf-8")

    assert "validateAudioProviderConfigBeforeStart" in app
    assert "OPENTALKING_STT_DASHSCOPE_API_KEY" in app
    assert "OPENTALKING_TTS_DASHSCOPE_API_KEY" in app
    assert "const startBlockReason = validateAudioProviderConfigBeforeStart" in app
    block = app[app.index("const startBlockReason"):app.index("const previousSessionId")]
    assert 'const sttStatus = runtimeStatus?.stt_providers?.[normalizeAsrProvider(sttProvider, "dashscope")]' in app
    assert "const sttKeySet = sttStatus?.key_set ?? runtimeStatus?.stt_key_set" in app
    assert "const ttsStatus = runtimeStatus?.tts_providers?.[ttsProvider]" in app
    assert "const ttsKeySet = ttsStatus?.key_set ?? runtimeStatus?.tts_key_set" in app
    assert "notify(startBlockReason, \"error\")" in block
    assert "return;" in block



def test_frontend_sends_stt_provider_when_creating_session():
    app = (WEB / "App.tsx").read_text(encoding="utf-8")

    block = app[app.index('apiPost<CreateSessionResponse>("/sessions"'):app.index("createdSessionId = created.session_id")]
    assert "stt_provider: lockedAsrProvider" in block


def test_frontend_refreshes_runtime_status_before_session_start():
    app = (WEB / "App.tsx").read_text(encoding="utf-8")

    block = app[app.index("const handleStart = useCallback"):app.index("const handleFasterLivePortraitConfigChange")]
    assert "latestRuntimeStatus = await apiGet<HealthResponse>(\"/health\")" in block
    assert "setRuntimeStatus(latestRuntimeStatus)" in block
    assert "runtimeStatus: latestRuntimeStatus" in block


def test_frontend_surfaces_runtime_audio_errors_in_chat_panel():
    app = (WEB / "App.tsx").read_text(encoding="utf-8")
    chat_input = (WEB / "components" / "ChatInput.tsx").read_text(encoding="utf-8")

    assert "appendAssistantError" in app
    assert "语音识别失败：" in app
    assert "发送失败：" in app
    assert "onSpeakAudioStreamError" in app
    assert "onSpeakAudioStreamErrorRef" in chat_input
    assert "voice segment failed" in chat_input


def test_frontend_preserves_custom_avatar_selection_across_model_changes():
    app = (WEB / "App.tsx").read_text(encoding="utf-8")

    assert "SELECTED_AVATAR_STORAGE_KEY" in app
    assert "readStoredAvatarId" in app
    assert "writeStoredAvatarId" in app
    assert 'fd.set("model", model)' in app
    assert "writeStoredAvatarId(created.id)" in app
    assert "storedAvatarSelection" in app
    assert "SELECTED_AVATAR_SOURCE_STORAGE_KEY" in app
    assert 'storedSelection?.source === "explicit"' in app
    assert 'if (newModel === "fasterliveportrait")' not in app
    assert 'setAvatarId(preferred.id)' not in app


def test_frontend_prefers_existing_custom_avatar_before_builtin_default():
    app = (WEB / "App.tsx").read_text(encoding="utf-8")

    assert "pickInitialCustomAvatar" in app
    assert "avatar.is_custom" in app
    assert "const customAvatar = pickInitialCustomAvatar(avatars, available)" in app
    custom_idx = app.index("const customAvatar = pickInitialCustomAvatar")
    builtin_idx = app.index('avatars.find((a) => a.id === "anime-handsome-guy"')
    assert custom_idx < builtin_idx



def test_frontend_defines_export_video_api_contract():
    api = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")

    assert "export type ExportVideoItem" in api
    for field in (
        "duration_sec",
        "size_bytes",
        "download_url",
        "session_id",
        "avatar_id",
        "model",
    ):
        assert field in api


def test_asset_library_workspace_lists_exported_videos():
    asset = (WEB / "components" / "AssetLibraryWorkspace.tsx").read_text(encoding="utf-8")
    app = (WEB / "App.tsx").read_text(encoding="utf-8")
    topbar = (WEB / "components" / "TopBar.tsx").read_text(encoding="utf-8")

    assert "AssetLibraryWorkspace" in app
    assert "assetLibrary" in topbar
    assert "导出视频" in asset
    assert "场景资产" in asset
    assert "声音资产" in asset
    assert 'apiGet<{ items: ExportVideoItem[] }>("/exports/videos")' in asset
    assert "listSceneCompositions()" in asset
    assert "download_url" in asset
    assert "navigator.clipboard.writeText" in asset
    assert "apiDelete(`/exports/videos/${item.id}`)" in asset
    assert "deleteSceneComposition(scene.id)" in asset


def test_realtime_recording_uses_browser_media_recorder_and_uploads_export():
    app = (WEB / "App.tsx").read_text(encoding="utf-8")
    webrtc = (WEB / "lib" / "webrtc.ts").read_text(encoding="utf-8")

    assert "remoteStream" in webrtc
    assert "onRemoteStream" in webrtc
    assert "MediaRecorder" in app
    assert "getUserMedia({ audio: true" in app
    assert "uploadExportVideo" in app
    assert 'kind", "realtime_dialogue"' in app or 'kind: "realtime_dialogue"' in app
    assert "pendingRealtimeExportRef" in app
    assert "retryPendingRealtimeExport" in app
    record_block = app[app.index("const startRealtimeRecording"):app.index("recorder.start(1000)")]
    assert '"video/mp4' in record_block
    assert record_block.index('"video/mp4') < record_block.index('"video/webm')
    assert "录制已保存，可在资产库查看" in app


def test_realtime_recording_clones_stage_video_tracks_before_cleanup():
    app = (WEB / "App.tsx").read_text(encoding="utf-8")

    record_block = app[app.index("const startRealtimeRecording"):app.index("recorder.start(1000)")]
    cleanup_block = app[app.index("const cleanupRealtimeRecordStreams"):app.index("const uploadRealtimeExport")]

    assert "stageStream.getVideoTracks().map((track) => track.clone())" in record_block
    assert "new MediaStream(recordVideoTracks)" in record_block
    assert "realtimeRecordStreamRef.current = outputStream" in record_block
    assert "realtimeRecordStreamRef.current.getTracks()" in cleanup_block


def test_export_upload_uses_blob_mime_type_for_filename_extension():
    api = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")

    assert "exportVideoExtensionForMimeType" in api
    assert '"video/mp4"' in api
    assert '".mp4"' in api
    assert '"video/webm"' in api
    assert '".webm"' in api
    assert "input.blob.type" in api
    assert "`${input.kind}${exportVideoExtensionForMimeType(input.blob.type)}`" in api


def test_realtime_recording_has_microphone_permission_timeout():
    app = (WEB / "App.tsx").read_text(encoding="utf-8")

    assert "requestUserAudioWithTimeout" in app
    assert "microphonePermissionTimeoutMs" in app
    assert "麦克风权限请求超时" in app
    record_block = app[app.index("const startRealtimeRecording"):app.index("recorder.start(1000)")]
    assert "requestUserAudioWithTimeout" in record_block
    assert "navigator.mediaDevices.getUserMedia({ audio: true })" not in record_block


def test_realtime_recording_start_failures_show_actionable_copy():
    app = (WEB / "App.tsx").read_text(encoding="utf-8")

    assert "realtimeRecordingStartErrorMessage" in app
    assert "当前访问地址不是浏览器安全来源" in app
    assert "http://127.0.0.1" in app
    assert "NotSupportedError" in app
    assert "SecurityError" in app
    assert "NotReadableError" in app
    assert "未检测到可用麦克风" in app
    record_error_block = app[
        app.index("function realtimeRecordingStartErrorMessage"):app.index("export default function App")
    ]
    assert "开始录制失败，请确认浏览器权限和当前会话状态。" not in record_error_block


def test_video_clone_records_output_canvas_without_audio():
    clone = (WEB / "components" / "VideoCloneWorkspace.tsx").read_text(encoding="utf-8")

    assert "outputRecordCanvasRef" in clone
    assert "captureStream(fps)" in clone
    assert "new MediaRecorder" in clone
    assert 'kind", "video_clone"' in clone or 'kind: "video_clone"' in clone
    assert "onExportCreated" in clone
    record_block = clone[clone.index("const startOutputRecording"):clone.index("recorder.start(1000)")]
    assert '"video/mp4' in record_block
    assert record_block.index('"video/mp4') < record_block.index('"video/webm')
    assert "视频克隆录制已保存，可在资产库查看" in clone
    assert "audio" not in clone[clone.index("const startOutputRecording"):clone.index("const stopOutputRecording")]


def test_video_creation_workspace_wires_offline_generation_flow():
    app = (WEB / "App.tsx").read_text(encoding="utf-8")
    topbar = (WEB / "components" / "TopBar.tsx").read_text(encoding="utf-8")
    api = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")
    workspace = (WEB / "components" / "VideoCreationWorkspace.tsx").read_text(encoding="utf-8")
    model_labels = (WEB / "lib" / "modelLabels.ts").read_text(encoding="utf-8")

    assert '"videoCreation"' in topbar
    assert "视频创作" in topbar
    assert "VideoCreationWorkspace" in app
    assert 'workflow === "videoCreation"' in app
    assert 'onExportCreated={() => setAssetLibraryRefreshKey((value) => value + 1)}' in app
    assert '"video_creation"' in api
    assert "export type VideoCreationJobResponse" in api
    assert "createVideoCreationJob" in api
    assert 'apiPostForm<VideoCreationJobResponse>("/video-creation/jobs", form)' in api
    assert '"flashtalk"' in workspace
    assert '"flashhead"' in workspace
    assert 'from "../lib/modelLabels"' in workspace
    assert "modelLabel(item)" in workspace
    assert 'flashtalk: "FlashTalk"' in model_labels
    assert 'flashhead: "FlashHead"' in model_labels
    assert '"musetalk"' in workspace
    assert 'musetalk: "MuseTalk"' in model_labels
    assert "音频来源" in workspace
    assert "上传音频" in workspace
    assert "口播合成" in workspace
    assert "双人对话" in workspace
    assert "复刻音色" in workspace
    assert "audioSource," in workspace
    assert 'form.set("audio_source", input.audioSource)' in api
    assert '"upload" | "tts_text" | "voice_clone" | "duo_dialog" | "reference_video"' in api
    assert "录制/上传复刻" in workspace
    assert "BailianVoiceClone" in workspace
    assert "onVoiceCloned" in workspace
    assert "已保存到资产库" in workspace
    assert "去资产库查看" in workspace


def test_video_creation_workspace_supports_one_off_scene_composition():
    app = (WEB / "App.tsx").read_text(encoding="utf-8")
    api = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")
    workspace = (WEB / "components" / "VideoCreationWorkspace.tsx").read_text(encoding="utf-8")

    assert "sceneBackgrounds={sceneBackgrounds}" in app
    assert "sceneCompositions={sceneCompositions}" in app
    assert "selectedSceneIdsByAvatar={selectedSceneIdsByAvatar}" in app
    assert "export type VideoCreationCompositionConfig" in api
    assert "compositionConfig?: VideoCreationCompositionConfig | null" in api
    assert 'form.set("composition_config", JSON.stringify(input.compositionConfig))' in api
    assert "sceneBackgrounds: SceneBackgroundAsset[]" in workspace
    assert "sceneCompositions: SceneComposition[]" in workspace
    assert "selectedSceneIdsByAvatar?: Record<string, string>" in workspace
    assert "生成前预览" in workspace
    assert "本次生成" in workspace
    assert "水平位置" in workspace
    assert "垂直位置" in workspace
    assert "人物缩放" in workspace
    assert "compositionConfig" in workspace
    assert "VIDEO_CREATION_OUTPUT_SIZES" in workspace
    assert '"16:9"' in workspace
    assert '"9:16"' in workspace
    assert '"1:1"' in workspace
    assert "videoOutputAspect" in workspace
    assert "selectedVideoOutputSize" in workspace
    assert "videoAvatarPreviewLayer" in workspace
    assert "left: `${videoAvatarPreviewLayer.leftPct}%`" in workspace
    assert "top: `${videoAvatarPreviewLayer.topPct}%`" in workspace
    assert "width: `${videoAvatarPreviewLayer.widthPct}%`" in workspace
    assert "height: `${videoAvatarPreviewLayer.heightPct}%`" in workspace
    assert "translate(${videoAvatarAdjust.x}px" not in workspace
    assert "output_width: selectedVideoOutputSize.width" in workspace
    assert "output_height: selectedVideoOutputSize.height" in workspace
    assert 'data-testid="video-creation-result-panel"' in workspace
    assert 'data-testid="video-creation-composition-controls"' in workspace
    assert "flex min-h-0 flex-col overflow-y-auto rounded-lg border border-slate-200 bg-white p-4 shadow-sm" in workspace
    assert "mt-3 space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-3" in workspace
    assert "mt-3 min-h-0 flex-1 space-y-3 overflow-y-auto" not in workspace
    assert "mt-4 shrink-0 overflow-hidden" in workspace
    assert "aspect-video w-full" in workspace
    assert "aspect-[9/16]" in workspace
    assert "aspect-square" in workspace
    assert "aspectRatio: selectedVideoOutputSize.aspectRatio" not in workspace
    assert "xl:grid-cols-[18rem_minmax(28rem,1fr)_minmax(32rem,42rem)]" in workspace
    assert "画面预览" in workspace
    assert "输出画幅" in workspace
    assert "h-[clamp(18rem,42vh,30rem)]" not in workspace
    assert workspace.index('data-testid="video-creation-result-panel"') < workspace.index("构图设置")
    assert workspace.index("构图设置") < workspace.index("生成前预览")


def test_frontend_export_controls_include_audio_renderer_models():
    app = (WEB / "App.tsx").read_text(encoding="utf-8")
    renderers_block = app[app.index("const SERVER_AUDIO_RENDERERS"):app.index("function isFlashRenderer")]

    for model in ("fasterliveportrait", "quicktalk", "musetalk", "wav2lip"):
        assert f'"{model}"' in renderers_block
    assert "音频驱动数字人会话连接后" in app


def test_frontend_wires_asset_library_knowledge_base_flow():
    app = (WEB / "App.tsx").read_text(encoding="utf-8")
    settings = (WEB / "components" / "SettingsPanel.tsx").read_text(encoding="utf-8")
    avatar_stage = (WEB / "components" / "AvatarSelectionStage.tsx").read_text(encoding="utf-8")
    asset_library = (WEB / "components" / "AssetLibraryWorkspace.tsx").read_text(encoding="utf-8")
    api = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")

    assert "KnowledgeDocument" in api
    assert "KnowledgeDocumentsResponse" in api
    assert '"/agent/knowledge-bases/default/documents"' not in app
    assert "apiPostForm<KnowledgeDocument>" in asset_library
    assert 'apiPostForm<KnowledgeDocument>("/agent/knowledge-documents", form)' in asset_library
    assert "/reindex" in asset_library
    assert "handleDeleteFilePoolDocument" in asset_library
    assert 'apiDelete(`/agent/knowledge-documents/${encodeURIComponent(document.id)}`)' in asset_library
    assert "文件池文件" in asset_library
    assert "新建知识库" in asset_library
    assert "onManageKnowledgeBases" in settings
    assert "{knowledgeBases.length} 个知识库" in settings
    assert "onKnowledgeUpload" not in settings
    assert "onKnowledgeReindex" not in settings
    assert "上传文档" not in settings
    assert "knowledgeUploading" not in app
    assert "knowledgeUploading?: boolean" not in avatar_stage
    assert "const knowledgeStartBlocked" not in avatar_stage
    assert "const startDisabled = baseDisabled" in avatar_stage
    assert "disabled={startDisabled}" in avatar_stage
    assert "knowledgeEnabled: true" in app
    assert "memoryEnabled: false" in app
    assert "长期记忆" not in avatar_stage


def test_video_creation_source_cards_hide_model_type():
    workspace = (WEB / "components" / "VideoCreationWorkspace.tsx").read_text(encoding="utf-8")
    source_block = workspace[
        workspace.index("{avatars.map((avatar) =>"):
        workspace.index("<section", workspace.index("{avatars.map((avatar) =>"))
    ]

    assert "avatar.model_type" not in source_block
    assert "{avatar.width}x{avatar.height}" in source_block
    assert "{avatar.model_type} · {avatar.width}x{avatar.height}" not in workspace


def test_video_creation_script_text_allows_longer_narration():
    workspace = (WEB / "components" / "VideoCreationWorkspace.tsx").read_text(encoding="utf-8")

    script_block = workspace[
        workspace.index("<span>口播文本</span>"):
        workspace.index("<div className=\"grid gap-3 md:grid-cols-3\">")
    ]
    assert "const VIDEO_CREATION_SCRIPT_MAX_CHARS = 1000" in workspace
    assert "{text.trim().length}/{VIDEO_CREATION_SCRIPT_MAX_CHARS}" in script_block
    assert "maxLength={VIDEO_CREATION_SCRIPT_MAX_CHARS}" in script_block


def test_tts_preview_text_allows_longer_narration():
    settings = (WEB / "components" / "SettingsPanel.tsx").read_text(encoding="utf-8")
    zh = Path("docs/zh/usage/webui/voice-and-tts.md").read_text(encoding="utf-8")
    en = Path("docs/en/usage/webui/voice-and-tts.md").read_text(encoding="utf-8")

    preview_block = settings[
        settings.index("<span className=\"mb-1.5 block text-xs text-slate-500\">音色试听</span>"):
        settings.index("{ttsPreviewing ? \"试听中...\" : \"试听一句\"}")
    ]
    assert "const TTS_PREVIEW_TEXT_MAX_CHARS = 1000" in settings
    assert "maxLength={TTS_PREVIEW_TEXT_MAX_CHARS}" in preview_block
    assert "{ttsPreviewText.trim().length}/{TTS_PREVIEW_TEXT_MAX_CHARS}" in preview_block
    assert "最多处理 1000 个字符" in zh
    assert "accepts up to 1000 characters" in en


def test_video_creation_workspace_previews_synthesized_voice_audio():
    workspace = (WEB / "components" / "VideoCreationWorkspace.tsx").read_text(encoding="utf-8")

    assert "requestTTSPreview" in workspace
    assert "buildTTSPreviewPayload" in workspace
    assert "handlePreviewTts" in workspace
    assert "ttsPreviewing" in workspace
    assert "试听中..." in workspace
    assert "试听口播" in workspace
    preview_block = workspace[workspace.index("const handlePreviewTts"):workspace.index("const handleGenerate")]
    assert "audio.play()" in preview_block
    assert "audioSource !== \"upload\"" in workspace


def test_video_creation_indextts_emotion_modes_default_to_full_strength():
    workspace = (WEB / "components" / "VideoCreationWorkspace.tsx").read_text(encoding="utf-8")

    assert "indexTTSEmotionModeConfig" in workspace
    mode_helper = workspace[
        workspace.index("export function indexTTSEmotionModeConfig"):
        workspace.index("function numberOr", workspace.index("export function indexTTSEmotionModeConfig"))
    ]
    assert "mode === \"voice\"" in mode_helper
    assert "emo_alpha: 0.6" in mode_helper
    assert "emo_alpha: 1" in mode_helper
    assert "indexTTSEmotionModeConfig(current, option.id)" in workspace


def test_video_creation_indextts_default_follows_voice_timbre():
    workspace = (WEB / "components" / "VideoCreationWorkspace.tsx").read_text(encoding="utf-8")

    default_block = workspace[
        workspace.index("const DEFAULT_INDEXTTS_CONFIG"):
        workspace.index("function buildIndexTTSQualityConfig")
    ]

    assert 'emotion_mode: "voice"' in default_block
    assert "emo_alpha: 0.6" in default_block
    assert "emo_vector: [0, 0, 0, 0, 0, 0, 0, 0]" in default_block


def test_video_creation_indextts_presets_use_explicit_vectors_for_clearer_emotion():
    workspace = (WEB / "components" / "VideoCreationWorkspace.tsx").read_text(encoding="utf-8")

    assert "config:" in workspace
    assert "emo_vector: [1, 0, 0, 0, 0, 0, 0, 0]" in workspace
    preset_helper = workspace[
        workspace.index("export function indexTTSEmotionPresetConfig"):
        workspace.index("export function indexTTSEmotionModeConfig")
    ]
    assert 'emotion_mode: "vector"' in preset_helper
    assert "emo_vector: [...vector]" in workspace
    assert "applyIndexTTSEmotionPreset(preset)" in workspace
    assert "applyIndexTTSEmotionPreset(preset.index)" not in workspace


def test_video_creation_indextts_presets_have_clear_active_state():
    workspace = (WEB / "components" / "VideoCreationWorkspace.tsx").read_text(encoding="utf-8")

    assert "IndexTTS 语音情绪" in workspace
    assert "语气、韵律" in workspace
    assert "表达增强" in workspace
    assert "activeIndexTTSPresetLabel" in workspace
    assert "setActiveIndexTTSPresetLabel(preset.label)" in workspace
    assert "preset.label === activeIndexTTSPresetLabel" in workspace
    assert "border-cyan-300 bg-cyan-50 text-cyan-700" in workspace
    assert workspace.count("setActiveIndexTTSPresetLabel(null)") >= 5


def test_video_creation_indextts_uses_quality_streaming_for_preview_and_generation():
    api = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")
    preview = (WEB / "lib" / "ttsPreview.ts").read_text(encoding="utf-8")
    workspace = (WEB / "components" / "VideoCreationWorkspace.tsx").read_text(encoding="utf-8")

    assert "streaming_mode?: \"segment\" | \"token_window\"" in api
    assert "max_text_tokens_per_segment?: number" in api
    assert "quick_streaming_tokens?: number" in api
    assert 'streaming_mode: "segment"' in workspace
    assert "max_text_tokens_per_segment: 80" in workspace
    assert "quick_streaming_tokens: 4" in workspace
    assert "buildIndexTTSQualityConfig" in workspace
    assert "payload.indextts_config = indexttsConfig" in preview


def test_video_creation_workspace_allows_source_video_uploads():
    workspace = (WEB / "components" / "VideoCreationWorkspace.tsx").read_text(encoding="utf-8")

    assert "handleSourceAsset" in workspace
    assert "sourceAssetBusy" in workspace
    assert 'accept="image/*,video/*"' in workspace
    assert 'form.set("video", file)' in workspace
    assert "file.type.startsWith(\"video/\")" in workspace
    assert "avatar.has_preview_video" in workspace
    assert "preview-video" in workspace
    assert "上传图片/视频" in workspace


def test_asset_library_labels_video_creation_exports():
    asset = (WEB / "components" / "AssetLibraryWorkspace.tsx").read_text(encoding="utf-8")

    assert "video_creation" in asset
    assert "视频创作" in asset


def test_frontend_treats_ready_cache_as_prepared_when_runtime_prewarm_fails():
    app = (WEB / "App.tsx").read_text(encoding="utf-8")

    assert "runtime_status" in app
    assert "isPrewarmAssetReady" in app
    assert '"skipped", "unknown"' in app
    assert 'response.runtime_status === "failed"' in app
    assert "资产已准备，运行时预热失败" in app


def test_avatar_grid_does_not_render_global_prewarm_failure_on_every_card():
    stage = (WEB / "components" / "AvatarSelectionStage.tsx").read_text(encoding="utf-8")

    grid_block = stage[stage.index("{avatars.map((avatar) =>"):stage.index("</section>")]
    assert "资产准备失败" not in grid_block
    assert 'prewarmState === "failed"' in stage



def test_tts_docs_include_indextts_omnirt_backend_env():
    env = Path(".env.example").read_text(encoding="utf-8")
    zh = Path("docs/zh/speech_models/tts/indextts.md").read_text(encoding="utf-8")
    en = Path("docs/en/speech_models/tts/indextts.md").read_text(encoding="utf-8")

    for doc in (env, zh, en):
        assert "OPENTALKING_TTS_DEFAULT_PROVIDER=indextts" in doc
        assert "OPENTALKING_TTS_INDEXTTS_BACKEND=omnirt" in doc
        assert "OPENTALKING_TTS_OMNIRT_INDEXTTS_SERVICE_URL" in doc
        assert "OPENTALKING_TTS_OMNIRT_INDEXTTS_STREAMING_MODE=token_window" in doc
        assert "OPENTALKING_TTS_OMNIRT_INDEXTTS_TOKEN_WINDOW_SIZE=40" in doc
    assert "token-window streaming" in en
    assert "分窗流式" in zh


def test_indextts_local_deployment_docs_start_sidecar_from_opentalking_root():
    zh = Path("docs/zh/speech_models/tts/indextts.md").read_text(encoding="utf-8")
    en = Path("docs/en/speech_models/tts/indextts.md").read_text(encoding="utf-8")

    for doc in (zh, en):
        assert "cd \"$OPENTALKING_HOME\"" in doc
        assert "bash scripts/quickstart/start_local_indextts.sh --port 19092 --device cuda:0" in doc
        assert "git clone \"${GITHUB_PROXY_PREFIX:-}https://github.com/index-tts/index-tts.git\" \"$OPENTALKING_MODEL_REPO_ROOT/index-tts\"" in doc
        assert "\"$OPENTALKING_RUNTIME_ROOT/index-tts/venv/bin/python\" -m pip install -e ." in doc
        start_pos = doc.index("scripts/quickstart/start_local_indextts.sh --port 19092 --device cuda:0")
        install_pos = doc.index("-m pip install -e .")
        assert install_pos < start_pos


def test_local_audio_docs_use_public_runtime_status_route():
    zh = Path("docs/zh/model-deployment/recipes/local-quicktalk-audio.md").read_text(encoding="utf-8")
    en = Path("docs/en/model-deployment/recipes/local-quicktalk-audio.md").read_text(encoding="utf-8")

    assert "/api/runtime/status" not in zh + en
    assert "http://127.0.0.1:8000/runtime/status" in zh
    assert "http://127.0.0.1:8000/runtime/status" in en


def test_indextts_local_deployment_docs_include_api_start_and_status_check():
    zh = Path("docs/zh/speech_models/tts/indextts.md").read_text(encoding="utf-8")
    en = Path("docs/en/speech_models/tts/indextts.md").read_text(encoding="utf-8")

    for doc in (zh, en):
        assert "bash scripts/start_unified.sh --backend local --model quicktalk --api-port 8210 --web-port 5283" in doc
        assert "http://127.0.0.1:8210/runtime/status" in doc
        assert "tts_providers.indextts.service_url_set" in doc
        assert "OPENTALKING_TTS_LOCAL_INDEXTTS_SERVICE_URL=http://127.0.0.1:19092/synthesize" in doc
    assert "复用已完整下载的模型目录" in zh
    assert "reuses fully downloaded model directories" in en
