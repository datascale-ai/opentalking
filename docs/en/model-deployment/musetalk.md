# MuseTalk

MuseTalk supports `local`, `omnirt`, and advanced `direct_ws` integration. This section separates the two common deployment modes.

| Item | Value |
|------|-------|
| Model ID | `musetalk` |
| Backends | `local`, `omnirt`, `direct_ws` |
| Repo default | `omnirt` |
| Recommended start | Use `local` when OpenMMLab dependencies are ready; use `omnirt` for service isolation. |

## Guides

- [MuseTalk Local](musetalk/local.md)
- [MuseTalk with OmniRT](musetalk/omnirt.md)
- [Support Matrix](support-matrix.md)

## Frontend Entry

After the model or backend service is running, use the OpenTalking WebUI:

```bash title="Terminal"
cd "$OPENTALKING_HOME"
bash scripts/quickstart/start_frontend.sh --api-port 8000 --web-port 5173 --host 0.0.0.0
```

For a remote server, forward your local browser port to the server `5173`, then open `http://127.0.0.1:5173`.
