# LLM 与 STT

LLM 决定数字人说什么。STT 只在用户通过麦克风说话时需要；纯文本 `chat` 和 `speak`
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

## STT

默认语音识别后端为 DashScope Paraformer realtime。

```env title=".env"
DASHSCOPE_API_KEY=<dashscope-api-key>
OPENTALKING_STT_MODEL=paraformer-realtime-v2
```

DashScope 部署中，`DASHSCOPE_API_KEY` 与 `OPENTALKING_LLM_API_KEY` 可以使用同一把 key。
如果文本对话正常但麦克风输入失败，优先检查这个 key。

## 验证

```bash title="终端"
curl -fsS http://127.0.0.1:8000/health
curl -s -X POST http://127.0.0.1:8000/sessions \
  -H 'content-type: application/json' \
  -d '{"avatar_id":"demo-avatar","model":"mock"}'
```

随后在前端麦克风流程中确认 session event stream 出现 STT 事件和 LLM 回复。
