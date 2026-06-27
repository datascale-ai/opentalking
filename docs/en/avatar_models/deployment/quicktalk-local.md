# QuickTalk Local Deployment

Local mode loads the QuickTalk adapter inside the OpenTalking process. Use it for single-machine CUDA validation, avatar-cache debugging, and confirming the Web/API pipeline before introducing OmniRT.

## Use Cases

- You have already validated `mock` and now need real talking-head output.
- GPU, WebUI, and API run on the same machine.
- You need to prewarm QuickTalk cache for commonly used shared avatars with
  `opentalking-prepare-cache`.

## Weight Preparation

Place weights under repository-root `models/quicktalk/`. Set `HF_ENDPOINT` when Hugging Face access is slow.

```bash title="Terminal"
cd "$DIGITAL_HUMAN_HOME/opentalking"
mkdir -p models/quicktalk/checkpoints

uv pip install -U "huggingface_hub[cli]"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

hf download datascale-ai/quicktalk \
  quicktalk.pth \
  repair.npy \
  chinese-hubert-large/config.json \
  chinese-hubert-large/preprocessor_config.json \
  chinese-hubert-large/pytorch_model.bin \
  --local-dir models/quicktalk/checkpoints
```

Prepare InsightFace `buffalo_l` separately:

```bash title="Terminal"
mkdir -p /tmp/opentalking-insightface models/quicktalk/checkpoints/auxiliary/models
curl -L \
  -o /tmp/opentalking-insightface/buffalo_l.zip \
  https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip
unzip -q -o /tmp/opentalking-insightface/buffalo_l.zip \
  -d /tmp/opentalking-insightface
rsync -a /tmp/opentalking-insightface/buffalo_l/ \
  models/quicktalk/checkpoints/auxiliary/models/buffalo_l/
```

## Start Command

```bash title="Terminal"
cd "$DIGITAL_HUMAN_HOME/opentalking"
uv sync --extra dev --extra models --extra quicktalk-cuda --python 3.11

export OPENTALKING_TORCH_DEVICE=cuda:0
export OPENTALKING_QUICKTALK_ASSET_ROOT="$DIGITAL_HUMAN_HOME/opentalking/models/quicktalk"
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
| `connected=false` | Check `OPENTALKING_QUICKTALK_ASSET_ROOT`, the CUDA device, and `models/quicktalk/checkpoints`. |
| Long first turn | Enable `OPENTALKING_QUICKTALK_WORKER_CACHE=1` or run `opentalking-prepare-cache` in advance. |
| Avatar load failure | Check that the avatar is readable; if a fixed template video is configured, confirm that path is reachable. |
| Hugging Face download fails | Configure `HF_ENDPOINT`, or download offline and sync into the same directory. |
