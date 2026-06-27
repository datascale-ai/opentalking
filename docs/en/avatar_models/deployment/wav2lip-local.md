# Wav2Lip Local Deployment

Local mode uses OpenTalking's built-in Wav2Lip adapter. It is the lightest path for validating real lip sync and works well for single-GPU demos and avatar-asset checks.

## Use Cases

- First move from `mock` to a real talking-head model.
- Run inference inside the OpenTalking process without deploying OmniRT.
- Use built-in or custom shared avatars, and let the Wav2Lip flow consume reference
  images or frame assets as needed.

## Weight Preparation

```bash title="Terminal"
cd "$DIGITAL_HUMAN_HOME/opentalking"
mkdir -p models/wav2lip

uv pip install -U "huggingface_hub[cli]"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

hf download Pypa/wav2lip384 \
  wav2lip384.pth \
  --local-dir models/wav2lip
hf download rippertnt/wav2lip \
  s3fd.pth \
  --local-dir models/wav2lip

stat models/wav2lip/wav2lip384.pth
stat models/wav2lip/s3fd.pth
```

## Start Command

```bash title="Terminal"
cd "$DIGITAL_HUMAN_HOME/opentalking"
uv sync --extra dev --extra models --python 3.11

export OPENTALKING_WAV2LIP_MODEL_ROOT="$DIGITAL_HUMAN_HOME/opentalking/models/wav2lip"
export OPENTALKING_WAV2LIP_DEVICE=cuda
export OPENTALKING_WAV2LIP_BATCH_SIZE=16
export OPENTALKING_WAV2LIP_MAX_LONG_EDGE=832
export OPENTALKING_WAV2LIP_FACE_DET_DEVICE=cpu

bash scripts/start_unified.sh --backend local --model wav2lip --api-port 8210 --web-port 5280
```

Open `http://localhost:5280`, choose an available avatar, and select the `wav2lip`
model.

## Verification

```bash title="Terminal"
curl -fsS http://127.0.0.1:8210/health
curl -s http://127.0.0.1:8210/models | jq '.statuses[] | select(.id=="wav2lip")'
```

Expect `backend=local` and `connected=true`. The first load initializes the checkpoint, S3FD, and avatar cache, which can take tens of seconds.

## Common Errors

| Symptom | Action |
|---------|--------|
| Checkpoint not found | Check `OPENTALKING_WAV2LIP_MODEL_ROOT` and both `.pth` files. |
| Out of GPU memory | Lower `OPENTALKING_WAV2LIP_BATCH_SIZE` or `OPENTALKING_WAV2LIP_MAX_LONG_EDGE`. |
| Slow first frame | Set `OPENTALKING_PREWARM_AVATARS=singer` for common avatars. |
| Enhancement mode fails | `easy_enhanced` requires GFPGAN and `OPENTALKING_WAV2LIP_GFPGAN_CHECKPOINT`. |
