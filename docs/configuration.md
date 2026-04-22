# 配置

## 配置来源与优先级

`Settings` 由 `src/opentalking/core/config.py` 定义，优先级从高到低如下:

1. 代码里显式传入的初始化参数
2. `OPENTALKING_*` 环境变量
3. `.env`
4. YAML 配置文件
5. 兼容旧变量名的 legacy env
6. 类默认值

YAML 配置文件路径由以下变量决定:

- `OPENTALKING_CONFIG_FILE`
- 或 `CONFIG_FILE`
- 默认 `./configs/default.yaml`

## 当前仓库里的默认配置

`configs/default.yaml` 当前默认值大致是:

- `flashtalk.mode: off`
- `tts.provider: xtts`
- `model.default_model: wav2lip`
- `model.torch_device: cpu`
- `api.port: 8000`
- `avatars_dir: ./examples/avatars`

这意味着:

- 如果你直接调用后端 API 而且不传 `tts_provider`，会优先按 XTTS 配置处理
- 仓库自带前端不会用这个默认值，它会显式选择 `edge:zh-CN-XiaoxiaoNeural`

## 常用配置模板

- `.env.example`: 通用起点
- `.env.local.example`: 本地 FlashTalk 引擎模式
- `.env.remote.example`: 远端 FlashTalk 服务模式

## 关键配置项

### 服务与基础设施

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OPENTALKING_API_HOST` | `0.0.0.0` | API 监听地址 |
| `OPENTALKING_API_PORT` | `8000` | API 监听端口 |
| `OPENTALKING_UNIFIED_HOST` | `0.0.0.0` | 统一模式监听地址 |
| `OPENTALKING_UNIFIED_PORT` | `8000` | 统一模式监听端口 |
| `OPENTALKING_WORKER_HOST` | `0.0.0.0` | Worker HTTP 服务地址 |
| `OPENTALKING_WORKER_PORT` | `9001` | Worker HTTP 服务端口 |
| `OPENTALKING_REDIS_URL` | `redis://localhost:6379/0` | 分布式模式 Redis |
| `OPENTALKING_WORKER_URL` | `http://127.0.0.1:9001` | API 转发 offer 的目标地址 |
| `OPENTALKING_AVATARS_DIR` | `./examples/avatars` | 头像根目录 |
| `OPENTALKING_MODELS_DIR` | `./models` | 模型根目录 |
| `OPENTALKING_CORS_ORIGINS` | `*` 或 YAML | 允许的前端来源 |

### FlashTalk

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OPENTALKING_FLASHTALK_MODE` | `remote` 默认值，YAML 中通常覆写为 `off` | `remote` / `local` / `off` |
| `OPENTALKING_FLASHTALK_WS_URL` | `ws://localhost:8765` | 远端 FlashTalk WebSocket 地址 |
| `OPENTALKING_FLASHTALK_CKPT_DIR` | `./models/SoulX-FlashTalk-14B` | 本地 FlashTalk 权重目录 |
| `OPENTALKING_FLASHTALK_WAV2VEC_DIR` | `./models/chinese-wav2vec2-base` | wav2vec 目录 |
| `OPENTALKING_FLASHTALK_GPU_COUNT` | `8` | `scripts/start_server.sh` 用于 `torchrun` |
| `OPENTALKING_FLASHTALK_DEVICE` | `auto` | 本地模式设备 |

还有一批 FlashTalk 的高级参数已经接入 `Settings`，例如:

- `OPENTALKING_FLASHTALK_FRAME_NUM`
- `OPENTALKING_FLASHTALK_SAMPLE_STEPS`
- `OPENTALKING_FLASHTALK_IDLE_CACHE_CHUNKS`
- `OPENTALKING_FLASHTALK_PREBUFFER_CHUNKS`
- `OPENTALKING_FLASHTALK_TTS_*`

适合做推理时延和口型体验调优。

### TTS

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OPENTALKING_TTS_PROVIDER` | `xtts` | `auto` / `edge` / `elevenlabs` / `xtts` / `cosyvoice` |
| `OPENTALKING_TTS_VOICE` | `zh-CN-XiaoxiaoNeural` | Edge 默认声线 |
| `OPENTALKING_TTS_LANGUAGE` | `zh-cn` | XTTS / Coqui 语言 |
| `OPENTALKING_TTS_SAMPLE_RATE` | `16000` | TTS 输出采样率 |
| `OPENTALKING_TTS_STREAMING_DECODE` | `true` | 是否边解码边产出 PCM |
| `OPENTALKING_TTS_CLONE_REFERENCE_AUDIO` | `./voice/my_voice_24k.wav` | XTTS / CosyVoice 参考音频 |
| `OPENTALKING_TTS_CLONE_MODEL_NAME` | `./models/XTTS-v2` | XTTS 模型目录 |
| `OPENTALKING_TTS_CLONE_DEVICE` | `auto` | XTTS 设备 |
| `OPENTALKING_TTS_COSYVOICE_MODEL_DIR` | `./models/cosyvoice2` | CosyVoice 权重目录 |
| `OPENTALKING_TTS_COSYVOICE_REPO_DIR` | `./third_party/CosyVoice` | CosyVoice 仓库目录 |

ElevenLabs 相关:

- `OPENTALKING_TTS_ELEVENLABS_API_KEY`
- `OPENTALKING_TTS_ELEVENLABS_BASE_URL`
- `OPENTALKING_TTS_ELEVENLABS_MODEL_ID`
- `OPENTALKING_TTS_ELEVENLABS_VOICE_ID`
- `OPENTALKING_TTS_ELEVENLABS_OUTPUT_FORMAT`

### LLM

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OPENTALKING_LLM_BASE_URL` | 空 | OpenAI 兼容接口地址 |
| `OPENTALKING_LLM_API_KEY` | 空 | API Key |
| `OPENTALKING_LLM_MODEL` | `qwen-turbo` | 模型名 |
| `OPENTALKING_LLM_SYSTEM_PROMPT` | 默认英文提示词 | FlashTalk runner 使用 |

### 渲染调试与开发

这些配置没有都写进 `.env.example`，但已经在代码里生效:

- `OPENTALKING_RENDER_CHUNK_MS`
- `OPENTALKING_RTC_SAMPLE_RATE`
- `OPENTALKING_DEBUG_DUMP_SPEECH_DIR`
- `OPENTALKING_TTS_PREWARM_ON_PREPARE`
- `OPENTALKING_WAV2LIP_LIVE_MODE`
- `OPENTALKING_WAV2LIP_RENDER_CHUNK_MS`
- `OPENTALKING_MUSETALK_*`
- `OPENTALKING_WAV2LIP_*`

## 建议用法

### 本地轻量联调

```bash
cp .env.example .env
export OPENTALKING_TTS_PROVIDER=edge
```

### 本地 FlashTalk

```bash
cp .env.local.example .env
```

### 远端 FlashTalk

```bash
cp .env.remote.example .env
```
