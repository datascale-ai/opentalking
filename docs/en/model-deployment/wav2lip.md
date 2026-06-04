# Wav2Lip

Wav2Lip supports both `local` and `omnirt` modes. It is the recommended first real talking-head model because the weights are small and the startup path is clear.

| Item | Value |
|------|-------|
| Model ID | `wav2lip` |
| Backends | `local`, `omnirt`, compatible `direct_ws` |
| Repo default | `local` |
| Recommended start | [Wav2Lip Local](wav2lip/local.md) |

## Guides

- [Wav2Lip Local](wav2lip/local.md)
- [Wav2Lip with OmniRT](wav2lip/omnirt.md)
- [Talking-Head Models](talking-head/index.md)

## Frontend Entry

After the model or backend service is running, use the OpenTalking WebUI:

```bash title="Terminal"
cd "$OPENTALKING_HOME"
bash scripts/quickstart/start_frontend.sh --api-port 8000 --web-port 5173 --host 0.0.0.0
```

For a remote server, forward your local browser port to the server `5173`, then open `http://127.0.0.1:5173`.
