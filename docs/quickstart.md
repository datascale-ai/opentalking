# 快速开始

这份 quickstart 优先覆盖仓库当前最容易跑通的路径: `统一模式 + demo avatars + Edge TTS`。

## 1. 准备环境

需要:

- Python 3.9+
- Node.js 18+
- FFmpeg

建议安装:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev,models]"
```

可选依赖:

- FlashTalk 本地推理: `pip install -e ".[engine]"`
- XTTS: `pip install -e ".[voiceclone]"`
- CosyVoice: `pip install -e ".[cosyvoice]"`

## 2. 复制配置

```bash
cp .env.example .env
```

如果你只是先跑通链路，建议显式切到 Edge:

```bash
export OPENTALKING_TTS_PROVIDER=edge
```

原因是 `configs/default.yaml` 当前默认 provider 是 `xtts`。

## 3. 启动统一模式后端

```bash
bash scripts/start_unified.sh
```

默认地址:

```text
http://127.0.0.1:8010
```

## 4. 启动前端

```bash
cd apps/web
npm ci
VITE_API_PROXY_TARGET=http://127.0.0.1:8010 npm run dev
```

打开:

```text
http://127.0.0.1:5175
```

## 5. 开始体验

页面会读取:

- `GET /avatars`
- `GET /tts/voices`

建议先选这些样例头像:

- `demo-musetalk-gesture-fullbody-v2`
- `demo-musetalk`
- `demo-wav2lip`

前端默认会选 Edge 声线，不依赖本地参考音频。

## 可选: 启用 FlashTalk

### 远端模式

```bash
cp .env.remote.example .env
bash scripts/start_server.sh
bash scripts/start_unified.sh
```

### 本地模式

```bash
cp .env.local.example .env
bash scripts/start_unified.sh
```

## 可选: 下载 FlashTalk 权重

```bash
python -m apps.cli.download_models
```

或:

```bash
bash scripts/download_models.sh
```

## 常见问题

### 页面打开了，但开始会话失败

先检查:

- 后端是不是跑在 `8010`
- 前端代理是不是指向 `http://127.0.0.1:8010`
- `FFmpeg` 是否可执行

### 直接调 API 时 XTTS 报错

如果你没有安装 XTTS 依赖，调用 `/sessions` 时请显式传:

```json
{"tts_provider":"edge","tts_voice":"zh-CN-XiaoxiaoNeural"}
```

### 想跑分布式 API + Worker

请看 [local-dev.md](local-dev.md) 和 [deployment.md](deployment.md)。
