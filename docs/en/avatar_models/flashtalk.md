# FlashTalk

## Support Status

| Item | Value |
|------|-------|
| Model ID | `flashtalk` |
| Backend | `omnirt`, with legacy `direct_ws` fallback |
| Evidence level | OmniRT path documented; Ascend path has validation records |
| Best for | High-quality private deployment, heavy models, multi-card GPU/NPU |

## Recommended Hardware

CUDA evaluation should use a 4090/A100-class GPU. Ascend 910B deployment should run in the
host CANN environment.

## Weights

Primary Hugging Face sources:

- [Soul-AILab/SoulX-FlashTalk-14B](https://huggingface.co/Soul-AILab/SoulX-FlashTalk-14B)
- [TencentGameMate/chinese-wav2vec2-base](https://huggingface.co/TencentGameMate/chinese-wav2vec2-base)

```bash title="Terminal"
hf download Soul-AILab/SoulX-FlashTalk-14B --local-dir "$OMNIRT_MODEL_ROOT/SoulX-FlashTalk-14B"
hf download TencentGameMate/chinese-wav2vec2-base --local-dir "$OMNIRT_MODEL_ROOT/chinese-wav2vec2-base"
```

For domestic mirrors, search ModelScope or Modelers for `SoulX-FlashTalk-14B` and
`chinese-wav2vec2-base`.

## Directory Layout

```text
$OMNIRT_MODEL_ROOT/
├── SoulX-FlashTalk-14B/
├── chinese-wav2vec2-base/
└── SoulX-FlashTalk/        # Optional for custom CUDA/manual paths
```

## Configuration

```yaml title="configs/default.yaml"
models:
  flashtalk:
    backend: omnirt
```

Legacy WebSocket fallback:

```env title=".env"
OPENTALKING_FLASHTALK_WS_URL=ws://127.0.0.1:8765
```

## Start

CUDA:

```bash title="Terminal"
bash scripts/quickstart/start_omnirt_flashtalk.sh --device cuda --nproc 1
bash scripts/quickstart/start_all.sh --omnirt http://127.0.0.1:9000
```

Ascend:

```bash title="Terminal"
source /usr/local/Ascend/ascend-toolkit/set_env.sh
bash scripts/quickstart/start_omnirt_flashtalk.sh --device npu --nproc 8
```

## `/models` Verification

```bash title="Terminal"
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="flashtalk")'
```

Expected:

```json
{"id":"flashtalk","backend":"omnirt","connected":true,"reason":"omnirt"}
```

## Common Errors

| Symptom | Action |
|---------|--------|
| Cold startup is slow | Inspect OmniRT/FlashTalk logs and separate dependency setup, weight load, and worker init. |
| CUDA OOM | Lower `OPENTALKING_FLASHTALK_FRAME_NUM`, `OPENTALKING_FLASHTALK_SAMPLE_STEPS`, or resolution. |
| NPU import failure | Confirm CANN is sourced and `torch_npu`, driver, and CANN versions match. |
| `reason=not_configured` | Configure `OMNIRT_ENDPOINT` or run `start_all.sh --omnirt ...`. |
