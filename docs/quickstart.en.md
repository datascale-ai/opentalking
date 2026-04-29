# Quickstart

> [中文](./quickstart.md) · English

Shortest path from a fresh checkout to a working real-time digital human: OpenTalking handles orchestration (LLM / STT / TTS all go through Bailian APIs); the FlashTalk video-generation model is served by [OmniRT](https://github.com/datascale-ai/omnirt) as a FlashTalk-compatible WebSocket. The whole pipeline only requires **one** locally deployed model service (FlashTalk WebSocket).

## 0. Prerequisites

- Python ≥ 3.9, Node.js ≥ 18, FFmpeg
- Alibaba Cloud Bailian API key — apply at [bailian.console.aliyun.com](https://bailian.console.aliyun.com/), used as the unified credential (`DASHSCOPE_API_KEY`) for LLM / STT / TTS
- A reference portrait (PNG / JPG) and a reference audio clip (WAV, 16 kHz)
- Model weights: `SoulX-FlashTalk-14B`, `chinese-wav2vec2-base` — download instructions in the [OmniRT docs](https://github.com/datascale-ai/omnirt)
- Ascend 910B deployment requires the CANN toolkit; CUDA deployment requires a matching PyTorch build

For convenience, set the following shell variables once with your real paths so the later commands are copy-paste friendly:

```bash
export OPENTALKING_HOME=/path/to/opentalking
export OMNIRT_HOME=/path/to/omnirt
export SOULX_FLASHTALK_REPO=/path/to/SoulX-FlashTalk   # SoulX-FlashTalk source tree containing flashtalk_server.py
export FLASHTALK_VENV=/path/to/flashtalk-venv          # standalone virtualenv that runs FlashTalk
```

## 1. OpenTalking orchestration environment

```bash
cd "$OPENTALKING_HOME"
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Open `.env` and fill in `DASHSCOPE_API_KEY` (or expose it as an OS environment variable). FlashTalk already points at `ws://127.0.0.1:8765`, no edits needed:

```env
OPENTALKING_FLASHTALK_MODE=remote
OPENTALKING_FLASHTALK_WS_URL=ws://127.0.0.1:8765
DASHSCOPE_API_KEY=sk-your-dashscope-key
```

## 2. FlashTalk inference environment (separate venv)

FlashTalk needs a dedicated venv (do not reuse OpenTalking's `.venv`). Inside it you'll install `torch` / `torch_npu` matching your machine's CANN release, the SoulX-FlashTalk dependencies (`diffusers` / `transformers` / `librosa` / `websockets` / `pyyaml`, etc.), and the SoulX-FlashTalk model weights.

> `python3 -m venv "$FLASHTALK_VENV"` only creates an empty Python environment — it does **not** read `pyproject.toml` and install anything; you have to run `pip install` afterwards. OmniRT's `start_flashtalk_ws.sh` only launches the service, it doesn't install FlashTalk dependencies for you.

The exact `torch` / `torch_npu` combination (aligned with your CANN release), SoulX-FlashTalk dependency installation, `import torch_npu / websockets` smoke-test commands, location of the CANN `set_env.sh` script, and model-weight download instructions all live in OmniRT's docs:

- GitHub source: [omnirt/docs/user_guide/serving/flashtalk_ws.en.md](https://github.com/datascale-ai/omnirt/blob/main/docs/user_guide/serving/flashtalk_ws.en.md)
- Docs site: <https://datascale-ai.github.io/omnirt/en/>

Once `flashtalk-venv` is ready per OmniRT's docs, return here for the next step.

## 3. Launch the FlashTalk WebSocket via OmniRT

```bash
cd "$OMNIRT_HOME"

OMNIRT_FLASHTALK_REPO_PATH="$SOULX_FLASHTALK_REPO" \
OMNIRT_FLASHTALK_CKPT_DIR=models/SoulX-FlashTalk-14B \
OMNIRT_FLASHTALK_WAV2VEC_DIR=models/chinese-wav2vec2-base \
OMNIRT_FLASHTALK_HOST=0.0.0.0 \
OMNIRT_FLASHTALK_PORT=8765 \
OMNIRT_FLASHTALK_NPROC_PER_NODE=8 \
OMNIRT_FLASHTALK_ENV_SCRIPT=/usr/local/Ascend/ascend-toolkit/set_env.sh \
OMNIRT_FLASHTALK_VENV_ACTIVATE="$FLASHTALK_VENV/bin/activate" \
OMNIRT_FLASHTALK_PYTHON="$FLASHTALK_VENV/bin/python" \
OMNIRT_FLASHTALK_TORCHRUN="$FLASHTALK_VENV/bin/torchrun" \
bash scripts/start_flashtalk_ws.sh
```

`start_flashtalk_ws.sh` first sources the CANN env script and the FlashTalk venv, then uses `torchrun` to launch the FlashTalk-compatible WebSocket. Run `bash scripts/start_flashtalk_ws.sh --help` for the full list of variables; background launch (nohup + pid file), quantization, warmup, and troubleshooting are all in the OmniRT FlashTalk WS doc linked above.

> **CUDA users**: drop `OMNIRT_FLASHTALK_ENV_SCRIPT` and replace `FLASHTALK_VENV` with a CUDA-matched torch installation.

## 4. Verify the WebSocket is up

```bash
python - <<'PY'
import asyncio
from websockets.asyncio.client import connect

async def main():
    async with connect("ws://127.0.0.1:8765", open_timeout=5, close_timeout=2):
        print("connected")

asyncio.run(main())
PY
```

## 5. Start OpenTalking backend + frontend

```bash
# backend
cd "$OPENTALKING_HOME"
source .venv/bin/activate
bash scripts/start_unified.sh

# frontend (separate terminal)
cd "$OPENTALKING_HOME/apps/web"
npm ci
npm run dev -- --host 0.0.0.0
```

Open `http://localhost:5173` in your browser.
