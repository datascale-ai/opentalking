# LLM and STT

The LLM decides what the digital human says. STT is required only when users speak
through the microphone; text-only `chat` and `speak` requests do not need STT.

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

Verify the API key and endpoint by starting OpenTalking and sending a text chat
request after creating a `mock` session.

## STT

The default speech-recognition backend is DashScope Paraformer realtime.

```env title=".env"
DASHSCOPE_API_KEY=<dashscope-api-key>
OPENTALKING_STT_MODEL=paraformer-realtime-v2
```

For DashScope-based deployments, `DASHSCOPE_API_KEY` and
`OPENTALKING_LLM_API_KEY` can use the same key. If microphone input fails but text
chat works, verify this key first.

## Verification

```bash title="terminal"
curl -fsS http://127.0.0.1:8000/health
curl -s -X POST http://127.0.0.1:8000/sessions \
  -H 'content-type: application/json' \
  -d '{"avatar_id":"demo-avatar","model":"mock"}'
```

Then use the frontend microphone flow to confirm STT events and LLM responses appear
in the session event stream.
