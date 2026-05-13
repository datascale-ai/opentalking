# TTS 与音色

提供不依赖会话的一次性语音合成与复刻音色管理。

## TTS 预览

### `POST /tts/preview`

不创建会话直接合成一段短音频。前端在启动会话前用以试听音色。

**请求体 — `application/json`**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `text` | string | 是 | 待合成文本，建议最长 200 字。 |
| `voice` | string | 否 | 音色标识符，格式取决于 `provider`。 |
| `provider` | string | 否 | `edge`、`dashscope`、`cosyvoice`、`elevenlabs` 之一，默认取 `OPENTALKING_TTS_PROVIDER`。 |
| `model` | string | 否 | provider 专属模型标识符。 |

**响应 — `200 OK`**

Content-Type：`audio/wav`。响应体为 16 位 PCM WAV，采样率与会话默认值一致（默认
16000 Hz）。

```bash title="curl"
curl -s -X POST http://localhost:8000/tts/preview \
  -H 'content-type: application/json' \
  -d '{"text": "你好，这是音色试听。", "provider": "edge", "voice": "zh-CN-XiaoxiaoNeural"}' \
  -o preview.wav
```

**错误响应**

| 状态码 | 条件 |
|--------|------|
| `400` | `text` 为空，或超出配置的长度上限。 |
| `502` | 上游 TTS provider 返回错误。 |

## 音色目录

音色目录使用本地 SQLite 数据库持久化复刻音色。复刻音色在显式删除前一直可用，进程
重启后仍存在。

### `GET /voices`

列出复刻音色。

**查询参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `provider` | string \| null | 按 provider 过滤（`cosyvoice` 或 `dashscope`）。 |

**响应 — `200 OK`**

```json
{
  "items": [
    {
      "id": 1,
      "user_id": null,
      "provider": "dashscope",
      "voice_id": "u3e7c12ab",
      "display_label": "Alice 的音色",
      "target_model": "qwen3-tts-flash-realtime",
      "source": "clone"
    }
  ]
}
```

字段说明：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | integer | 目录主键，用于 `DELETE /voices/{entry_id}`。 |
| `user_id` | string \| null | 为多租户预留。 |
| `provider` | string | `cosyvoice` 或 `dashscope`。 |
| `voice_id` | string | provider 端的音色标识符。会话中作为 `tts_voice` 传入即可使用该复刻音色。 |
| `display_label` | string | 人类可读名。 |
| `target_model` | string | 复刻所针对的 TTS 模型标识符。 |
| `source` | string | 通过本端点创建的条目恒为 `"clone"`。 |

```bash title="curl"
curl -s 'http://localhost:8000/voices?provider=dashscope' | jq
```

### `POST /voices/clone`

由音频样本复刻音色。支持两种 provider，各有不同要求。

**请求体 — `multipart/form-data`**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `provider` | string | 是 | `cosyvoice` 或 `dashscope`。 |
| `target_model` | string | 是 | 复刻所针对的 TTS 模型标识符。DashScope 需支持复刻的 Qwen VC 模型；CosyVoice 需 CosyVoice 模型标识符。 |
| `display_label` | string | 是 | 人类可读名。同名时端点自动追加时间戳后缀去重。 |
| `audio` | file | 是 | 音频样本，最小 256 字节，最大 12 MB。 |
| `prefix` | string | 否 | 仅 CosyVoice 使用。可选音色标识符前缀，缺省时随机生成。 |
| `preferred_name` | string | 否 | 仅 DashScope 使用。建议音色名，缺省时随机生成。 |

**provider 相关要求**

- **CosyVoice** 将音频样本上传至本地并把样本的公网 URL 提供给 DashScope；OpenTalking
  服务须能被 DashScope 反向访问。通过 `OPENTALKING_PUBLIC_BASE_URL` 指定公网 URL。
  样本上传后约 300 秒由后台任务自动从磁盘移除。
- **DashScope** 使用 base64 内联音频，无需公网可达。

**响应 — `200 OK`**

```json
{
  "ok": true,
  "entry_id": 12,
  "voice_id": "u3e7c12ab",
  "display_label": "Alice 的音色",
  "provider": "dashscope",
  "target_model": "qwen3-tts-flash-realtime",
  "message": "..."
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `entry_id` | integer | 目录主键，供后续删除使用。 |
| `voice_id` | string | provider 端的音色标识符。`speak` 或 `chat` 调用时使用该值。 |
| `display_label` | string | 解析后的展示名（可能含去重后缀）。 |
| `message` | string | 人类可读状态信息。 |

```bash title="curl：DashScope 复刻"
curl -s -X POST http://localhost:8000/voices/clone \
  -F provider=dashscope \
  -F target_model=qwen3-tts-flash-realtime \
  -F display_label="Alice 的音色" \
  -F audio=@sample.wav
```

**错误响应**

| 状态码 | 条件 |
|--------|------|
| `400` | `provider` 不是 `cosyvoice` 或 `dashscope`；音频过短、缺失或超过 12 MB；音频格式无法转换为 24 kHz 单声道 WAV。 |
| `502` | 上游 provider 返回错误（DashScope 拒绝、CosyVoice 复刻失败等）。 |

### `DELETE /voices/{entry_id}`

从目录中删除复刻音色。

**路径参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `entry_id` | integer | 来自 `GET /voices` 的目录主键。 |

**响应 — `200 OK`**

```json
{"deleted": true}
```

**错误响应**

| 状态码 | 条件 |
|--------|------|
| `404` | 条目不存在。 |

### `GET /voice-uploads/{token}`

供 CosyVoice 反查上传音频样本的内部端点。其存在的目的是让 DashScope CosyVoice 服务
通过 HTTP 取得样本。

**路径参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `token` | string | `POST /voices/clone` 生成的 32 字符十六进制 token。 |

**响应 — `200 OK`**

Content-Type：`audio/wav`。响应体为上传的音频样本。

**错误响应**

| 状态码 | 条件 |
|--------|------|
| `404` | token 格式错误或样本已过期。 |

!!! warning "公网暴露"
    该端点对外提供用户上传音频。生产部署应在反向代理层对该路径限流，并仅在启用
    CosyVoice 复刻时将 `OPENTALKING_PUBLIC_BASE_URL` 指向公网可达地址。

## Provider 对比

| Provider | 复刻 | 音色格式 | 说明 |
|----------|------|---------|------|
| `edge` | 不支持 | `<lang>-<region>-<name>Neural`（如 `zh-CN-XiaoxiaoNeural`） | 内置，无须 API Key。 |
| `dashscope` | 支持 | 控制台音色名（如 `xiaoxiao`）或复刻返回的 `voice_id` | 需 `DASHSCOPE_API_KEY`。 |
| `cosyvoice` | 支持 | 复刻返回的 `voice_id`（带前缀） | OpenTalking 服务须可被 DashScope 反向访问。 |
| `elevenlabs` | 在 OpenTalking 之外完成 | ElevenLabs `voice_id` | 需 `OPENTALKING_TTS_ELEVENLABS_API_KEY`。 |

## 源文件

- `apps/api/routes/tts_preview.py` —— `/tts/preview`。
- `apps/api/routes/voices.py` —— `/voices/*`、`/voice-uploads/{token}`。
- `opentalking/providers/tts/dashscope_qwen/clone.py` —— DashScope 与 CosyVoice 复刻实现。
- `opentalking/voice/store.py` —— 音色目录（SQLite）。
- `opentalking/tts/adapters/` —— `/tts/preview` 与会话合成所用的 provider 适配器。
