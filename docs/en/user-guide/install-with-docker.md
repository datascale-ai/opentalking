# Install with Docker Compose

The Docker Compose installation provides a packaged stack for OpenTalking. It is best
used for repeatable deployments and production-like validation. For quick CPU
evaluation, single-GPU evaluation, or Ascend NPU bring-up, prefer
[Install from source](install-from-source.md) first because it keeps driver, CANN,
CUDA, weight paths, and model logs directly visible on the host.

The packaged stack has the following operational characteristics:

- The orchestrator (API, Worker, frontend, Redis) is built from Dockerfiles in `docker/`.
- The inference runtime (OmniRT) is pulled from `ghcr.io/datascale-ai/omnirt` and enabled by Compose profiles.
- Deployment scenarios are selected by Compose profile, not by separate Compose files.

For development scenarios where source-level access is required, see
[Install from source](install-from-source.md). For Ascend NPU deployment, only the
source installation method is currently supported.

## Compose layout

The repository contains two Compose files:

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Base file. Defines `redis`, `api`, `worker`, `web` services unconditionally. Defines `omnirt` under the `gpu` profile. |
| `docker-compose.gpu.yml` | Override applied with the `gpu` profile. Wires `api` and `worker` to OmniRT and disables mock synthesis. |

Containers built from local Dockerfiles:

| Container | Dockerfile | Purpose |
|-----------|-----------|---------|
| `api` | `docker/Dockerfile.api` | FastAPI server on port 8000. |
| `worker` | `docker/Dockerfile.worker` | Asynchronous pipeline executor. |
| `web` | `docker/Dockerfile.web` | Vite-built frontend behind nginx, port 5173. |

Additional Dockerfiles (`docker/Dockerfile.flashtalk`, `docker/Dockerfile.flashtalk.ascend`)
are used for legacy bare-metal FlashTalk deployments and are not invoked by the
default Compose stack.

## Prerequisites

- Docker Engine 20.10 or later with the Compose v2 plugin (`docker compose ...`).
- Approximately 8 GB of free disk space for images and built containers.
- For the GPU profile: the NVIDIA Container Toolkit. Verify with `docker info | grep -i runtimes`; the output must include `nvidia`.
- Network access to `ghcr.io` (or a configured registry mirror) for the OmniRT image.

## CPU profile {#cpu-profile}

Suitable for laptops, continuous integration, and frontend development. Only the
`mock` synthesis backend is functional; real talking-head models cannot be exercised
in this profile.

### Initial setup

```bash title="terminal"
git clone https://github.com/datascale-ai/opentalking.git
cd opentalking
cp .env.example .env
```

Edit `.env` and set the required language model and speech recognition keys:

```env title=".env"
OPENTALKING_LLM_API_KEY=<dashscope-api-key>
DASHSCOPE_API_KEY=<dashscope-api-key>
```

The Compose stack reads `.env` automatically via the `env_file` directive in
`docker-compose.yml`.

### Start

```bash title="terminal"
docker compose up -d
```

Services started:

| Service | Address | Notes |
|---------|---------|-------|
| `redis` | internal only | Health-checked before `api` and `worker` start. |
| `api` | `http://localhost:8000` | FastAPI server. |
| `worker` | internal only | Connects to `api` via Redis. |
| `web` | `http://localhost:5173` | Frontend. |

The default profile sets `OPENTALKING_INFERENCE_MOCK=1`, so the `api` and `worker`
containers route all synthesis requests through the in-process mock. The `omnirt`
service is not started.

### Verify

```bash title="terminal"
docker compose ps
docker compose logs -f api
curl -s http://localhost:8000/health
```

### Stop

```bash title="terminal"
docker compose down
```

To also remove the Redis volume:

```bash title="terminal"
docker compose down -v
```

## GPU profile {#gpu-profile}

Suitable for single-host deployment with an NVIDIA GPU. Pulls and runs OmniRT in
addition to the orchestrator services.

### Initial setup

Identical to the CPU profile: clone the repository, copy `.env.example`, and set the
language model and speech recognition keys.

### Start

```bash title="terminal"
docker compose --profile gpu \
  -f docker-compose.yml -f docker-compose.gpu.yml \
  up -d
```

Compose starts the `omnirt` service in addition to the CPU-profile services. The
GPU profile sets `OPENTALKING_INFERENCE_MOCK=0` and points the API and Worker at
`http://omnirt:9000`, enabling real talking-head synthesis.

### Memory and disk

| Resource | Approximate requirement |
|----------|------------------------|
| GPU VRAM | 24 GB minimum for wav2lip, 22 GB+ free for FlashTalk-14B |
| RAM | 16 GB minimum, 32 GB recommended |
| Disk | 30 GB for images, 35 GB for FlashTalk weights pulled by OmniRT on first start |

### Verify GPU access

```bash title="terminal"
docker compose --profile gpu exec omnirt nvidia-smi
```

The output should list the host GPUs.

### Selecting a model

The Compose stack does not select a synthesis model. Model selection is performed by
the client when a session is created. To verify the available models:

```bash title="terminal"
curl -s http://localhost:8000/models | jq
```

To restrict the GPU profile to a specific model (e.g. wav2lip only), the OmniRT
container can be configured with environment variables; see the OmniRT documentation
for current options.

### Stop

```bash title="terminal"
docker compose --profile gpu \
  -f docker-compose.yml -f docker-compose.gpu.yml \
  down
```

## Persistent state

The Compose stack writes the following persistent state:

| Path inside container | Volume | Description |
|----------------------|--------|-------------|
| `/app/examples/avatars` | Bind mount or named volume | Avatar bundles read by the API. |
| `/app/var/voices` | Named volume | Cloned voice catalog and audio uploads. |
| `/app/data` | Named volume | SQLite database. |
| Redis data | Named volume | Session state and FlashTalk queue. |

Production deployments should bind-mount avatar and voice directories from host
storage rather than using anonymous volumes; the precise mounts are defined in the
`docker-compose.yml` `volumes` section.

## .env layout for Docker deployments

The Compose stack reads `.env` from the repository root. Variables relevant to Docker
deployments:

| Variable | Default in Compose | Purpose |
|----------|-------------------|---------|
| `OPENTALKING_LLM_API_KEY` | _empty_ | Language model API key. Forwarded to `api` and `worker`. |
| `DASHSCOPE_API_KEY` | _empty_ | Speech recognition API key. |
| `OPENTALKING_INFERENCE_MOCK` | `1` (CPU), `0` (GPU) | Set automatically by the profile. |
| `OMNIRT_ENDPOINT` | `http://omnirt:9000` (GPU profile only) | Set automatically by the override file. |
| `OPENTALKING_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Override when serving the frontend from a different origin. |

Variables that override Compose defaults (such as `OPENTALKING_INFERENCE_MOCK`) should
be set in `.env` only when intentionally diverging from the profile defaults.

## Operations

### Inspect logs

```bash title="terminal"
docker compose logs -f api worker
docker compose --profile gpu logs -f omnirt
```

### Restart a single service

```bash title="terminal"
docker compose restart api
```

### Rebuild after code changes

```bash title="terminal"
docker compose build api worker web
docker compose up -d
```

### Update to a new OpenTalking version

```bash title="terminal"
git pull
docker compose build
docker compose up -d
```

### Update the OmniRT image

```bash title="terminal"
docker compose --profile gpu pull omnirt
docker compose --profile gpu up -d
```

## Troubleshooting

| Symptom | Resolution |
|---------|------------|
| `Error response from daemon: could not select device driver "" with capabilities: [[gpu]]` | The NVIDIA Container Toolkit is not installed or not registered with Docker. Install the toolkit and restart the Docker daemon. |
| `omnirt` container exits with `CUDA driver mismatch` | The host NVIDIA driver is older than the CUDA version in the OmniRT image. Update the host driver. |
| `api` cannot reach `omnirt` | Verify both containers are in the `gpu` profile: `docker compose --profile gpu ps`. The default profile does not start OmniRT. |
| `web` container 502s on frontend requests | The `api` container is not yet healthy. Inspect `docker compose logs api`. |
| `.env` changes have no effect | Compose reads `.env` at container start. Restart the affected services with `docker compose restart <service>`. |

## Migration from source installation

When migrating from a source installation to Docker Compose:

1. Stop the source-installation processes (`bash scripts/quickstart/stop_all.sh`).
2. Ensure `.env` references container-internal hostnames (e.g. `redis://redis:6379/0`, not `redis://localhost:6379/0`). The Compose stack handles this automatically when the values are unset.
3. Copy any custom avatar bundles into the `examples/avatars/` directory before starting the stack; the directory is bind-mounted by the `api` and `worker` services.
4. Run `docker compose up -d`.

## Limitations

- The Ascend 910B deployment path is not yet packaged in Compose. Use the [source installation Ascend scenario](install-from-source.md#ascend-910b).
- The Docker stack does not include the legacy bare-metal FlashTalk single-process server. Real FlashTalk synthesis is served exclusively through OmniRT in the Compose deployment.
- Multi-host Worker scaling is not supported by the default Compose stack. Use the source installation [API and Worker split](install-from-source.md#api-and-worker-split) scenario.
