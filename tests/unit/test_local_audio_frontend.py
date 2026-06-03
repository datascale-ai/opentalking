from __future__ import annotations

from pathlib import Path


WEB = Path("apps/web/src")


def test_frontend_lists_local_tts_models_and_labels():
    constants = (WEB / "constants" / "ttsBailian.ts").read_text(encoding="utf-8")
    settings = (WEB / "components" / "SettingsPanel.tsx").read_text(encoding="utf-8")
    app = (WEB / "App.tsx").read_text(encoding="utf-8")

    assert "local_cosyvoice" in constants
    assert "Local CosyVoice" in settings
    assert "本地模型" in constants
    assert "local_cosyvoice" in app
    assert "FunAudioLLM/Fun-CosyVoice3-0.5B-2512" in constants
    assert "iic/CosyVoice-300M" not in constants
    assert "local_qwen3_tts" not in settings


def test_single_model_tts_provider_opens_voice_picker_first():
    settings = (WEB / "components" / "SettingsPanel.tsx").read_text(encoding="utf-8")

    assert "providerHasSingleModel" in settings
    assert 'setVoiceView(providerHasSingleModel(provider) ? "voices" : "models")' in settings
    assert 'voiceView === "voices" && ttsProvider !== "edge" && !providerHasSingleModel(ttsProvider)' in settings
    assert "选择音色 ·" in settings
    assert "const qwenModelColumnOptions" in settings
    assert "const providerOptions" in settings
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
    assert "DashScope API" in settings
    assert "onAsrProviderChange" in settings
    assert "stt_provider" in chat_input
    assert "fd.append(\"stt_provider\"" in app


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
    assert "Avatar资产" in asset
    assert "声音资产" in asset
    assert 'apiGet<{ items: ExportVideoItem[] }>("/exports/videos")' in asset
    assert "download_url" in asset
    assert "navigator.clipboard.writeText" in asset
    assert "apiDelete(`/exports/videos/${item.id}`)" in asset


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

    assert '"videoCreation"' in topbar
    assert "视频创作" in topbar
    assert "VideoCreationWorkspace" in app
    assert 'workflow === "videoCreation"' in app
    assert 'onExportCreated={() => setAssetLibraryRefreshKey((value) => value + 1)}' in app
    assert '"video_creation"' in api
    assert "export type VideoCreationJobResponse" in api
    assert "createVideoCreationJob" in api
    assert 'apiPostForm<VideoCreationJobResponse>("/video-creation/jobs", form)' in api
    assert "音频来源" in workspace
    assert "上传音频" in workspace
    assert "文本合成" in workspace
    assert "复刻音色" in workspace
    assert 'audioSource: audioSource === "upload" ? "upload" : "tts_text"' in workspace
    assert 'form.set("audio_source", input.audioSource)' in api
    assert '"upload" | "tts_text"' in api
    assert "BailianVoiceClone" in workspace
    assert "onVoiceCloned" in workspace
    assert "已保存到资产库" in workspace
    assert "去资产库查看" in workspace


def test_video_creation_source_cards_hide_model_type():
    workspace = (WEB / "components" / "VideoCreationWorkspace.tsx").read_text(encoding="utf-8")
    source_block = workspace[
        workspace.index("{avatars.map((avatar) =>"):
        workspace.index("<section", workspace.index("{avatars.map((avatar) =>"))
    ]

    assert "avatar.model_type" not in source_block
    assert "{avatar.width}x{avatar.height}" in source_block
    assert "{avatar.model_type} · {avatar.width}x{avatar.height}" not in workspace


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


def test_asset_library_labels_video_creation_exports():
    asset = (WEB / "components" / "AssetLibraryWorkspace.tsx").read_text(encoding="utf-8")

    assert "video_creation" in asset
    assert "视频创作" in asset
