# Text-to-Speech

TTS converts LLM output into audio that drives the talking-head backend. Start with
Edge TTS for the lightest local evaluation, then switch providers when you need
production voices, cloning, or provider-specific voice quality.

## Provider options

| Provider | Best for | Required configuration |
|----------|----------|------------------------|
| `edge` | First run, CPU evaluation, no API key | `OPENTALKING_TTS_DEFAULT_PROVIDER=edge` |
| `dashscope` | Chinese realtime TTS and voice cloning | `OPENTALKING_TTS_DASHSCOPE_API_KEY` plus DashScope TTS settings |
| `local_cosyvoice` | Local Chinese TTS, built-in voices, and cloned voices | CosyVoice3 weights and a local service URL |
| `cosyvoice` | Custom voice service or CosyVoice deployment | CosyVoice WebSocket URL/settings |
| `elevenlabs` | Hosted multilingual voices | ElevenLabs API key and voice id |

## Edge TTS default

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=edge
OPENTALKING_TTS_EDGE_VOICE=zh-CN-XiaoxiaoNeural
```

Edge TTS still needs `ffmpeg` because OpenTalking decodes provider audio into PCM for
the synthesis backend.

## DashScope Qwen realtime TTS

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=dashscope
OPENTALKING_TTS_DASHSCOPE_API_KEY=<dashscope-api-key>
OPENTALKING_TTS_DASHSCOPE_MODEL=qwen3-tts-flash-realtime
OPENTALKING_QWEN_TTS_REUSE_WS=1
```

DashScope TTS does not read `OPENTALKING_LLM_API_KEY` or `DASHSCOPE_API_KEY`. If LLM and TTS use the same actual key, write it explicitly to `OPENTALKING_TTS_DASHSCOPE_API_KEY` too.

## Local CosyVoice3 0.5B

The recommended shape is a standalone local CosyVoice service. OpenTalking's `local_cosyvoice` provider calls that service and consumes the returned PCM audio stream.

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=local_cosyvoice
OPENTALKING_TTS_ENABLED_PROVIDERS=local_cosyvoice,dashscope,edge
OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL=FunAudioLLM/Fun-CosyVoice3-0.5B-2512
OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL_DIR=./models/local-audio/FunAudioLLM__Fun-CosyVoice3-0.5B-2512
OPENTALKING_TTS_LOCAL_COSYVOICE_RUNTIME_DIR=./models/local-audio/runtime/CosyVoice
OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL=http://127.0.0.1:19090/synthesize
OPENTALKING_TTS_LOCAL_COSYVOICE_DEVICE=cuda:0
```

Download the local audio weights:

```bash title="terminal"
uv sync --extra dev --extra models --extra local-audio --extra local-cosyvoice-service --python 3.11
python scripts/download_local_audio_models.py \
  --root ./models/local-audio \
  --model fun-cosyvoice3-0.5b-2512
```

Prepare the CosyVoice runtime:

```bash title="terminal"
mkdir -p ./models/local-audio/runtime
git clone https://github.com/FunAudioLLM/CosyVoice.git ./models/local-audio/runtime/CosyVoice
cd ./models/local-audio/runtime/CosyVoice
git submodule update --init --recursive
```

Start the local TTS service:

```bash title="terminal"
OPENTALKING_TTS_LOCAL_COSYVOICE_PRELOAD=1 \
python scripts/local_cosyvoice_service.py --host 127.0.0.1 --port 19090
```

CosyVoice3 first-chunk latency still depends on model inference. OpenTalking splits service audio into `AudioChunk` streams and keeps driving QuickTalk / WebRTC. For the full local speech input, speech synthesis, and QuickTalk video chain, see [Local STT/TTS + QuickTalk](recipes/local-quicktalk-audio.md).

## ElevenLabs

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=elevenlabs
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
