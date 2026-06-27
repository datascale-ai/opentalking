# 事件与流式接口

OpenTalking 在会话维度提供两类流式接口：用于流水线带外事件的 Server-Sent Events 通
道，以及用于实时音频输入的 WebSocket 端点。

## 会话事件流 {#session-events}

### `GET /sessions/{session_id}/events`

Server-Sent Events 流，推送会话整个生命周期的事件：识别结果、语言模型 token delta、
TTS 生命周期标记、视频帧时序、错误信息。流在会话存续期间保持开放。

**路径参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `session_id` | string | 会话 UUID4。 |

**响应 — `200 OK`**

Content-Type：`text/event-stream`。每条消息遵循 SSE 线路格式：

```text
event: <type>
data: <json payload>

```

`event` 字段为下文列出的类型之一；`data` 字段为 JSON 对象，schema 取决于 `event`。

**反向代理配置**

SSE 流要求反代关闭响应缓冲。nginx 示例：

```nginx
location ~ ^/sessions/[^/]+/events$ {
    proxy_pass http://opentalking;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_cache off;
    proxy_set_header Connection '';
    chunked_transfer_encoding off;
}
```

### 事件类型

| 事件 | payload schema | 发出时机 |
|------|--------------|---------|
| `transcript` | `{ "text": string, "is_final": boolean }` | 语音识别产出部分或最终结果。 |
| `llm` | `{ "delta": string }` | 语言模型 token delta。完整回复为下一个 `status` 边界之前所有 `llm.delta` 字符串的拼接。 |
| `tts` | `{ "stage": string, "ms_elapsed": integer, "sentence_index": integer? }` | TTS 生命周期标记。`stage` 取值：`start`、`first_audio`、`complete`。 |
| `frame` | `{ "frame_idx": integer, "pts_ms": integer }` | 一帧合成视频已入队。`pts_ms` 为相对于 speak/chat 回合开始的 presentation timestamp。 |
| `status` | `{ "stage": string, "message": string? }` | 流水线高层状态变更。`stage` 取值：`listening`、`thinking`、`speaking`、`idle`、`interrupted`、`error`。 |
| `error` | `{ "code": string, "message": string }` | 可恢复或不可恢复的错误。可恢复错误后会有 `status: idle` 事件；不可恢复错误后会有 `session.terminated`。 |
| `session.terminated` | `{}` | 会话已终止，流即将关闭。 |

### 示例事件流

下述序列对应一次用户输入后的一次完整回复：

```text
event: transcript
data: {"text":"今天天气","is_final":false}

event: transcript
data: {"text":"今天天气如何","is_final":true}

event: status
data: {"stage":"thinking","message":""}

event: llm
data: {"delta":"今天"}

event: llm
data: {"delta":"天气"}

event: tts
data: {"stage":"start","ms_elapsed":340,"sentence_index":0}

event: tts
data: {"stage":"first_audio","ms_elapsed":520,"sentence_index":0}

event: frame
data: {"frame_idx":0,"pts_ms":600}

event: frame
data: {"frame_idx":1,"pts_ms":640}

event: status
data: {"stage":"idle","message":""}
```

### 客户端示例

```javascript title="EventSource"
const events = new EventSource(`/sessions/${sessionId}/events`);

events.addEventListener('transcript', (e) => {
  const { text, is_final } = JSON.parse(e.data);
  console.log(is_final ? 'final' : 'partial', text);
});

events.addEventListener('llm', (e) => {
  const { delta } = JSON.parse(e.data);
  appendToResponse(delta);
});

events.addEventListener('error', (e) => {
  const { code, message } = JSON.parse(e.data);
  console.error('pipeline error', code, message);
});

events.addEventListener('session.terminated', () => {
  events.close();
});
```

```python title="httpx 异步流"
import httpx, json

async with httpx.AsyncClient(timeout=None) as client:
    async with client.stream(
        "GET", f"http://localhost:8000/sessions/{session_id}/events"
    ) as response:
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                event_name = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                payload = json.loads(line.removeprefix("data:").strip())
                handle_event(event_name, payload)
```

## 音频输入 WebSocket {#audio-input-websocket}

### `WebSocket /sessions/{session_id}/speak_audio_stream`

将客户端原始 PCM 音频实时推送至服务端用于合成。客户端开启连接、按帧发送音频、并
显式标记结束。服务端将合成产物经 SSE 事件流与 WebRTC track 推送。

**路径参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `session_id` | string | 已 start 的会话 UUID4。 |

**子协议** —— 无，端点使用原始 WebSocket 帧。

### 消息格式

消息分为二进制帧（音频数据）与文本帧（控制命令）。

**二进制帧**

原始 16 位有符号 PCM，小端字节序，单声道，采样率与会话配置一致（默认 16000 Hz）。
单帧可包含任意数量的完整 PCM 样本；建议低时延场景下使用 20 ms 帧（16 kHz 下 640
字节）。

**文本帧（控制）**

JSON 编码的控制消息。

| 消息 | schema | 用途 |
|------|--------|------|
| `{ "type": "config", "sample_rate": integer? }` | 可选的首条消息，覆盖本次流的采样率。 |
| `{ "type": "eos" }` | 标识音频流结束。服务端将剩余音频排空合成。 |
| `{ "type": "interrupt" }` | 等价于 `POST /sessions/{id}/interrupt`，取消当前合成。 |

### 服务端到客户端消息

服务端可能发送状态相关的文本帧：

| 消息 | schema | 用途 |
|------|--------|------|
| `{ "type": "ack" }` | 在 config 消息被接受后发送。 |
| `{ "type": "error", "code": string, "message": string }` | 不可恢复错误关闭前发送。 |

合成音视频通过 WebRTC track 推送，**不**通过本 WebSocket。状态变更与帧时序仍位于
SSE 事件流。

### 关闭行为

服务端将在以下情况关闭连接：

- 客户端发送 `eos` 消息且流水线已排空。
- 发生不可恢复错误（关闭前先发 `error` 消息）。
- 会话被终止。

客户端应将任何关闭视为终结状态，不应使用相同 `session_id` 重连。

### 客户端示例

```javascript title="浏览器 WebSocket"
const ws = new WebSocket(`ws://localhost:8000/sessions/${sessionId}/speak_audio_stream`);
ws.binaryType = 'arraybuffer';

ws.onopen = () => {
  ws.send(JSON.stringify({ type: 'config', sample_rate: 16000 }));
  startMicrophoneCapture((pcmFrame /* Int16Array */) => {
    ws.send(pcmFrame.buffer);
  });
};

ws.onmessage = (e) => {
  if (typeof e.data === 'string') {
    const msg = JSON.parse(e.data);
    if (msg.type === 'error') console.error(msg);
  }
};

function stopRecording() {
  ws.send(JSON.stringify({ type: 'eos' }));
}
```

```python title="websockets 客户端"
import asyncio, json, websockets

async def stream_audio(session_id: str, pcm_chunks):
    uri = f"ws://localhost:8000/sessions/{session_id}/speak_audio_stream"
    async with websockets.connect(uri, max_size=2**22) as ws:
        await ws.send(json.dumps({"type": "config", "sample_rate": 16000}))
        for chunk in pcm_chunks:           # 16 位 PCM 字节迭代器
            await ws.send(chunk)
        await ws.send(json.dumps({"type": "eos"}))
        async for message in ws:           # 排空服务端状态消息
            if isinstance(message, str):
                print(json.loads(message))
```

## 事件顺序与背压

- 在单次 speak 或 chat 回合内，事件按因果顺序产出：`transcript` → `status:thinking` → `llm.delta`* → `tts:start` → `tts:first_audio` → `frame`* → `status:idle`。
- `frame` 事件 `frame_idx` 单调递增。WebRTC track 上的帧推送不依赖对应 SSE 事件是否已被消费。
- 服务端**不**对慢速 SSE 消费者施加背压。落后超过约 5 秒的消费者可能被断开。
- WebSocket 音频输入存在背压：发送速率快于合成流水线处理能力时，客户端从底层传输收到流控信号。

## 源文件

- `apps/api/routes/events.py` —— SSE 端点。
- `apps/api/routes/sessions.py` —— `speak_audio_stream` WebSocket 端点。
- `opentalking/core/events.py` —— 事件 schema。
- `opentalking/core/bus.py` —— pub/sub 总线。
