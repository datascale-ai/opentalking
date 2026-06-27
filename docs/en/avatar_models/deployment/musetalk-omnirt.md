# MuseTalk OmniRT Deployment

OmniRT mode lets an external MuseTalk service own weight loading, the official runtime, and GPU scheduling. OpenTalking connects through `/v1/audio2video/musetalk`.

## Use Cases

- MuseTalk dependencies are heavy and should be isolated from the OpenTalking process.
- Web/API and inference GPU run separately.
- Wav2Lip, QuickTalk, and MuseTalk should share one OmniRT entrypoint.

## Weight Preparation

```bash title="Terminal"
export DIGITAL_HUMAN_HOME="$HOME/digital-human"
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
mkdir -p "$OMNIRT_MODEL_ROOT" "$DIGITAL_HUMAN_HOME/model-repos"

uv pip install -U "huggingface_hub[cli]"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

hf download TMElyralab/MuseTalk \
  --local-dir "$OMNIRT_MODEL_ROOT"

git clone https://github.com/TMElyralab/MuseTalk.git \
  "$DIGITAL_HUMAN_HOME/model-repos/MuseTalk"
```

Confirm `musetalk/`, `sd-vae-ft-mse/`, `whisper/`, `dwpose/`, and `face-parse-bisenet/` exist under `$OMNIRT_MODEL_ROOT`.

## Start Command

Use the quickstart script to prepare and start the MuseTalk runtime:

```bash title="Terminal"
cd "$OMNIRT_HOME"
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
export OMNIRT_MUSETALK_REPO="$DIGITAL_HUMAN_HOME/model-repos/MuseTalk"
export OMNIRT_MUSETALK_DEVICE=cuda
export OMNIRT_MUSETALK_PORT=8766

bash scripts/quickstart/start_omnirt_musetalk.sh
```

Then start OpenTalking:

```bash title="Terminal"
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/start_unified.sh \
  --backend omnirt \
  --model musetalk \
  --omnirt http://127.0.0.1:9000 \
  --api-port 8310 \
  --web-port 5380
```

## Verification

```bash title="Terminal"
curl -fsS http://127.0.0.1:9000/v1/audio2video/models | jq
curl -s http://127.0.0.1:8310/models | jq '.statuses[] | select(.id=="musetalk")'
```

## Common Errors

| Symptom | Action |
|---------|--------|
| OmniRT does not list `musetalk` | Check `OMNIRT_MUSETALK_REPO`, model directories, and startup logs. |
| `reason=omnirt_unavailable` | Check the OpenTalking `--omnirt` URL and OmniRT port. |
| MuseTalk child-service port conflict | Change `OMNIRT_MUSETALK_PORT`. |
| Slow first load | MuseTalk preload and avatar preprocessing are expensive; prewarm in production. |
