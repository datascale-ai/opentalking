# FlashHead

## 支持状态

| 项 | 值 |
|----|----|
| 模型 ID | `flashhead` |
| Backend | `direct_ws` |
| 证据等级 | 已文档化 |
| 推荐用途 | 已有独立 FlashHead WebSocket 服务 |

## 推荐硬件

由 FlashHead 服务自行决定。OpenTalking 只连接其 HTTP/WebSocket 端点。

## 权重下载

OpenTalking 不管理 FlashHead 权重。常用搜索入口：

- [Hugging Face 搜索 SoulX FlashHead](https://huggingface.co/models?search=SoulX%20FlashHead)
- [ModelScope 搜索 FlashHead](https://modelscope.cn/models?name=FlashHead)
- [魔乐社区搜索 FlashHead](https://modelers.cn/models?name=FlashHead)

## 目录结构

权重目录由 FlashHead 服务管理。OpenTalking 只需要 avatar manifest 与服务 URL。

## 配置项

```env title=".env"
OPENTALKING_FLASHHEAD_WS_URL=ws://<flashhead-host>:8766/v1/avatar/realtime
OPENTALKING_FLASHHEAD_BASE_URL=http://<flashhead-host>:8766
OPENTALKING_FLASHHEAD_MODEL=soulx-flashhead-1.3b
```

```yaml title="configs/default.yaml"
models:
  flashhead:
    backend: direct_ws
```

## 启动命令

先启动 FlashHead 服务，再启动 OpenTalking：

```bash title="终端"
bash scripts/quickstart/start_all.sh
```

## `/models` 验证

```bash title="终端"
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="flashhead")'
```

配置 WebSocket URL 后，期望：

```json
{"id":"flashhead","backend":"direct_ws","connected":true,"reason":"direct_ws"}
```

## 常见错误

| 现象 | 处理 |
|------|------|
| `reason=not_configured` | 设置 `OPENTALKING_FLASHHEAD_WS_URL`。 |
| WebSocket 握手失败 | 检查 FlashHead 服务路径、端口和跨机器网络。 |
| Avatar 不匹配 | 确认 avatar 能被服务读取，并且 FlashHead 服务端能访问所需参考图。 |
