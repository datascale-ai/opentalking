# Health and Models

Endpoints for liveness, readiness, queue introspection, and synthesis capability
discovery.

## `GET /health`

Returns a fixed liveness payload. Used by load balancers and orchestrators.

**Response — `200 OK`**

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Always `"ok"` when the process is responsive. |

```bash title="curl"
curl -s http://localhost:8000/health
```

```json title="response"
{"status": "ok"}
```

## `GET /healthz`

Kubernetes-style alias for `GET /health`. The response is identical. Most Kubernetes
liveness probe configurations expect this path.

## `GET /queue/status`

Returns the state of the FlashTalk synthesis queue. The data is read from Redis;
deployments without Redis or with Redis unreachable receive zero values.

**Response — `200 OK`**

| Field | Type | Description |
|-------|------|-------------|
| `slot_occupied` | boolean | `true` when an inference slot is currently in use. |
| `queue_size` | integer | Number of pending FlashTalk requests in the queue. |

```bash title="curl"
curl -s http://localhost:8000/queue/status
```

```json title="response"
{
  "slot_occupied": false,
  "queue_size": 0
}
```

The endpoint never fails with HTTP `5xx`. Redis errors are caught and translated to
the default zero payload, allowing the endpoint to be used as a readiness probe
without false negatives during Redis disruptions.

## `GET /models`

Returns the synthesis backends that are usable in the current deployment. The set is
computed from configuration and from probing the configured inference services.

**Response — `200 OK`**

| Field | Type | Description |
|-------|------|-------------|
| `models` | array of strings | Identifiers of known synthesis models. |
| `statuses` | array of objects | Per-model availability metadata. |

`statuses[].id` is the model identifier, `statuses[].backend` is the selected backend,
`statuses[].connected` indicates whether the backend is usable, and
`statuses[].reason` provides a short diagnostic string.

```bash title="curl"
curl -s http://localhost:8000/models | jq
```

```json title="response"
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

A model that appears in `models` but is `connected: false` cannot be selected for a
new session; `POST /sessions` rejects disconnected models with HTTP `400`.

## Status code reference

| Code | Condition |
|------|-----------|
| `200` | Successful response for all endpoints in this group. |
| `5xx` | The process is not responsive; the load balancer or orchestrator should treat the instance as unhealthy. The endpoints themselves are designed not to raise. |

## Source files

- `apps/api/routes/health.py` — `/health`, `/healthz`, `/queue/status`.
- `apps/api/routes/models.py` — `/models`.
- `opentalking/providers/synthesis/availability.py` — `resolve_model_statuses()`.
- `opentalking/core/queue_status.py` — `get_flashtalk_queue_status()`.
