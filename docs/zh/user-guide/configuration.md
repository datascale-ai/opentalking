# 配置

OpenTalking 从两个来源加载配置，按优先级从高到低：

1. **环境变量** —— 通过 `.env` 文件或进程环境提供。
2. **YAML 文件** —— `configs/default.yaml`，及可选叠加层 `configs/profiles/*.yaml` 与
   `configs/synthesis/*.yaml`。

参考模板 `.env.example` 划分为四层，分别对应不同部署场景，按需要配置对应小节即可。

| 层级 | 须配置的小节 | 部署场景 |
|------|------------|---------|
| 1 — 评估 | §1 | 仅 mock 合成，不依赖外部推理服务。 |
| 2 — 轻量模型 | §1 + §2 | 通过 OmniRT 接入 wav2lip、musetalk 或 flashtalk。 |
| 3 — 生产部署 | §1 + §2 + §3 | API/Worker 分离、Redis、硬件 profile 选择。 |
| 4 — 进阶调优 | + §4 | 帧预算、JPEG 质量、idle 帧、声音复刻。 |

## 1. 语言模型、语音识别与语音合成 {#1-llm-stt-tts}

任意部署场景的最小必填项。合成后端（mock、wav2lip、flashtalk 等）由客户端在创建会话时
选择，本节不予以配置。

### 语言模型

支持任意 OpenAI 兼容的对话补全端点。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OPENTALKING_LLM_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 对话补全端点的 Base URL。支持 DashScope、OpenAI、vLLM、Ollama、DeepSeek。 |
| `OPENTALKING_LLM_API_KEY` | _空_ | 鉴权使用的 Bearer Token。 |
| `OPENTALKING_LLM_MODEL` | `qwen-flash` | 传递给端点的模型标识。 |
| `OPENTALKING_LLM_SYSTEM_PROMPT` | _口语化默认值_ | System prompt。默认值指示模型以纯文本口语方式回复，不使用 markdown。 |

### 语音识别

默认语音识别后端为 DashScope Paraformer realtime。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DASHSCOPE_API_KEY` | _空_ | 由 DashScope SDK 直接读取。语言模型亦在 DashScope 运行时，须与 `OPENTALKING_LLM_API_KEY` 保持一致。 |
| `OPENTALKING_STT_MODEL` | `paraformer-realtime-v2` | DashScope 实时语音识别模型。 |

### 语音合成

默认语音合成后端为 Edge TTS，本地通过 ffmpeg 解码，无需 API key。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OPENTALKING_TTS_PROVIDER` | `edge` | 取值范围：`edge`、`dashscope`、`cosyvoice`、`elevenlabs`。 |
| `OPENTALKING_TTS_VOICE` | `zh-CN-XiaoxiaoNeural` | 音色标识，格式取决于 provider。 |

切换 DashScope 实时 TTS 与 ElevenLabs 的配置，参见 [§4 进阶调优](#4)。

## 2. 推理服务

本节变量仅在客户端选择 `wav2lip`、`musetalk`、`flashtalk` 或 `flashhead` 时生效。
`mock` 后端忽略本节全部条目。
各模型权重下载与启动命令见 [模型](../model-deployment/index.md)。

OpenTalking 通过每个模型的 `backend` 字段选择推理入口，不绑定单一平台。推荐默认值如下：

```yaml
models:
  wav2lip:
    backend: omnirt      # 可切换为 local / direct_ws
  musetalk:
    backend: omnirt      # 可切换为 local / direct_ws
  flashtalk:
    backend: omnirt
  flashhead:
    backend: direct_ws
  quicktalk:
    backend: local
  mock:
    backend: mock
```

| backend | 适用场景 |
|---------|----------|
| `mock` | 本地自测，不需要推理服务 |
| `local` | 轻量模型或本地 adapter，例如 QuickTalk |
| `direct_ws` | 单模型 WebSocket 服务，例如 FlashHead 或自托管轻量模型 |
| `omnirt` | 重模型、多卡、NPU/GPU 远端推理 |

### OmniRT（推荐）

单一 OmniRT 端点承载所有 `backend: omnirt` 的模型，按 URL 模板路由：
`ws://<host>:9000/v1/audio2video/{model}`。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OMNIRT_ENDPOINT` | _空_ | OmniRT 实例的 Base URL，例如 `http://127.0.0.1:9000`。仅影响 `backend: omnirt` 的模型。 |
| `OMNIRT_API_KEY` | _空_ | 可选 Bearer Token，转发给 OmniRT。 |
| `OPENTALKING_OMNIRT_AUDIO2VIDEO_PATH_TEMPLATE` | `/v1/audio2video/{model}` | 仅当 OmniRT 部署在非默认路径时需要覆盖。 |

本地启动 OmniRT 实例：

```bash title="终端"
bash scripts/run_omnirt.sh
# 单模型入口：
bash scripts/quickstart/start_omnirt_wav2lip.sh --device cuda
bash scripts/quickstart/start_omnirt_flashtalk.sh --device cuda
```

### 单模型直连（兼容路径）

用于直接接入单模型 WebSocket 服务。FlashTalk 保留 legacy 兼容：当 `OMNIRT_ENDPOINT` 未配置时，可通过 `OPENTALKING_FLASHTALK_WS_URL` 直连。

| 变量 | 说明 |
|------|------|
| `OPENTALKING_FLASHTALK_WS_URL` | SoulX FlashTalk 单进程服务的 `ws://<host>:8765`。 |

### FlashHead（独立路径）

FlashHead 使用专属 WebSocket 协议，不经过 OmniRT。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OPENTALKING_FLASHHEAD_WS_URL` | _空_ | `ws://<host>:8766/v1/avatar/realtime` |
| `OPENTALKING_FLASHHEAD_BASE_URL` | _空_ | `http://<host>:8766`，REST 控制面。 |
| `OPENTALKING_FLASHHEAD_MODEL` | `soulx-flashhead-1.3b` | 模型标识。 |

## 3. 生产部署

本节变量仅适用于 API/Worker 分离部署。单进程模式（`opentalking-unified`）全部忽略。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OPENTALKING_REDIS_URL` | `redis://localhost:6379/0` | API 与 Worker 之间的消息总线。 |
| `OPENTALKING_REDIS_MODE` | `redis` | 设为 `memory` 切换至进程内总线（仅单进程模式）。 |
| `OPENTALKING_API_HOST` | `0.0.0.0` | API 监听地址。 |
| `OPENTALKING_API_PORT` | `8000` | API 监听端口。 |
| `OPENTALKING_WORKER_HOST` | `0.0.0.0` | Worker 监听地址。 |
| `OPENTALKING_WORKER_PORT` | `9001` | Worker 监听端口。 |
| `OPENTALKING_WORKER_URL` | `http://127.0.0.1:9001` | API 访问 Worker 时使用的 URL。 |
| `OPENTALKING_TORCH_DEVICE` | `cpu` | 编排侧音频与帧后处理使用的设备。 |
| `OPENTALKING_AVATARS_DIR` | `./examples/avatars` | Avatar bundle 根目录。 |
| `OPENTALKING_VOICES_DIR` | `./var/voices` | 声音复刻存储目录。 |
| `OPENTALKING_SQLITE_PATH` | `./data/opentalking.sqlite3` | 本地元数据数据库文件。 |
| `OPENTALKING_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | 允许的前端 origin，逗号分隔。 |

## 4. 进阶调优 {#4}

本节变量针对特定后端的细粒度控制。完整列表参见 `.env.example`。下列为代表性条目。

### DashScope Qwen 实时 TTS

```env
OPENTALKING_TTS_PROVIDER=dashscope
OPENTALKING_QWEN_TTS_MODEL=qwen3-tts-flash-realtime
OPENTALKING_QWEN_TTS_REUSE_WS=1
```

### ElevenLabs TTS

```env
OPENTALKING_TTS_PROVIDER=elevenlabs
OPENTALKING_TTS_ELEVENLABS_API_KEY=sk_...
OPENTALKING_TTS_ELEVENLABS_VOICE_ID=...
OPENTALKING_TTS_ELEVENLABS_MODEL_ID=eleven_flash_v2_5
```

### FlashTalk 渲染参数

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OPENTALKING_FLASHTALK_FRAME_NUM` | `25` | 每次推理输出帧数。 |
| `OPENTALKING_FLASHTALK_SAMPLE_STEPS` | `2` | diffusion 采样步数。数值越大，质量越高，推理时间越长。 |
| `OPENTALKING_FLASHTALK_HEIGHT` | `704` | 输出视频高度。 |
| `OPENTALKING_FLASHTALK_WIDTH` | `416` | 输出视频宽度。 |
| `OPENTALKING_FLASHTALK_JPEG_QUALITY` | `55` | WebRTC 流的 JPEG 质量。 |
| `OPENTALKING_FLASHTALK_IDLE_ENABLE` | `1` | 在语音间隙生成 idle 帧。 |
| `OPENTALKING_FLASHTALK_TTS_BOUNDARY_FADE_MS` | `18` | TTS 片段衔接处的音频淡入淡出时长。 |

### QuickTalk（本地实时）

| 变量 | 说明 |
|------|------|
| `OPENTALKING_QUICKTALK_ASSET_ROOT` | QuickTalk 资产包路径。 |
| `OPENTALKING_QUICKTALK_TEMPLATE_VIDEO` | QuickTalk 模板视频文件路径。 |
| `OPENTALKING_QUICKTALK_WORKER_CACHE` | 设为 `1` 时跨会话复用 Worker，降低冷启动延迟。 |
| `OPENTALKING_PREWARM_AVATARS` | 服务启动时预热的 avatar id，逗号分隔。 |

## YAML 配置

YAML 配置层提供结构化默认值。运行时加载 `configs/default.yaml`，再叠加
`OPENTALKING_CONFIG_FILE` 指向的文件。

### `configs/default.yaml` 顶层 key

```yaml title="configs/default.yaml（节选）"
api:
  host: 0.0.0.0
  port: 8000
  cors_origins: [http://localhost:5173, http://127.0.0.1:5173]
infrastructure:
  redis_url: redis://localhost:6379/0
  avatars_dir: ./examples/avatars
  models_dir: ./models
  worker_url: http://127.0.0.1:9001
flashtalk:
  mode: off
  ckpt_dir: ./models/SoulX-FlashTalk-14B
  port: 8765
flashhead:
  ws_url: ""
  model: soulx-flashhead-1.3b
  fps: 25
  sample_rate: 16000
llm:
  model: qwen-flash
tts:
  voice: zh-CN-XiaoxiaoNeural
  sample_rate: 16000
model:
  torch_device: cpu
  default_model: wav2lip
models:
  wav2lip: { stream_batch_size: 8, pads: [0, 10, 0, 0] }
  musetalk: { context_ms: 320.0, silence_gate: 0.04 }
  flashtalk: { frame_num: 33, sample_steps: 2 }
```

### 硬件 profile

`configs/profiles/` 提供四个预设：

- `cpu-demo.yaml` —— 仅编排，mock 合成。
- `cuda-3090.yaml` —— 单 GPU 上的 wav2lip 与 musetalk。
- `cuda-4090.yaml` —— 单 GPU 上的 flashtalk-14B。
- `ascend-910b.yaml` —— NPU 部署。

应用 profile：

```bash title="终端"
export OPENTALKING_CONFIG_FILE=./configs/profiles/cuda-3090.yaml
opentalking-unified
```

### 合成模型专属调参

`configs/synthesis/` 下的文件仅覆盖 `models.<name>` 子树，无需重复完整默认配置。

## 优先级总结

最终生效配置按以下顺序解析，由高到低：

1. Shell 环境变量。
2. `.env` 文件中的变量。
3. `OPENTALKING_CONFIG_FILE` 指向的 YAML 文件。
4. `configs/default.yaml`。

!!! note "变更须重启"
    所有配置值在进程启动时读取一次。配置变更须重启相关进程方可生效。
