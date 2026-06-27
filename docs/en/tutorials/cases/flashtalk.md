# FlashTalk Integration Case

## Goal

Connect `flashtalk` through OmniRT for high-quality talking-head synthesis. OpenTalking
handles session orchestration, TTS, events, and WebRTC; model loading and inference belong
to OmniRT or the external model service.

## Prerequisites

- [Mock E2E](mock-e2e.md) has passed.
- SoulX-FlashTalk-14B and wav2vec2 weights are prepared as described in
  [Talking-head Models → FlashTalk](../../../avatar_models/flashtalk.md).
- CUDA evaluation needs a 4090/A100-class GPU; Ascend evaluation needs the CANN environment.

## Steps

CUDA evaluation:

```bash title="Terminal"
cd opentalking
bash scripts/quickstart/start_omnirt_flashtalk.sh --device cuda --nproc 1
bash scripts/quickstart/start_all.sh --omnirt http://127.0.0.1:9000
```

Ascend 910B evaluation:

```bash title="Terminal"
source /usr/local/Ascend/ascend-toolkit/set_env.sh
bash scripts/deploy_ascend_910b.sh
```

## Verification

```bash title="Terminal"
curl -fsS http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="flashtalk")'
curl -fsS http://127.0.0.1:8000/health
```

Choose a FlashTalk-compatible avatar and the `flashtalk` model in the browser. If the
orchestration path is uncertain, return to `mock` first and isolate the model service after
LLM/TTS/WebRTC are healthy.

## Troubleshooting

| Symptom | Action |
|---------|--------|
| First startup is slow | Cold start includes dependency setup, weight loading, and worker initialization; inspect OmniRT logs by phase. |
| CUDA out of memory | Lower `OPENTALKING_FLASHTALK_FRAME_NUM`, `OPENTALKING_FLASHTALK_SAMPLE_STEPS`, or output resolution. |
| NPU import failure | Confirm CANN is sourced and `torch_npu`, driver, and CANN versions match. |
