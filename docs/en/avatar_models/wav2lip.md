# Wav2Lip

Wav2Lip is the recommended first real lip-sync model path in OpenTalking. It is lighter than heavyweight talking-head models and is useful when moving from `mock` to real video output and testing the end-to-end audio-driven video chain.

## Support Status

| Item | Value |
|------|-------|
| Model ID | `wav2lip` |
| Backend | `local` / `omnirt` |
| Evidence level | Local adapter is built in; OmniRT compatibility path is documented |
| Best for | First real lip-sync model, lightweight demos, low-cost pipeline validation |

## Benchmark Reference

The numbers below are summarized from [Benchmark](../reference/benchmark.md). `Steady FPS` is model-generation throughput, not full user-perceived latency; STT, LLM, TTS, queueing, and WebRTC still affect the complete experience.

| Hardware | Backend | Output | Steady FPS | First-turn total/ms | TTFV/ms | Peak inference VRAM/GB |
|----------|---------|--------|------------|---------------------|---------|------------------------|
| RTX 3090 | OmniRT | 498×832 / 30fps | 37.269 | 3002.526 | 1625.962 | 7.928 |
| RTX 4090 | OmniRT | 498×832 / 30fps | 31.542 | 3689.764 | 1955.629 | 8.133 |
| NPU 910B2 | OmniRT | 498×832 / 30fps | 23.945 | 4019.564 | 2615.322 | 9.113 |

## Choose a Deployment Mode

| Mode | Best for | Entry |
|------|----------|-------|
| Local | Single-machine deployment, minimal moving parts, first real lip-sync validation | [Wav2Lip Local Deployment](deployment/wav2lip-local.md) |
| OmniRT | Isolated inference service, OmniRT preloading, and device configuration | [Wav2Lip OmniRT Deployment](deployment/wav2lip-omnirt.md) |

## When to Choose Another Model

- Need lower-latency realtime speaking: see [QuickTalk](quicktalk.md).
- Need higher quality or official MuseTalk preprocessing: see [MuseTalk](musetalk.md).
- Need a heavyweight high-quality private deployment: see [FlashTalk](flashtalk.md).

## Related Pages

- [Support Matrix](../deployment/support-matrix.md)
- [Avatar Assets](avatar.md)
- [Talking-head Model Deployment](index.md)
