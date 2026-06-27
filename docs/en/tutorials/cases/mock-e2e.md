# Mock E2E Case

## Goal

Run the browser, API, LLM, STT, TTS, event stream, and WebRTC path with the `mock`
synthesis backend. This path does not require GPU, NPU, or talking-head weights.

## Prerequisites

- [Installation](../installation.md) is complete.
- `.env` contains `OPENTALKING_LLM_API_KEY` and `OPENTALKING_STT_DASHSCOPE_API_KEY`.
- Ports `8000` and `5173` are available, or custom ports are prepared.

## Steps

```bash title="Terminal"
cd opentalking
source .venv/bin/activate
bash scripts/quickstart/start_mock.sh
```

Open <http://localhost:5173>, choose a built-in avatar and the `mock` model, then use the
microphone button to start a session.

## Verification

```bash title="Terminal"
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="mock")'
```

The `mock` status should report `connected: true`, and the browser should receive text
events plus placeholder video frames.

## Troubleshooting

| Symptom | Action |
|---------|--------|
| Port already in use | Run `bash scripts/quickstart/start_mock.sh --api-port 8010 --web-port 5180`. |
| LLM returns 401 | Check both DashScope key variables in `.env`. |
| No browser video | Use a Chromium-based browser and inspect WebRTC/CORS errors in the console. |
