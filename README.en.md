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

- **Quick experience**: `demo-avatar / wav2lip`, no standalone model service required, ideal for validating the API, TTS, WebRTC, and frontend.
- **Lightweight adapter validation**: `wav2lip / musetalk`, useful for Avatar assets, model adapters, and end-to-end orchestration checks.
- **QuickTalk realtime path**: the local `quicktalk` adapter supports streaming LLM → sentence-level TTS → realtime lip rendering, with Worker caching to reduce first-turn startup cost.
- **High-quality deployment**: FlashTalk-compatible WebSocket via [OmniRT](https://github.com/datascale-ai/omnirt), targeting consumer GPUs and enterprise private inference services.

## Capabilities

- **Real-time digital-human dialogue**: LLM reply, streaming TTS, subtitle events, status events, and WebRTC playback all happen in one pipeline.
- **QuickTalk adapter**: built-in `quicktalk` model registration, Avatar validation, realtime render queue, audio-video sync, and benchmark CLI.
- **FlashTalk-compatible path**: speaks the FlashTalk WebSocket protocol, with either local or remote inference servers behind it as the high-quality renderer.
- **Lightweight demo path**: the API, TTS, WebRTC, and frontend can be exercised without first downloading the full FlashTalk weights.
- **Basic barge-in**: current speaking turns can already be interrupted; full pipeline cancellation is on the roadmap.
- **OpenAI-compatible LLM**: works with DashScope, Ollama, vLLM, DeepSeek, and any other OpenAI-compatible endpoint.
- **Multiple deployment shapes**: single-process demo, distributed API + Worker mode, and Docker Compose.

## Community

Join our QQ group to discuss real-time digital humans, FlashTalk, OmniRT, model deployment, and product use cases.

<p align="center">
  <img src="images/qq_group_qrcode.png" alt="AI Digital Human QQ group QR code" width="280">
</p>

<p align="center">
  <b>AI Digital Human QQ group</b> · ID: <code>1103327938</code>
</p>

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

![OpenTalking Architecture](images/opentalking_architecture.png)

## Project layout

```text
opentalking/
├── src/opentalking/
│   ├── core/         # config, interface protocols, type definitions
│   ├── engine/       # FlashTalk-compatible local inference path
│   ├── server/       # distributed WebSocket inference service
│   ├── models/       # avatar model adapters
│   ├── worker/       # session orchestration
│   ├── llm/          # OpenAI-compatible LLM client
│   ├── tts/          # TTS adapters
│   ├── rtc/          # WebRTC transport
│   ├── voices/       # voice profiles and provider integration
│   └── events/       # SSE and runtime events
├── apps/
│   ├── api/          # FastAPI service
│   ├── unified/      # single-process mode
│   ├── web/          # React frontend
│   └── cli/          # model download, video generation, demo tools
├── configs/          # YAML config samples
├── docker/           # Docker Compose
├── scripts/          # startup and deployment scripts
├── tests/            # unit / integration tests
└── docs/             # documentation
```

## Quickstart

The default quickstart uses `demo-avatar / wav2lip` with `OPENTALKING_FLASHTALK_MODE=off`, so you do not need to download FlashTalk weights or start OmniRT first. LLM / STT can use Alibaba Cloud Bailian APIs, and TTS defaults to Edge TTS with no key required. Full notes live in [docs/quickstart.en.md](docs/quickstart.en.md).

### 1. Set up the OpenTalking orchestration layer

```bash
git clone https://github.com/datascale-ai/opentalking.git
cd opentalking

python3 -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"
cp .env.example .env
```

Apply for a Bailian API key at [bailian.console.aliyun.com](https://bailian.console.aliyun.com/), then fill it into `.env`; other fields can stay at their defaults:

```env
# Quick experience: disable FlashTalk and use demo-avatar / wav2lip
OPENTALKING_DEFAULT_MODEL=wav2lip
OPENTALKING_FLASHTALK_MODE=off

# LLM: Bailian OpenAI-compatible endpoint
OPENTALKING_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENTALKING_LLM_API_KEY=sk-your-dashscope-key
OPENTALKING_LLM_MODEL=qwen-flash

# STT: Bailian Paraformer realtime
DASHSCOPE_API_KEY=sk-your-dashscope-key
OPENTALKING_STT_MODEL=paraformer-realtime-v2

# TTS: Edge TTS by default, no key needed
OPENTALKING_TTS_PROVIDER=edge
OPENTALKING_TTS_VOICE=zh-CN-XiaoxiaoNeural

# Optional: switch to Bailian Qwen realtime TTS (reuses DASHSCOPE_API_KEY above)
# OPENTALKING_TTS_PROVIDER=dashscope
# OPENTALKING_QWEN_TTS_MODEL=qwen3-tts-flash-realtime
```

### 2. Start OpenTalking and the frontend

Open two terminals:

```bash
# Terminal 1: backend
cd opentalking
source .venv/bin/activate
bash scripts/start_unified.sh

# Terminal 2: frontend
cd opentalking/apps/web
npm ci
npm run dev -- --host 0.0.0.0
```

Open `http://localhost:5173`.

Requirements: Python ≥ 3.9, Node.js ≥ 18, FFmpeg; distributed mode also requires Redis.

### Three usage paths

| Path | Recommended for | Config | Notes |
| --- | --- | --- | --- |
| Quick experience | First run, general users | `.env.example`, `OPENTALKING_FLASHTALK_MODE=off`, `OPENTALKING_DEFAULT_MODEL=wav2lip` | No standalone model service; defaults to `demo-avatar / wav2lip` |
| Lightweight adapter validation | Model / Avatar adapter development | `wav2lip` or `musetalk` | MuseTalk is currently best treated as adapter validation and prepared-asset experience |
| QuickTalk realtime path | Local realtime digital-human demos, LLM dialogue | `OPENTALKING_DEFAULT_MODEL=quicktalk`, Avatar `model_type=quicktalk` | Avatar manifests need `metadata.asset_root` and `metadata.template_video`; use `opentalking-quicktalk-bench` for local benchmarks |
| High-quality deployment | Private deployment, production validation, high-quality digital humans | `.env.flashtalk.example`, FlashTalk + OmniRT | See [FlashTalk + OmniRT deployment](docs/flashtalk-omnirt.en.md) |

### Supported models

| Model | Input | OpenTalking integration |
| --- | --- | --- |
| `wav2lip` (default quickstart) | frames + audio | Lightweight lip-sync demo / fallback; no standalone model service required |
| `musetalk` | full frames + audio | Lightweight talking-head adapter validation |
| `quicktalk` | template video + audio | Local realtime talking-head adapter with Worker caching, streaming rendering, and the `/chat` dialogue pipeline |
| `soulx-flashtalk-14b` | portrait + audio | OmniRT FlashTalk WebSocket; enable with `.env.flashtalk.example` |
| `soulx-flashhead-1.3b` | portrait + audio | OmniRT currently exposes only HTTP `/v1/generate`; OpenTalking WebSocket adapter is planned |
| `soulx-liveact-14b` | portrait + audio | same as above |


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
