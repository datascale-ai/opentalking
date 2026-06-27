# Speech Recognition Models

Speech recognition models convert microphone or uploaded audio into text. Text-only `speak` requests do not require STT; configure this section only when users speak through voice input.

## Provider Options

| Provider / model | Best for | Required configuration |
| --- | --- | --- |
| DashScope Paraformer realtime | Hosted realtime Chinese speech recognition and the default microphone path | `OPENTALKING_STT_DASHSCOPE_API_KEY` |
| [SenseVoiceSmall](stt/sensevoice.md) | Local short-utterance recognition for private deployments and QuickTalk local setups | SenseVoiceSmall weights and FunASR dependencies |

## DashScope Paraformer Realtime

```env title=".env"
OPENTALKING_STT_DEFAULT_PROVIDER=dashscope
OPENTALKING_STT_DASHSCOPE_API_KEY=<dashscope-api-key>
OPENTALKING_STT_DASHSCOPE_MODEL=paraformer-realtime-v2
```

For DashScope deployments, LLM and STT may use the same actual key, but it must be written separately to `OPENTALKING_LLM_API_KEY` and `OPENTALKING_STT_DASHSCOPE_API_KEY`.

## Local SenseVoiceSmall

```env title=".env"
OPENTALKING_STT_DEFAULT_PROVIDER=sensevoice
OPENTALKING_STT_ENABLED_PROVIDERS=sensevoice,dashscope
OPENTALKING_STT_SENSEVOICE_MODEL=iic/SenseVoiceSmall
OPENTALKING_STT_SENSEVOICE_MODEL_DIR=./avatar_models/local-audio/iic__SenseVoiceSmall
OPENTALKING_STT_SENSEVOICE_DEVICE=cpu
```

Download the weights:

```bash title="Terminal"
uv sync --extra dev --extra models --extra local-audio --python 3.11
python scripts/download_local_audio_models.py \
  --root ./avatar_models/local-audio \
  --model sensevoice-small
```

SenseVoiceSmall uses the local FunASR adapter and supports both uploaded audio and WebSocket PCM microphone input. CPU inference is usually enough for short realtime utterances.

## Verification

```bash title="Terminal"
curl -fsS http://127.0.0.1:8000/health
curl -s -X POST http://127.0.0.1:8000/sessions \
  -H 'content-type: application/json' \
  -d '{"avatar_id":"demo-avatar","model":"mock"}'
```

Then use the frontend microphone flow to confirm STT events and LLM responses appear in the session event stream.
