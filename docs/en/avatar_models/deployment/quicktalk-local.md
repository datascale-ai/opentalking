# QuickTalk Local Deployment

Local mode loads the QuickTalk adapter inside the OpenTalking process. Use it for single-machine CUDA validation, avatar-cache debugging, and confirming the Web/API pipeline before introducing OmniRT.

## Use Cases

- You have already validated `mock` and now need real talking-head output.
- GPU, WebUI, and API run on the same machine.
- You need to prewarm QuickTalk cache for commonly used shared avatars with
  `opentalking-prepare-cache`.

## Weight Preparation

Place weights under deployment-root `models/quicktalk/`. Set `HF_ENDPOINT` when Hugging Face access is slow.

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

`datascale-ai/quicktalk` now includes QuickTalk, HuBERT, and InsightFace `buffalo_l`.
Use the manual fallback below only when an older mirror or offline bundle is missing
`auxiliary/models/buffalo_l/`:

```bash title="Terminal"
TMP_DIR="$OPENTALKING_QUICKTALK_ASSET_ROOT/_tmp/insightface"
mkdir -p "$TMP_DIR" "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints/auxiliary/models"
curl -L \
  -o "$TMP_DIR/buffalo_l.zip" \
  https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip
unzip -q -o "$TMP_DIR/buffalo_l.zip" \
  -d "$TMP_DIR"
rsync -a "$TMP_DIR/buffalo_l/" \
  "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints/auxiliary/models/buffalo_l/"
```

## Start Command

```bash title="Terminal"
cd "$DIGITAL_HUMAN_HOME/opentalking"
uv sync --extra dev --extra models --extra quicktalk-cuda --python 3.11

export OPENTALKING_TORCH_DEVICE=cuda:0
export OPENTALKING_MODEL_ROOT="${OPENTALKING_MODEL_ROOT:-$DIGITAL_HUMAN_HOME/models}"
export OPENTALKING_QUICKTALK_ASSET_ROOT="${OPENTALKING_QUICKTALK_ASSET_ROOT:-$OPENTALKING_MODEL_ROOT/quicktalk}"
export OPENTALKING_QUICKTALK_WORKER_CACHE=1

bash scripts/start_unified.sh --backend local --model quicktalk --api-port 8210 --web-port 5280
```

Open `http://localhost:5280`, select a shared avatar, and choose the `quicktalk`
model. If a fixed template video is required, confirm the template asset is reachable
from the session or deployment configuration.

## Verification

```bash title="Terminal"
curl -fsS http://127.0.0.1:8210/health
curl -s http://127.0.0.1:8210/models | jq '.statuses[] | select(.id=="quicktalk")'
```

Expect `backend=local` and `connected=true`. To prepare cache ahead of time:

```bash title="Terminal"
opentalking-prepare-cache \
  --model quicktalk \
  --avatars-root examples/avatars \
  --quicktalk-model-root models/quicktalk \
  --device cuda:0 \
  --model-backend pth \
  --verify
```

## Common Errors

| Symptom | Action |
|---------|--------|
| `connected=false` | Check `OPENTALKING_QUICKTALK_ASSET_ROOT`, the CUDA device, and `$DIGITAL_HUMAN_HOME/models/quicktalk/checkpoints`. |
| Long first turn | Enable `OPENTALKING_QUICKTALK_WORKER_CACHE=1` or run `opentalking-prepare-cache` in advance. |
| Avatar load failure | Check that the avatar is readable; if a fixed template video is configured, confirm that path is reachable. |
| Hugging Face download fails | Configure `HF_ENDPOINT`, or download offline and sync into the same directory. |

## Stop Services

Stop the OpenTalking API, WebUI, and local model processes started by
`scripts/start_unified.sh` or the quickstart helpers:

```bash title="Terminal"
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/stop_all.sh
```
