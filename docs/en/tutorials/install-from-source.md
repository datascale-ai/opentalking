# Install from source

A source installation provides the most flexibility and is required for development
work and for Ascend NPU deployment. The procedure differs in detail depending on the
target scenario; this page documents each variant.

If your environment matches the Docker-supported configurations, the
[Docker Compose installation](install-with-docker.md) is also a viable choice and may
be operationally simpler.

## Common steps

These steps are shared by all source installations.

### 1. Clone the repository

```bash title="terminal"
git clone https://github.com/datascale-ai/opentalking.git
cd opentalking
```

The repository assumes a parent directory that also contains the OmniRT checkout for
deployments that use real talking-head models. The recommended layout:

```text
$DIGITAL_HUMAN_HOME/
├── opentalking/
├── omnirt/
└── models/
    ├── wav2lip/
    ├── SoulX-FlashTalk-14B/
    └── chinese-wav2vec2-base/
```

Set the environment variable:

```bash title="terminal"
export DIGITAL_HUMAN_HOME=/opt/digital_human   # or your preferred path
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
```

### 2. Install Python dependencies

```bash title="terminal"
uv sync --extra dev --python 3.11
source .venv/bin/activate
```

The `[dev]` extra installs runtime dependencies plus `ruff`, `pytest`,
`pytest-asyncio`, `pytest-cov`, and related development tooling.

If you need the compatibility fallback instead:

```bash title="terminal"
python3 -m venv .venv
source .venv/bin/activate
pip install --index-url https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
```

Notes:

- The lockfile is validated with Python 3.11.
- When PyAV resolves to a wheel, only runtime `ffmpeg` is required.
- If you move to an unvalidated Python or PyAV combination and trigger a source build, you will also need `ffmpeg 7`, `pkg-config`, and a C compiler.

### 3. Install frontend dependencies

```bash title="terminal"
cd apps/web
npm ci
cd ../..
```

### 4. Configure environment

```bash title="terminal"
cp .env.example .env
```

Edit `.env` and set the minimum required variables:

```env title=".env"
OPENTALKING_LLM_API_KEY=<dashscope-api-key>
OPENTALKING_STT_DEFAULT_PROVIDER=dashscope
OPENTALKING_STT_DASHSCOPE_API_KEY=<dashscope-api-key>
```

LLM and STT may use the same actual key, but each module variable must be set
explicitly. The complete configuration reference is in [Configuration](configuration.md).

### 5. Verify the installation

```bash title="terminal"
opentalking-unified --help
opentalking-api --help
opentalking-worker --help
```

## Scenario: development with CPU and mock synthesis {#development-cpu-mock-synthesis}

For frontend development, API iteration, and orchestration changes on a workstation
without GPU access.

### Run the unified server

```bash title="terminal"
bash scripts/quickstart/start_mock.sh
```

This launches the OpenTalking unified server on `http://127.0.0.1:8000` and the Vite
development server on `http://localhost:5173`. The mock synthesis path returns
placeholder frames; no inference service is required.

For backend hot-reload during development:

```bash title="terminal"
uvicorn apps.unified.main:app --reload --port 8000
```

The frontend is started separately:

```bash title="terminal"
cd apps/web
npm run dev -- --host 0.0.0.0
```

System resources required:

- 1–2 GB of RAM for the unified process.
- No GPU.
- Network access to the configured language model and TTS endpoints.

## Scenario: single GPU with Wav2Lip {#scenario-single-gpu-with-wav2lip}

For evaluation on a single NVIDIA 3090 or equivalent 24 GB GPU using the lightweight
`wav2lip` model.

### Install OmniRT

OmniRT is the inference runtime. Clone it next to OpenTalking:

```bash title="terminal"
cd "$DIGITAL_HUMAN_HOME"
git clone https://github.com/datascale-ai/omnirt.git
cd omnirt
uv sync --extra server --python 3.11
```

### Download model weights

```bash title="terminal"
mkdir -p "$OMNIRT_MODEL_ROOT/wav2lip"
# Place wav2lip384.pth and s3fd.pth at $OMNIRT_MODEL_ROOT/wav2lip/
# Refer to the OmniRT documentation for current download locations.
```

### Start OmniRT

```bash title="terminal"
bash "$DIGITAL_HUMAN_HOME/opentalking/scripts/quickstart/start_omnirt_wav2lip.sh" --device cuda
```

The script handles dependency installation, environment variable setup, and starts
OmniRT on `http://127.0.0.1:9000`. The script writes the process ID to
`$DIGITAL_HUMAN_HOME/run/omnirt-wav2lip.pid` and logs to
`$DIGITAL_HUMAN_HOME/logs/omnirt-wav2lip.log`.

### Configure OpenTalking

Append to `.env`:

```env
OMNIRT_ENDPOINT=http://127.0.0.1:9000
```

### Run OpenTalking

```bash title="terminal"
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_all.sh --omnirt http://127.0.0.1:9000
```

In the frontend, select the `wav2lip` model when creating a session.

System resources required:

- 1 NVIDIA GPU with 24 GB of VRAM.
- 16 GB of RAM.
- 5 GB of disk for the wav2lip checkpoints.

## Scenario: single GPU with FlashTalk

For evaluation on a single NVIDIA 4090 or A100 using the SoulX FlashTalk-14B model.

The steps are identical to the wav2lip scenario, with the following changes:

```bash title="terminal: start OmniRT"
bash "$DIGITAL_HUMAN_HOME/opentalking/scripts/quickstart/start_omnirt_flashtalk.sh" --device cuda
```

Model weights:

- `SoulX-FlashTalk-14B/` (~28 GB) at `$OMNIRT_MODEL_ROOT/`.
- `chinese-wav2vec2-base/` (~400 MB) at `$OMNIRT_MODEL_ROOT/`.

System resources required:

- 1 NVIDIA GPU with at least 22 GB of free VRAM (4090 24 GB or A100 40 GB).
- 32 GB of RAM.
- 35 GB of disk for the FlashTalk checkpoints and the wav2vec2 base model.

Lower-VRAM configurations may be achieved by tuning the parameters documented in
[Configuration → FlashTalk rendering parameters](configuration.md#flashtalk-rendering-parameters).

## Scenario: Ascend 910B {#ascend-910b}

For NPU production deployment. Requires CANN 8.0 or later.

### Verify CANN installation

```bash title="terminal"
test -f /usr/local/Ascend/ascend-toolkit/set_env.sh && echo "CANN present"
source /usr/local/Ascend/ascend-toolkit/set_env.sh
npu-smi info
```

### Install OpenTalking

Complete the OpenTalking installation from the common steps first, preferably with
Python 3.11. In China-friendly environments, set these mirrors before installing:

```bash title="terminal"
export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
```

The OmniRT installation requires the NPU-specific PyTorch wheel; the deployment
script handles that part.

### Deploy

```bash title="terminal"
source /usr/local/Ascend/ascend-toolkit/set_env.sh
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/deploy_ascend_910b.sh
```

The script:

1. Sources the CANN environment file.
2. Verifies the sibling `omnirt/` checkout, the OmniRT virtualenv, and the `wav2lip` model directory.
3. Configures the NPU-specific environment variables (`OMNIRT_WAV2LIP_DEVICE=npu`, `OMNIRT_WAV2LIP_FACE_DET_DEVICE=cpu`).
4. Starts OmniRT via `scripts/quickstart/start_omnirt_wav2lip.sh --device npu`.

### Supported models

| Model | Status on Ascend 910B |
|-------|----------------------|
| `mock` | Supported |
| `wav2lip` | Supported via OmniRT `--backend ascend` |
| `flashtalk` | Supported |
| `musetalk` | Not currently ported |

System resources required:

- 1 Ascend 910B card (Atlas 800T or equivalent server).
- CANN 8.0 or later.
- `torch-npu` package, installed by the deployment script.

## Scenario: API and Worker split {#api-and-worker-split}

For production deployments that require horizontal Worker scaling or component
isolation. The architecture and operational characteristics are documented in
[Deployment](../model-deployment/deployment.md#api-and-worker-split).

### Prerequisites

In addition to the common installation:

- Redis 6 or later, reachable from both the API and Worker processes.
- A process manager (systemd, supervisor, Kubernetes Deployment).

### Configure

The relevant environment variables (see [Configuration §3](configuration.md#3-production-deployment)):

```env title=".env"
OPENTALKING_REDIS_URL=redis://<redis-host>:6379/0
OPENTALKING_API_HOST=0.0.0.0
OPENTALKING_API_PORT=8000
OPENTALKING_WORKER_HOST=0.0.0.0
OPENTALKING_WORKER_PORT=9001
OPENTALKING_WORKER_URL=http://<worker-host>:9001
```

### Run

The API and Worker processes are started separately:

```bash title="terminal: API"
uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
```

```bash title="terminal: Worker"
python -m apps.worker.main --host 0.0.0.0 --port 9001
```

Multiple Worker processes may be started across hosts; each Worker subscribes to the
same Redis bus.

## Scenario: production deployment {#production-deployment}

For single-host production deployments using source installation:

1. Install OpenTalking and OmniRT as described in the appropriate hardware scenario.
2. Configure `.env` according to [Configuration → Production deployment](configuration.md#3-production-deployment).
3. Wrap the relevant commands in a process manager. An example systemd unit:

   ```ini title="/etc/systemd/system/opentalking.service"
   [Unit]
   Description=OpenTalking unified server
   After=network.target redis.service
   Requires=redis.service

   [Service]
   Type=simple
   User=opentalking
   WorkingDirectory=/opt/digital_human/opentalking
   EnvironmentFile=/opt/digital_human/opentalking/.env
   ExecStart=/opt/digital_human/opentalking/.venv/bin/opentalking-unified
   Restart=on-failure
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

4. Configure the production checklist items documented in [Deployment → Production checklist](../model-deployment/deployment.md#production-checklist).

## Updates

To update an existing source installation:

```bash title="terminal"
cd "$DIGITAL_HUMAN_HOME/opentalking"
git pull
uv sync --extra dev --python 3.11
source .venv/bin/activate
cd apps/web && npm ci && cd ../..
```

Database schema migrations are applied automatically at process startup.

## Troubleshooting

| Symptom | Resolution |
|---------|------------|
| `ModuleNotFoundError: opentalking` | Activate the virtual environment with `source .venv/bin/activate` or run `uv sync --extra dev --python 3.11`; the fallback is `pip install --index-url https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"`. |
| `ffmpeg: not found` during TTS decoding | Install ffmpeg. macOS: `brew install ffmpeg`. Debian/Ubuntu: `apt install ffmpeg`. |
| `torch.cuda.is_available()` returns False | Verify the NVIDIA driver, CUDA Toolkit, and that the installed `torch` package matches the CUDA version. |
| OmniRT exits with `CUDA out of memory` | Lower `OPENTALKING_FLASHTALK_FRAME_NUM`, `OPENTALKING_FLASHTALK_SAMPLE_STEPS`, or the output resolution. See [Configuration → FlashTalk rendering parameters](configuration.md#flashtalk-rendering-parameters). |
| `npu-smi: command not found` | The CANN toolkit is not on the path. Source `/usr/local/Ascend/ascend-toolkit/set_env.sh`. |
| Port 8000 already in use | Override the bound port via `--api-port` on the start script or `OPENTALKING_API_PORT` in `.env`. |

## Uninstallation

To remove a source installation:

```bash title="terminal"
cd "$DIGITAL_HUMAN_HOME"
rm -rf opentalking omnirt models
# Optional: remove the log and PID directories
rm -rf "$DIGITAL_HUMAN_HOME/logs" "$DIGITAL_HUMAN_HOME/run"
```

The local SQLite database referenced by `OPENTALKING_SQLITE_PATH` is also removed if
it resides under the repository.
