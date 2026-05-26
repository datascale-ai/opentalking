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
