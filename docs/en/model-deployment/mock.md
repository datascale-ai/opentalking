# Mock

## Support Status

| Item | Value |
|------|-------|
| Model ID | `mock` |
| Backend | `mock` |
| Evidence level | Built in, verified |
| Best for | First run, CI, API/WebRTC debugging |

## Recommended Hardware

CPU only. No GPU, NPU, model weights, or external model service are required.

## Weights

None. `mock` returns placeholder frames in the OpenTalking process to validate orchestration.

## Directory Layout

```text
opentalking/
├── examples/avatars/
└── scripts/quickstart/start_mock.sh
```

## Configuration

At minimum, configure the LLM and STT module keys:

```env title=".env"
OPENTALKING_LLM_API_KEY=<dashscope-api-key>
OPENTALKING_STT_DEFAULT_PROVIDER=dashscope
OPENTALKING_STT_DASHSCOPE_API_KEY=<dashscope-api-key>
```

## Start

```bash title="Terminal"
bash scripts/quickstart/start_mock.sh
```

## `/models` Verification

```bash title="Terminal"
curl -s http://127.0.0.1:8000/models | python3 -m json.tool
```

Expected:

```json
{"id":"mock","backend":"mock","connected":true,"reason":"local_self_test"}
```

## Common Errors

| Symptom | Action |
|---------|--------|
| LLM returns 401 | Check `OPENTALKING_LLM_API_KEY` and `OPENTALKING_STT_DASHSCOPE_API_KEY` separately. |
| No browser video | Use a Chromium-based browser and inspect WebRTC/CORS errors. |
| Port conflict | Run `bash scripts/quickstart/start_mock.sh --api-port 8010 --web-port 5180`. |

## Frontend Entry

After the model or backend service is running, use the OpenTalking WebUI:

```bash title="Terminal"
cd "$OPENTALKING_HOME"
bash scripts/quickstart/start_frontend.sh --api-port 8000 --web-port 5173 --host 0.0.0.0
```

For a remote server, forward your local browser port to the server `5173`, then open `http://127.0.0.1:5173`.
