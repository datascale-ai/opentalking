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
| TTS | Edge TTS | Local provider adapter | Default first-run path | Built-in, Validated | Lightest path; no API key required. |
| TTS | DashScope Qwen realtime TTS | Provider adapter | Recommended when you want hosted Chinese realtime TTS | Built-in, Documented | Also used for voice-cloning-related workflows. |
| TTS | CosyVoice service | Provider adapter / remote service | Use for custom voice service deployments | Built-in, Documented | Requires a reachable CosyVoice service and, in some flows, `OPENTALKING_PUBLIC_BASE_URL`. |
| TTS | ElevenLabs | Provider adapter | Use for hosted multilingual voices | Built-in, Documented | Requires API key and voice id. |
| Avatar | Built-in example avatars | Local asset bundles | Default first-run path | Built-in, Validated | Good for `mock`, Wav2Lip, and other documented flows. |
| Avatar | Custom uploaded portraits | `/avatars/custom` | Use when you want quick custom avatars | Built-in, Documented | Best compatibility today is with Wav2Lip-style image avatars. |
| Avatar | Model-specific manifests | Local asset bundles | Required for QuickTalk / FlashHead / FlashTalk matching | Built-in, Documented | `model_type` must match the selected synthesis model. |

## Talking-Head Model Matrix

| Model | Backend choices | Repo default | Validation level | Recommended hardware path | Current guidance |
|-------|-----------------|-------------|------------------|---------------------------|------------------|
| `mock` | `mock` | `mock` | Built-in, Validated | CPU | Fastest full-pipeline self-test; no model weights. |
| `wav2lip` | `omnirt`, `local`, `direct_ws` | `omnirt` for compatibility | OmniRT path validated; local path planned | Single GPU or Ascend 910B | Best first real model. Directionally local-first, but current runnable default is OmniRT. |
| `musetalk` | `omnirt`, `direct_ws`, `local` | `omnirt` | Documented; local adapter missing | Single GPU or remote model service | Framework is ready, but bundled local runtime is not included yet. |
| `quicktalk` | `local` | `local` | Built-in, Validated | Local CUDA GPU | Reference local realtime adapter. Best example of the decoupled local path. |
| `flashtalk` | `omnirt`, legacy `direct_ws` fallback | `omnirt` | OmniRT path documented, Ascend path validated | 4090-class GPU or Ascend 910B multi-card | High-quality path for heavyweight deployment. |
| `flashhead` | `direct_ws` | `direct_ws` | Documented | External FlashHead service | OpenTalking acts as the orchestrator and client, not the model host. |

## Backend Behavior Matrix

| Backend | What OpenTalking expects | Connected when | Typical models |
|---------|--------------------------|----------------|----------------|
| `mock` | No external runtime | Always | `mock` |
| `local` | In-process adapter/runtime | The adapter imports and dependencies are satisfied | `quicktalk`, future local Wav2Lip / MuseTalk |
| `direct_ws` | Model-specific remote service | A model-specific WebSocket URL is configured | `flashhead`, custom single-model services |
| `omnirt` | OmniRT `/v1/audio2video/{model}` | OmniRT is reachable and reports the model | `wav2lip`, `musetalk`, `flashtalk` |

## Validation Notes

| Path | Evidence in the repo/docs |
|------|---------------------------|
| `mock` | Quickstart and `/models` examples show the full self-test path. |
| `wav2lip + omnirt` | Documented startup scripts, `/models` status semantics, and README benchmark plus connectivity examples for 3090 and Ascend 910B. |
| `quicktalk + local` | `/models` tests explicitly cover `reason=local_runtime` for the local adapter path. |
| `flashtalk + omnirt` | Documented startup scripts, legacy fallback behavior, and README validation notes for Ascend 910B2 x8. |
| `flashhead + direct_ws` | Configured integration path plus the `/models` `reason=direct_ws` example in the talking-head guide. |

## Recommended First Paths

1. Use `mock` to validate the browser, API, LLM, STT, TTS, and WebRTC path.
2. Use `wav2lip` when you want the lightest real talking-head integration.
3. Use `quicktalk` when you specifically want a local in-process realtime adapter.
4. Use `flashtalk` when quality matters more than deployment weight.
5. Use `flashhead` only when you already operate a FlashHead service.

## Next Pages

- [Overview](index.md)
- [LLM and STT](llm-stt.md)
- [Text-to-Speech](tts.md)
- [Avatar Assets](avatar.md)
- [Talking-Head Models](talking-head.md)
