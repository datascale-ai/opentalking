# 本地开发

## 推荐路径: 统一模式

这是当前仓库最顺手的联调方式，因为它同时具备:

- REST
- SSE
- WebRTC
- `/tts/voices`
- 内存版 broker

### 1. 启动后端

```bash
pip install -e ".[dev,models]"
export OPENTALKING_TTS_PROVIDER=edge
bash scripts/start_unified.sh
```

脚本默认监听 `8010`。

### 2. 启动前端

```bash
cd apps/web
npm ci
VITE_API_PROXY_TARGET=http://127.0.0.1:8010 npm run dev
```

前端地址:

```text
http://127.0.0.1:5175
```

### 3. 打开页面

选择一个 demo avatar，点击开始后前端会按下面顺序调用:

1. `POST /sessions`
2. `POST /sessions/{id}/webrtc/offer`
3. `POST /sessions/{id}/start`
4. `GET /sessions/{id}/events`

## 分布式本地联调

### 1. 启动 Redis

```bash
docker run --rm -p 6379:6379 redis:7-alpine
```

### 2. 启动 API

```bash
export OPENTALKING_REDIS_URL=redis://127.0.0.1:6379/0
export OPENTALKING_WORKER_URL=http://127.0.0.1:9001
opentalking-api
```

### 3. 启动 Worker

```bash
export OPENTALKING_REDIS_URL=redis://127.0.0.1:6379/0
export OPENTALKING_AVATARS_DIR=./examples/avatars
export OPENTALKING_TORCH_DEVICE=cpu
opentalking-worker
```

### 4. 选择前端接入方式

当前有两个现实选择:

- 继续使用统一模式对接仓库内 React 前端
- 或自己调用分布式 API，因为 `apps/api.main` 目前没有挂 `/tts/voices`

如果你坚持用仓库前端直连分布式 API，至少还需要补上 `/tts/voices` 路由。

## FlashTalk 本地或远端联调

### 远端模式

```bash
cp .env.remote.example .env
bash scripts/start_server.sh
```

然后再启动统一模式或分布式 API/Worker。

### 本地模式

```bash
cp .env.local.example .env
```

本地模式会由 worker 直接创建 `FlashTalkLocalClient`。

## 调试建议

### 导出播报产物

```bash
export OPENTALKING_DEBUG_DUMP_SPEECH_DIR=./debug
```

### 强制使用 Edge，绕开 XTTS

```bash
export OPENTALKING_TTS_PROVIDER=edge
```

这对刚开始联调很有帮助，因为 `configs/default.yaml` 里的默认 provider 是 `xtts`。
