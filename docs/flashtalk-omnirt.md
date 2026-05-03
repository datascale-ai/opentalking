# FlashTalk + OmniRT 部署

> 中文 · [English](./flashtalk-omnirt.en.md)

这条路径面向高质量数字人效果、私有化部署和企业 GPU / NPU 推理服务。第一次体验 OpenTalking 时，建议先按 [快速开始](./quickstart.md) 使用 `demo-avatar / wav2lip` 跑通链路。

## 0. 先决条件

- Python ≥ 3.9、Node.js ≥ 18、FFmpeg
- 阿里云百炼 API Key：在 [bailian.console.aliyun.com](https://bailian.console.aliyun.com/) 申请，作为 LLM / STT / TTS 的统一密钥（`DASHSCOPE_API_KEY`）
- 一张参考头像（PNG / JPG）和一段参考音频（WAV，16 kHz）
- 模型权重：`SoulX-FlashTalk-14B`、`chinese-wav2vec2-base`（下载方式见 [OmniRT 文档](https://github.com/datascale-ai/omnirt)）
- 910B / Ascend 部署需要 CANN toolkit；CUDA 部署需要对应版本的 PyTorch

为方便后续步骤复制粘贴，先在 shell 里按本机实际路径设置以下变量：

```bash
export OPENTALKING_HOME=/path/to/opentalking
export OMNIRT_HOME=/path/to/omnirt
export SOULX_FLASHTALK_REPO=/path/to/SoulX-FlashTalk   # 包含 flashtalk_server.py 的 SoulX-FlashTalk 源码目录
export FLASHTALK_VENV=/path/to/flashtalk-venv          # 运行 FlashTalk 的独立虚拟环境
```

## 1. OpenTalking 编排环境

```bash
cd "$OPENTALKING_HOME"
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.flashtalk.example .env
```

打开 `.env`，把 `DASHSCOPE_API_KEY` 填上即可（也可以改用 OS 环境变量）；FlashTalk 默认指向本机 `ws://127.0.0.1:8765`，无需改动：

```env
OPENTALKING_DEFAULT_MODEL=flashtalk
OPENTALKING_FLASHTALK_MODE=remote
OPENTALKING_FLASHTALK_WS_URL=ws://127.0.0.1:8765
DASHSCOPE_API_KEY=sk-your-dashscope-key
```

## 2. FlashTalk 推理环境（独立 venv）

FlashTalk 需要一个独立 venv（不要复用 OpenTalking 的 `.venv`），里面装与机器 CANN 版本对齐的 `torch` / `torch_npu`、SoulX-FlashTalk 自身的依赖（`diffusers` / `transformers` / `librosa` / `websockets` / `pyyaml` 等），以及 SoulX-FlashTalk 模型权重。

> `python3 -m venv "$FLASHTALK_VENV"` 只创建一个空的 Python 环境，**不会**自动读 `pyproject.toml` 安装依赖；后续的 `pip install` 是必须的。OmniRT 仓库的 `start_flashtalk_ws.sh` 也只负责启动，不会替你装 FlashTalk 依赖。

具体的 torch / torch_npu 版本搭配（与机器 CANN 对齐）、SoulX-FlashTalk 依赖安装步骤、`import torch_npu / websockets` 自检命令、CANN 环境脚本 `set_env.sh` 的位置、模型权重下载方式，都直接参考 OmniRT 文档：

- GitHub 原文：[omnirt/docs/user_guide/serving/flashtalk_ws.md](https://github.com/datascale-ai/omnirt/blob/main/docs/user_guide/serving/flashtalk_ws.md)
- 文档站点：<https://datascale-ai.github.io/omnirt/>

按 OmniRT 文档把 `flashtalk-venv` 准备好后，回到下一步即可。

## 3. 用 OmniRT 启动 FlashTalk WebSocket

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

`start_flashtalk_ws.sh` 会先 source CANN 环境脚本与 FlashTalk venv，再用 torchrun 拉起 FlashTalk-compatible WebSocket。所有可用变量见 `bash scripts/start_flashtalk_ws.sh --help`；后台启动（nohup + pid 文件）、量化参数、warmup、常见错误排查都在上面提到的 OmniRT FlashTalk WS 文档里。

> **CUDA 用户**：去掉 `OMNIRT_FLASHTALK_ENV_SCRIPT`，把 `FLASHTALK_VENV` 换成 CUDA 对应的 torch 安装即可。

## 4. 验证 WebSocket 已就绪

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

## 5. 启动 OpenTalking 后端 + 前端

```bash
# 后端
cd "$OPENTALKING_HOME"
source .venv/bin/activate
bash scripts/start_unified.sh

# 前端（另一个终端）
cd "$OPENTALKING_HOME/apps/web"
npm ci
npm run dev -- --host 0.0.0.0
```

浏览器打开 `http://localhost:5173` 即可。
