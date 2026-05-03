# Quickstart

> [中文](./quickstart.md) · English

Shortest path from a fresh checkout to a working real-time digital-human loop: OpenTalking handles orchestration and defaults to `demo-avatar / wav2lip`, so you do not need to download FlashTalk weights or start a standalone model service. First validate the API, TTS, WebRTC, and frontend; then upgrade to [FlashTalk + OmniRT](./flashtalk-omnirt.en.md) when you need higher-quality rendering.

## 0. Prerequisites

- Python ≥ 3.9, Node.js ≥ 18, FFmpeg
- Alibaba Cloud Bailian API key — apply at [bailian.console.aliyun.com](https://bailian.console.aliyun.com/), used for LLM and STT
- TTS defaults to Edge TTS and requires no key

## 1. Install OpenTalking

```bash
git clone https://github.com/datascale-ai/opentalking.git
cd opentalking

python3 -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"
cp .env.example .env
```

Open `.env` and keep the quick-experience defaults:

```env
OPENTALKING_DEFAULT_MODEL=wav2lip
OPENTALKING_FLASHTALK_MODE=off
```

Then fill in your Bailian key:

```env
OPENTALKING_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENTALKING_LLM_API_KEY=sk-your-dashscope-key
OPENTALKING_LLM_MODEL=qwen-flash

DASHSCOPE_API_KEY=sk-your-dashscope-key
OPENTALKING_STT_MODEL=paraformer-realtime-v2

OPENTALKING_TTS_PROVIDER=edge
OPENTALKING_TTS_VOICE=zh-CN-XiaoxiaoNeural
```

## 2. Start backend + frontend

```bash
# backend
cd opentalking
source .venv/bin/activate
bash scripts/start_unified.sh

# frontend (separate terminal)
cd opentalking/apps/web
npm ci
npm run dev -- --host 0.0.0.0
```

Open `http://localhost:5173` in your browser. The default path uses `demo-avatar / wav2lip`; in this mode `/models` does not expose `flashtalk`, so no FlashTalk WebSocket is required.

## 3. Next steps

- Lightweight adapter work: see [Avatar format](./avatar-format.md) and [Model adapters](./model-adapter.md), then use `wav2lip` or `musetalk` to validate assets and adapters.
- High-quality deployment: copy `.env.flashtalk.example` to `.env`, then follow [FlashTalk + OmniRT deployment](./flashtalk-omnirt.en.md) to start the FlashTalk-compatible WebSocket.
- Distributed deployment, Docker Compose, and hardware notes: see [Deployment](./deployment.md) and [Hardware guide](./hardware.md).
