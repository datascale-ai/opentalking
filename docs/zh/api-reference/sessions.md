# 会话

会话表示客户端与 OpenTalking 服务之间的一次对话连接，封装所选 avatar、合成模型、
WebRTC track 以及底层流水线的生命周期状态。

会话端点分为四类：

- **生命周期** —— 创建、查询、启动、终止。
- **对话交互** —— `speak`、`chat`、`transcribe`、`interrupt`、人设定制。
- **直接音频输入** —— `speak_audio`、`speak_flashtalk_audio`，以及 [事件与流式接口](events.md) 中说明的 WebSocket 变体。
- **WebRTC 信令与 FlashTalk 录制** —— SDP 交换、在线录制、离线渲染。

## 生命周期

### `POST /sessions`

创建新会话。

**请求体 — `application/json`**

`CreateSessionRequest`：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `avatar_id` | string | 是 | 来自 `GET /avatars` 的 avatar 标识符。 |
| `model` | string | 是 | 合成模型，须在 `GET /models` 中 `connected=true`。 |
| `tts_provider` | string \| null | 否 | 仅此会话覆盖 `OPENTALKING_TTS_PROVIDER`。可选值：`edge`、`dashscope`、`cosyvoice`、`elevenlabs`。 |
| `tts_voice` | string \| null | 否 | 覆盖默认音色，格式取决于 provider。 |
| `llm_system_prompt` | string \| null | 否 | 仅此会话覆盖 `OPENTALKING_LLM_SYSTEM_PROMPT`。 |
| `wav2lip_postprocess_mode` | string \| null | 否 | wav2lip 专属后处理开关，所选 Wav2Lip backend 支持时转发。 |

**响应 — `200 OK`**

`CreateSessionResponse`：

| 字段 | 类型 | 说明 |
|------|------|------|
| `session_id` | string | 新建会话的 UUID4。 |
| `status` | string | 成功时恒为 `"created"`。 |

```bash title="curl"
curl -s -X POST http://localhost:8000/sessions \
  -H 'content-type: application/json' \
  -d '{
        "avatar_id": "demo-avatar",
        "model": "mock"
      }'
```

```json title="响应"
{
  "session_id": "1f4a8c98-3e5e-4b6c-a3f1-9b8e2c4d7e91",
  "status": "created"
}
```

**错误响应**

| 状态码 | 条件 |
|--------|------|
| `400` | `avatar_id` 不存在；`model` 未连接；或 `tts_provider` 未知。 |
| `502` | 初始化过程中上游服务（DashScope、OmniRT 或 direct WebSocket backend）返回错误。 |

### `GET /sessions/{session_id}`

返回会话当前状态。

**路径参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `session_id` | string | `POST /sessions` 返回的 UUID4。 |

**响应 — `200 OK`**

响应体包含会话元数据（avatar、模型、音色）与高层状态（`created`、`running`、
`paused`、`terminated`）。

**错误响应**

| 状态码 | 条件 |
|--------|------|
| `404` | 会话不存在。 |

### `POST /sessions/{session_id}/start`

将会话标记为 active，使后续 `speak` 与 `chat` 请求生效。每个会话仅可调用一次。

**响应 — `200 OK`**

```json
{"status": "running"}
```

**错误响应**

| 状态码 | 条件 |
|--------|------|
| `404` | 会话不存在。 |
| `409` | 会话已处于 running 或 terminated。 |

### `DELETE /sessions/{session_id}`

终止会话。关闭 WebRTC track、释放对应 Worker、清除 Redis 中的会话状态。

**响应 — `200 OK`**

```json
{"status": "terminated"}
```

**错误响应**

| 状态码 | 条件 |
|--------|------|
| `404` | 会话不存在。 |

## 对话交互

### `POST /sessions/{session_id}/chat`

将用户输入送入完整流水线：语音识别结果（或直接的文本）转发给语言模型，模型输出由
TTS 合成为音频，再驱动合成生成视频帧并通过 WebRTC track 推送。事件经会话的 SSE 频道
推送，详见 [事件与流式接口](events.md#session-events)。

**请求体 — `application/json`**

`ChatRequest`：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `prompt` | string | 是 | 用户输入文本。 |
| `voice` | string \| null | 否 | 仅本次请求覆盖会话音色。 |
| `tts_provider` | string \| null | 否 | 仅本次请求覆盖会话 TTS provider。 |
| `tts_model` | string \| null | 否 | provider 专属模型标识符。 |

**响应 — `200 OK`**

HTTP 响应体为空；流水线输出经 SSE 事件流与 WebRTC track 推送。

```bash title="curl"
curl -s -X POST "http://localhost:8000/sessions/$SID/chat" \
  -H 'content-type: application/json' \
  -d '{"prompt": "今天天气如何？"}'
```

**错误响应**

| 状态码 | 条件 |
|--------|------|
| `404` | 会话不存在。 |
| `409` | 上一次 chat 或 speak 请求仍在进行中，须先调用 `/interrupt`。 |

### `POST /sessions/{session_id}/speak`

合成固定文本，跳过语言模型。适用于脚本化欢迎语、演示场景或预先计算文本的播放。

**请求体 — `application/json`**

`SpeakRequest`：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `text` | string | 是 | 待合成文本。 |
| `voice` | string \| null | 否 | 音色覆盖。Edge：`zh-CN-*Neural` 短名；DashScope：控制台中的音色名；ElevenLabs：`voice_id`。 |
| `tts_provider` | string \| null | 否 | `edge`、`dashscope`、`cosyvoice`、`elevenlabs`、`qwen_tts`、`sambert` 之一。 |
| `tts_model` | string \| null | 否 | provider 专属模型。例：`qwen3-tts-flash-realtime`、`cosyvoice-v3-flash`、`eleven_flash_v2_5`。 |

**响应 — `200 OK`** —— 响应体为空。流水线输出经 SSE 与 WebRTC 推送。

```bash title="curl"
curl -s -X POST "http://localhost:8000/sessions/$SID/speak" \
  -H 'content-type: application/json' \
  -d '{"text": "欢迎使用 OpenTalking。"}'
```

### `POST /sessions/{session_id}/transcribe`

提交 PCM 音频缓冲区进行语音识别，返回识别文本。识别文本可根据请求 flag 选择性
转发至语言模型，触发类似 chat 的响应。

**请求体 — `multipart/form-data`**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `audio` | file | 是 | PCM 音频，16 位有符号、单声道，采样率与会话配置一致（默认 16000 Hz）。 |
| `trigger_chat` | boolean | 否 | 为 `true` 时识别结果转发至语言模型。 |

**响应 — `200 OK`**

```json
{"transcript": "识别后的文本。"}
```

### `POST /sessions/{session_id}/interrupt`

取消进行中的 `chat`、`speak`、`speak_audio` 或 `transcribe` 请求。流水线在下一帧
边界停止、排空 in-flight 帧并回到 idle 状态。

**响应 — `200 OK`**

```json
{"interrupted": true}
```

流水线通常在 200 ms 内回到 idle 状态。

### `POST /sessions/{session_id}/customize` 与衍生端点

运行时人设定制端点：

- `POST /sessions/{session_id}/customize` —— 单次调用替换多个人设属性。
- `POST /sessions/{session_id}/customize/prompt` —— 替换会话的 system prompt。
- `POST /sessions/{session_id}/customize/reference` —— 设置音色延续用的参考音频。

schema 定义于 `apps/api/routes/sessions.py`。最新请求体与校验规则以源码为准。

## 直接音频输入

### `POST /sessions/{session_id}/speak_audio`

提交预先生成的音频字节进行合成，跳过 TTS 阶段。适用于音频由外部系统（自定义 TTS、
录制片段、独立音频流水线）产生的场景。

**请求体 — `multipart/form-data`**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `audio` | file | 是 | PCM 或 MP3 音频，格式自动识别。 |
| `sample_rate` | integer | 否 | 音频为原始 PCM 时必填，默认 16000。 |

**响应 — `200 OK`** —— 响应体为空。合成帧经 SSE 与 WebRTC 推送。

### `POST /sessions/{session_id}/speak_flashtalk_audio`

`speak_audio` 的 FlashTalk 优化变体。针对 FlashTalk 的片段大小与 idle 帧模型做额外的
音频切分与平滑处理。合成模型为 `flashtalk` 时建议使用该端点。

请求体格式与 `speak_audio` 一致。

### WebSocket 变体

`WebSocket /sessions/{session_id}/speak_audio_stream` —— 实时流式提交音频用于合成。
详见 [事件与流式接口 → 音频输入 WebSocket](events.md#audio-input-websocket)。

## WebRTC 信令

### `POST /sessions/{session_id}/webrtc/offer`

通过 SDP 交换建立 WebRTC 连接。客户端发送 SDP offer，服务端返回包含音视频 track 的
SDP answer。

**请求体 — `application/json`**

`WebRTCOfferRequest`：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `sdp` | string | 是 | 客户端 RTCPeerConnection 生成的 SDP offer 字符串。 |
| `type` | string | 是 | 恒为 `"offer"`。 |

**响应 — `200 OK`**

```json
{
  "sdp": "v=0\r\no=- ...",
  "type": "answer"
}
```

**错误响应**

| 状态码 | 条件 |
|--------|------|
| `400` | SDP 格式错误。 |
| `404` | 会话不存在。 |
| `409` | 会话已 terminated。 |

## FlashTalk 录制

下述端点捕获进行中的 FlashTalk 会话以供事后审阅。

| 端点 | 用途 |
|------|------|
| `POST /sessions/{session_id}/flashtalk-recording/start` | 开始录制会话的音频与帧。 |
| `POST /sessions/{session_id}/flashtalk-recording/stop` | 结束录制，将产物写入磁盘。 |
| `GET /sessions/{session_id}/flashtalk-recording` | 返回当前录制状态，完成后包含可下载产物标识符。 |

`GET /sessions/{session_id}/flashtalk-recording` 的响应：

```json
{
  "state": "idle | recording | complete",
  "artifact_url": "<state=complete 时的下载 URL>",
  "duration_ms": 12500
}
```

## FlashTalk 离线 bundle

用于将整段会话批量渲染、一次性播放的端点。离线 bundle 在会话结束后渲染，产物为
MP4 文件。

### `POST /sessions/{session_id}/flashtalk-offline-bundle`

提交 bundle 渲染任务。

**响应 — `200 OK`**

```json
{
  "job_id": "<uuid4>",
  "status": "pending"
}
```

### `GET /sessions/{session_id}/flashtalk-offline-bundle/{job_id}`

返回任务状态。

**响应 — `200 OK`**

```json
{
  "job_id": "<uuid4>",
  "status": "pending | running | complete | failed",
  "progress": 0.62,
  "error": null
}
```

### `GET /sessions/{session_id}/flashtalk-offline-bundle/{job_id}/download`

`status=complete` 后下载渲染好的 MP4。响应 Content-Type 为 `video/mp4`。

**错误响应**

| 状态码 | 条件 |
|--------|------|
| `404` | 任务标识符不存在。 |
| `409` | 任务尚未完成。 |

## 源文件

- `apps/api/routes/sessions.py` —— 端点实现。
- `apps/api/schemas/session.py` —— `CreateSessionRequest`、`CreateSessionResponse`、`SpeakRequest`、`ChatRequest`、`WebRTCOfferRequest`。
- `opentalking/worker/` —— 处理 `chat`、`speak`、`transcribe`、`interrupt` 的流水线驱动。
- `opentalking/rtc/` —— `/webrtc/offer` 调用的 WebRTC track 管理。
