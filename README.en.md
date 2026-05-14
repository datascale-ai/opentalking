<h1 align="center">OpenTalking</h1>

<p align="center">
  <b>Open-source real-time digital-human pipeline: LLM, TTS, WebRTC, character voices, and pluggable model backends</b>
</p>

<p align="center">
  <a href="./README.md">中文</a> ·
  <a href="https://datascale-ai.github.io/opentalking/">📖 Documentation</a> ·
  <a href="https://github.com/datascale-ai/opentalking">GitHub</a>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License"></a>
  <img src="https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg" alt="Python">
  <img src="https://img.shields.io/badge/React-18-61dafb.svg" alt="React">
  <img src="https://img.shields.io/badge/FastAPI-009688.svg" alt="FastAPI">
  <img src="https://img.shields.io/badge/WebRTC-realtime-orange.svg" alt="WebRTC">
</p>

<p align="center">
  <a href="#capabilities">Capabilities</a> ·
  <a href="#community">Community</a> ·
  <a href="#demo-videos">Demo videos</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#quickstart">Quickstart</a> ·
  <a href="#roadmap">Roadmap</a> ·
  <a href="#documentation">Documentation</a> ·
  <a href="#acknowledgements">Acknowledgements</a>
</p>

---

## Overview

OpenTalking is an open-source real-time digital-human framework. The goal is to wire up everything a **digital-human conversational product** needs: frontend interaction, session state, LLM replies, TTS / voice selection, barge-in control, subtitle events, WebRTC media playback, and calls into external model services.

OpenTalking focuses on the **pipeline orchestration layer** and supports both external API providers and locally deployed models. The default entrypoint is optimized for getting a first working loop quickly, then upgrading model quality as needed:

- **Quick experience**: `mock / no-driver mode`, no standalone model service required, ideal for validating the API, TTS, WebRTC, and frontend.
- **Lightweight adapter validation**: `wav2lip` / `musetalk` can use local, direct single-model WebSocket, or OmniRT backends, useful for validating Avatar asset format, model adapters, and end-to-end orchestration.
- **QuickTalk realtime path**: OmniRT exposes `quicktalk` as an audio2video service for streaming LLM → sentence-level TTS → realtime lip rendering, while asset-local templates and face caches reduce first-turn startup cost.
- **High-quality deployment**: connect `flashtalk` and other high-quality models through OmniRT for GPU / NPU private inference services.

- Stable documentation URL: <https://datascale-ai.github.io/opentalking/>
- Chinese documentation entry: <https://datascale-ai.github.io/opentalking/>

## Capabilities

- **Real-time digital-human dialogue**: LLM reply, streaming TTS, subtitle events, status events, and WebRTC playback all happen in one pipeline.
- **FlashTalk-compatible path**: speaks the FlashTalk WebSocket protocol, with either local or remote inference servers behind it as the high-quality renderer.
- **Lightweight demo path**: the API, TTS, WebRTC, and frontend can be exercised without first downloading the full FlashTalk weights.
- **Basic barge-in**: current speaking turns can already be interrupted; full pipeline cancellation is on the roadmap.
- **OpenAI-compatible LLM**: works with DashScope, Ollama, vLLM, DeepSeek, and any other OpenAI-compatible endpoint.
- **Multiple deployment shapes**: single-process demo, distributed API + Worker mode, and Docker Compose.
- **QuickTalk OmniRT path**: built-in `quicktalk` model registration, Avatar validation, unified `/v1/audio2video/quicktalk` calls, asset-local template caches, and audio/video sync.

## Community

Join our QQ group to discuss real-time digital humans, FlashTalk, OmniRT, model deployment, and product use cases.

<p align="center">
  <img src="docs/assets/images/qq_group_qrcode.png" alt="AI Digital Human QQ group QR code" width="280">
</p>

<p align="center">
  <b>AI Digital Human QQ group</b> · ID: <code>1103327938</code>
</p>

## Digital-human service interface

OpenTalking includes a Web service interface for managing the digital-human dialogue pipeline. You can select or create avatars, configure voices, LLM, TTS, STT, and avatar driver models, check model connection status, and verify realtime dialogue, subtitles, and audio/video playback from one page.

![OpenTalking WebUI](docs/assets/images/WebUI.png)

## Demo videos

These demo videos show how the OpenTalking pipeline behaves across different real-time digital-human scenarios. The landscape clip spans the full width on its own row; portrait clips follow so row height is not dominated by the landscape video (which can make portrait previews look vertically clipped).

<table>
  <tr>
    <td align="center" colspan="3">
      <b>Realtime mobile capture</b><br/>
      <video src="https://github.com/user-attachments/assets/a3abce76-12c0-4b8b-844f-bbc5c3227dc7" controls width="100%"></video><br/>
    </td>
  </tr>
  <tr>
    <td align="center" valign="top" width="33%">
      <b>Anime stand-up</b><br/>
      <video src="https://github.com/user-attachments/assets/b3743604-7f50-40d1-9248-f2df80ea7308" controls width="100%"></video><br/>
    </td>
    <td align="center" valign="top" width="33%">
      <b>E-commerce livestream</b><br/>
      <video src="https://github.com/user-attachments/assets/826c777b-a9d2-49be-a1a0-b295c8a4b498" controls width="100%"></video><br/>
    </td>
    <td align="center" valign="top" width="33%">
      <b>News anchor</b><br/>
      <video src="https://github.com/user-attachments/assets/34a282da-84cb-4134-bc4b-644356ac4f6f" controls width="100%"></video><br/>
    </td>
  </tr>
  <tr>
    <td align="center" valign="top" colspan="3">
      <table>
        <tr>
          <td align="center" valign="top" width="50%">
            <b>Singing / impression</b><br/>
            <video src="https://github.com/user-attachments/assets/98e813c2-f170-4cc8-b934-a77a72061d2e" controls width="100%"></video><br/>
          </td>
          <td align="center" valign="top" width="50%">
            <b>Companion character</b><br/>
            <video src="https://github.com/user-attachments/assets/44bbf1d9-75b1-4b0a-9704-c7f81c39446e" controls width="100%"></video><br/>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>

## Architecture

![OpenTalking Current Code Architecture](docs/assets/images/opentalking_architecture_en.png)

## Project layout

```text
opentalking/
├── opentalking/                  # orchestration Python package (flat layout)
│   ├── core/                     # interfaces, types, config, registry
│   ├── providers/                # capability adapters (capability / vendor)
│   │   ├── stt/dashscope/        # speech-to-text
│   │   ├── tts/{edge,dashscope_qwen,cosyvoice_ws,...}/   # text-to-speech + cloning
│   │   ├── llm/openai_compatible/                        # large language model
│   │   ├── rtc/aiortc/                                   # WebRTC transport
│   │   └── synthesis/{flashtalk,flashhead,omnirt,mock}/  # avatar synthesis (thin client)
│   ├── avatar/                   # avatar asset management
│   ├── voice/                    # voice asset management
│   ├── media/                    # neutral DSP utilities
│   ├── pipeline/{session,speak,recording}/   # business orchestration
│   └── runtime/                  # process glue (task_consumer / bus / timing)
├── apps/
│   ├── api/                      # FastAPI service
│   ├── unified/                  # single-process mode (dev friendly)
│   ├── web/                      # React frontend
│   └── cli/                      # download_models / doctor / ...
├── configs/                      # YAML config (profiles / inference / synthesis)
├── docker/ + docker-compose.yml  # container deployments
├── scripts/                      # helpers (run_omnirt.sh / prepare-avatar.sh)
├── tests/                        # unit / integration tests
└── docs/                         # documentation
```

## Quickstart

OpenTalking's **orchestration layer** (API + Worker + frontend) and the selected **synthesis backend** (`mock`, `local`, `direct_ws`, or [OmniRT](https://github.com/datascale-ai/omnirt)) deploy independently. The three paths below are organised by *what you want to do*. For Docker, see [Deployment](docs/en/user-guide/deployment.md), and for per-model weight downloads and startup commands see [Models](docs/en/model-deployment/index.md).

### Step 0 (shared): install the orchestration layer

```bash
git clone https://github.com/datascale-ai/opentalking.git && cd opentalking
uv sync --extra dev --python 3.11
source .venv/bin/activate
cp .env.example .env
```

Requirements: Python ≥ 3.10 (3.11 recommended), Node.js ≥ 18, FFmpeg.

If `uv` is not available in your environment, use the compatibility fallback instead:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install --index-url https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
```

Notes:

- The lockfile is validated with Python 3.11.
- When PyAV resolves to a prebuilt wheel, only runtime `ffmpeg` is required.
- If you intentionally move to an unvalidated Python or PyAV combination and trigger a source build, you will also need `ffmpeg 7`, `pkg-config`, and a C compiler.

> Run `opentalking-doctor` any time to see what's missing.

### Path 1: Quick experience (recommended for first-run)

**Goal**: validate the frontend, API, LLM, TTS, STT, WebRTC, and browser path without downloading model weights or starting OmniRT.
**How**: synthesis goes through the built-in Mock; LLM / STT / TTS use the providers configured in `.env`.

Configure at least LLM / STT / TTS in `.env`:

```env
# LLM: DashScope / Bailian / any OpenAI-compatible endpoint
OPENTALKING_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENTALKING_LLM_API_KEY=sk-your-key
OPENTALKING_LLM_MODEL=qwen-flash

# Voice synthesis / voice cloning when using DashScope-backed providers
DASHSCOPE_API_KEY=sk-your-key

# Other TTS options
OPENTALKING_TTS_PROVIDER=edge
OPENTALKING_TTS_VOICE=zh-CN-XiaoxiaoNeural
```

Start the mock quickstart helper:

```bash
bash scripts/quickstart/start_mock.sh
```

To use custom ports, pass them directly to the helper:

```bash
bash scripts/quickstart/start_mock.sh --api-port 8010 --web-port 5180
```

The default frontend URL is `http://localhost:5173`; with the custom-port example above, open `http://localhost:5180`. Replace localhost with your server IP for remote deployment. Pick a built-in avatar. Frames are static (reference image)—**LLM reply, streaming TTS, subtitle events, and WebRTC delivery are real**; only lip-sync is faked.

Stop the helper-managed services with:

```bash
bash scripts/quickstart/stop_all.sh
```

Without port arguments, `stop_all.sh` stops all OpenTalking API / frontend instances managed by the quickstart scripts. You can also pass ports to stop only a specific instance:

```bash
bash scripts/quickstart/stop_all.sh --api-port 8010 --web-port 5180
```

### Path 2: Lightweight adapter validation

Goal: validate Avatar assets, model adapters, and real lip-sync / talking-head rendering. Lightweight models can run behind a local adapter, a direct single-model WebSocket, or the current OmniRT compatibility path.

First install OmniRT in the sibling checkout and prepare the model directory:

```bash
export DIGITAL_HUMAN_HOME=/opt/digital_human
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"

mkdir -p "$DIGITAL_HUMAN_HOME"
cd "$DIGITAL_HUMAN_HOME"
git clone https://github.com/datascale-ai/omnirt.git
cd omnirt
uv sync --extra server --python 3.11
source .venv/bin/activate
uv pip install -U "huggingface_hub[cli]"
```

#### 1. Download model weights

Some models require accepting a license or requesting access on Hugging Face first. If a download returns `401`, `403`, or `Repository not found`, open the model page, confirm access, and run `hf auth login`.

Download only the models you plan to run:

- Choose **Wav2Lip** for the fastest real digital-human smoke test.
- Choose **MuseTalk** to validate a full-frame talking-head path.
- Choose **FlashTalk** for higher quality if hardware resources are sufficient.
- Download multiple models only if you need to test model switching.

If Hugging Face is slow or unstable, you can enable a mirror first:

```bash
export HF_ENDPOINT=https://hf-mirror.com
hf auth login
```

Download Wav2Lip:

```bash
mkdir -p "$OMNIRT_MODEL_ROOT/wav2lip"
hf download Pypa/wav2lip384 \
  wav2lip384.pth \
  --local-dir "$OMNIRT_MODEL_ROOT/wav2lip"
hf download rippertnt/wav2lip \
  s3fd.pth \
  --local-dir "$OMNIRT_MODEL_ROOT/wav2lip"
```

Check the Wav2Lip files:

```bash
test -f "$OMNIRT_MODEL_ROOT/wav2lip/wav2lip384.pth"
test -f "$OMNIRT_MODEL_ROOT/wav2lip/s3fd.pth"
```

Download MuseTalk:

MuseTalk runtime code is managed by OmniRT through `runtime install musetalk`; OpenTalking does not need an extra MuseTalk repo setting. You only need to place the weights under `$OMNIRT_MODEL_ROOT` using the MuseTalk v1.5 layout:

```text
$OMNIRT_MODEL_ROOT/
  musetalk/
    pytorch_model.bin
    musetalk.json
  sd-vae-ft-mse/
    config.json
    diffusion_pytorch_model.bin
  whisper/
    tiny.pt
  dwpose/
    dw-ll_ucoco_384.pth
  face-parse-bisenet/
    79999_iter.pth
```

Check the MuseTalk files:

```bash
test -f "$OMNIRT_MODEL_ROOT/musetalk/pytorch_model.bin"
test -f "$OMNIRT_MODEL_ROOT/musetalk/musetalk.json"
test -f "$OMNIRT_MODEL_ROOT/sd-vae-ft-mse/config.json"
test -f "$OMNIRT_MODEL_ROOT/sd-vae-ft-mse/diffusion_pytorch_model.bin"
test -f "$OMNIRT_MODEL_ROOT/whisper/tiny.pt"
test -f "$OMNIRT_MODEL_ROOT/dwpose/dw-ll_ucoco_384.pth"
test -f "$OMNIRT_MODEL_ROOT/face-parse-bisenet/79999_iter.pth"
```

Notes:

- The official MuseTalk README / `download_weights.sh` also mentions `syncnet/latentsync_syncnet.pt`.
- The current OpenTalking + OmniRT MuseTalk path only uses the weights required for realtime inference: UNet, VAE, Whisper, DWPose, and face-parse.
- In the upstream repo, `syncnet` is mainly used for training, evaluation, or lip-sync scoring. It is not required by the current online `musetalk_ws_server.py` inference path.
- If you later need to train MuseTalk, reproduce upstream experiments, or add an offline SyncNet scoring flow, download `syncnet` separately.
- `whisper/tiny.pt` must be the official OpenAI `openai-whisper` checkpoint. Do not substitute it by renaming Hugging Face `pytorch_model.bin`.

For more complete weight layout and troubleshooting details, see:

- `omnirt/model_backends/musetalk/README.md`
- `omnirt/docs/user_guide/serving/musetalk_ws.md`

Download FlashTalk (optional):

```bash
hf download Soul-AILab/SoulX-FlashTalk-14B \
  --local-dir "$OMNIRT_MODEL_ROOT/SoulX-FlashTalk-14B"

hf download TencentGameMate/chinese-wav2vec2-base \
  --local-dir "$OMNIRT_MODEL_ROOT/chinese-wav2vec2-base"
```

SoulX-FlashTalk inference code is not a model weight. In the recommended Ascend 910B path, OmniRT runtime install prepares the code, applies patches, and records runtime state. You only need to point to your own SoulX checkout when using a custom fork or a manual CUDA path.

Model pages:

- Wav2Lip 384: https://huggingface.co/Pypa/wav2lip384
- Wav2Lip S3FD: https://huggingface.co/rippertnt/wav2lip
- MuseTalk code: https://github.com/TMElyralab/MuseTalk
- SoulX FlashTalk code: https://github.com/Soul-AILab/SoulX-FlashTalk
- SoulX FlashTalk 14B: https://huggingface.co/Soul-AILab/SoulX-FlashTalk-14B
- Chinese wav2vec2: https://huggingface.co/TencentGameMate/chinese-wav2vec2-base

#### 2. Start Wav2Lip on OmniRT

CUDA GPU:

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_omnirt_wav2lip.sh --device cuda
```

Ascend 910B NPU:

Source the CANN environment before starting the NPU service:

```bash
source /usr/local/Ascend/ascend-toolkit/set_env.sh
```

> If your CANN path differs, replace it with the actual `set_env.sh` path.

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_omnirt_wav2lip.sh --device npu
```

Verify:

```bash
curl http://127.0.0.1:9000/v1/audio2video/models
```

`wav2lip` should report `connected: true`.

This helper sets the following defaults:

- `OMNIRT_WAV2LIP_CPU_THREADS=4`
- `OMNIRT_WAV2LIP_PRELOAD=1`
- `OMNIRT_WAV2LIP_MAX_LONG_EDGE=832`
- CUDA batch size defaults to `16`
- Ascend NPU batch size defaults to `8`

Once dependencies are installed, you can add `--skip-install` on repeated starts. If your OmniRT checkout does not yet define the `wav2lip-cuda` extra, the helper falls back to `model_backends/wav2lip/requirements-wav2lip.txt`; updating OmniRT to the latest `main` is also recommended.

#### 3. Start MuseTalk on OmniRT

MuseTalk follows the same orchestration pattern as Wav2Lip and FlashTalk: inference and serving both run on OmniRT, and OpenTalking only connects through the unified `audio2video` interface. Unlike Wav2Lip's single-layer `serve-avatar-ws`, the MuseTalk helper starts a WebSocket backend first and then an OmniRT gateway.

CUDA GPU:

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_omnirt_musetalk.sh --device cuda
```

If port `9000` or the default GPU is already in use, change the port or GPU index directly. For example:

```bash
export CUDA_VISIBLE_DEVICES=4
bash scripts/quickstart/start_omnirt_musetalk.sh \
  --device cuda \
  --port 9001 \
  --musetalk-port 8766
```

Ascend 910B NPU:

Source the CANN environment before starting the NPU service:

```bash
source /usr/local/Ascend/ascend-toolkit/set_env.sh
```

> If your CANN path differs, replace it with the actual `set_env.sh` path.

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_omnirt_musetalk.sh --device npu
```

Verify:

```bash
curl http://127.0.0.1:9000/v1/audio2video/models
```

`musetalk` should report `connected: true`.

This helper does two things:

- Starts the MuseTalk WS backend, default `127.0.0.1:8766`
- Starts the OmniRT gateway, default `0.0.0.0:9000`

Once dependencies are installed, you can add `--skip-install` on repeated starts.

#### 4. Start FlashTalk on OmniRT (optional)

FlashTalk is heavier than Wav2Lip. It is better to validate Wav2Lip first, then start FlashTalk.

CUDA GPU:

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_omnirt_flashtalk.sh --device cuda --nproc 1
```

Ascend 910B NPU:

Source the CANN environment before starting the NPU service:

```bash
source /usr/local/Ascend/ascend-toolkit/set_env.sh
```

> If your CANN path differs, replace it with the actual `set_env.sh` path.

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_omnirt_flashtalk.sh --device npu --nproc 8
```

Verify:

```bash
curl http://127.0.0.1:9000/v1/audio2video/models
```

`flashtalk` should report `connected: true`.

#### 5. Start OpenTalking in real-model mode and connect OmniRT

Keep the OmniRT service from step 2, 3, or 4 running, then start the OpenTalking API and frontend:

```bash
export DIGITAL_HUMAN_HOME=/opt/digital_human

cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_all.sh --omnirt http://127.0.0.1:9000
```

For custom ports:

```bash
bash scripts/quickstart/start_all.sh \
  --omnirt http://127.0.0.1:9000 \
  --api-port 8010 \
  --web-port 5180
```

If OmniRT runs on a remote GPU / NPU machine, change `--omnirt` to `http://<gpu-or-npu-server-ip>:9000`:

```bash
bash scripts/quickstart/start_all.sh \
  --omnirt http://<gpu-or-npu-server-ip>:9000 \
  --api-port 8010 \
  --web-port 5180
```

The default frontend is `http://localhost:5173`; if you use `--web-port 5180`, open `http://localhost:5180`.

Choose `wav2lip`, `musetalk`, `quicktalk`, or `flashtalk`. Real-model cards should show **Connected**; `mock / driverless mode` shows **No connection required**.

QuickTalk uses the same OmniRT endpoint and is routed by `/v1/audio2video/quicktalk`.
For weights, dependency layout, CUDA startup, and performance data, see
[Models → Talking-Head Models](docs/en/model-deployment/talking-head.md#quicktalk).

For helper-managed services, use the same custom port arguments when checking status. Without port arguments, `stop_all.sh` stops all OpenTalking API / frontend instances managed by the quickstart scripts; pass ports to stop only a specific instance:

```bash
bash scripts/quickstart/status.sh --api-port 8010 --web-port 5180
bash scripts/quickstart/stop_all.sh --api-port 8010 --web-port 5180
```

Avatar asset format: see [Avatar Format](docs/en/user-guide/avatar-format.md).

### Path 3: High-quality deployment

**Goal**: run FlashTalk 14B / FlashHead-class high-quality models for private deployments / production.
**How**: same `OMNIRT_ENDPOINT` as Path 2, plus multi-process / Redis / GPU orchestration:

```env
OMNIRT_ENDPOINT=http://<gpu-host>:9000
OMNIRT_API_KEY=sk-omnirt-xxx           # if your OmniRT enforces auth
OPENTALKING_DEFAULT_MODEL=flashtalk     # or flashhead

OPENTALKING_TORCH_DEVICE=cuda           # for orchestration-layer audio PCM acceleration
OPENTALKING_REDIS_URL=redis://redis:6379/0    # multi-process needs a real Redis
```

Multi-process startup (recommended for production):

```bash
opentalking-api &
opentalking-worker &
# Build the frontend separately and serve via nginx
cd apps/web && npm ci && npm run build
```

Avatar manifest, inference endpoint mapping, and hardware profiles: see
[Configuration](docs/en/user-guide/configuration.md) and
[Models](docs/en/model-deployment/index.md).

For Ascend 910B, use the host CANN environment and the thin deployment wrapper:

```bash
source /usr/local/Ascend/ascend-toolkit/set_env.sh
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/deploy_ascend_910b.sh
```

### Three paths at a glance

| Path | Inference backend | GPU | Best for |
| --- | --- | --- | --- |
| 1. Quick experience | Built-in Mock | not required | First-run, frontend dev, pipeline validation |
| 2. Lightweight validation | Local / direct WS / OmniRT | entry-level GPU | Model / Avatar adapter development |
| QuickTalk realtime | OmniRT QuickTalk | CUDA GPU | Realtime digital-human demos |
| 3. High-quality deployment | OmniRT + FlashTalk / FlashHead | 4090 / 910B | Private, production-quality deployment |

### Supported models

| Model | Input | OpenTalking integration | Recommended path |
| --- | --- | --- | --- |
| `mock` | reference image | Built-in static frames | Path 1 |
| `wav2lip` | frames + audio | Pluggable lightweight lip-sync backend | Path 2 |
| `musetalk` | full frames + audio | Pluggable lightweight talking-head backend | Path 2 |
| `quicktalk` | template video + audio | OmniRT `/v1/audio2video/quicktalk` | QuickTalk realtime |
| `soulx-flashtalk-14b` | portrait + audio | OmniRT high-quality FlashTalk | Path 3 |
| `soulx-flashhead-1.3b` | portrait + audio | direct FlashHead WebSocket | Path 3 |


## Roadmap

- [x] **Real-time digital-human baseline**
  Web console, LLM dialogue, TTS, subtitle events, WebRTC media playback.

- [ ] **More natural realtime dialogue (in progress)**
  Barge-in, session state, low-latency response, audio-video sync, error recovery.

- [x] **OmniRT model service integration**
  OmniRT backend for heavyweight, multi-card, and remote inference while lightweight models can remain local or direct-WS.

- [x] **Consumer-grade GPU support**
  Lightweight models, single-card realtime configs, end-to-end benchmarks for RTX 3090 / 4090.

- [ ] **High-quality private deployment (in progress)**
  Enterprise private deployment with pluggable synthesis backends, OmniRT capacity scheduling for heavyweight models, health checks, production monitoring; Ascend 910B and similar enterprise GPU / NPU paths in progress.

- [x] **Custom characters and voices**
  Character config, built-in voice selection, reference audio upload, natural-language voice description, and OmniRT-driven voice synthesis.

- [ ] **Agent and memory capabilities**
  Integration with OpenClaw or external agents to reuse their memory, tool use, and knowledge-base capabilities.

- [ ] **Production-grade platform**
  Multi-session scheduling, observability, security and compliance, licensed voices, synthetic-content provenance.

## Documentation

- [Quickstart](docs/en/user-guide/quickstart.md)
- [Models](docs/en/model-deployment/index.md) (weights, domestic mirrors, startup, verification)
- [Architecture](docs/en/developer-guide/architecture.md)
- [Configuration](docs/en/user-guide/configuration.md)
- [Deployment](docs/en/user-guide/deployment.md) (Docker Compose, distributed deployment)
- [Model adapters](docs/en/developer-guide/model-adapter.md)
- [Contributing](CONTRIBUTING.md) (dev environment, CLI tools, ruff / mypy / pytest)

## Acknowledgements

OpenTalking draws inspiration from and benefits from outstanding projects in the real-time digital-human ecosystem:

- [SoulX-FlashTalk](https://github.com/Soul-AILab/SoulX-FlashTalk) and [SoulX-FlashTalk-14B](https://huggingface.co/Soul-AILab/SoulX-FlashTalk-14B)
- [LiveTalking](https://github.com/lipku/LiveTalking)
- [OmniRT](https://github.com/datascale-ai/omnirt)
- [Edge TTS](https://github.com/rany2/edge-tts)
- [aiortc](https://github.com/aiortc/aiortc)
- [Wan Video](https://github.com/Wan-Video)

## License

[Apache License 2.0](LICENSE)
