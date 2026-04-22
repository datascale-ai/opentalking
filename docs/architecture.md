# 架构

## 代码分层

| 组件 | 位置 | 作用 |
|------|------|------|
| Web 控制台 | `apps/web` | 创建会话、发起 WebRTC、订阅 SSE、发送文本 |
| 分布式 API | `apps/api` | REST 入口，会话创建、头像列表、SSE、中转 WebRTC offer |
| 统一模式 | `apps/unified` | FastAPI + 内存 broker + worker 消费循环，适合本地开发 |
| Worker | `src/opentalking/worker` | 消费 `init/speak/interrupt/close` 任务，驱动 TTS、模型与 WebRTC |
| 模型适配层 | `src/opentalking/models` | `wav2lip`、`musetalk` 适配器，以及 FlashTalk 客户端 |
| TTS 层 | `src/opentalking/tts` | `edge`、`elevenlabs`、`xtts`、`cosyvoice` |
| LLM 层 | `src/opentalking/llm` | OpenAI 兼容流式聊天客户端，只在 FlashTalk runner 中使用 |
| WebRTC | `src/opentalking/rtc` | `aiortc` 封装，向浏览器推送音视频 |
| FlashTalk 服务 | `src/opentalking/server` | 远端或本地 14B 推理 WebSocket 服务 |

## 两条主运行路径

### 1. `wav2lip` / `musetalk`

```text
浏览器
  -> FastAPI (/sessions, /webrtc/offer, /events)
  -> SessionRunner
  -> TTSAdapter
  -> ModelAdapter (wav2lip / musetalk)
  -> WebRTCSession
  -> 浏览器播放
```

特点:

- 输入文本直接进入 TTS，不经过 LLM
- Worker 里维护空闲帧循环，避免视频轨断流
- 同一条语音会拆成多个 PCM chunk，再由渲染线程生成视频帧

### 2. `flashtalk`

```text
浏览器
  -> FastAPI
  -> FlashTalkRunner
  -> OpenAICompatibleLLMClient
  -> TTS
  -> FlashTalkWSClient / FlashTalkLocalClient
  -> WebRTCSession
  -> 浏览器播放
```

特点:

- 走完整对话链路: `用户文本 -> LLM -> TTS -> FlashTalk`
- 可切换 `remote` 和 `local` 两种 FlashTalk 模式
- 支持空闲缓存、句首 opener、音频预缓冲等 FlashTalk 专属优化

## 统一模式与分布式模式

### 统一模式

`apps.unified.main` 会同时做三件事:

- 启动 FastAPI
- 创建 `InMemoryRedis`
- 在后台启动 `consume_task_queue(...)`

它和分布式模式复用了同一套任务协议，因此本地联调时最接近真实链路。

### 分布式模式

```text
apps/api -> Redis(opentalking:task_queue) -> worker/task_consumer
                                       -> session runner / flashtalk runner
```

特点:

- API 和 Worker 可独立部署
- 会话状态保存在 Redis 哈希
- WebRTC offer 由 API 转发给 Worker 的 `POST /webrtc/{session_id}/offer`

## 数据流

### 创建会话

1. 客户端调用 `POST /sessions`
2. API 校验头像、模型和 TTS 参数
3. API 写入 `opentalking:session:{id}`，并向 `opentalking:task_queue` 推入 `init`
4. Worker 读取任务，构建对应 runner 并 `prepare()`

### 建立 WebRTC

1. 浏览器创建 SDP offer
2. 调用 `POST /sessions/{id}/webrtc/offer`
3. 统一模式直接交给进程内 runner
4. 分布式模式由 API 转发给 Worker
5. runner 返回 SDP answer，浏览器开始接收音视频轨

### 发起播报

1. 浏览器调用 `POST /sessions/{id}/speak`
2. Worker 开始执行 TTS / LLM / 模型推理
3. 事件经 Redis pubsub 或内存 pubsub 发往 SSE
4. 音视频经 `WebRTCSession` 推送给浏览器

## 会话状态

会话记录的 `state` 目前主要使用这些值:

- `created`
- `ready`
- `speaking`
- `error`
- `closed`

`closed` 和 `error` 会在存储层设置 600 秒 TTL。

## 当前实现里的一个注意点

`apps/web` 默认会请求 `GET /tts/voices`。这个路由当前只挂在统一模式里，分布式 `apps/api.main` 还没有挂上，所以仓库内自带的 React 前端更适合先对接统一模式。
