# QuickTalk OmniRT Deployment

OmniRT mode runs QuickTalk inference outside the OpenTalking process. Use it when multiple models share one service endpoint, GPU dependencies need isolation, or inference runs on a separate machine.

## Use Cases

- OpenTalking owns sessions, TTS, and WebRTC while QuickTalk is served externally.
- One OmniRT endpoint needs to expose `quicktalk`, `wav2lip`, and other models.
- Web-service resources and inference GPU resources need separate scaling.

## Weight Preparation

OmniRT reads `$OMNIRT_MODEL_ROOT/quicktalk` by default:

```bash title="Terminal"
export DIGITAL_HUMAN_HOME="$HOME/digital-human"
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
mkdir -p "$OMNIRT_MODEL_ROOT/quicktalk/checkpoints"

uv pip install -U "huggingface_hub[cli]"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

hf download datascale-ai/quicktalk \
  quicktalk.pth \
  repair.npy \
  chinese-hubert-large/config.json \
  chinese-hubert-large/preprocessor_config.json \
  chinese-hubert-large/pytorch_model.bin \
  --local-dir "$OMNIRT_MODEL_ROOT/quicktalk/checkpoints"
```

Confirm `quicktalk.pth`, `repair.npy`, HuBERT, and InsightFace `buffalo_l` all exist under the QuickTalk model directory. Prepare InsightFace as shown in [Local](quicktalk-local.md).

## Start Command

Start OmniRT first:

```bash title="Terminal"
cd "$OMNIRT_HOME"
uv sync --extra server --extra quicktalk-cuda --python 3.11
source .venv/bin/activate

export OMNIRT_QUICKTALK_RUNTIME=1
export OMNIRT_QUICKTALK_MODEL_ROOT="$OMNIRT_MODEL_ROOT/quicktalk"
export OMNIRT_QUICKTALK_CHECKPOINT="$OMNIRT_MODEL_ROOT/quicktalk/checkpoints/quicktalk.pth"
export OMNIRT_QUICKTALK_DEVICE=cuda:0
export OMNIRT_QUICKTALK_HUBERT_DEVICE=cuda:0
export OMNIRT_QUICKTALK_MAX_LONG_EDGE=900
export OMNIRT_QUICKTALK_MAX_TEMPLATE_SECONDS=1

omnirt serve-avatar-ws --host 0.0.0.0 --port 9000 --backend cuda
```

Then start OpenTalking:

```bash title="Terminal"
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/start_unified.sh \
  --backend omnirt \
  --model quicktalk \
  --omnirt http://127.0.0.1:9000 \
  --api-port 8310 \
  --web-port 5380
```

## Verification

```bash title="Terminal"
curl -fsS http://127.0.0.1:9000/v1/audio2video/models | jq
curl -s http://127.0.0.1:8310/models | jq '.statuses[] | select(.id=="quicktalk")'
```

OpenTalking should report `backend=omnirt` and `connected=true`.

## Common Errors

| Symptom | Action |
|---------|--------|
| `reason=omnirt_unavailable` | Check the OmniRT port, `OMNIRT_ENDPOINT`, and `/v1/audio2video/models`. |
| OmniRT does not list `quicktalk` | Check `OMNIRT_QUICKTALK_RUNTIME=1`, checkpoint paths, and startup logs. |
| Slow first frame or high VRAM | Tune `OMNIRT_QUICKTALK_MAX_LONG_EDGE`, HuBERT device, or prewarm strategy. |
| Avatar asset unavailable | Check that the selected avatar is uploaded, readable, and the session configuration is complete. |
