# Quickstart

> 中文 · [English](./quickstart.en.md)

用户视角的最短路径：OpenTalking 负责实时数字人编排，默认使用 `demo-avatar / wav2lip`，不需要下载 FlashTalk 权重，也不需要启动独立模型服务。先跑通 API、TTS、WebRTC 和前端，再按需要升级到 [FlashTalk + OmniRT](./flashtalk-omnirt.md)。

## 0. 先决条件

- Python ≥ 3.9、Node.js ≥ 18、FFmpeg
- 阿里云百炼 API Key：在 [bailian.console.aliyun.com](https://bailian.console.aliyun.com/) 申请，用于 LLM 和 STT
- TTS 默认 Edge TTS，无需 key

## 1. 安装 OpenTalking

```bash
git clone https://github.com/datascale-ai/opentalking.git
cd opentalking

python3 -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"
cp .env.example .env
```

打开 `.env`，确认快速体验默认值保持如下：

```env
OPENTALKING_DEFAULT_MODEL=wav2lip
OPENTALKING_FLASHTALK_MODE=off
```

然后填入百炼密钥：

```env
OPENTALKING_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENTALKING_LLM_API_KEY=sk-your-dashscope-key
OPENTALKING_LLM_MODEL=qwen-flash

DASHSCOPE_API_KEY=sk-your-dashscope-key
OPENTALKING_STT_MODEL=paraformer-realtime-v2

OPENTALKING_TTS_PROVIDER=edge
OPENTALKING_TTS_VOICE=zh-CN-XiaoxiaoNeural
```

## 2. 启动后端 + 前端

```bash
# 后端
cd opentalking
source .venv/bin/activate
bash scripts/start_unified.sh

# 前端（另一个终端）
cd opentalking/apps/web
npm ci
npm run dev -- --host 0.0.0.0
```

浏览器打开 `http://localhost:5173`。默认会使用 `demo-avatar / wav2lip`；在这个模式下 `/models` 不暴露 `flashtalk`，因此不需要 FlashTalk WebSocket。

## 3. 下一步

- 轻量模型适配：查看 [Avatar 格式](./avatar-format.md) 和 [模型适配](./model-adapter.md)，使用 `wav2lip` 或 `musetalk` 验证资产与适配器。
- 高质量部署：复制 `.env.flashtalk.example` 为 `.env`，按 [FlashTalk + OmniRT 部署](./flashtalk-omnirt.md) 启动 FlashTalk-compatible WebSocket。
- 分布式部署、Docker Compose、硬件建议：查看 [部署文档](./deployment.md) 和 [硬件指南](./hardware.md)。
