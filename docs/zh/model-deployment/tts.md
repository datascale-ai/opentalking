# 语音合成

TTS 将 LLM 输出转为音频，并驱动 talking-head backend。首次评估建议使用 Edge TTS；
需要生产音色、复刻或更高质量时，再切换 provider。

## Provider 选项

| Provider | 适用场景 | 必要配置 |
|----------|----------|----------|
| `edge` | 首次运行、CPU 评估、无需 API key | `OPENTALKING_TTS_PROVIDER=edge` |
| `dashscope` | 中文实时 TTS 与声音复刻 | `DASHSCOPE_API_KEY` 及 DashScope TTS 配置 |
| `cosyvoice` | 自托管 CosyVoice 服务 | CosyVoice WebSocket URL/settings |
| `elevenlabs` | 托管多语言音色 | ElevenLabs API key 和 voice id |

## Edge TTS 默认配置

```env title=".env"
OPENTALKING_TTS_PROVIDER=edge
OPENTALKING_TTS_VOICE=zh-CN-XiaoxiaoNeural
```

Edge TTS 仍需要 `ffmpeg`，因为 OpenTalking 会将 provider 音频解码为 PCM 再送入合成
backend。

## DashScope Qwen realtime TTS

```env title=".env"
OPENTALKING_TTS_PROVIDER=dashscope
DASHSCOPE_API_KEY=<dashscope-api-key>
OPENTALKING_QWEN_TTS_MODEL=qwen3-tts-flash-realtime
OPENTALKING_QWEN_TTS_REUSE_WS=1
```

## ElevenLabs

```env title=".env"
OPENTALKING_TTS_PROVIDER=elevenlabs
OPENTALKING_TTS_ELEVENLABS_API_KEY=<elevenlabs-api-key>
OPENTALKING_TTS_ELEVENLABS_VOICE_ID=<voice-id>
OPENTALKING_TTS_ELEVENLABS_MODEL_ID=eleven_flash_v2_5
```

## 验证

先创建 `mock` 会话，再调用 `/speak`。这样可以验证 TTS，不依赖真实 talking-head 模型。

```bash title="终端"
SID=<session-id>
curl -s -X POST "http://127.0.0.1:8000/sessions/$SID/speak" \
  -H 'content-type: application/json' \
  -d '{"text":"你好，这是一次 OpenTalking 语音合成测试。"}'
```
