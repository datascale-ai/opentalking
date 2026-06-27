# FlashTalk

## When to Use FlashTalk

FlashTalk is suited to high-quality realtime digital humans, livestream hosts, customer-support avatars, and other scenarios that need stronger expressiveness. It is heavier than Wav2Lip / QuickTalk and should usually run as an OmniRT service instead of inside the OpenTalking API process.

## OpenTalking and OmniRT Boundary

OpenTalking owns the WebUI, sessions, TTS, WebRTC, recording, and status management. FlashTalk weight loading, GPU scheduling, and actual inference are handled by OmniRT or a dedicated FlashTalk service.

## Requirements

### GPU

Multi-GPU is recommended, or a single GPU with enough VRAM. FlashTalk has stricter requirements for memory, throughput, and service stability.

### NPU

If the FlashTalk backend is already adapted for NPU, expose it through OmniRT. OpenTalking should not manage the NPU runtime directly.

### Memory

If memory is tight, prefer quantization, lower resolution, fewer concurrent sessions, shorter cache windows, or splitting the model service.

### Disk

You need space for weights, quantized weights, temporary audio/video files, and logs. Production deployments should keep weights and runtime caches on fast disks.

## Prepare Weights

FlashTalk weights usually live on the OmniRT service side. OpenTalking keeps the following default paths:

```bash
OPENTALKING_FLASHTALK_CKPT_DIR=./avatar_models/SoulX-FlashTalk-14B
OPENTALKING_FLASHTALK_WAV2VEC_DIR=./avatar_models/chinese-wav2vec2-base
```

For production, let OmniRT manage these paths.

## Start OmniRT

```bash
bash scripts/quickstart/start_omnirt_flashtalk.sh
```

## Configure OpenTalking

```bash
export OPENTALKING_OMNIRT_ENDPOINT=http://127.0.0.1:9000
export OPENTALKING_FLASHTALK_BACKEND=omnirt
```

## Start OpenTalking

```bash
bash scripts/start_unified.sh \
  --backend omnirt \
  --model flashtalk \
  --omnirt http://127.0.0.1:9000
```

## Verify

1. Run `bash scripts/quickstart/status.sh`.
2. Confirm that `flashtalk` appears in the model list.
3. Select a FlashTalk-compatible avatar in the WebUI.
4. Send a short prompt and observe first-frame latency, audio boundaries, and stability.

## Performance Notes

- Do not run the API process and the FlashTalk heavy model in the same process.
- Limit session duration and queue length in production.
- TTS chunking affects first-frame latency and continuity.
- For multi-model deployments, give FlashTalk a dedicated GPU or host.

## Troubleshooting

### Queue is blocked

Check slot timeout, max session, and active sessions. Production deployments should have explicit session release rules.

### First-frame latency is too high

Check for cold starts, long TTS waits, overly large `frame_num`, or heavy sampling settings.

### Out of memory

Consider quantization, lower resolution, fewer concurrent sessions, service splitting, or a larger VRAM device.
