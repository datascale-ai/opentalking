# API 参考

所有接口默认返回 JSON。SSE 接口返回 `text/event-stream`。

- 统一模式常见地址: `http://127.0.0.1:8010`
- 直接运行 `opentalking-unified` 的默认端口: `8000`
- 分布式 API 默认端口: `8000`
- Worker 信令默认端口: `9001`

## 健康检查

### `GET /health`

返回:

```json
{"status":"ok"}
```

### `GET /healthz`

与 `/health` 等价，便于容器探活。

## 模型与头像

### `GET /models`

返回当前部署下可创建会话的模型列表。

- `wav2lip`、`musetalk` 由 `ModelAdapter` 注册表提供
- `flashtalk` 只会在 `OPENTALKING_FLASHTALK_MODE != off` 时出现

示例:

```json
{"models":["musetalk","wav2lip"]}
```

### `GET /avatars`

列出 `OPENTALKING_AVATARS_DIR` 下所有通过基础校验的头像目录。

示例:

```json
[
  {
    "id": "demo-wav2lip",
    "name": "Demo Wav2Lip HD",
    "manifest_id": "demo-wav2lip",
    "model_type": "wav2lip",
    "width": 768,
    "height": 1024
  }
]
```

### `GET /avatars/{avatar_id}`

返回单个头像概要信息。不存在时返回 `404`。

### `GET /avatars/{avatar_id}/preview`

返回 `preview.png`。不存在时返回 `404`。

## 会话生命周期

### `POST /sessions`

创建会话并向队列写入 `init` 任务。

请求体:

```json
{
  "avatar_id": "demo-wav2lip",
  "model": "wav2lip",
  "tts_provider": "edge",
  "tts_voice": "zh-CN-XiaoxiaoNeural",
  "tts_reference_audio": null
}
```

字段说明:

- `avatar_id`: 头像目录名
- `model`: 必须和 `manifest.json` 里的 `model_type` 一致
- `tts_provider`: 可选，支持 `edge`、`elevenlabs`、`xtts`、`cosyvoice`、`auto`
- `tts_voice`: 可选，主要给 `edge` / `elevenlabs` 使用
- `tts_reference_audio`: 可选，给 `xtts` / `cosyvoice` 使用；必须位于参考音频根目录内

返回:

```json
{
  "session_id": "sess_123456abcdef",
  "status": "created"
}
```

常见校验失败:

- 头像不存在: `404`
- 头像与模型类型不匹配: `400`
- FlashTalk 被禁用但请求了 `flashtalk`: `400`
- `xtts` / `cosyvoice` 缺少参考音频: `400`

### `GET /sessions/{session_id}`

读取 Redis 或内存 broker 中的会话记录。

典型返回:

```json
{
  "session_id": "sess_123456abcdef",
  "avatar_id": "demo-wav2lip",
  "model": "wav2lip",
  "state": "ready"
}
```

### `POST /sessions/{session_id}/start`

将会话标记为 `ready`。前端在 WebRTC 建连成功后会调用它。

### `POST /sessions/{session_id}/speak`

请求体:

```json
{"text":"你好，介绍一下这个项目。"}
```

返回:

```json
{"session_id":"sess_123456abcdef","status":"queued"}
```

说明:

- `wav2lip` / `musetalk` 路径会直接把 `text` 送入 TTS
- `flashtalk` 路径会走 `用户文本 -> LLM(若已配置) -> TTS -> FlashTalk`

### `POST /sessions/{session_id}/interrupt`

打断当前播报。

### `DELETE /sessions/{session_id}`

关闭会话，释放 runner / WebRTC 资源，并把会话状态置为 `closed`。

### `POST /sessions/{session_id}/webrtc/offer`

提交浏览器 offer，返回 answer。

请求体:

```json
{
  "sdp": "v=0\r\n...",
  "type": "offer"
}
```

返回:

```json
{
  "sdp": "v=0\r\n...",
  "type": "answer"
}
```

统一模式下这个请求直接命中当前进程内的 `SessionRunner`。分布式模式下 API 会转发到 `OPENTALKING_WORKER_URL`。

## 事件流

### `GET /sessions/{session_id}/events`

SSE 通道，消息来自 `opentalking:events:{session_id}`。

当前实际使用的事件:

- `speech.started`
- `subtitle.chunk`
- `speech.ended`
- `error`
- `ping`

示例:

```text
event: subtitle.chunk
data: {"session_id":"sess_123","text":"你好，世界","is_final":true}
```

行为差异:

- `wav2lip` / `musetalk` 当前通常只发一次 `subtitle.chunk`，内容就是最终文本
- `flashtalk` 会随着 LLM/TTS 流式处理持续发 `subtitle.chunk`

## TTS 选项

### `GET /tts/voices`

返回前端可直接展示的语音选项列表。

当前只在 `apps.unified.main` 中挂载。也就是说:

- 统一模式: 可用
- 分布式 `apps.api.main`: 当前未挂载

示例:

```json
[
  {
    "id": "edge:zh-CN-XiaoxiaoNeural",
    "label": "Edge 晓晓",
    "provider": "edge",
    "voice": "zh-CN-XiaoxiaoNeural",
    "description": "默认在线女声，不使用参考音频。"
  },
  {
    "id": "xtts:my_voice_24k.wav",
    "label": "my_voice_24k",
    "provider": "xtts",
    "reference_audio": "my_voice_24k.wav",
    "description": "参考音频: my_voice_24k.wav"
  }
]
```
