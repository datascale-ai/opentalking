# Speech Generation Models

Speech generation models are usually integrated as TTS providers. They convert LLM
output into audio that drives the talking-head backend. This page is only for model
selection and navigation; weight preparation, startup, verification, and troubleshooting
live in the model pages.

## Provider Options

| Provider | Type | Best for | Entry |
|----------|------|----------|-------|
| `edge` | Hosted / online | First run, CPU evaluation, no API key | `.env` provider config |
| `dashscope` | Hosted API | Chinese realtime TTS, voice cloning, DashScope deployments | `.env` provider config |
| `cosyvoice` | Self-hosted service | Existing CosyVoice WebSocket / HTTP service | Service-specific docs |
| `elevenlabs` | Hosted API | Hosted multilingual voices | `.env` provider config |
| `local_cosyvoice` | Local deployment | Local Chinese TTS, built-in voices, and cloned voices | [CosyVoice](tts/cosyvoice.md) |
| `indextts` | Local deployment / OmniRT | Controllable dubbing, emotion control, and voice cloning | [IndexTTS](tts/indextts.md) |
| `local_f5_tts` | Local deployment | Local F5-TTS Base voice cloning | [F5-TTS](tts/f5-tts.md) |
| `local_qwen3_tts` | Local deployment | Local Qwen3-TTS Base voice cloning | [Qwen3-TTS](tts/qwen3-tts.md) |

## Local Model Entries

- [CosyVoice Local Deployment](tts/cosyvoice.md)
- [IndexTTS Local Deployment](tts/indextts.md)
- [F5-TTS Local Deployment](tts/f5-tts.md)
- [Qwen3-TTS Local Deployment](tts/qwen3-tts.md)

Each local model page contains use cases, weight preparation, startup commands,
verification commands, and common errors.
