# 语音合成

TTS 将 LLM 输出转为音频，并驱动 talking-head backend。首次评估建议使用 Edge TTS；
需要生产音色、复刻或更高质量时，再切换 provider。

## Provider 选项

| Provider | 适用场景 | 必要配置 |
|----------|----------|----------|
| `edge` | 首次运行、CPU 评估、无需 API key | `OPENTALKING_TTS_DEFAULT_PROVIDER=edge` |
| `dashscope` | 中文实时 TTS 与声音复刻 | `OPENTALKING_TTS_DASHSCOPE_API_KEY` 及 DashScope TTS 配置 |
| `local_cosyvoice` | 本地中文 TTS、内置音色和复刻音色 | CosyVoice3 权重和本地 service URL |
| `cosyvoice` | 自托管 CosyVoice 服务 | CosyVoice WebSocket URL/settings |
| `elevenlabs` | 托管多语言音色 | ElevenLabs API key 和 voice id |

## Edge TTS 默认配置

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=edge
OPENTALKING_TTS_EDGE_VOICE=zh-CN-XiaoxiaoNeural
```

Edge TTS 仍需要 `ffmpeg`，因为 OpenTalking 会将 provider 音频解码为 PCM 再送入合成
backend。

## DashScope Qwen realtime TTS

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=dashscope
OPENTALKING_TTS_DASHSCOPE_API_KEY=<dashscope-api-key>
OPENTALKING_TTS_DASHSCOPE_MODEL=qwen3-tts-flash-realtime
OPENTALKING_QWEN_TTS_REUSE_WS=1
```

DashScope TTS 不读取 `OPENTALKING_LLM_API_KEY` 或 `DASHSCOPE_API_KEY`；即使和 LLM 使用同一把实际 key，也要显式写入 `OPENTALKING_TTS_DASHSCOPE_API_KEY`。

## 本地 CosyVoice3 0.5B

推荐把 CosyVoice 作为独立本地服务启动，再由 OpenTalking 的 `local_cosyvoice` provider 通过 HTTP 读取 PCM 音频流。

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=local_cosyvoice
OPENTALKING_TTS_ENABLED_PROVIDERS=local_cosyvoice,dashscope,edge
OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL=FunAudioLLM/Fun-CosyVoice3-0.5B-2512
OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL_DIR=./models/local-audio/FunAudioLLM__Fun-CosyVoice3-0.5B-2512
OPENTALKING_TTS_LOCAL_COSYVOICE_RUNTIME_DIR=./models/local-audio/runtime/CosyVoice
OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL=http://127.0.0.1:19090/synthesize
OPENTALKING_TTS_LOCAL_COSYVOICE_DEVICE=cuda:0
```

下载本地音频权重：

```bash title="终端"
uv sync --extra dev --extra models --extra local-audio --extra local-cosyvoice-service --python 3.11
python scripts/download_local_audio_models.py \
  --root ./models/local-audio \
  --model fun-cosyvoice3-0.5b-2512
```

准备 CosyVoice runtime：

```bash title="终端"
mkdir -p ./models/local-audio/runtime
git clone https://github.com/FunAudioLLM/CosyVoice.git ./models/local-audio/runtime/CosyVoice
cd ./models/local-audio/runtime/CosyVoice
git submodule update --init --recursive
```

启动本地 TTS service：

```bash title="终端"
OPENTALKING_TTS_LOCAL_COSYVOICE_PRELOAD=1 \
python scripts/local_cosyvoice_service.py --host 127.0.0.1 --port 19090
```

CosyVoice3 首包延迟仍取决于模型推理，OpenTalking 会把 service 返回的音频切成 `AudioChunk` 流继续驱动 QuickTalk / WebRTC。完整本地语音输入、语音合成和 QuickTalk 视频链路见 [本地 STT/TTS + QuickTalk](recipes/local-quicktalk-audio.md)。

## ElevenLabs

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=elevenlabs
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
