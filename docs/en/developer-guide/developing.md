# Developing

This page documents the development workflow for OpenTalking itself: repository layout,
setup, local execution, linting, testing, and debugging.

## Repository layout

```text
opentalking/
├── opentalking/          # Library code (flat layout)
│   ├── core/             # Interfaces, registry, types, config, bus
│   ├── models/           # Local synthesis adapters (quicktalk) and remote shims
│   ├── llm/  tts/  stt/  # Provider adapters
│   ├── rtc/              # WebRTC track management
│   ├── voices/           # Voice cloning (CosyVoice, Qwen, ElevenLabs)
│   ├── avatars/          # Avatar bundle loader and validator
│   ├── worker/           # Pipeline orchestrators
│   └── server/  cli/  engine/
├── apps/
│   ├── api/              # FastAPI routes and schemas
│   ├── worker/           # Worker entry point
│   ├── unified/          # Single-process entry point
│   ├── cli/              # Command-line utilities
│   └── web/              # React frontend (TypeScript, Vite)
├── configs/              # default.yaml, profiles/*, synthesis/*
├── scripts/quickstart/   # Start and stop helpers
├── examples/avatars/     # Sample avatar bundles
├── tests/                # pytest suite
└── docs/                 # Documentation site
```

## Environment setup

```bash title="terminal"
git clone https://github.com/datascale-ai/opentalking.git
cd opentalking
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
```

The `[dev]` extra installs `ruff`, `pytest`, `pytest-asyncio`, `pytest-cov`, and
related development dependencies.

## Running locally

OpenTalking can be run locally in four configurations. Each is appropriate for a
different scope of development work.

### Unified mode with mock synthesis

The recommended configuration for frontend changes, orchestration changes, and API or
schema modifications. No GPU is required.

```bash title="terminal"
bash scripts/quickstart/start_all.sh --mock
```

- Backend: <http://127.0.0.1:8000>
- Frontend: <http://localhost:5173>

Auto-reload for Python source changes:

```bash title="terminal"
uvicorn apps.unified.main:app --reload --port 8000
```

Frontend in a separate terminal:

```bash title="terminal"
cd apps/web && npm ci && npm run dev -- --host 0.0.0.0
```

Vite hot module replacement is enabled by default; backend changes require a restart
unless `uvicorn --reload` is used.

### Unified mode with a real backend

Includes a real talking-head model. The default Wav2Lip path uses OmniRT; local
adapters and direct WebSocket services can be selected with `models.<name>.backend`
or `OPENTALKING_<MODEL>_BACKEND`.

```bash title="terminal: start OmniRT (terminal 1)"
bash scripts/quickstart/start_omnirt_wav2lip.sh --device cuda
```

```bash title="terminal: opentalking (terminal 2)"
echo "OMNIRT_ENDPOINT=http://127.0.0.1:9000" >> .env
bash scripts/quickstart/start_all.sh
```

The frontend model selector lists `wav2lip` after OmniRT is reachable.
For model-specific weight downloads and startup commands, see
[Models](../model-deployment/index.md).

### API and Worker split with local Redis

Use this configuration when debugging the event bus or Worker lifecycle.

```bash title="terminal: redis"
redis-server --port 6379 --save "" --appendonly no
```

```bash title="terminal: API"
export OPENTALKING_REDIS_URL=redis://localhost:6379/0
export OPENTALKING_WORKER_URL=http://127.0.0.1:9001
uvicorn apps.api.main:app --reload --port 8000
```

```bash title="terminal: Worker"
export OPENTALKING_REDIS_URL=redis://localhost:6379/0
python -m apps.worker.main --port 9001
```

```bash title="terminal: frontend"
cd apps/web && npm run dev -- --host 0.0.0.0
```

Four processes run concurrently. Use `redis-cli MONITOR` to inspect bus traffic.

### Frontend only

When the backend is already running on a separate host:

```bash title="terminal"
cd apps/web
export VITE_BACKEND_URL=http://teammate-host:8000
npm run dev -- --host 0.0.0.0
```

To stop all processes started by the quickstart helpers:

```bash title="terminal"
bash scripts/quickstart/stop_all.sh
```

For manually started components, terminate the relevant `uvicorn`,
`python -m apps.worker.main`, or `redis-server` processes.

## Linting and formatting

```bash title="terminal"
ruff check opentalking apps tests
ruff format opentalking apps tests
```

The pre-commit hook runs these checks on staged files automatically.

## Testing

```bash title="terminal"
pytest tests -v
# Run a single test file:
pytest tests/test_session_state.py -v
# Coverage report:
pytest tests --cov=opentalking --cov-report=term-missing
```

Test conventions:

- Asynchronous tests use `pytest_asyncio`. Shared fixtures are defined in `conftest.py`.
- External HTTP calls are mocked with `respx`; WebSocket calls are mocked with `pytest-aiohttp`.
- Tests that perform live calls to external language models or text-to-speech services are gated by `OPENTALKING_TEST_LIVE=1` and are disabled by default.

## Debugging

### Verbose logging

```bash title="terminal"
OPENTALKING_LOG_LEVEL=DEBUG opentalking-unified
```

### Server-sent event stream

After creating a session via `POST /sessions`:

```bash title="terminal"
curl -N http://127.0.0.1:8000/sessions/<id>/events
```

The stream interleaves `transcript`, `llm`, `tts`, and `status` events with frame
timing markers.

### Redis bus inspection

```bash title="terminal"
redis-cli MONITOR
```

### Direct endpoint invocation

```bash title="terminal"
# List avatars
curl -s http://127.0.0.1:8000/avatars | jq

# Create a session
curl -s -X POST http://127.0.0.1:8000/sessions \
  -H 'content-type: application/json' \
  -d '{"avatar_id":"demo-avatar","model":"mock"}'

# Synthesize a fixed phrase
curl -s -X POST http://127.0.0.1:8000/sessions/<id>/speak \
  -H 'content-type: application/json' \
  -d '{"text":"Hello world"}'
```

The complete endpoint surface is documented in the [API Reference](../api-reference/index.md).

## Common issues

| Symptom | Likely cause |
|---------|--------------|
| `ModuleNotFoundError: opentalking` | The package was not installed with `pip install -e ".[dev]"`. |
| Browser reports WebRTC is unavailable | The browser blocks WebRTC on non-HTTPS, non-localhost origins. |
| Worker logs `redis connection refused` | Switch to unified mode or start `redis-server`. |
| A test hangs at `await ws.send_text()` | `OPENTALKING_TEST_LIVE` is set and the live service is unreachable. |

## Pull request checklist

Verify the following before opening a pull request:

- [ ] `ruff check` passes (enforced by the pre-commit hook).
- [ ] `pytest tests` passes.
- [ ] User-visible behavior changes are reflected in `README.md` or the relevant documentation page.
- [ ] Tests are added or updated for new code paths.
- [ ] Commits are scoped (adapter, route, worker, etc.) for ease of review.

See [Contributing](contributing.md) for additional guidelines.
