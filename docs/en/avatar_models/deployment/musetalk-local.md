# MuseTalk Local Deployment

Local mode starts the MuseTalk adapter from OpenTalking and runs official preprocessing before session creation. Use it when you want MuseTalk quality without deploying OmniRT yet.

## Use Cases

- Single-machine CUDA deployment with Web/API and MuseTalk runtime together.
- OpenTalking should generate avatar `prepared/` assets automatically.
- Extra first-session time for DWPose, face parsing, and VAE loading is acceptable.

## Weight Preparation

MuseTalk local needs model weights, the official source checkout, and a preprocessing Python:

```bash title="Terminal"
export DIGITAL_HUMAN_HOME="$HOME/digital-human"
export OPENTALKING_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
mkdir -p "$OPENTALKING_MODEL_ROOT" "$DIGITAL_HUMAN_HOME/model-repos"

uv pip install -U "huggingface_hub[cli]"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

hf download TMElyralab/MuseTalk \
  --local-dir "$OPENTALKING_MODEL_ROOT"

git clone https://github.com/TMElyralab/MuseTalk.git \
  "$DIGITAL_HUMAN_HOME/model-repos/MuseTalk"
```

The model root must contain directories such as `musetalk/`, `sd-vae-ft-mse/`, `whisper/`, `dwpose/`, and `face-parse-bisenet/`. Use the repository script to check the preprocessing environment:

```bash title="Terminal"
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/prepare_local_musetalk.sh
```

## Start Command

```bash title="Terminal"
cd "$DIGITAL_HUMAN_HOME/opentalking"
uv sync --extra dev --extra models --python 3.11

export OPENTALKING_MUSETALK_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
export OPENTALKING_MUSETALK_REPO="$DIGITAL_HUMAN_HOME/model-repos/MuseTalk"
export OPENTALKING_MUSETALK_PREPROCESS_PYTHON="$DIGITAL_HUMAN_HOME/runtimes/musetalk-preprocess/venv/bin/python"

bash scripts/start_unified.sh --backend local --model musetalk --api-port 18000 --web-port 18173
```

When creating a session, OpenTalking runs official MuseTalk preprocessing first if the avatar does not already have `prepared/prepared_info.json`.

## Verification

```bash title="Terminal"
curl -fsS http://127.0.0.1:18000/health
curl -s http://127.0.0.1:18000/models | jq '.statuses[] | select(.id=="musetalk")'
```

Expect `backend=local` and `connected=true`.

## Common Errors

| Symptom | Action |
|---------|--------|
| `No module named 'mmcv._ext'` | The preprocessing Python needs full `mmcv`, not only `mmcv-lite`. |
| Preprocessing fails | Check `OPENTALKING_MUSETALK_REPO`, `dwpose`, and `face-parse-bisenet`. |
| First session is slow | Preprocessing and VAE loading are expected; pre-generate `prepared/` for common avatars. |
| Avatar asset unavailable | Check that the avatar is uploaded, readable, and the session configuration is complete. |
