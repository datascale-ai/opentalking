# 语音生成模型

语音生成模型通常以 TTS provider 的形式接入。它们将 LLM 输出转为音频，再驱动
talking-head backend。本文只做选型和入口导航；权重、启动、验证和排错放在各模型页面。

## Provider 选项

| Provider | 类型 | 适用场景 | 入口 |
|----------|------|----------|------|
| `edge` | 托管 / 在线 | 首次运行、CPU 评估、无需 API key | `.env` provider 配置 |
| `dashscope` | 托管 API | 中文实时 TTS、声音复刻、百炼体系 | `.env` provider 配置 |
| `cosyvoice` | 自托管服务 | 已有 CosyVoice WebSocket / HTTP 服务 | 服务提供方文档 |
| `elevenlabs` | 托管 API | 多语言托管音色 | `.env` provider 配置 |
| `local_cosyvoice` | 本地部署 | 本地中文 TTS、内置音色和复刻音色 | [CosyVoice](tts/cosyvoice.md) |
| `indextts` | 本地部署 / OmniRT | 可控配音、情绪控制和复刻音色 | [IndexTTS](tts/indextts.md) |
| `local_f5_tts` | 本地部署 | 本地 F5-TTS Base 音色克隆 | [F5-TTS](tts/f5-tts.md) |
| `local_qwen3_tts` | 本地部署 | 本地 Qwen3-TTS Base 复刻音色 | [Qwen3-TTS](tts/qwen3-tts.md) |

## 本地模型入口

- [CosyVoice 本地部署](tts/cosyvoice.md)
- [IndexTTS 本地部署](tts/indextts.md)
- [F5-TTS 本地部署](tts/f5-tts.md)
- [Qwen3-TTS 本地部署](tts/qwen3-tts.md)

每个本地模型页面都包含适用场景、权重准备、启动命令、验证命令和常见错误。
