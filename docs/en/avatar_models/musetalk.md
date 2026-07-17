# MuseTalk

MuseTalk is the higher-quality video-avatar lip-sync path in OpenTalking. Compared with Wav2Lip, it has heavier dependencies and preprocessing; compared with QuickTalk, it is more quality-oriented and useful when you already have a MuseTalk runtime. This page explains when to choose MuseTalk and which deployment mode to use.

## Support Status

| Item | Value |
|------|-------|
| Model ID | `musetalk` |
| Backend | `local` / `omnirt` / `direct_ws` |
| Evidence level | Local adapter is wired; local mode runs official MuseTalk preprocessing before session initialization |
| Best for | Higher-quality lip sync, video avatars, existing MuseTalk runtimes |

## Benchmark Reference

The numbers below are summarized from [Benchmark](../reference/benchmark.md). `Steady FPS` is model-generation throughput, not full user-perceived latency; STT, LLM, TTS, queueing, and WebRTC still affect the complete experience.

| Hardware | Backend | Output | Steady FPS | First-turn total/ms | TTFV/ms | Peak inference VRAM/GB |
|----------|---------|--------|------------|---------------------|---------|------------------------|
| RTX 3090 | OmniRT | 512×512 / 25fps | 28.868 | 3235.518 | 1769.484 | 5.078 |
| RTX 4090 | OmniRT | 512×512 / 25fps | 24.767 | 3605.564 | 2095.522 | 5.203 |
| NPU 910B2 | OmniRT | 512×512 / 25fps | 12.276 | 5781.453 | 4211.721 | 8.754 |

## Choose a Deployment Mode

| Mode | Best for | Entry |
|------|----------|-------|
| Local | Single-machine CUDA, with OpenTalking running official avatar preprocessing | [MuseTalk Local Deployment](deployment/musetalk-local.md) |
| OmniRT | Isolating MuseTalk dependencies from the main OpenTalking process | [MuseTalk OmniRT Deployment](deployment/musetalk-omnirt.md) |
| Direct WebSocket | Connecting an existing MuseTalk-compatible service directly | See [Runtime Backends](../model-support/runtime-backends/direct-websocket.md) |

## When to Choose Another Model

- Need the lightest real lip-sync validation: see [Wav2Lip](wav2lip.md).
- Need lower-latency realtime speaking: see [QuickTalk](quicktalk.md).
- Need a high-quality heavyweight service path: see [FlashTalk](flashtalk.md).

## Related Pages

- [Support Matrix](../deployment/support-matrix.md)
- [Avatar Assets](avatar.md)
- [Talking-head Model Deployment](index.md)
