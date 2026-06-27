# QuickTalk

QuickTalk is the realtime-oriented talking-head model path in OpenTalking. Use it for low-latency digital-human conversations and fast local GPU trials. This page is a mode-selection overview; weights, startup commands, and verification live in the deployment-mode pages below.

## Support Status

| Item | Value |
|------|-------|
| Model ID | `quicktalk` |
| Backend | `local` / `omnirt` |
| Evidence level | Local adapter is built in and verified; OmniRT service path is documented |
| Best for | Realtime speaking avatars, low-latency validation, local or service-hosted inference |

## Benchmark Reference

The numbers below are summarized from [Benchmark](../reference/benchmark.md). `Steady FPS` is model-generation throughput, not full user-perceived latency; STT, LLM, TTS, queueing, and WebRTC still affect the complete experience.

| Hardware | Backend | Output | Steady FPS | First-turn total/ms | TTFV/ms | Peak inference VRAM/GB |
|----------|---------|--------|------------|---------------------|---------|------------------------|
| RTX 3090 | OmniRT | 540×900 / 25fps | 29.23 | 3356.019 | 1800.524 | 1.662 |
| RTX 4090 | OmniRT | 540×900 / 25fps | 46.921 | 2561.146 | 1064.825 | 1.838 |
| NPU 910B2 | OmniRT | 540×900 / 25fps | 29.66 | 3212.053 | 1782.861 | 2.473 |
| RTX 3050 Laptop | OmniRT | 306×512 / 25fps | 20.695 | 4243.26 | 2661 | 1.396 |

## Choose a Deployment Mode

| Mode | Best for | Entry |
|------|----------|-------|
| Local | Single-machine CUDA, in-process adapter, fastest real-chain validation | [QuickTalk Local Deployment](deployment/quicktalk-local.md) |
| Apple Silicon | Weight, manifest, and WebUI flow checks on macOS | [QuickTalk Apple Silicon Deployment](deployment/quicktalk-apple-silicon.md) |
| OmniRT | Isolating inference from OpenTalking, or sharing one model endpoint across runtimes | [QuickTalk OmniRT Deployment](deployment/quicktalk-omnirt.md) |

## Related Pages

- [Support Matrix](../deployment/support-matrix.md): compare QuickTalk with other model-chain backends.
- [Avatar Assets](avatar.md): understand shared avatar assets and session selection.
- [Local Audio + QuickTalk](../recipes/local-quicktalk-audio.md): full local SenseVoice, CosyVoice, and QuickTalk chain.
