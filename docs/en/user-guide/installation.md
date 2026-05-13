# Installation

OpenTalking ships two installation methods. Selecting the appropriate method is a
function of two questions: where the work happens (development, single-machine
production, multi-machine production) and what hardware is available (CPU only,
NVIDIA GPU, or Ascend NPU).

This page presents the decision matrix and links to the detailed instructions. For a
streamlined first-run procedure, see the [Quickstart](quickstart.md).

## Choosing an installation method

| Use case | Hardware | Recommended method | Detailed guide |
|----------|----------|-------------------|----------------|
| Local development, frontend changes, API iteration | Any | Source install + mock synthesis | [From source](install-from-source.md#development-cpu-mock-synthesis) |
| CPU evaluation | CPU | Source install + mock synthesis | [From source](install-from-source.md#development-cpu-mock-synthesis) |
| Evaluation on a single GPU machine | NVIDIA 3090 / 4090 / A100 (CUDA 12) | Source install + model-specific backend | [From source → single GPU](install-from-source.md#scenario-single-gpu-with-wav2lip) |
| Evaluation on Ascend NPU | Huawei 910B (CANN 8.0+) | Source install on the host CANN environment | [From source → Ascend 910B](install-from-source.md#ascend-910b) |
| Continuous integration | CPU | Source install or Docker Compose, depending on reproducibility needs | [From source](install-from-source.md#development-cpu-mock-synthesis) or [Docker Compose → CPU profile](install-with-docker.md#cpu-profile) |
| Production single-host deployment | Linux + GPU or NPU | Source install or Docker, depending on operations preference | [From source → Production](install-from-source.md#production-deployment) or [Docker Compose](install-with-docker.md) |
| Production multi-host deployment with horizontal Worker scaling | Linux + GPU or NPU | Source install, API/Worker split, external Redis | [From source → API and Worker split](install-from-source.md#api-and-worker-split) and [Deployment](deployment.md) |

## Platform support matrix

| Platform | Synthesis backends | Notes |
|----------|-------------------|-------|
| macOS (Apple Silicon and Intel) | `mock` | Suitable for orchestration and frontend development. Real talking-head models are not supported on macOS. |
| Linux x86_64 + CUDA 12 | `mock`, `wav2lip`, `musetalk`, `flashtalk`, `flashhead`, `quicktalk` | Primary deployment target. |
| Linux aarch64 + Ascend 910B (CANN 8.0+) | `mock`, `wav2lip`, `flashtalk` | NPU production deployment path. |
| Windows | `mock` (WSL2 recommended) | Not part of the continuous integration matrix. |

## Common prerequisites

Independent of the installation method, the following components are required:

- A DashScope (Bailian) API key for the default language model (`qwen-flash`) and speech recognition (`paraformer-realtime-v2`). Other OpenAI-compatible endpoints may be used; see [Configuration §1](configuration.md#1-language-model-speech-recognition-and-text-to-speech).
- WebRTC-compatible client. The bundled frontend has been tested against Chromium-based browsers. Safari requires additional CORS configuration.

Source-installation additional requirements:

- Python 3.9 or later (3.11 recommended).
- Node.js 18 or later for the frontend toolchain.
- ffmpeg for the text-to-speech decoding stage.
- Optionally Redis 6 or later for the API/Worker split deployment.

Docker Compose is a deployment packaging option, not the lightest evaluation path.
Use it when repeatable images, containerized service boundaries, or production-like
operations are more important than first-run simplicity.

Docker-installation additional requirements:

- Docker Engine 20.10 or later and the Compose v2 plugin.
- NVIDIA Container Toolkit when running the GPU profile.

## Verification

Regardless of the installation method, the orchestrator can be verified with the
following requests once it is running:

```bash title="terminal"
curl -s http://127.0.0.1:8000/health
# {"status":"ok"}

curl -s http://127.0.0.1:8000/models | jq
# Lists available synthesis backends.
```

## Next steps

- [From source](install-from-source.md) — install from a git checkout. Covers development, production, and Ascend variants.
- [Docker Compose](install-with-docker.md) — install with the packaged Docker stack for reproducible deployments.
- [Configuration](configuration.md) — required environment configuration after installation.
- [Deployment](deployment.md) — selecting a runtime topology.
