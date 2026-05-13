# 使用 Docker Compose 安装

Docker Compose 安装方式为 OpenTalking 提供打包后的部署栈，更适合可复现部署和贴近
生产的验证。若只是 CPU 快速评估、单 GPU 评估或昇腾 NPU 首次拉起，优先使用
[源码安装](install-from-source.md)，这样驱动、CANN、CUDA、权重路径和模型日志都直接
暴露在宿主机上，排错更轻。

打包栈运行特征如下：

- 编排服务（API、Worker、前端、Redis）由 `docker/` 下的 Dockerfile 构建。
- 推理运行时（OmniRT）由 `ghcr.io/datascale-ai/omnirt` 拉取，按 Compose profile 启用。
- 部署场景通过 Compose profile 切换，而非不同的 Compose 文件路径。

需要源码级访问的开发场景请参见 [源码安装](install-from-source.md)。Ascend NPU 部署
当前仅支持源码安装方式。

## Compose 结构

仓库包含两份 Compose 文件：

| 文件 | 用途 |
|------|------|
| `docker-compose.yml` | 基础文件。无条件定义 `redis`、`api`、`worker`、`web` 服务。在 `gpu` profile 下定义 `omnirt`。 |
| `docker-compose.gpu.yml` | `gpu` profile 启用时叠加的 override。将 `api` 与 `worker` 接到 OmniRT，并关闭 mock 合成。 |

由本地 Dockerfile 构建的容器：

| 容器 | Dockerfile | 用途 |
|------|-----------|------|
| `api` | `docker/Dockerfile.api` | FastAPI 服务，端口 8000。 |
| `worker` | `docker/Dockerfile.worker` | 异步流水线执行器。 |
| `web` | `docker/Dockerfile.web` | Vite 构建后的前端，由 nginx 代理，端口 5173。 |

`docker/Dockerfile.flashtalk` 与 `docker/Dockerfile.flashtalk.ascend` 用于历史的
裸金属 FlashTalk 部署，**不**由默认 Compose 栈调用。

## 前置条件

- Docker Engine 20.10 或更新版本，含 Compose v2 插件（`docker compose ...`）。
- 约 8 GB 磁盘空间用于镜像与构建产物。
- GPU profile 须安装 NVIDIA Container Toolkit。`docker info | grep -i runtimes` 输出
  须包含 `nvidia`。
- 可访问 `ghcr.io`（或已配置的镜像加速）以拉取 OmniRT 镜像。

## CPU profile {#cpu-profile}

适用于笔记本、持续集成与前端开发。该 profile 仅 `mock` 合成后端可用，**无法**
运行真实 talking-head 模型。

### 初始配置

```bash title="终端"
git clone https://github.com/datascale-ai/opentalking.git
cd opentalking
cp .env.example .env
```

编辑 `.env` 并配置必填的语言模型与语音识别 Key：

```env title=".env"
OPENTALKING_LLM_API_KEY=<dashscope-api-key>
DASHSCOPE_API_KEY=<dashscope-api-key>
```

Compose 栈通过 `docker-compose.yml` 中的 `env_file` 指令自动读取 `.env`。

### 启动

```bash title="终端"
docker compose up -d
```

启动的服务：

| 服务 | 地址 | 备注 |
|------|------|------|
| `redis` | 内部访问 | `api` 与 `worker` 启动前会做健康检查。 |
| `api` | `http://localhost:8000` | FastAPI 服务。 |
| `worker` | 内部访问 | 通过 Redis 与 `api` 通信。 |
| `web` | `http://localhost:5173` | 前端。 |

默认 profile 将 `OPENTALKING_INFERENCE_MOCK` 设为 `1`，`api` 与 `worker` 容器将所有
合成请求路由至进程内 mock。`omnirt` 服务**不**启动。

### 验证

```bash title="终端"
docker compose ps
docker compose logs -f api
curl -s http://localhost:8000/health
```

### 停止

```bash title="终端"
docker compose down
```

同时移除 Redis 卷：

```bash title="终端"
docker compose down -v
```

## GPU profile {#gpu-profile}

适用于单机带 NVIDIA GPU 的部署。在编排服务之外，额外拉取并启动 OmniRT。

### 初始配置

与 CPU profile 一致：克隆仓库、复制 `.env.example`、配置语言模型与语音识别 Key。

### 启动

```bash title="终端"
docker compose --profile gpu \
  -f docker-compose.yml -f docker-compose.gpu.yml \
  up -d
```

Compose 在 CPU profile 服务之上启动 `omnirt`。GPU profile 将
`OPENTALKING_INFERENCE_MOCK` 设为 `0`，并将 API 与 Worker 指向 `http://omnirt:9000`，
启用真实 talking-head 合成。

### 内存与磁盘

| 资源 | 大致需求 |
|------|---------|
| GPU 显存 | wav2lip 最少 24 GB；FlashTalk-14B 须 22 GB+ 可用显存 |
| 内存 | 最低 16 GB，推荐 32 GB |
| 磁盘 | 镜像 30 GB；OmniRT 首次启动拉取 FlashTalk 权重需要额外 35 GB |

### 验证 GPU 可访问

```bash title="终端"
docker compose --profile gpu exec omnirt nvidia-smi
```

输出应列出宿主机 GPU。

### 选择模型

Compose 栈不选择合成模型；模型由客户端在创建会话时指定。验证可用模型：

```bash title="终端"
curl -s http://localhost:8000/models | jq
```

将 GPU profile 限制为特定模型（例如仅 wav2lip）可通过 OmniRT 容器的环境变量配置；
具体选项参见 OmniRT 文档。

### 停止

```bash title="终端"
docker compose --profile gpu \
  -f docker-compose.yml -f docker-compose.gpu.yml \
  down
```

## 持久化状态

Compose 栈写入以下持久化状态：

| 容器内路径 | 卷 | 说明 |
|----------|-----|------|
| `/app/examples/avatars` | 绑定挂载或具名卷 | API 读取的 Avatar bundle。 |
| `/app/var/voices` | 具名卷 | 复刻音色目录与音频上传。 |
| `/app/data` | 具名卷 | SQLite 数据库。 |
| Redis 数据 | 具名卷 | 会话状态与 FlashTalk 队列。 |

生产部署应将 avatar 与音色目录从宿主机存储绑定挂载，而非使用匿名卷；具体挂载位置
在 `docker-compose.yml` 的 `volumes` 节中定义。

## Docker 部署的 .env 结构

Compose 栈从仓库根目录读取 `.env`。与 Docker 部署相关的变量：

| 变量 | Compose 中的默认值 | 用途 |
|------|------------------|------|
| `OPENTALKING_LLM_API_KEY` | _空_ | 语言模型 API Key，转发至 `api` 与 `worker`。 |
| `DASHSCOPE_API_KEY` | _空_ | 语音识别 API Key。 |
| `OPENTALKING_INFERENCE_MOCK` | CPU profile 为 `1`，GPU profile 为 `0` | 由 profile 自动设定。 |
| `OMNIRT_ENDPOINT` | 仅 GPU profile 下为 `http://omnirt:9000` | 由 override 文件自动设定。 |
| `OPENTALKING_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | 前端使用不同 origin 时须覆盖。 |

覆盖 Compose 默认值的变量（如 `OPENTALKING_INFERENCE_MOCK`）仅在确需偏离 profile
默认时才在 `.env` 中设置。

## 运维

### 查看日志

```bash title="终端"
docker compose logs -f api worker
docker compose --profile gpu logs -f omnirt
```

### 重启单个服务

```bash title="终端"
docker compose restart api
```

### 代码变更后重建

```bash title="终端"
docker compose build api worker web
docker compose up -d
```

### 升级 OpenTalking 版本

```bash title="终端"
git pull
docker compose build
docker compose up -d
```

### 更新 OmniRT 镜像

```bash title="终端"
docker compose --profile gpu pull omnirt
docker compose --profile gpu up -d
```

## 故障排查

| 现象 | 处理方式 |
|------|---------|
| `Error response from daemon: could not select device driver "" with capabilities: [[gpu]]` | 未安装 NVIDIA Container Toolkit 或未在 Docker 注册。安装工具包并重启 Docker daemon。 |
| `omnirt` 容器因 `CUDA driver mismatch` 退出 | 宿主机 NVIDIA driver 版本低于 OmniRT 镜像的 CUDA 版本。升级宿主机驱动。 |
| `api` 无法访问 `omnirt` | 确认两个容器都启用了 `gpu` profile：`docker compose --profile gpu ps`。默认 profile 不启动 OmniRT。 |
| `web` 容器对前端请求返回 502 | `api` 容器尚未健康。检查 `docker compose logs api`。 |
| `.env` 变更未生效 | Compose 在容器启动时读取 `.env`。通过 `docker compose restart <service>` 重启相关服务。 |

## 从源码安装迁移

由源码安装迁移到 Docker Compose 时：

1. 停止源码安装的进程（`bash scripts/quickstart/stop_all.sh`）。
2. 确认 `.env` 引用容器内主机名（如 `redis://redis:6379/0`，而非 `redis://localhost:6379/0`）。变量未设置时 Compose 栈会自动处理。
3. 在启动 Compose 栈之前，将自定义 Avatar bundle 复制到 `examples/avatars/`；该目录被 `api` 与 `worker` 服务绑定挂载。
4. 运行 `docker compose up -d`。

## 限制

- 当前 Compose 未打包昇腾 910B 部署路径。须使用 [源码安装的昇腾场景](install-from-source.md#ascend-910b)。
- Docker 栈不包含历史的裸金属 FlashTalk 单进程服务。Compose 部署中真实 FlashTalk 合成仅通过 OmniRT 提供。
- 默认 Compose 栈不支持多机 Worker 扩展。须使用源码安装的 [API 与 Worker 分离场景](install-from-source.md#api-and-worker-split)。
