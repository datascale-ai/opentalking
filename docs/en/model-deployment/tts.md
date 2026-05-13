# Text-to-Speech

TTS converts LLM output into audio that drives the talking-head backend. Start with
Edge TTS for the lightest local evaluation, then switch providers when you need
production voices, cloning, or provider-specific voice quality.

## Provider options

| Provider | Best for | Required configuration |
|----------|----------|------------------------|
| `edge` | First run, CPU evaluation, no API key | `OPENTALKING_TTS_PROVIDER=edge` |
| `dashscope` | Chinese realtime TTS and voice cloning | `DASHSCOPE_API_KEY` plus DashScope TTS settings |
| `cosyvoice` | Custom voice service or CosyVoice deployment | CosyVoice WebSocket URL/settings |
| `elevenlabs` | Hosted multilingual voices | ElevenLabs API key and voice id |

## Edge TTS default

```env title=".env"
OPENTALKING_TTS_PROVIDER=edge
OPENTALKING_TTS_VOICE=zh-CN-XiaoxiaoNeural
```

Edge TTS still needs `ffmpeg` because OpenTalking decodes provider audio into PCM for
the synthesis backend.

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

## Verification

Create a `mock` session first, then call `/speak` with fixed text. This verifies TTS
without depending on a real talking-head model.

```bash title="terminal"
SID=<session-id>
curl -s -X POST "http://127.0.0.1:8000/sessions/$SID/speak" \
  -H 'content-type: application/json' \
  -d '{"text":"Hello, this is an OpenTalking TTS test."}'
```
