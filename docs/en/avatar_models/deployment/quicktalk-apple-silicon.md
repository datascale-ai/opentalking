# QuickTalk Apple Silicon Deployment

Apple Silicon is useful for configuration, avatar, and WebUI flow validation. For realtime production inference, prefer CUDA or OmniRT; treat Mac usage as a development path.

## Use Cases

- Prepare weights, inspect manifests, and validate WebUI flow on an M-series Mac.
- Reuse the same QuickTalk directory layout without CUDA access.
- Prepare assets that will later be synced to a Linux GPU or OmniRT service.

## Weight Preparation

Keep the same layout as Linux local mode:

```bash title="Terminal"
cd "$DIGITAL_HUMAN_HOME/opentalking"
export OPENTALKING_MODEL_ROOT="${OPENTALKING_MODEL_ROOT:-$DIGITAL_HUMAN_HOME/models}"
export OPENTALKING_QUICKTALK_ASSET_ROOT="${OPENTALKING_QUICKTALK_ASSET_ROOT:-$OPENTALKING_MODEL_ROOT/quicktalk}"
mkdir -p "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints"

uv pip install -U "huggingface_hub[cli]"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

hf download datascale-ai/quicktalk \
  --local-dir "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints"
```

`datascale-ai/quicktalk` includes QuickTalk, HuBERT, and InsightFace `buffalo_l`;
after downloading, `checkpoints/auxiliary/models/buffalo_l/` should exist.

If this machine is only used for documentation and asset checks, you can skip CUDA-specific dependencies and only verify weights, shared avatars, and optional template assets.

## Start Command

Validate API/WebUI with `mock` first, then switch to QuickTalk asset checks:

```bash title="Terminal"
cd "$DIGITAL_HUMAN_HOME/opentalking"
uv sync --extra dev --extra models --extra quicktalk-cpu --python 3.11

export OPENTALKING_TORCH_DEVICE=mps
export OPENTALKING_MODEL_ROOT="${OPENTALKING_MODEL_ROOT:-$DIGITAL_HUMAN_HOME/models}"
export OPENTALKING_QUICKTALK_ASSET_ROOT="${OPENTALKING_QUICKTALK_ASSET_ROOT:-$OPENTALKING_MODEL_ROOT/quicktalk}"
export OPENTALKING_QUICKTALK_WORKER_CACHE=0

bash scripts/start_unified.sh --backend local --model quicktalk --api-port 8210 --web-port 5280
```

If a dependency or operator does not support MPS, use `--backend mock` for product-flow checks, or sync the same `$DIGITAL_HUMAN_HOME/models/quicktalk/` directory to a CUDA machine.

## Verification

```bash title="Terminal"
curl -fsS http://127.0.0.1:8210/health
curl -s http://127.0.0.1:8210/models | jq '.statuses[] | select(.id=="quicktalk")'
```

On Apple Silicon, `connected=false` does not always mean the assets are wrong. Read `reason` to distinguish missing dependencies, missing weights, and unsupported devices.

## Common Errors

| Symptom | Action |
|---------|--------|
| MPS operator is unsupported | Use a CUDA machine or OmniRT for real inference; keep Mac for asset validation. |
| ONNX Runtime provider mismatch | Use `quicktalk-cpu` dependencies or switch to Linux CUDA. |
| Template video not found | If a fixed template video is configured, use a reachable absolute path or a repository asset path. |
| Slow downloads | Set `HF_ENDPOINT`, or download on another network and sync the files. |

## Stop Services

Stop the OpenTalking API, WebUI, and local model processes started by
`scripts/start_unified.sh` or the quickstart helpers:

```bash title="Terminal"
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/stop_all.sh
```
