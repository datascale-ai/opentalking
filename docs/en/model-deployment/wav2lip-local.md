# Wav2Lip Local

The Wav2Lip local guide has moved to [Wav2Lip / Local](wav2lip/local.md).

This compatibility page keeps old links working. Use the new deployment structure:

- [Wav2Lip Overview](wav2lip.md)
- [Wav2Lip Local](wav2lip/local.md)
- [Wav2Lip with OmniRT](wav2lip/omnirt.md)

## Frontend Entry

After the model or backend service is running, use the OpenTalking WebUI:

```bash title="Terminal"
cd "$OPENTALKING_HOME"
bash scripts/quickstart/start_frontend.sh --api-port 8000 --web-port 5173 --host 0.0.0.0
```

For a remote server, forward your local browser port to the server `5173`, then open `http://127.0.0.1:5173`.
