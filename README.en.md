<h1 align="center">OpenTalking</h1>

<p align="center">
  <b>Open-source real-time digital-human pipeline: LLM, TTS, WebRTC, character voices, and pluggable model backends</b>
</p>

<p align="center">
  <a href="./README.md">中文</a> ·
  <a href="https://datascale-ai.github.io/opentalking/en/">📖 Documentation</a> ·
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
  <a href="#quickstart">Quickstart</a> ·
  <a href="#choose-a-deployment-path">Deployment</a> ·
  <a href="#supported-models">Models</a> ·
  <a href="#progress-and-roadmap">Roadmap</a> ·
  <a href="#architecture-and-project-layout">Architecture</a> ·
  <a href="#documentation-and-community">Docs & Community</a> ·
  <a href="#acknowledgements">Acknowledgements</a>
</p>

---

## Overview

OpenTalking is an open-source real-time digital-human conversation orchestration framework. It provides the core pipeline needed by a **digital-human conversational product**: frontend interaction, session state, LLM replies, TTS and voice selection, interruption control, subtitle events, WebRTC audio/video playback, and calls into local or remote model services.

OpenTalking focuses on **digital-human pipeline orchestration**, so you can build different levels of digital-human experiences quickly:

- **Fast trial**: `mock / driverless mode`, suitable for validating the API, TTS, and WebRTC pipeline for the first time. It does not run video inference.
- **Lightweight single-machine deployment**: consumer-GPU friendly, with quick access to `Wav2Lip/MuseTalk/QuickTalk` style rendering.
- **High-quality deployment**: connect `FlashTalk` and other high-quality models through OmniRT for multi-GPU, distributed, or private inference.

More documentation:

- Documentation site: <https://datascale-ai.github.io/opentalking/en/>
- Chinese docs: <https://datascale-ai.github.io/opentalking/>

## WebUI And Demos

OpenTalking provides a Web service interface for managing the digital-human conversation pipeline. You can select or create avatars, configure voices, LLM, TTS, STT, and avatar driver models, inspect model connection status, and validate real-time dialogue, subtitles, and audio/video playback on the same page.

![OpenTalking WebUI](docs/assets/images/WebUI.png)

### Demo Videos

The following demos show three frontend workflows in OpenTalking: real-time conversation, video creation, and video clone.

<table width="100%" cellpadding="0" cellspacing="0">
  <tr>
    <th align="center" colspan="3">A. Real-Time Conversation</th>
  </tr>
  <tr>
    <td align="center" valign="top" width="33%">
      <b>E-commerce Livestream</b><br/>
      <video src="https://github.com/user-attachments/assets/4646f29d-f773-4f95-84a9-8128ea97ac14" controls preload="metadata" width="248" height="441"></video><br/>
    </td>
    <td align="center" valign="top" width="33%">
      <b>Companion Case</b><br/>
      <video src="https://github.com/user-attachments/assets/6e80d2ac-36a0-41bb-8394-26e0c1121cb6" controls preload="metadata" width="248" height="441"></video><br/>
    </td>
    <td align="center" valign="top" width="33%">
      <b>News Anchor</b><br/>
      <video src="https://github.com/user-attachments/assets/ff7ba86b-927a-46f9-91a6-cfed5d332bda" controls preload="metadata" width="248" height="441"></video><br/>
    </td>
  </tr>
</table>

<table width="100%" cellpadding="0" cellspacing="0">
  <tr>
    <th align="center" colspan="3">B. Video Creation</th>
  </tr>
  <tr>
    <td align="center" valign="top" width="33%">
      <b>Audio Drive</b><br/>
      <video src="https://github.com/user-attachments/assets/d2b93d0c-2ee6-409f-84d9-79d109d8592c" controls preload="metadata" width="248" height="140"></video><br/>
    </td>
    <td align="center" valign="top" width="33%">
      <b>Text Drive</b><br/>
      <video src="https://github.com/user-attachments/assets/d1d4df8d-c599-4c6d-b61c-eec361e9556c" controls preload="metadata" width="248" height="140"></video><br/>
    </td>
    <td align="center" valign="top" width="33%">
      <b>Voice Clone Drive</b><br/>
      <video src="https://github.com/user-attachments/assets/87b3efc4-d54a-4d2a-8d70-c37834154518" controls preload="metadata" width="248" height="140"></video><br/>
    </td>
  </tr>
</table>

<table width="100%" cellpadding="0" cellspacing="0">
  <tr>
    <th align="center" colspan="2">C. Video Clone</th>
  </tr>
  <tr>
    <td align="center" valign="top" width="50%">
      <b>Real-Time Camera Mimicry</b><br/>
      <video src="https://github.com/user-attachments/assets/cd8c9e7b-66a6-46c8-b6c8-61632ce1a712" controls preload="metadata" width="386" height="217"></video><br/>
    </td>
    <td align="center" valign="top" width="50%">
      <b>Uploaded Video Mimicry</b><br/>
      <video src="https://github.com/user-attachments/assets/5e8a5ae9-e39e-48ee-8c41-930369edc6b4" controls preload="metadata" width="386" height="217"></video><br/>
    </td>
  </tr>
</table>

## Quickstart

OpenTalking's **orchestration layer** (API / Worker / frontend) and **digital-human synthesis backend** (`mock`, `local`, `direct_ws`, or [OmniRT](https://github.com/datascale-ai/omnirt)) can be deployed independently. If you are new to the project, start with Mock mode to validate the full pipeline, then switch to real rendering models based on your GPU and model requirements.

### 0. Install OpenTalking

```bash
export DIGITAL_HUMAN_HOME=/opt/digital_human
mkdir -p "$DIGITAL_HUMAN_HOME"

cd "$DIGITAL_HUMAN_HOME"
git clone https://github.com/datascale-ai/opentalking.git && cd opentalking

# Optional: use a mirror to speed up Python package downloads.
export UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple

# Install dependencies.
uv sync --extra dev --python 3.11
source .venv/bin/activate
cp .env.example .env
```

Requirements: Python 3.10+ (3.11 recommended), Node.js 18+, and FFmpeg. If `uv` is not available, use the compatibility installation:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --index-url https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
```

Edit `.env` and configure at least LLM / TTS. `edge` TTS does not require an API key:

```env
# LLM configuration (DashScope, DeepSeek, Doubao, or any OpenAI-compatible endpoint)
OPENTALKING_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENTALKING_LLM_API_KEY=sk-your-key
OPENTALKING_LLM_MODEL=qwen-flash

# Speech-to-text when using DashScope STT; local SenseVoice does not need a key
OPENTALKING_STT_DEFAULT_PROVIDER=dashscope
OPENTALKING_STT_DASHSCOPE_MODEL=paraformer-realtime-v2
OPENTALKING_STT_DASHSCOPE_API_KEY=sk-your-key

# Voice synthesis / voice cloning when using DashScope TTS
OPENTALKING_TTS_DASHSCOPE_API_KEY=sk-your-key

# Other TTS options
OPENTALKING_TTS_DEFAULT_PROVIDER=edge
OPENTALKING_TTS_EDGE_VOICE=zh-CN-XiaoxiaoNeural
```

> Note: `edge` TTS does not require a key. LLM, STT, and TTS no longer share fallback keys; if you use the same DashScope key, set it explicitly in each `OPENTALKING_*_API_KEY` variable.

### 1. Fast First Run

Use this path when you do not want to download model weights or deploy an inference backend yet. It validates the frontend, API, LLM, TTS, STT, WebRTC, and browser playback path. The digital-human video uses the built-in Mock static frame, while LLM replies, streaming TTS, subtitle events, and WebRTC delivery remain real.

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/start_unified.sh --mock
```

The default frontend URL is `http://localhost:5173`. To use custom ports:

```bash
bash scripts/start_unified.sh --mock --api-port 8210 --web-port 5280
```

Stop services:

```bash
bash scripts/quickstart/stop_all.sh
```

### 2. Common Startup Options

`scripts/start_unified.sh` is the recommended entrypoint. The older `scripts/quickstart/*` scripts are still available for lower-level model-service debugging.

| Option | Purpose | Example |
| --- | --- | --- |
| `--mock` | Use the built-in Mock backend. No model weights or video inference backend required. | `--mock` |
| `--backend <mock\|local\|omnirt\|direct_ws>` | Select the inference backend for a model. | `--backend local` |
| `--model <name>` | Select the model to run inference with. | `--model quicktalk` |
| `--omnirt <url>` | Connect to an OmniRT inference service URL. | `--omnirt http://127.0.0.1:9000` |
| `--api-port <port>` | OpenTalking backend API port. | `--api-port 8010` |
| `--web-port <port>` | OpenTalking WebUI port. | `--web-port 5180` |
| `--host <host>` | WebUI bind host, optional. | `--host 0.0.0.0` |
| `--env <file>` | Source a custom env file, optional. | `--env scripts/quickstart/env` |

Examples:

```bash
# Beginner 1 path: consumer-GPU single-machine route.
# Weights live under repository-root models/ after following the deployment steps below.
bash scripts/start_unified.sh --backend local --model quicktalk

# Beginner 2 path: single-machine Wav2Lip on consumer GPUs, using OpenTalking's built-in local runtime.
bash scripts/start_unified.sh --backend local --model wav2lip

# Advanced 2 path: OmniRT remote inference route.
# Start OmniRT first, then connect its endpoint.
bash scripts/start_unified.sh --backend omnirt --model flashtalk --omnirt http://<gpu-server>:9000
```

## Choose A Deployment Path

After Mock mode works, choose one path based on your deployment scenario.

| Path | Recommended model | Inference backend | Best for |
| --- | --- | --- | --- |
| Beginner 1: consumer-GPU single-machine deployment | `quicktalk` | No standalone inference service required | Real-time video rendering on a single 3090 / 4090 machine |
| Beginner 2: consumer-GPU single-machine deployment | `wav2lip` | No standalone inference service required | Lightweight lip sync and quick custom-avatar validation |
| Advanced 1: local audio + QuickTalk | `sensevoice` + `local_cosyvoice` + `quicktalk` | Local STT/TTS weights and a CosyVoice service | Private validation with local voice input and local speech synthesis |
| Advanced 2: remote high-quality inference | `flashtalk` | Required | Multi-GPU, remote GPU/NPU, private deployment, and higher visual quality |

To extend the Beginner 1 QuickTalk single-machine path with local STT and TTS, continue with Advanced 1 and see [Local STT/TTS + QuickTalk](docs/en/model-deployment/local-quicktalk-audio.md). The LLM is still configured through an OpenAI-compatible endpoint by default; if you already run a local LLM server, point `OPENTALKING_LLM_BASE_URL` to that service.

### Beginner 1: Consumer-GPU Single-Machine Deployment

Use this path when you want real-time digital-human rendering on a local GPU machine without introducing inference services such as OmniRT at the beginning. We recommend starting with **QuickTalk**. If you are interested in **Wav2Lip**, see [Beginner 2](docs/en/model-deployment/wav2lip-local.md); the two beginner paths are similar.

#### 1. Install Local Model Dependencies

If you only installed `--extra dev` earlier, install the local model dependencies:

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
uv sync --extra dev --extra models --python 3.11
source .venv/bin/activate
```

#### 2. Prepare QuickTalk Weights

Local weights, third-party HuBERT / InsightFace dependencies, and caches are organized under repository-root `models/quicktalk/`. QuickTalk weights and HuBERT dependencies can be downloaded from Hugging Face:

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
mkdir -p models/quicktalk/checkpoints

uv pip install -U "huggingface_hub[cli]"

# Optional: use a mirror when the network is slow.
export HF_ENDPOINT=https://hf-mirror.com

hf download datascale-ai/quicktalk \
  quicktalk.pth \
  repair.npy \
  chinese-hubert-large/config.json \
  chinese-hubert-large/preprocessor_config.json \
  chinese-hubert-large/pytorch_model.bin \
  --local-dir models/quicktalk/checkpoints
```

QuickTalk weights and HuBERT files are included in `datascale-ai/quicktalk`. QuickTalk still needs the InsightFace `buffalo_l` dependency weights prepared separately:

```bash
# Download and unpack InsightFace buffalo_l into the QuickTalk auxiliary directory.
mkdir -p /tmp/opentalking-insightface models/quicktalk/checkpoints/auxiliary/models
curl -L \
  -o /tmp/opentalking-insightface/buffalo_l.zip \
  https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip
unzip -q -o /tmp/opentalking-insightface/buffalo_l.zip \
  -d /tmp/opentalking-insightface
rsync -a /tmp/opentalking-insightface/buffalo_l/ \
  models/quicktalk/checkpoints/auxiliary/models/buffalo_l/
```

If Hugging Face or GitHub access is unstable, use an internal mirror or manually sync offline files. The final directory layout should match the structure below:

```text
models/
  quicktalk/
    checkpoints/
      quicktalk.pth
      repair.npy
      chinese-hubert-large/
        config.json
        preprocessor_config.json
        pytorch_model.bin
      auxiliary/models/buffalo_l/
        det_10g.onnx
        ...
```

Recommended SHA256 checks:

```text
quicktalk.pth: fc8a7ea025c99a471ef00738874be5ecb6b5dfaf88ff6a1255a5d45a05d73001
repair.npy: 9ea50edde851bf3b12aa22d67b6f0db4f2930f3d9b7b3febcbd383e14117bfca
chinese-hubert-large/config.json: 8511d73054ac289ef47a527efdfd6738d2cb60f69f2973fdc9277492d9ff854b
chinese-hubert-large/preprocessor_config.json: 6334d6e0c5f2084c9a99b85ddff243cbc79dbaa4aa790bcddf8c41c496fab6fb
chinese-hubert-large/pytorch_model.bin: 9cf43abec3f0410ad6854afa4d376c69ccb364b48ddddfd25c4c5aa16398eab0
```

Check key files. Missing files will show `No such file or directory`:

```bash
stat models/quicktalk/checkpoints/quicktalk.pth
stat models/quicktalk/checkpoints/repair.npy
stat models/quicktalk/checkpoints/chinese-hubert-large/pytorch_model.bin
stat models/quicktalk/checkpoints/auxiliary/models/buffalo_l/det_10g.onnx
```

For more QuickTalk weight sources, third-party dependency notes, and offline sync details, see [Talking-Head Model Deployment](docs/en/model-deployment/talking-head.md#quicktalk).

#### 3. Start OpenTalking With QuickTalk

```bash
export OPENTALKING_TORCH_DEVICE=cuda:0
export OPENTALKING_QUICKTALK_ASSET_ROOT="$DIGITAL_HUMAN_HOME/opentalking/models/quicktalk"
export OPENTALKING_QUICKTALK_WORKER_CACHE=1

cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/start_unified.sh --backend local --model quicktalk
```

Open `http://localhost:5173`, select the `QuickTalk Local` avatar and the `quicktalk` model. The first startup builds face cache and workers, which may take tens of seconds. Later sessions reuse the cache.

#### 4. Upload Your Own Digital Human Avatar

The WebUI avatar library supports creating custom avatars from local reference images. Open the avatar page, click **Upload local avatar**, enter a name, and upload a frontal face or half-body reference image. The system creates a deletable custom avatar based on the currently selected avatar.

Select `QuickTalk` as the driver model, upload your reference image, name the digital human, then adjust voice settings on the left if needed and start the conversation.

![OpenTalking Custom Avatar Upload](https://github.com/user-attachments/assets/491b84b6-4b5c-4b5c-b886-27ea3cc68320)

#### 5. Consumer-GPU Tuning

If GPU memory is tight or first-frame latency is high, tune these parameters first:

> Restart the service after changing these values.

| Parameter | Recommended default | Purpose |
| --- | --- | --- |
| `OPENTALKING_QUICKTALK_MAX_TEMPLATE_SECONDS` | `1` | Limit template-video preprocessing duration to reduce cold start. |
| `OPENTALKING_QUICKTALK_RESOLUTION` | `256` | Lower values reduce memory and inference pressure. |
| `OPENTALKING_QUICKTALK_HUBERT_DEVICE` | empty or `cuda:1` | Put HuBERT on another GPU when using multiple cards. |
| `OPENTALKING_PREWARM_AVATARS` | `quicktalk-local` | Prewarm avatars when the service starts. |

### Beginner 2: Consumer-GPU Single-Machine Wav2Lip Deployment

Use this path when you want to validate a lighter lip-sync effect on a single consumer GPU and do not want to introduce a standalone inference service at the beginning. OpenTalking includes the `wav2lip` local adapter and runtime, so you only need local model dependencies and Wav2Lip weights.

#### 1. Install Local Model Dependencies

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
uv sync --extra dev --extra models --python 3.11
source .venv/bin/activate
```

#### 2. Prepare Wav2Lip Weights

Place the weights under repository-root `models/wav2lip/`:

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
mkdir -p models/wav2lip

# Install the Hugging Face CLI if it is not already installed.
uv pip install -U "huggingface_hub[cli]"

# Wav2Lip 384 main checkpoint.
hf download Pypa/wav2lip384 \
  wav2lip384.pth \
  --local-dir models/wav2lip

# S3FD face detector checkpoint.
hf download rippertnt/wav2lip \
  s3fd.pth \
  --local-dir models/wav2lip
```

The final layout should look like this:

```text
models/
  wav2lip/
    wav2lip384.pth
    s3fd.pth
```

Check key files:

```bash
stat models/wav2lip/wav2lip384.pth
stat models/wav2lip/s3fd.pth
```

If the server cannot access Hugging Face directly, download the files on a machine with network access first, then sync the same files into `models/wav2lip/` with `rsync` or an offline package.

#### 3. Start OpenTalking With Wav2Lip

```bash
export OPENTALKING_WAV2LIP_MODEL_ROOT="$DIGITAL_HUMAN_HOME/opentalking/models/wav2lip"
export OPENTALKING_WAV2LIP_DEVICE=cuda
export OPENTALKING_WAV2LIP_BATCH_SIZE=16
export OPENTALKING_WAV2LIP_MAX_LONG_EDGE=832
export OPENTALKING_WAV2LIP_FACE_DET_DEVICE=cpu

cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/start_unified.sh --backend local --model wav2lip --api-port 8210 --web-port 5280
```

Open `http://localhost:5280`, select a built-in Wav2Lip avatar such as `singer`, `office-woman`, or `ancient-beauty`, select the `wav2lip` model, and start a conversation. If you omit `--web-port`, the default frontend URL is `http://localhost:5173`. The first load initializes the Wav2Lip checkpoint, S3FD face detector, and avatar cache, which may take tens of seconds.

#### 4. Wav2Lip Single-Machine Tuning

If GPU memory is tight or first-frame latency is high, tune these parameters first:

| Parameter | Recommended default | Purpose |
| --- | --- | --- |
| `OPENTALKING_WAV2LIP_DEVICE` | `cuda` | Select the Wav2Lip runtime device; use `cpu` for debugging. |
| `OPENTALKING_WAV2LIP_BATCH_SIZE` | `16` | Matches the OmniRT CUDA quickstart default; lower it if GPU memory is tight. |
| `OPENTALKING_WAV2LIP_MAX_LONG_EDGE` | `832` | Matches the OmniRT CUDA quickstart default and keeps render latency closer to realtime; set `0` only when prioritizing full source resolution over latency. |
| `OPENTALKING_WAV2LIP_JPEG_QUALITY` | `85` | Output-frame JPEG quality; higher values improve visuals but increase bandwidth. |
| `OPENTALKING_PREWARM_AVATARS` | `singer` | Prewarm Wav2Lip avatars when the service starts. |

### Advanced 1: Local Audio + QuickTalk

Use this path when you want to keep Beginner 1's local QuickTalk video driver and also move STT and TTS to local models for private validation, local voice input, and local speech synthesis. It requires SenseVoiceSmall and Fun-CosyVoice3-0.5B-2512 weights plus a CosyVoice service, so the setup cost is higher than the beginner paths, but Bailian STT/TTS is no longer required.

For the full walkthrough, see [Local STT/TTS + QuickTalk](docs/en/model-deployment/local-quicktalk-audio.md).

### Advanced 2: Remote High-Quality Inference

Use OmniRT when you need higher visual quality, remote GPU/NPU, multi-GPU scheduling, or production isolation. Full OmniRT deployment is documented in [Model Deployment](docs/en/model-deployment/talking-head.md).

After OmniRT is running on a remote GPU machine and exposes an endpoint such as `http://<gpu-server>:9000`, connect OpenTalking to it:

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"

bash scripts/start_unified.sh \
  --backend omnirt \
  --model flashtalk \
  --api-port 8210 \
  --web-port 5280 \
  --omnirt http://<gpu-server>:9000
```

Recommended models for the advanced path:

- **FlashTalk / FlashHead**: high-quality digital-human video generation, recommended through OmniRT on remote GPU/NPU or multi-GPU machines.
- **Wav2Lip / MuseTalk**: if you want OmniRT to manage all lightweight models, they can be connected through the same endpoint.

### Route Summary

| Stage | Recommended model | Startup | Result |
| --- | --- | --- | --- |
| Fast first run | `mock` | `bash scripts/start_unified.sh --mock` | Validate API, LLM, TTS, and WebRTC |
| Beginner 1 | `quicktalk` | `bash scripts/start_unified.sh --backend local --model quicktalk` | Real video rendering on consumer GPUs |
| Beginner 2 | `wav2lip` | `bash scripts/start_unified.sh --backend local --model wav2lip` | Lightweight lip sync and custom-avatar validation |
| Advanced 1 | `sensevoice` + `local_cosyvoice` + `quicktalk` | See [Local STT/TTS + QuickTalk](docs/en/model-deployment/local-quicktalk-audio.md) | Local audio pipeline and private validation |
| Advanced 2 | `flashtalk` | `bash scripts/start_unified.sh --backend omnirt --model flashtalk --omnirt ...` | High quality, multi-GPU, production deployment |

## Supported Models

| Model | Input | Recommended backend | Resource suggestion | Current role |
| --- | --- | --- | --- | --- |
| `mock` | reference image / static frame | `mock` | No GPU required | First run and integration testing |
| `quicktalk` | template video + audio | `local` | CUDA GPU, 3090 / 4090 recommended | Beginner consumer-GPU path |
| `wav2lip` | reference image / frames + audio | `local` / `omnirt` | `>= 8 GB` GPU / NPU memory | Fast lip sync |
| `musetalk` | full frames + audio | `omnirt` / `local` | `>= 12 GB` GPU memory | Lightweight full-frame talking head |
| `soulx-flashtalk-14b` | portrait + audio | `omnirt` | Multi-GPU / NPU | Advanced high-quality generation |
| `soulx-flashhead-1.3b` | portrait + audio | `omnirt` | Multi-GPU / NPU | High-quality real-time head driving |

### Consumer-GPU Reference

The table below contains tested deployment data. More 4090 / 5090 and other GPU data will be added later, including cold-start time, first-response latency, and memory usage.

| Model | Hardware | Input | Output | GPU memory | Throughput |
| --- | --- | --- | --- | --- | --- |
| `quicktalk` | RTX 3090 | template video + audio | 720x900 / 25fps | about 3.8 GiB | about 35 fps |

For more weight downloads, Docker, troubleshooting, and model configuration, see the [model deployment index](docs/en/model-deployment/index.md), [talking-head model deployment](docs/en/model-deployment/talking-head.md), and [deployment guide](docs/en/user-guide/deployment.md).

### Cloud Model API: Atlas Cloud

<p align="center">
  <a href="https://www.atlascloud.ai/?utm_source=github&utm_medium=link&utm_campaign=opentalking">
    <img src="docs/assets/images/atlas-cloud-logo.png" alt="Atlas Cloud" width="200">
  </a>
</p>

> 🎁 **[Atlas Cloud](https://www.atlascloud.ai/?utm_source=github&utm_medium=link&utm_campaign=opentalking)** is a full-modal AI inference platform that gives developers a single API to access video generation, image generation, and LLM APIs — connect once and get unified access to 300+ curated models across all modalities.

OpenTalking's LLM uses the OpenAI-compatible interface, so pointing `OPENTALKING_LLM_BASE_URL` at `https://api.atlascloud.ai/v1` lets you use Atlas-hosted models such as DeepSeek and Qwen directly; see [LLM and STT](docs/en/model-deployment/llm-stt.md). For more budget-friendly API access, see the Atlas Cloud [coding plan](https://www.atlascloud.ai/console/coding-plan).

## Progress And Roadmap

### Coming Soon

- [ ] **More natural real-time conversations**
  Continue improving interruption, low-latency response, audio/video sync, long-session recovery, and runtime-state visibility.

- [ ] **Consumer-GPU multi-model path**
  Improve asset checks, warmup, cache reuse, low-VRAM settings, and more 3090 / 4090 / WSL2 benchmarks for QuickTalk, Wav2Lip, and MuseTalk local, while continuing FasterLivePortrait video-creation and video-clone benchmarks.

- [ ] **Windows / WSL2 one-command deployment**
  Build on the current Windows deployment guide and test records to simplify model downloads, runtime setup, environment checks, and diagnostics.

- [ ] **High-quality private deployment**
  Improve external OmniRT inference services, multi-model endpoints, capacity scheduling, health checks, production monitoring, and GPU / NPU deployment guidance.

- [ ] **More cloud speech and multimodal providers**
  Build on the current OpenAI-compatible, DashScope, and Xiaomi MiMo profiles to add more pluggable STT / TTS / LLM providers, a unified frontend selection experience, and provider-level health checks.

- [ ] **Agent, memory, and platform capabilities**
  Connect OpenClaw or external agents, reuse memory, tool calling, and knowledge-base capabilities, and gradually add multi-session scheduling, observability metrics, security and compliance, authorized voices, and synthetic-content labeling.

### Completed Progress

- **2026-06-05: OpenAI-compatible audio APIs and Xiaomi MiMo profiles**
  Added OpenAI-compatible STT / TTS adapters, Xiaomi MiMo STT / TTS / voice-clone profiles, frontend provider selection and voice lists, provider-level key/base_url validation, and a reorganized `.env.example` with separate LLM / STT / TTS profiles to avoid mixing generic OpenAI-compatible and Xiaomi configuration.

- **2026-06-04: FasterLivePortrait video creation and video clone**
  Added the FasterLivePortrait video-creation parameter panel, video-clone workspace, custom source-asset upload, camera/uploaded-video driving input, and documentation screenshots outside the existing real-time conversation path, reusing the OmniRT + FasterLivePortrait runtime route.

- **2026-05-28: Windows / WSL2 deployment docs and benchmark conventions**
  Added the Windows / WSL2 deployment guide, WSL2 VRAM statistics notes, benchmark metric definitions, test records, and documentation navigation entries.

- **2026-05-26: local STT/TTS + QuickTalk private path**
  Added local SenseVoiceSmall STT, local CosyVoice3 TTS service integration, frontend provider switching, startup key checks, local audio model download helpers, and full deployment docs.

- **2026-05-25: MuseTalk local backend**
  Added the MuseTalk local adapter, asset preparation script, support matrix updates, and startup entrypoint for lightweight full-frame digital-human validation.

- **2026-05-22: unified audio2video runner**
  Unified local adapters and OmniRT through the audio2video client / runner path, reducing session-pipeline branching across QuickTalk, Wav2Lip, MuseTalk, and related models.

- **2026-05-21: avatar asset warmup and caching**
  Improved QuickTalk / Wav2Lip custom-avatar preprocessing, warmup, cache-hit handling, and frontend status display to reduce first-session waiting time.

- **2026-05-13: model backend decoupling**
  Decoupled `mock`, `local`, `direct_ws`, and `omnirt` at the architecture level so different models can choose different deployment backends.

- **2026-04-16: baseline real-time digital-human experience**
  Built the main Web console, LLM conversation, TTS, subtitle events, and WebRTC audio/video playback pipeline.

## Architecture And Project Layout

![OpenTalking Architecture](docs/assets/images/opentalking_architecture_zh.png)

```text
opentalking/
├── opentalking/                  # Orchestration-layer Python package (flat layout)
│   ├── core/                     # Interfaces, types, config, registry
│   ├── providers/                # Capability adapters by domain/provider
│   │   ├── stt/dashscope/        # Speech recognition
│   │   ├── tts/{edge,dashscope_qwen,cosyvoice_ws,...}/   # TTS + voice cloning
│   │   ├── llm/openai_compatible/                        # Large language models
│   │   ├── rtc/aiortc/                                   # WebRTC streaming
│   │   └── synthesis/{flashtalk,flashhead,omnirt,mock}/  # Remote/protocol synthesis providers
│   ├── models/                   # Local adapter code (quicktalk / wav2lip / musetalk, etc.)
│   ├── avatar/                   # Avatar asset management
│   ├── voice/                    # Voice asset management
│   ├── media/                    # Media utilities
│   ├── pipeline/{session,speak,recording}/   # Business orchestration
│   └── runtime/                  # Process glue (task_consumer / bus / timing)
├── models/                       # Local weights, templates, caches, and user assets
├── apps/
│   ├── api/                      # FastAPI service
│   ├── unified/                  # Single-process mode for development
│   ├── web/                      # React frontend
│   └── cli/                      # download_models / doctor / ...
├── configs/                      # YAML config (profiles / inference / synthesis)
├── docker/ + docker-compose.yml  # Containerized deployment
├── scripts/                      # start_unified.sh / quickstart / run_omnirt.sh, etc.
├── tests/                        # Unit / integration tests
└── docs/                         # Documentation
```

## Documentation And Community

- [Quickstart](docs/en/user-guide/quickstart.md)
- [Models](docs/en/model-deployment/index.md) (weights, mirrors, startup, validation)
- [Architecture](docs/en/developer-guide/architecture.md)
- [Configuration](docs/en/user-guide/configuration.md)
- [Deployment](docs/en/user-guide/deployment.md) (Docker Compose and distributed deployment)
- [Model Adapter](docs/en/developer-guide/model-adapter.md)
- [Contributing](CONTRIBUTING.md) (development environment, CLI tools, ruff / mypy / pytest)

Join the QQ group to discuss real-time digital humans, FlashTalk, OmniRT, model deployment, and product scenarios.

<p align="center">
  <img src="docs/assets/images/qq_group_qrcode.png" alt="AI digital human QQ group QR code" width="280">
</p>

<p align="center">
  <b>AI Digital Human QQ Group</b> · Group ID: <code>1103327938</code>
</p>

## Acknowledgements

OpenTalking references and benefits from excellent projects in the real-time digital-human ecosystem:

- [SoulX-FlashTalk](https://github.com/Soul-AILab/SoulX-FlashTalk) and [SoulX-FlashTalk-14B](https://huggingface.co/Soul-AILab/SoulX-FlashTalk-14B)
- [LiveTalking](https://github.com/lipku/LiveTalking)
- [OmniRT](https://github.com/datascale-ai/omnirt)
- [Edge TTS](https://github.com/rany2/edge-tts)
- [aiortc](https://github.com/aiortc/aiortc)
- [Wan Video](https://github.com/Wan-Video)

## License

[Apache License 2.0](LICENSE)
