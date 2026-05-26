# Mock

## 支持状态

| 项 | 值 |
|----|----|
| 模型 ID | `mock` |
| Backend | `mock` |
| 证据等级 | 已内置，已验证 |
| 推荐用途 | 首次运行、CI、API/WebRTC 排查 |

## 推荐硬件

CPU 即可，不需要 GPU、NPU、模型权重或外部模型服务。

## 权重下载

无。`mock` 在 OpenTalking 进程内返回占位帧，用于验证编排链路。

## 目录结构

只需要 OpenTalking checkout 和内置示例 avatar：

```text
opentalking/
├── examples/avatars/
└── scripts/quickstart/start_mock.sh
```

## 配置项

至少配置 LLM 与 STT 模块 key：

```env title=".env"
OPENTALKING_LLM_API_KEY=<dashscope-api-key>
OPENTALKING_STT_DEFAULT_PROVIDER=dashscope
OPENTALKING_STT_DASHSCOPE_API_KEY=<dashscope-api-key>
```

## 启动命令

```bash title="终端"
bash scripts/quickstart/start_mock.sh
```

## `/models` 验证

```bash title="终端"
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="mock")'
```

期望：

```json
{"id":"mock","backend":"mock","connected":true,"reason":"local_self_test"}
```

## 常见错误

| 现象 | 处理 |
|------|------|
| LLM 返回 401 | 分别检查 `OPENTALKING_LLM_API_KEY` 与 `OPENTALKING_STT_DASHSCOPE_API_KEY`。 |
| 浏览器没有视频 | 使用 Chromium 内核浏览器并检查 WebRTC/CORS 报错。 |
| 端口占用 | 使用 `bash scripts/quickstart/start_mock.sh --api-port 8010 --web-port 5180`。 |
