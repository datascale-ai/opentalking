# LLM 与 STT

LLM 决定数字人说什么。STT 只在用户通过麦克风说话时需要；纯文本 `speak`
请求不依赖 STT。

## LLM

OpenTalking 使用 OpenAI-compatible chat completions 接口。默认推荐 DashScope，是因为它
与中文 demo 配置最容易跑通。

```env title=".env"
OPENTALKING_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENTALKING_LLM_API_KEY=<dashscope-api-key>
OPENTALKING_LLM_MODEL=qwen-flash
```

常见替代：

| Provider | 配置说明 |
|----------|----------|
| OpenAI | 设置 `OPENTALKING_LLM_BASE_URL=https://api.openai.com/v1` 并使用 OpenAI 模型 id。 |
| vLLM | 指向 vLLM OpenAI-compatible server。 |
| Ollama | 使用 Ollama OpenAI-compatible endpoint，通常为 `http://localhost:11434/v1`。 |
| DeepSeek | 使用 provider 提供的 OpenAI-compatible base URL 和模型 id。 |
| Atlas Cloud | OpenAI-compatible 网关，托管 DeepSeek、Qwen 等模型。设置 `OPENTALKING_LLM_BASE_URL=https://api.atlascloud.ai/v1`。参见 [Atlas Cloud](https://www.atlascloud.ai/?utm_source=github&utm_medium=link&utm_campaign=opentalking)。 |

Atlas Cloud 是 OpenAI-compatible 网关，可作为 LLM 后端直接替换：

```env title=".env"
OPENTALKING_LLM_BASE_URL=https://api.atlascloud.ai/v1
OPENTALKING_LLM_API_KEY=<atlascloud-api-key>
OPENTALKING_LLM_MODEL=deepseek-ai/deepseek-v4-pro
```

`deepseek-ai/deepseek-v4-pro` 是带推理（reasoning）的模型，请给足 `max_tokens`
（≥ 512），否则回复可能在产生可见文本前被截断。

<details>
<summary>Atlas Cloud 全部对话模型（59 个）</summary>

- **Anthropic (Claude)：** `anthropic/claude-haiku-4.5-20251001`, `anthropic/claude-opus-4.8`, `anthropic/claude-sonnet-4.6`
- **OpenAI (GPT)：** `openai/gpt-5.4`, `openai/gpt-5.5`
- **Google (Gemini)：** `google/gemini-3.1-flash-lite`, `google/gemini-3.1-pro-preview`, `google/gemini-3.5-flash`
- **Qwen：** `qwen/qwen2.5-7b-instruct`, `Qwen/Qwen3-235B-A22B-Instruct-2507`, `qwen/qwen3-235b-a22b-thinking-2507`, `qwen/qwen3-30b-a3b`, `Qwen/Qwen3-30B-A3B-Instruct-2507`, `qwen/qwen3-30b-a3b-thinking-2507`, `qwen/qwen3-32b`, `qwen/qwen3-8b`, `Qwen/Qwen3-Coder`, `qwen/qwen3-coder-next`, `qwen/qwen3-max-2026-01-23`, `Qwen/Qwen3-Next-80B-A3B-Instruct`, `Qwen/Qwen3-Next-80B-A3B-Thinking`, `Qwen/Qwen3-VL-235B-A22B-Instruct`, `qwen/qwen3-vl-235b-a22b-thinking`, `qwen/qwen3-vl-30b-a3b-instruct`, `qwen/qwen3-vl-30b-a3b-thinking`, `qwen/qwen3-vl-8b-instruct`, `qwen/qwen3.5-122b-a10b`, `qwen/qwen3.5-27b`, `qwen/qwen3.5-35b-a3b`, `qwen/qwen3.5-397b-a17b`, `qwen/qwen3.6-35b-a3b`, `qwen/qwen3.6-plus`
- **DeepSeek：** `deepseek-ai/deepseek-ocr`, `deepseek-ai/deepseek-r1-0528`, `deepseek-ai/DeepSeek-V3-0324`, `deepseek-ai/DeepSeek-V3.1`, `deepseek-ai/DeepSeek-V3.1-Terminus`, `deepseek-ai/deepseek-v3.2`, `deepseek-ai/DeepSeek-V3.2-Exp`, `deepseek-ai/deepseek-v4-flash`, `deepseek-ai/deepseek-v4-pro`
- **Moonshot (Kimi)：** `moonshotai/Kimi-K2-Instruct`, `moonshotai/Kimi-K2-Instruct-0905`, `moonshotai/Kimi-K2-Thinking`, `moonshotai/kimi-k2.5`, `moonshotai/kimi-k2.6`
- **智谱 (GLM)：** `zai-org/GLM-4.6`, `zai-org/glm-4.7`, `zai-org/glm-5`, `zai-org/glm-5-turbo`, `zai-org/glm-5.1`, `zai-org/glm-5v-turbo`
- **MiniMax：** `MiniMaxAI/MiniMax-M2`, `minimaxai/minimax-m2.1`, `minimaxai/minimax-m2.5`, `minimaxai/minimax-m2.7`
- **xAI：** `xai/grok-4.3`
- **Kwaipilot：** `kwaipilot/kat-coder-pro-v2`
- **其他：** `owl`

</details>

## STT

STT provider 通过 `OPENTALKING_STT_DEFAULT_PROVIDER` 指定。前端也可以在创建会话前选择本地 STT 或 API STT；选择 API STT 时必须配置该 provider 对应的 key，不会从 LLM key 自动 fallback。

### DashScope Paraformer realtime

```env title=".env"
OPENTALKING_STT_DEFAULT_PROVIDER=dashscope
OPENTALKING_STT_DASHSCOPE_API_KEY=<dashscope-api-key>
OPENTALKING_STT_DASHSCOPE_MODEL=paraformer-realtime-v2
```

DashScope 部署中，LLM 与 STT 可以使用同一把实际 key，但必须分别写入
`OPENTALKING_LLM_API_KEY` 与 `OPENTALKING_STT_DASHSCOPE_API_KEY`。如果文本对话正常但麦克风输入失败，优先检查 STT 模块 key。

### 本地 SenseVoiceSmall

```env title=".env"
OPENTALKING_STT_DEFAULT_PROVIDER=sensevoice
OPENTALKING_STT_ENABLED_PROVIDERS=sensevoice,dashscope
OPENTALKING_STT_SENSEVOICE_MODEL=iic/SenseVoiceSmall
OPENTALKING_STT_SENSEVOICE_MODEL_DIR=./models/local-audio/iic__SenseVoiceSmall
OPENTALKING_STT_SENSEVOICE_DEVICE=cpu
```

SenseVoiceSmall 走本地 FunASR adapter，支持上传音频和 WebSocket PCM 语音输入。短句场景下 CPU 通常可以满足实时交互，适合和 QuickTalk local 组合使用。

下载权重：

```bash title="终端"
uv sync --extra dev --extra models --extra local-audio --python 3.11
python scripts/download_local_audio_models.py \
  --root ./models/local-audio \
  --model sensevoice-small
```

## 验证

```bash title="终端"
curl -fsS http://127.0.0.1:8000/health
curl -s -X POST http://127.0.0.1:8000/sessions \
  -H 'content-type: application/json' \
  -d '{"avatar_id":"demo-avatar","model":"mock"}'
```

随后在前端麦克风流程中确认 session event stream 出现 STT 事件和 LLM 回复。
