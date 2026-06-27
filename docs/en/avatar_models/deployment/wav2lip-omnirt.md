# Wav2Lip OmniRT Deployment

OmniRT mode serves Wav2Lip outside OpenTalking. Use it to decouple model dependencies from the web/API process, or to expose multiple talking-head models from one OmniRT endpoint.

## Use Cases

- Web/API and inference GPU run separately.
- Models are managed through `/v1/audio2video/{model}`.
- You want OmniRT preloading, batching, and device controls.

## Weight Preparation

```bash title="Terminal"
export DIGITAL_HUMAN_HOME="$HOME/digital-human"
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
mkdir -p "$OMNIRT_MODEL_ROOT/wav2lip"

uv pip install -U "huggingface_hub[cli]"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

hf download Pypa/wav2lip384 \
  wav2lip384.pth \
  --local-dir "$OMNIRT_MODEL_ROOT/wav2lip"
hf download rippertnt/wav2lip \
  s3fd.pth \
  --local-dir "$OMNIRT_MODEL_ROOT/wav2lip"
```

## Start Command

```bash title="Terminal"
cd "$OMNIRT_HOME"
uv sync --extra server --extra wav2lip-cuda --python 3.11
source .venv/bin/activate

export OMNIRT_WAV2LIP_RUNTIME=1
export OMNIRT_WAV2LIP_MODELS_DIR="$OMNIRT_MODEL_ROOT"
export OMNIRT_WAV2LIP_CHECKPOINT="$OMNIRT_MODEL_ROOT/wav2lip/wav2lip384.pth"
export OMNIRT_WAV2LIP_DEVICE=cuda
export OMNIRT_WAV2LIP_FACE_DET_DEVICE=cpu
export OMNIRT_WAV2LIP_BATCH_SIZE=16
export OMNIRT_WAV2LIP_MAX_LONG_EDGE=832
export OMNIRT_WAV2LIP_PRELOAD=1

omnirt serve-avatar-ws --host 0.0.0.0 --port 9000 --backend cuda
```

Start OpenTalking from another terminal:

```bash title="Terminal"
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/start_unified.sh \
  --backend omnirt \
  --model wav2lip \
  --omnirt http://127.0.0.1:9000 \
  --api-port 8310 \
  --web-port 5380
```

## Verification

```bash title="Terminal"
curl -fsS http://127.0.0.1:9000/v1/audio2video/models | jq
curl -s http://127.0.0.1:8310/models | jq '.statuses[] | select(.id=="wav2lip")'
```

## Common Errors

| Symptom | Action |
|---------|--------|
| OmniRT does not load Wav2Lip | Check `OMNIRT_WAV2LIP_RUNTIME=1` and `OMNIRT_WAV2LIP_CHECKPOINT`. |
| `reason=omnirt_unavailable` | Check the OpenTalking `--omnirt` URL and OmniRT health. |
| End-to-end latency is high | Lower batch size, limit `MAX_LONG_EDGE`, and enable `OMNIRT_WAV2LIP_PRELOAD=1`. |
| Avatar asset unavailable | Confirm the avatar asset is readable and the session configuration is complete. |
