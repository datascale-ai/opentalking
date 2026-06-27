# FlashHead

## Support Status

| Item | Value |
|------|-------|
| Model ID | `flashhead` |
| Backend | `direct_ws` |
| Evidence level | Documented |
| Best for | Existing standalone FlashHead WebSocket service |

## Recommended Hardware

Owned by the FlashHead service. OpenTalking only connects to its HTTP/WebSocket endpoints.

## Weights

OpenTalking does not manage FlashHead weights. Search:

- [Hugging Face search for SoulX FlashHead](https://huggingface.co/models?search=SoulX%20FlashHead)
- [ModelScope search for FlashHead](https://modelscope.cn/models?name=FlashHead)
- [Modelers search for FlashHead](https://modelers.cn/models?name=FlashHead)

## Directory Layout

The FlashHead service owns its weight directory. OpenTalking only needs avatar manifests and
service URLs.

## Configuration

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

## Start

Start the FlashHead service first, then OpenTalking:

```bash title="Terminal"
bash scripts/quickstart/start_all.sh
```

## `/models` Verification

```bash title="Terminal"
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="flashhead")'
```

After configuring the WebSocket URL, expected:

```json
{"id":"flashhead","backend":"direct_ws","connected":true,"reason":"direct_ws"}
```

## Common Errors

| Symptom | Action |
|---------|--------|
| `reason=not_configured` | Set `OPENTALKING_FLASHHEAD_WS_URL`. |
| WebSocket handshake fails | Check FlashHead service path, port, and cross-host network. |
| Avatar issue | Confirm that the avatar is readable and that the FlashHead service can access the required reference image. |
