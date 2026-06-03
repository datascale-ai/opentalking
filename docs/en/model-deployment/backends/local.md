# Local Adapter Deployment

The `local` backend means OpenTalking imports the model adapter in-process and runs audio-to-video inference directly. It is the shortest single-machine validation path.

```bash title="Terminal"
cd "$OPENTALKING_HOME"
uv sync --extra dev --extra models --python 3.11
source .venv/bin/activate
bash scripts/start_unified.sh --backend local --model MODEL --api-port 8000 --web-port 5173
```

`MODEL` can be `wav2lip`, `quicktalk`, or `musetalk` when their local dependencies and weights are available.

```bash title="Terminal"
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.backend=="local")'
```

Expected for the selected model:

```json
{"backend":"local","connected":true,"reason":"local_runtime"}
```

## Model Guides

- [QuickTalk Local](../quicktalk/local.md)
- [Wav2Lip Local](../wav2lip/local.md)
- [MuseTalk Local](../musetalk/local.md)
