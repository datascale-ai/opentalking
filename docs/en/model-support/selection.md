# Model and Backend Selection

## Choose by Goal

### Fastest Validation

Choose `mock` when you only need to verify WebUI, API, TTS, events, and WebRTC.

### First Real Avatar

Choose `wav2lip` or `quicktalk` with `backend=local`. They are the lightest
paths for validating a real avatar and talking-head output.

Use [Model Deployment / Local Audio + QuickTalk](../model-deployment/recipes/local-quicktalk-audio.md) when you also need to validate local STT, local TTS, and QuickTalk together.

### High-quality Model

Choose MuseTalk, FlashTalk, or FlashHead. MuseTalk can run through `local` for
single-machine CUDA validation, or through `omnirt` / `direct_ws` when you want
model-service isolation. FlashTalk and FlashHead are better kept as external
services.

### Production Service

Prefer service boundaries: OpenTalking API / WebUI for orchestration, workers for
task execution, Redis for state, and OmniRT or direct model services for heavy
inference.

## Choose by Hardware

| Hardware | Recommended path |
| --- | --- |
| CPU | `mock` only, or non-realtime experiments |
| Single NVIDIA GPU | Wav2Lip local, QuickTalk local, MuseTalk local, or one OmniRT model service |
| Multi-GPU | Split heavyweight model services or bind different models to different GPUs |
| Ascend NPU | Use OmniRT for models that have an Ascend runtime |
| Remote inference service | Use `omnirt` or `direct_ws` so OpenTalking does not own model weights |

## Choose by Service Shape

| Shape | Use when | Tradeoff |
| --- | --- | --- |
| In-process `local` | You want a simple single-machine demo or adapter development loop | Dependencies and GPU memory share the API process |
| Standalone WebSocket | You already operate a model-specific service | You own protocol, health, and version management |
| OmniRT | You want a consistent audio2video service boundary | Requires a separate OmniRT deployment |

## Recommended Paths

| Stage | Model | Backend | Goal |
| --- | --- | --- | --- |
| Install validation | Mock | `mock` | Confirm environment and page flow |
| First real path | Wav2Lip / QuickTalk | `local` | Validate avatar and lip sync |
| Local audio validation | SenseVoiceSmall + CosyVoice3 + QuickTalk | `local` | Validate local STT/TTS/Video |
| Single-machine quality validation | MuseTalk | `local` | Evaluate MuseTalk quality with official preprocessing |
| High-quality service demo | FlashTalk / FlashHead | `omnirt` / `direct_ws` | Validate heavyweight output |
| Production | Multi-model stack | `omnirt` + worker | Stable, scalable, observable deployment |
