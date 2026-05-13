# 数字人形象

用于浏览 avatar bundle、获取 manifest 与预览图、由人像图创建自定义 avatar 的端点。

avatar bundle 格式在 [Avatar 资产格式](../user-guide/avatar-format.md) 中单独说明。

## `GET /avatars`

返回 `OPENTALKING_AVATARS_DIR` 下的 avatar bundle 列表。隐藏 avatar（`metadata.hidden=true`）
被过滤。

**响应 — `200 OK`**

响应体类型：`list[AvatarSummary]`。

### `AvatarSummary`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 全局唯一 avatar 标识符。 |
| `name` | string \| null | 展示名，默认为 `id`。 |
| `model_type` | string | `wav2lip`、`musetalk`、`quicktalk`、`flashtalk`、`flashhead`、`mock` 之一。 |
| `width` | integer | 输出视频宽度（像素）。 |
| `height` | integer | 输出视频高度（像素）。 |
| `is_custom` | boolean | `true` 表示通过 `POST /avatars/custom` 创建，可被删除。 |

```bash title="curl"
curl -s http://localhost:8000/avatars | jq
```

```json title="响应"
[
  {
    "id": "demo-avatar",
    "name": "Demo",
    "model_type": "mock",
    "width": 512,
    "height": 512,
    "is_custom": false
  },
  {
    "id": "custom-alice-20260513-153012-001",
    "name": "Alice",
    "model_type": "wav2lip",
    "width": 1024,
    "height": 1024,
    "is_custom": true
  }
]
```

## `GET /avatars/{avatar_id}`

返回所请求 avatar 的完整 `manifest.json`，包含 `metadata` 块。

**路径参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `avatar_id` | string | 来自 `GET /avatars` 的 avatar 标识符。 |

**响应 — `200 OK`**

完整 manifest 对象。schema 见
[Avatar 资产格式 → manifest.json schema](../user-guide/avatar-format.md#manifestjson-schema)。

```bash title="curl"
curl -s http://localhost:8000/avatars/demo-avatar | jq
```

```json title="响应"
{
  "id": "demo-avatar",
  "name": "Demo",
  "model_type": "mock",
  "fps": 25,
  "sample_rate": 16000,
  "width": 512,
  "height": 512,
  "version": "1.0",
  "metadata": {}
}
```

**错误响应**

| 状态码 | 条件 |
|--------|------|
| `404` | avatar 标识符不存在。 |

## `GET /avatars/{avatar_id}/preview`

返回该 avatar 的 `preview.png` 文件，响应体为二进制图像内容。

**路径参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `avatar_id` | string | avatar 标识符。 |

**响应 — `200 OK`**

Content-Type：`image/png`。响应体为原始 PNG 数据。

**错误响应**

| 状态码 | 条件 |
|--------|------|
| `404` | avatar 不存在，或 `preview.png` 缺失。 |

## `POST /avatars/custom`

由用户提供的人像图与 base avatar 的 manifest 合成新 avatar bundle。新 avatar 标记为
`metadata.custom_avatar=true`，从而可通过 `DELETE /avatars/{avatar_id}` 删除。

**请求体 — `multipart/form-data`**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | 新 avatar 的展示名。 |
| `base_avatar_id` | string | 是 | 用作 manifest 模板的现有 avatar 标识符。该 avatar 须为 `model_type=wav2lip`。 |
| `image` | file | 是 | 人像图，最大 10 MB。可接受格式：JPEG、PNG、WebP。 |

**行为**

1. 加载 base avatar 的 `manifest.json`。
2. 生成形如 `custom-<slug>-<timestamp>` 的新 avatar 标识符。
3. 将上传图转换为 RGB 并保存为新 bundle 目录下的 `frames/frame_00000.png`。
4. 尝试 MediaPipe 嘴部检测；成功时结果写入 `metadata.animation`，失败时仍返回成功但缺失 `animation` 字段。
5. 覆盖新 manifest 的 `id` 与 `name`，并记录 `metadata.custom_avatar=true` 与 `metadata.base_avatar_id=<base>`。

**响应 — `200 OK`**

响应体类型：新建 avatar 的 `AvatarSummary`。

```bash title="curl"
curl -X POST http://localhost:8000/avatars/custom \
  -F name="Alice" \
  -F base_avatar_id=demo-wav2lip \
  -F image=@portrait.jpg
```

```json title="响应"
{
  "id": "custom-alice-20260513-153012-001",
  "name": "Alice",
  "model_type": "wav2lip",
  "width": 1024,
  "height": 1024,
  "is_custom": true
}
```

**错误响应**

| 状态码 | 条件 |
|--------|------|
| `400` | 上传图为空、无效，或超过 10 MB。 |
| `404` | base avatar 标识符不存在。 |
| `413` | 上传图超过 10 MB。 |

## `DELETE /avatars/{avatar_id}`

从磁盘移除自定义 avatar bundle。仅通过 `POST /avatars/custom` 创建的 avatar 可删除；
试图删除内置或隐藏 avatar 会被拒绝。

**路径参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `avatar_id` | string | avatar 标识符，须满足 `is_custom=true`。 |

**响应 — `200 OK`**

```json
{"deleted": true}
```

**错误响应**

| 状态码 | 条件 |
|--------|------|
| `403` | avatar 未标记为 custom，不可删除。 |
| `404` | avatar 标识符不存在。 |

## 源文件

- `apps/api/routes/avatars.py` —— 端点实现。
- `apps/api/schemas/avatar.py` —— `AvatarSummary` 响应模型。
- `opentalking/avatar/loader.py` —— `load_avatar_bundle()`。
- `opentalking/avatar/validator.py` —— `list_avatar_dirs()`。
- `opentalking/avatar/mouth_metadata.py` —— MediaPipe 嘴部检测。
