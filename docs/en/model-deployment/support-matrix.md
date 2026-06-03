# Support Matrix

This page summarizes what is currently built into OpenTalking, what is only
documented as an integration path, and what has repo-grounded validation evidence.
Use it as the decision page before following the deeper setup guides.

## How to read the matrix

| Status | Meaning |
|--------|---------|
| Built-in | The capability is implemented directly in this repository and can be selected in the current product surface. |
| Documented | The integration path is documented, but runtime availability still depends on your external service or weights. |
| Validated | The repository docs or tests include concrete validation evidence for the path. |
| Planned | The architectural boundary exists, but the local runtime is not bundled yet. |

## End-to-End Capability Matrix

| Layer | Option | Integration shape | Default / recommendation | Status | Notes |
|-------|--------|-------------------|--------------------------|--------|-------|
| LLM | DashScope `qwen-flash` | OpenAI-compatible endpoint | Default first-run path | Built-in, Validated | This is the repo's default quickstart path. |
| LLM | OpenAI-compatible endpoints | `OPENTALKING_LLM_BASE_URL` | Use when already standard in your environment | Built-in, Documented | Covers OpenAI, vLLM, Ollama, DeepSeek, and similar servers. |
| STT | DashScope Paraformer realtime | Provider adapter | Default microphone path | Built-in, Validated | Required for the default voice-input flow. |
| STT | SenseVoiceSmall | Local FunASR adapter | Local speech-input path | Built-in, Validated | CPU-capable and suitable for short realtime utterances. |
| TTS | Edge TTS | Local provider adapter | Default first-run path | Built-in, Validated | Lightest path; no API key required. |
| TTS | DashScope Qwen realtime TTS | Provider adapter | Recommended when you want hosted Chinese realtime TTS | Built-in, Documented | Also used for voice-cloning-related workflows. |
| TTS | Local CosyVoice3 0.5B | Local CosyVoice service / adapter | Local voice and cloning path | Built-in, Validated | Uses `local_cosyvoice`; the standalone service is recommended. |
| TTS | CosyVoice service | Provider adapter / remote service | Use for custom voice service deployments | Built-in, Documented | Requires a reachable CosyVoice service and, in some flows, `OPENTALKING_PUBLIC_BASE_URL`. |
| TTS | ElevenLabs | Provider adapter | Use for hosted multilingual voices | Built-in, Documented | Requires API key and voice id. |
| Avatar | Built-in example avatars | Local asset bundles | Default first-run path | Built-in, Validated | Good for `mock`, Wav2Lip, and other documented flows. |
| Avatar | Custom uploaded portraits | `/avatars/custom` | Use when you want quick custom avatars | Built-in, Documented | Best compatibility today is with Wav2Lip-style image avatars. |
| Avatar | Model-specific manifests | Local asset bundles | Required for QuickTalk / FlashHead / FlashTalk matching | Built-in, Documented | `model_type` must match the selected synthesis model. |

## Talking-Head Model Matrix

| Model | Backend choices | Repo default | Validation level | Recommended hardware path | Current guidance |
|-------|-----------------|-------------|------------------|---------------------------|------------------|
| `mock` | `mock` | `mock` | Built-in, Validated | CPU | Fastest full-pipeline self-test; no model weights. |
| `wav2lip` | `local`, `omnirt`, `direct_ws` | `local` | Local adapter is built in and covered by tests; OmniRT compatibility path is documented | CPU-capable; OmniRT compatibility path uses a single GPU or Ascend 910B | Best first lightweight talking-head validation path. |
| `musetalk` | `omnirt`, `direct_ws`, `local` | `omnirt` | Local adapter is built in and runs official preprocessing before session initialization; OmniRT and direct WebSocket paths remain documented | Single GPU or remote model service | Use `local` for single-machine validation when weights and OpenMMLab preprocessing dependencies are installed; use OmniRT for service isolation. |
| `quicktalk` | `local`, `omnirt` | `omnirt` | The local adapter is built in and validated in the real chain; the OmniRT compatibility path remains documented | CUDA GPU | Use `--backend local` for the single-machine path; use OmniRT when service isolation is needed. |
| `fasterliveportrait` | `omnirt` | `omnirt` | Documented | Single CUDA GPU with TensorRT | Realtime JoyVASA audio driving plus FasterLivePortrait pasteback through OmniRT `/v1/audio2video/fasterliveportrait`. |
| `flashtalk` | `omnirt`, legacy `direct_ws` fallback | `omnirt` | OmniRT path documented, Ascend path validated | 4090-class GPU or Ascend 910B multi-card | High-quality path for heavyweight deployment. |
| `flashhead` | `direct_ws` | `direct_ws` | Documented | External FlashHead service | OpenTalking acts as the orchestrator and client, not the model host. |

## Backend Behavior Matrix

| Backend | What OpenTalking expects | Connected when | Typical models |
|---------|--------------------------|----------------|----------------|
| `mock` | No external runtime | Always | `mock` |
| `local` | In-process adapter/runtime | The adapter imports and dependencies are satisfied | `wav2lip`, `quicktalk`, `musetalk` |
| `direct_ws` | Model-specific remote service | A model-specific WebSocket URL is configured | `flashhead`, custom single-model services |
| `omnirt` | OmniRT `/v1/audio2video/{model}` | OmniRT is reachable and reports the model | `wav2lip`, `musetalk`, `quicktalk`, `fasterliveportrait`, `flashtalk` |

## Validation Notes

| Path | Evidence in the repo/docs |
|------|---------------------------|
| `mock` | Quickstart and `/models` examples show the full self-test path. |
| `wav2lip + local` | Built-in adapter registration, `/models` `reason=local_runtime`, and local render tests. |
| `musetalk + local` | Built-in adapter registration, local MuseTalk tests, and official avatar preprocessing before session initialization. |
| `wav2lip + omnirt` | Startup scripts and `/models` status semantics remain documented for the checkpoint-backed compatibility path. |
| `sensevoice + local_cosyvoice + quicktalk local` | Local STT/TTS providers, the QuickTalk local adapter, frontend provider selection, and custom-avatar flow are covered by tests or real-chain validation. |
| `quicktalk + omnirt` | Retained as a compatible service-hosted path; prefer `quicktalk + local` for single-machine deployment. |
| `fasterliveportrait + omnirt` | The FasterLivePortrait guide covers JoyVASA/chinese-hubert-base checkpoints, TensorRT startup, `/v1/audio2video/fasterliveportrait`, frontend controls, and hot updates. |
| `flashtalk + omnirt` | Documented startup scripts, legacy fallback behavior, and README validation notes for Ascend 910B2 x8. |
| `flashhead + direct_ws` | Configured integration path plus the `/models` `reason=direct_ws` example in the talking-head guide. |

## Recommended First Paths

1. Use `mock` to validate the browser, API, LLM, STT, TTS, and WebRTC path.
2. Use local `wav2lip` when you want the lightest talking-head validation path.
3. Use [Local STT/TTS + QuickTalk](recipes/local-quicktalk-audio.md) when you want local speech input, local speech synthesis, and QuickTalk realtime video.
4. Use local `musetalk` when you want MuseTalk quality on one CUDA machine and can install the preprocessing dependencies.
5. Use [QuickTalk Local](quicktalk/local.md) for single-machine realtime audio2video on CUDA, or [QuickTalk with OmniRT](quicktalk/omnirt.md) for service isolation.
6. Use `fasterliveportrait` when you want realtime audio-driven portrait pasteback on a single CUDA GPU.
7. Use `flashtalk` when quality matters more than deployment weight.
8. Use `flashhead` only when you already operate a FlashHead service.

## Next Pages

- [Overview](index.md)
- [LLM and STT](llm-stt.md)
- [Text-to-Speech](tts.md)
- [Avatar Assets](avatar.md)
- [Talking-Head Models](talking-head/index.md)
