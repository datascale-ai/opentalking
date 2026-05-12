<h1 align="center">OpenTalking</h1>

<p align="center">
  <b>Open-source real-time digital-human pipeline: LLM, TTS, WebRTC, character voices, and external OmniRT model services</b>
</p>

<p align="center">
  <a href="./README.md">中文</a> ·
  <a href="https://github.com/datascale-ai/opentalking">GitHub</a>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License"></a>
  <img src="https://img.shields.io/badge/Python-3.9%2B-brightgreen.svg" alt="Python">
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
  <a href="#acknowledgements">Acknowledgements</a>
</p>

---

## Overview

OpenTalking is an open-source real-time digital-human framework. The goal is to wire up everything a **digital-human conversational product** needs: frontend interaction, session state, LLM replies, TTS / voice selection, barge-in control, subtitle events, WebRTC media playback, and calls into external model services.

OpenTalking focuses on the **pipeline orchestration layer** and supports both external API providers and locally deployed models. The default entrypoint is optimized for getting a first working loop quickly, then upgrading model quality as needed:

- **Quick experience**: `mock / no-driver mode`, no standalone model service required, ideal for validating the API, TTS, WebRTC, and frontend.
- **Lightweight adapter validation**: start `wav2lip` through [OmniRT](https://github.com/datascale-ai/omnirt), useful for validating Avatar asset format, model adapters, and end-to-end orchestration.
- **QuickTalk realtime path**: the local `quicktalk` adapter supports streaming LLM → sentence-level TTS → realtime lip rendering, with Worker caching to reduce first-turn startup cost.
- **High-quality deployment**: connect `flashtalk` and other high-quality models through OmniRT for GPU / NPU private inference services.

## Capabilities

- **Real-time digital-human dialogue**: LLM reply, streaming TTS, subtitle events, status events, and WebRTC playback all happen in one pipeline.
- **FlashTalk-compatible path**: speaks the FlashTalk WebSocket protocol, with either local or remote inference servers behind it as the high-quality renderer.
- **Lightweight demo path**: the API, TTS, WebRTC, and frontend can be exercised without first downloading the full FlashTalk weights.
- **Basic barge-in**: current speaking turns can already be interrupted; full pipeline cancellation is on the roadmap.
- **OpenAI-compatible LLM**: works with DashScope, Ollama, vLLM, DeepSeek, and any other OpenAI-compatible endpoint.
- **Multiple deployment shapes**: single-process demo, distributed API + Worker mode, and Docker Compose.
- **QuickTalk adapter**: built-in `quicktalk` model registration, Avatar validation, realtime render queue, audio-video sync, and benchmark CLI.

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

![OpenTalking Architecture](docs/assets/images/opentalking_architecture.png)

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

OpenTalking's **orchestration layer** (API + Worker + frontend) and the **inference service** ([OmniRT](https://github.com/datascale-ai/omnirt)) deploy independently—they can run on the same host or on different hosts. The three paths below are organised by *what you want to do*. For Docker, see [docs/deployment.md](docs/deployment.en.md).

### Step 0 (shared): install the orchestration layer

```bash
git clone https://github.com/datascale-ai/opentalking.git && cd opentalking
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Requirements: Python ≥ 3.10, Node.js ≥ 18, FFmpeg.

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

**Goal**: iterate on Avatar assets, validate model adapters, run real wav2lip / musetalk / flashtalk models.
**How**: run an [OmniRT](https://github.com/datascale-ai/omnirt) inference service locally or remotely; OpenTalking routes every audio2video model through one `OMNIRT_ENDPOINT`.

For a quick real-model smoke test, start Wav2Lip OmniRT first:

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_omnirt_wav2lip.sh --device cuda
```

If OmniRT is on a remote GPU / NPU host, expose its `9000` port and use that host in `--omnirt`.

OpenTalking derives each audio2video WebSocket route from the OmniRT endpoint. For example, `--omnirt http://omnirt:9000` + `model=wav2lip` becomes `ws://omnirt:9000/v1/audio2video/wav2lip`; `flashtalk`, `musetalk`, and `wav2lip` share this rule.

Start OpenTalking and point it at OmniRT:

```bash
bash scripts/quickstart/start_all.sh --omnirt http://127.0.0.1:9000
```

For custom OpenTalking ports:

```bash
bash scripts/quickstart/start_all.sh \
  --omnirt http://127.0.0.1:9000 \
  --api-port 8010 \
  --web-port 5180
```

If OmniRT runs on a remote machine:

```bash
bash scripts/quickstart/start_all.sh \
  --omnirt http://<gpu-or-npu-server-ip>:9000 \
  --api-port 8010 \
  --web-port 5180
```

The default API models endpoint is `http://127.0.0.1:8000/models`; with `--api-port 8010`, use port `8010`. The default frontend is `http://localhost:5173`; with `--web-port 5180`, use port `5180`.

For helper-managed services, use the same custom port arguments when checking status. Without port arguments, `stop_all.sh` stops all OpenTalking API / frontend instances managed by the quickstart scripts; pass ports to stop only a specific instance:

```bash
bash scripts/quickstart/status.sh --api-port 8010 --web-port 5180
bash scripts/quickstart/stop_all.sh --api-port 8010 --web-port 5180
```

Avatar asset format: see [docs/avatar-format.md](docs/avatar-format.md).

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

Avatar manifest, inference endpoint mapping, hardware profiles: see [docs/configuration.md](docs/configuration.md) and [docs/hardware.md](docs/hardware.md).

### Three paths at a glance

| Path | Inference backend | GPU | Best for |
| --- | --- | --- | --- |
| 1. Quick experience | Built-in Mock | not required | First-run, frontend dev, pipeline validation |
| 2. Lightweight adapter validation | Local OmniRT + lightweight model | entry-level GPU (3060+) | Model / Avatar adapter development |
| QuickTalk realtime path | Local QuickTalk adapter | CUDA GPU | Local realtime digital-human demos and LLM dialogue |
| 3. High-quality deployment | OmniRT + FlashTalk/FlashHead | 4090 / 910B | Private deployment, production, high-quality |

### Supported models

| Model | Input | OpenTalking integration | Recommended path |
| --- | --- | --- | --- |
| `mock` | reference image | Built-in static frames | Path 1 |
| `wav2lip` | frames + audio | OmniRT lightweight lip-sync | Path 2 |
| `musetalk` | full frames + audio | OmniRT lightweight talking-head | Path 2 |
| `quicktalk` | template video + audio | Local realtime talking-head adapter with Worker caching and `/chat` | QuickTalk realtime path |
| `soulx-flashtalk-14b` | portrait + audio | OmniRT high-quality FlashTalk | Path 3 |
| `soulx-flashhead-1.3b` | portrait + audio | direct FlashHead WebSocket | Path 3 |


## Roadmap

- [x] **Real-time digital-human baseline**  
  Web console, LLM dialogue, TTS, subtitle events, WebRTC media playback.

- [ ] **More natural realtime dialogue(in progress)**  
  Barge-in, session state, low-latency response, audio-video sync, error recovery.

- [ ] **OmniRT model service integration**  
  Unified access via OmniRT for FlashTalk, lightweight talking-head, ASR, speech synthesis, and voice services.

- [ ] **Consumer-grade GPU support**  
  Lightweight models, single-card realtime configs, end-to-end benchmarks for RTX 3090 / 4090.

- [ ] **High-quality private deployment(in progress)**  
  Enterprise private deployment with external OmniRT inference, capacity scheduling, health checks, production monitoring; Ascend 910B and similar enterprise GPU / NPU paths in progress.

- [ ] **Custom characters and voices**  
  Character config, built-in voice selection, reference audio upload, natural-language voice description, and OmniRT-driven voice synthesis.

- [ ] **Agent and memory capabilities**  
  Integration with OpenClaw or external agents to reuse their memory, tool use, and knowledge-base capabilities.

- [ ] **Production-grade platform**  
  Multi-session scheduling, observability, security and compliance, licensed voices, synthetic-content provenance.

## Documentation

- [Quickstart](docs/quickstart.en.md)
- [FlashTalk + OmniRT deployment](docs/flashtalk-omnirt.en.md)
- [Architecture](docs/architecture.md)
- [Configuration](docs/configuration.md)
- [Deployment](docs/deployment.md) (Docker Compose, distributed deployment)
- [Hardware guide](docs/hardware.md)
- [Model adapters](docs/model-adapter.md)
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
