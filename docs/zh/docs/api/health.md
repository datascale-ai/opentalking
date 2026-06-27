# 健康检查与模型

用于存活探针、就绪探针、队列检视与合成能力发现的端点。

## `GET /health`

返回固定的存活 payload。供负载均衡器与编排系统调用。

**响应 — `200 OK`**

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | 进程可响应时恒为 `"ok"`。 |

```bash title="curl"
curl -s http://localhost:8000/health
```

```json title="响应"
{"status": "ok"}
```

## `GET /healthz`

`GET /health` 的 Kubernetes 风格别名，响应一致。Kubernetes liveness 探针默认使用该
路径。

## `GET /queue/status`

返回 FlashTalk 合成队列状态。数据来自 Redis；未部署 Redis 或 Redis 不可达时返回
零值。

**响应 — `200 OK`**

| 字段 | 类型 | 说明 |
|------|------|------|
| `slot_occupied` | boolean | 当前是否有推理 slot 被占用。 |
| `queue_size` | integer | FlashTalk 等待队列中的请求数。 |

```bash title="curl"
curl -s http://localhost:8000/queue/status
```

```json title="响应"
{
  "slot_occupied": false,
  "queue_size": 0
}
```

该端点不会返回 HTTP `5xx`。Redis 错误被捕获并转换为默认零 payload，便于在 Redis
波动期间继续作为 readiness 探针使用。

## `GET /models`

返回当前部署可用的合成后端集合。结果由配置以及对推理服务的可达性探测综合得出。

**响应 — `200 OK`**

| 字段 | 类型 | 说明 |
|------|------|------|
| `models` | string array | 已知合成模型标识符列表。 |
| `statuses` | object array | 每个模型的可用性元数据。 |

`statuses[].id` 为模型标识符，`statuses[].backend` 为所选 backend，
`statuses[].connected` 标识该 backend 是否可用，`statuses[].reason` 提供简短诊断信息。

```bash title="curl"
curl -s http://localhost:8000/models | jq
```

```json title="响应"
{
  "models": ["mock", "flashtalk", "musetalk", "wav2lip", "flashhead", "quicktalk"],
  "statuses": [
    {"id": "mock", "backend": "mock", "connected": true, "reason": "local_self_test"},
    {"id": "flashtalk", "backend": "omnirt", "connected": false, "reason": "not_configured"},
    {"id": "musetalk", "backend": "omnirt", "connected": false, "reason": "not_configured"},
    {"id": "wav2lip", "backend": "omnirt", "connected": false, "reason": "not_configured"},
    {"id": "flashhead", "backend": "direct_ws", "connected": false, "reason": "not_configured"},
    {"id": "quicktalk", "backend": "local", "connected": true, "reason": "local_runtime"}
  ]
}
```

`models` 中列出但 `connected: false` 的模型无法用于新会话；`POST /sessions` 会以
HTTP `400` 拒绝未连接模型。

## 状态码

| 状态码 | 条件 |
|--------|------|
| `200` | 本分组所有端点的成功响应。 |
| `5xx` | 进程不可响应；负载均衡或编排系统应将实例视为 unhealthy。本分组端点本身设计为不抛出。 |

## 源文件

- `apps/api/routes/health.py` —— `/health`、`/healthz`、`/queue/status`。
- `apps/api/routes/models.py` —— `/models`。
- `opentalking/providers/synthesis/availability.py` —— `resolve_model_statuses()`。
- `opentalking/core/queue_status.py` —— `get_flashtalk_queue_status()`。
