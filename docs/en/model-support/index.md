# Model Support

This section explains which talking-head models OpenTalking supports, which
runtime backends can host them, and how to choose a path for different scenarios.

OpenTalking is the application and orchestration layer. It owns WebUI, sessions,
avatar loading, TTS, audio chunking, frame delivery, and WebRTC playback. Model
weights, GPU scheduling, and inference throughput are handled by the selected
runtime backend.

## Runtime Backends

| Backend | Shape | Typical use |
| --- | --- | --- |
| `mock` | No real inference | First-run validation and CI |
| `local` | In-process adapter/runtime | Single-machine validation for Wav2Lip, QuickTalk, and MuseTalk |
| `direct_ws` | Model-specific WebSocket service | Existing single-model services |
| `omnirt` | OmniRT `/v1/audio2video/{model}` service | Service isolation and multi-model deployment |

## Current Support Status

| Model | Recommended backends | Positioning |
| --- | --- | --- |
| Mock | `mock` | Install and WebUI flow validation |
| Wav2Lip | `local` / `omnirt` | Lightweight lip sync and avatar asset validation |
| QuickTalk | `local` / `omnirt` | Realtime talking-head validation |
| MuseTalk | `local` / `omnirt` / `direct_ws` | Higher-quality lip sync; local mode runs official avatar preprocessing before session initialization |
| FlashTalk | `omnirt` | High-quality realtime digital human, better as a service |
| FlashHead | `direct_ws` / HTTP adapter | Clip-style generation or existing FlashHead service |
| FasterLivePortrait | `omnirt` | Single-GPU portrait pasteback, audio-driven realtime conversation, and video clone |

Actual availability depends on weights, hardware, backend services, and installed
dependencies. Model-specific pages describe the supported parameters and asset
requirements.

## Next Steps

- Not sure which model to choose: start with [Model and Backend Selection](./selection.md).
- Need local STT/TTS with QuickTalk: read [Model Deployment / Local Audio + QuickTalk](../model-deployment/recipes/local-quicktalk-audio.md).
- Need local runtime details: read [Local Adapter](./runtime-backends/local-adapter.md).
- Need MuseTalk local setup: read [MuseTalk](./models/musetalk.md).
- Need camera- or selfie-video-driven cloning: read [FasterLivePortrait](./models/fasterliveportrait.md).
