# 部署

## 部署模式

### 1. 统一模式

适合:

- 本地开发
- 单机演示
- 先跑通 WebRTC / SSE / 前端交互

启动命令:

```bash
bash scripts/start_unified.sh
```

默认端口:

- 后端: `8010`
- 前端开发服务器: `5175`

### 2. 分布式模式

适合:

- API / Worker 拆分
- Redis 队列驱动
- FlashTalk GPU 机器和业务机器分离

最小拓扑:

```text
browser -> api:8000 -> redis:6379 -> worker:9001 -> flashtalk:8765
```

### 3. FlashTalk 仅推理服务

适合:

- 已有外部编排层
- 只想部署 14B 推理 WebSocket 服务

## Docker Compose

### 全栈分布式

```bash
docker compose -f docker/docker-compose.yml up --build
```

默认端口:

- `8080`: Nginx 托管的前端
- `8000`: API
- `9001`: Worker
- `8765`: FlashTalk
- `6379`: Redis

注意:

- 这个 compose 更偏 FlashTalk 分布式链路
- `apps/api.main` 当前没有挂 `/tts/voices`
- `Dockerfile.api` / `Dockerfile.worker` 只安装了基础依赖，没有安装 `.[models]`、`.[voiceclone]`、`.[cosyvoice]`

如果你想在容器里跑 `wav2lip` / `musetalk` / XTTS / CosyVoice，需要自己扩充镜像依赖。

### 统一模式 + FlashTalk 服务

```bash
docker compose -f docker/docker-compose.unified.yml up --build
```

说明:

- 这里的 `unified` 容器运行 `opentalking-unified`
- 同时也会启动一个 `flashtalk` 容器
- 适合想保留统一模式 API 体验，但把 FlashTalk 推理放到独立容器里

### 只启动 FlashTalk

```bash
docker compose -f docker/docker-compose.flashtalk.yml up --build
```

## 手动部署

### 分布式 API + Worker

```bash
# 终端 1
opentalking-api

# 终端 2
opentalking-worker
```

需要提前准备:

- Redis
- `OPENTALKING_REDIS_URL`
- `OPENTALKING_WORKER_URL`
- `OPENTALKING_AVATARS_DIR`

### FlashTalk 远端服务

```bash
bash scripts/start_server.sh
```

等价于:

```bash
torchrun --nproc_per_node=8 -m opentalking.server \
  --host 0.0.0.0 \
  --port 8765 \
  --ckpt_dir ./models/SoulX-FlashTalk-14B \
  --wav2vec_dir ./models/chinese-wav2vec2-base
```

## 昇腾 910B

仓库提供了部署脚本:

```bash
bash scripts/deploy_ascend_910b.sh
```

使用前建议先阅读脚本本身，并根据机器环境确认:

- 驱动与 CANN 版本
- `torch-npu` 版本
- FlashTalk 权重与依赖是否齐全

## 生产化建议

- API / Worker / FlashTalk 分开部署
- Redis 独立实例
- 前端走反向代理，统一 CORS 与 `/api` 前缀
- 为 `GET /healthz` 和 Worker `/healthz` 配置探活
- 把 `voice/`、`models/`、`examples/avatars/` 挂成持久卷
