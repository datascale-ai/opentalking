# Voice and TTS

Voice and TTS decide how the digital human speaks. OpenTalking can synthesize speech through different TTS providers, and WebUI lets you select, preview, and apply voices.

## What You Will Build

This page explains:

- How to think about TTS providers and voices.
- How to start with the default voice.
- How to switch and preview voices in WebUI.
- How to clone voices with DashScope / Qwen or CosyVoice.
- How to troubleshoot unavailable voices, preview failures, and clone failures.

## TTS Provider Selection

A TTS provider is the service or model that generates speech audio. Providers differ in configuration, voice identifiers, credentials, and latency.

Common choices:

- `edge`: good for quick validation.
- `dashscope` / `qwen`: for DashScope / Tongyi TTS capabilities.
- `cosyvoice`: for CosyVoice voices and voice cloning.
- `sambert`: for compatibility with existing Sambert setups.

For the first run, use the default provider and voice. Configure cloud providers or cloned voices when a business-specific voice is needed.

## Use Default Voice

After starting Mock or local services, WebUI usually shows available voices. Select the default voice to create a session.

Default voices are useful for checking:

- Session creation.
- TTS audio generation.
- Audio and video synchronization.
- Captions and replies.

## Switch Voice

Select the TTS provider and voice in WebUI settings. Future replies use the new voice; existing audio is not re-synthesized.

Use a short test sentence after switching:

```text
Hello, please say one welcome sentence naturally.
```

If the voice identifier is invalid, the provider may return a missing voice, invalid parameter, or authorization error.

## Preview Voice

WebUI supports voice preview before session creation. Keep preview text short; the current preview endpoint accepts up to 240 characters.

![Voice and TTS panel in WebUI.](../../../assets/images/usage/webui/voice-tts-panel.png)

*Voice and TTS panel in WebUI. Select a provider and voice, then click the preview button.*

If preview fails, check provider credentials, network access, voice identifier, and backend logs.

## Voice Cloning

Voice cloning creates a new voice from sample audio. The current WebUI clone flow focuses on DashScope / Qwen and CosyVoice.

### Prepare Sample Audio

Recommended sample qualities:

- Clear speech with low background noise.
- One speaker only.
- Natural speaking speed.
- File within the upload limit. WebUI voice clone upload currently has a 12MB limit.

WebUI uses a fixed sample text for the clone flow:

```text
你好，今天阳光很好，我正在用自然清晰的声音，记录这一段音色。
```

### DashScope / Qwen

DashScope / Qwen usually requires provider credentials. After configuration, upload sample audio in WebUI and generate a voice id.

Apply the new voice to the current session, then preview or test it with a short message.

### CosyVoice

CosyVoice cloning usually requires the provider to access the sample audio URL. For local deployments, configure `OPENTALKING_PUBLIC_BASE_URL` if the external service cannot reach local temporary URLs.

If cloning fails, check public access, upload status, provider health, and backend logs.

## Use Voice in WebUI

1. Select a TTS provider.
2. Select an existing voice or create one through voice cloning.
3. Preview the voice.
4. Create or recreate the session.
5. Test the digital human response with a short message.

If a session already exists and you switch voices, recreating the session helps avoid confusing state.

## Common Issues

### Preview Has No Audio

Check browser mute state, autoplay restrictions, provider credentials, and whether the backend returned audio.

### Cloned Voice Does Not Appear

Refresh the voice list or reload the page. If it still does not appear, check whether the backend voice store was updated.

### CosyVoice Clone Fails

Confirm the sample audio is reachable by the service. Cloud CosyVoice cannot download audio that only exists at a local temporary URL.

### Voice and Lip Sync Drift

Test with short text first, then check TTS audio duration, model latency, and browser playback state. Long text, cloud TTS latency, and low-performance devices can all affect sync.

## Reference: Configuration Reference

Common related settings include:

- Provider keys for different TTS services.
- `OPENTALKING_PUBLIC_BASE_URL` for externally reachable uploaded audio or static resources.
- Default TTS provider and voice.

The full configuration reference will be organized later.
