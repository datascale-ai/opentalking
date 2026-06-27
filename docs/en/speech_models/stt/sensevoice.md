# SenseVoice Local Deployment

SenseVoiceSmall is the recommended local speech-recognition model for OpenTalking. Use it for private deployments, short realtime utterances, and the local audio + QuickTalk path.

## Use Cases

- Microphone audio should not be sent to an external STT service.
- Short realtime recognition should run on CPU.
- STT, TTS, and QuickTalk local need to run on one machine for validation.

## Weight Preparation

```bash title="Terminal"
cd "$OPENTALKING_HOME"
uv sync --extra dev --extra models --extra local-audio --python 3.11

python scripts/download_local_audio_models.py \
  --root ./avatar_models/local-audio \
  --model sensevoice-small
```

## Configuration

```env title=".env"
OPENTALKING_STT_DEFAULT_PROVIDER=sensevoice
OPENTALKING_STT_ENABLED_PROVIDERS=sensevoice,dashscope
OPENTALKING_STT_SENSEVOICE_MODEL=iic/SenseVoiceSmall
OPENTALKING_STT_SENSEVOICE_MODEL_DIR=./avatar_models/local-audio/iic__SenseVoiceSmall
OPENTALKING_STT_SENSEVOICE_DEVICE=cpu
```

## Start Command

```bash title="Terminal"
cd "$OPENTALKING_HOME"
bash scripts/start_unified.sh --backend mock --model mock --api-port 8000 --web-port 5173
```

## Verification

```bash title="Terminal"
curl -fsS http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/api/runtime/status | jq
```

Then select microphone input in the WebUI and confirm that STT results and LLM responses appear in the event stream.

## Common Errors

| Symptom | Action |
|---------|--------|
| Model directory not found | Check that `OPENTALKING_STT_SENSEVOICE_MODEL_DIR` points to the downloaded directory. |
| Recognition latency is high | Validate short utterances on CPU first; use a dedicated STT service for long audio or high concurrency. |
| API STT key errors | Local SenseVoice does not read the DashScope key; confirm that the frontend selected local STT. |
