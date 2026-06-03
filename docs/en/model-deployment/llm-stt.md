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
| Atlas Cloud | OpenAI-compatible gateway hosting DeepSeek, Qwen, and other models. Set `OPENTALKING_LLM_BASE_URL=https://api.atlascloud.ai/v1`. See [Atlas Cloud](https://www.atlascloud.ai/?utm_source=github&utm_medium=link&utm_campaign=opentalking). |

Atlas Cloud is OpenAI-compatible, so it works as a drop-in LLM backend:

```env title=".env"
OPENTALKING_LLM_BASE_URL=https://api.atlascloud.ai/v1
OPENTALKING_LLM_API_KEY=<atlascloud-api-key>
OPENTALKING_LLM_MODEL=deepseek-ai/deepseek-v4-pro
```

`deepseek-ai/deepseek-v4-pro` is a reasoning model, so allow enough `max_tokens`
(≥ 512) or the reply may be truncated before any visible text is produced.

<details>
<summary>All Atlas Cloud chat models (59)</summary>

- **Anthropic (Claude):** `anthropic/claude-haiku-4.5-20251001`, `anthropic/claude-opus-4.8`, `anthropic/claude-sonnet-4.6`
- **OpenAI (GPT):** `openai/gpt-5.4`, `openai/gpt-5.5`
- **Google (Gemini):** `google/gemini-3.1-flash-lite`, `google/gemini-3.1-pro-preview`, `google/gemini-3.5-flash`
- **Qwen:** `qwen/qwen2.5-7b-instruct`, `Qwen/Qwen3-235B-A22B-Instruct-2507`, `qwen/qwen3-235b-a22b-thinking-2507`, `qwen/qwen3-30b-a3b`, `Qwen/Qwen3-30B-A3B-Instruct-2507`, `qwen/qwen3-30b-a3b-thinking-2507`, `qwen/qwen3-32b`, `qwen/qwen3-8b`, `Qwen/Qwen3-Coder`, `qwen/qwen3-coder-next`, `qwen/qwen3-max-2026-01-23`, `Qwen/Qwen3-Next-80B-A3B-Instruct`, `Qwen/Qwen3-Next-80B-A3B-Thinking`, `Qwen/Qwen3-VL-235B-A22B-Instruct`, `qwen/qwen3-vl-235b-a22b-thinking`, `qwen/qwen3-vl-30b-a3b-instruct`, `qwen/qwen3-vl-30b-a3b-thinking`, `qwen/qwen3-vl-8b-instruct`, `qwen/qwen3.5-122b-a10b`, `qwen/qwen3.5-27b`, `qwen/qwen3.5-35b-a3b`, `qwen/qwen3.5-397b-a17b`, `qwen/qwen3.6-35b-a3b`, `qwen/qwen3.6-plus`
- **DeepSeek:** `deepseek-ai/deepseek-ocr`, `deepseek-ai/deepseek-r1-0528`, `deepseek-ai/DeepSeek-V3-0324`, `deepseek-ai/DeepSeek-V3.1`, `deepseek-ai/DeepSeek-V3.1-Terminus`, `deepseek-ai/deepseek-v3.2`, `deepseek-ai/DeepSeek-V3.2-Exp`, `deepseek-ai/deepseek-v4-flash`, `deepseek-ai/deepseek-v4-pro`
- **Moonshot (Kimi):** `moonshotai/Kimi-K2-Instruct`, `moonshotai/Kimi-K2-Instruct-0905`, `moonshotai/Kimi-K2-Thinking`, `moonshotai/kimi-k2.5`, `moonshotai/kimi-k2.6`
- **Zhipu (GLM):** `zai-org/GLM-4.6`, `zai-org/glm-4.7`, `zai-org/glm-5`, `zai-org/glm-5-turbo`, `zai-org/glm-5.1`, `zai-org/glm-5v-turbo`
- **MiniMax:** `MiniMaxAI/MiniMax-M2`, `minimaxai/minimax-m2.1`, `minimaxai/minimax-m2.5`, `minimaxai/minimax-m2.7`
- **xAI:** `xai/grok-4.3`
- **Kwaipilot:** `kwaipilot/kat-coder-pro-v2`
- **Other:** `owl`

</details>

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
OPENTALKING_STT_SENSEVOICE_MODEL_DIR=./models/local-audio/iic__SenseVoiceSmall
OPENTALKING_STT_SENSEVOICE_DEVICE=cpu
```

SenseVoiceSmall uses the local FunASR adapter and supports both uploaded audio and WebSocket PCM microphone input. CPU inference is usually enough for short realtime utterances, which makes it a good match for QuickTalk local.

Download the weights:

```bash title="terminal"
uv sync --extra dev --extra models --extra local-audio --python 3.11
python scripts/download_local_audio_models.py \
  --root ./models/local-audio \
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
