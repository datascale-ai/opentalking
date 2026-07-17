# LLM and STT

The LLM decides what the digital human says. STT is required only when users speak
through the microphone; text-only `speak` requests do not need STT.

## LLM

OpenTalking uses an OpenAI-compatible chat-completions interface. DashScope is the
default because it works with the default Chinese demo settings.

```env title=".env"
OPENTALKING_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENTALKING_LLM_API_KEY=<dashscope-api-key>
OPENTALKING_LLM_MODEL=qwen-flash
```

Common alternatives:

| Provider | Configuration notes |
|----------|---------------------|
| OpenAI | Set `OPENTALKING_LLM_BASE_URL=https://api.openai.com/v1` and use an OpenAI model id. |
| vLLM | Point `OPENTALKING_LLM_BASE_URL` to the vLLM OpenAI-compatible server. |
| Ollama | Use the Ollama OpenAI-compatible endpoint, usually `http://localhost:11434/v1`. |
| DeepSeek | Use the provider's OpenAI-compatible base URL and model id. |

Verify the API key and endpoint by starting OpenTalking and sending a text `speak`
request after creating a `mock` session.

## STT

Select the STT provider with `OPENTALKING_STT_DEFAULT_PROVIDER`. The frontend can also select local STT or API STT before a session starts. When API STT is selected, the provider-specific key must be configured; it is not populated from the LLM key.

### DashScope Paraformer realtime

```env title=".env"
OPENTALKING_STT_DEFAULT_PROVIDER=dashscope
OPENTALKING_STT_DASHSCOPE_API_KEY=<dashscope-api-key>
OPENTALKING_STT_DASHSCOPE_MODEL=paraformer-realtime-v2
```

For DashScope-based deployments, LLM and STT may use the same actual key, but it
must be written explicitly to `OPENTALKING_LLM_API_KEY` and
`OPENTALKING_STT_DASHSCOPE_API_KEY`. If microphone input fails but text `speak` works, verify
the STT module key first.

### Local SenseVoiceSmall

```env title=".env"
OPENTALKING_STT_DEFAULT_PROVIDER=sensevoice
OPENTALKING_STT_ENABLED_PROVIDERS=sensevoice,dashscope
OPENTALKING_STT_SENSEVOICE_MODEL=iic/SenseVoiceSmall
OPENTALKING_STT_SENSEVOICE_MODEL_DIR=./avatar_models/local-audio/iic__SenseVoiceSmall
OPENTALKING_STT_SENSEVOICE_DEVICE=cpu
```

SenseVoiceSmall uses the local FunASR adapter and supports both uploaded audio and WebSocket PCM microphone input. CPU inference is usually enough for short realtime utterances, which makes it a good match for QuickTalk local.

Download the weights:

```bash title="terminal"
uv sync --extra dev --extra models --extra local-audio --python 3.11
python scripts/download_local_audio_models.py \
  --root ./avatar_models/local-audio \
  --model sensevoice-small
```

## Verification

```bash title="terminal"
curl -fsS http://127.0.0.1:8000/health
curl -s -X POST http://127.0.0.1:8000/sessions \
  -H 'content-type: application/json' \
  -d '{"avatar_id":"demo-avatar","model":"mock"}'
```

Then use the frontend microphone flow to confirm STT events and LLM responses appear
in the session event stream.
