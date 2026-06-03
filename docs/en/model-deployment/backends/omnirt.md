# OmniRT Deployment

The `omnirt` backend means OpenTalking connects to an external OmniRT service instead of loading the talking-head model in the main process.

```bash title="Terminal"
cd "$DIGITAL_HUMAN_HOME"
git clone https://github.com/datascale-ai/opentalking.git opentalking
git clone https://github.com/datascale-ai/omnirt.git omnirt

export OPENTALKING_HOME="$DIGITAL_HUMAN_HOME/opentalking"
export OMNIRT_REPO="$DIGITAL_HUMAN_HOME/omnirt"
export OMNIRT_HOME="$OMNIRT_REPO/.omnirt"
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"

cd "$OMNIRT_REPO"
uv sync --extra server --python 3.11
```

Start a model-specific OmniRT quickstart script, then point OpenTalking at it:

```bash title="Terminal"
cd "$OPENTALKING_HOME"
bash scripts/start_unified.sh \
  --backend omnirt \
  --model MODEL \
  --omnirt http://127.0.0.1:9000 \
  --api-port 8000 \
  --web-port 5173
```

```bash title="Terminal"
curl -fsS http://127.0.0.1:9000/v1/audio2video/models | jq
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.backend=="omnirt")'
```

## Model Guides

- [QuickTalk with OmniRT](../quicktalk/omnirt.md)
- [Wav2Lip with OmniRT](../wav2lip/omnirt.md)
- [MuseTalk with OmniRT](../musetalk/omnirt.md)
- [FasterLivePortrait](../fasterliveportrait.md)
- [FlashTalk](../flashtalk.md)
