# 安装

OpenTalking 提供两种安装方式。选择哪一种取决于两个问题：工作环境（开发、单机生产、
多机生产）与硬件类型（仅 CPU、NVIDIA GPU、昇腾 NPU）。

本页提供选型矩阵并指向各方式的详细文档。首次运行的精简流程参见 [快速上手](quickstart.md)。

## 安装方式选型

| 使用场景 | 硬件 | 推荐方式 | 详细文档 |
|---------|------|---------|---------|
| 本地开发、前端修改、API 迭代 | 任意 | 源码安装 + mock 合成 | [源码安装](install-from-source.md#development-cpu-mock-synthesis) |
| CPU 评估 | CPU | 源码安装 + mock 合成 | [源码安装](install-from-source.md#development-cpu-mock-synthesis) |
| 单 GPU 机器评估 | NVIDIA 3090 / 4090 / A100（CUDA 12） | 源码安装 + 模型专属 backend | [源码安装 → 单 GPU](install-from-source.md#scenario-single-gpu-with-wav2lip) |
| 昇腾 NPU 评估 | 华为 910B（CANN 8.0+） | 宿主机 CANN 环境 + 源码安装 | [源码安装 → 昇腾 910B](install-from-source.md#ascend-910b) |
| 持续集成 | CPU | 源码安装或 Docker Compose，按复现需求选择 | [源码安装](install-from-source.md#development-cpu-mock-synthesis) 或 [Docker Compose → CPU profile](install-with-docker.md#cpu-profile) |
| 单机生产部署 | Linux + GPU 或 NPU | 源码安装或 Docker，按运维偏好 | [源码安装 → 生产](install-from-source.md#production-deployment) 或 [Docker Compose](install-with-docker.md) |
| 多机生产部署、Worker 横向扩展 | Linux + GPU 或 NPU | 源码安装、API/Worker 分离、外部 Redis | [源码安装 → API/Worker 分离](install-from-source.md#api-and-worker-split) 与 [部署](deployment.md) |

## 平台支持矩阵

| 平台 | 合成后端 | 说明 |
|------|---------|------|
| macOS（Apple Silicon 与 Intel） | `mock` | 适用于编排与前端开发；macOS 不支持真实 talking-head 模型。 |
| Linux x86_64 + CUDA 12 | `mock`、`wav2lip`、`musetalk`、`flashtalk`、`flashhead`、`quicktalk` | 主要部署目标。 |
| Linux aarch64 + 昇腾 910B（CANN 8.0+） | `mock`、`wav2lip`、`flashtalk` | NPU 生产部署路径。 |
| Windows | `mock`（建议 WSL2） | 不在持续集成矩阵中。 |

## 共同前置条件

无论使用何种安装方式，下列组件均为必需：

- 用于默认语言模型（`qwen-flash`）与语音识别（`paraformer-realtime-v2`）的 DashScope（百炼）API Key。可使用其它 OpenAI 兼容端点替代，详见 [配置 §1](configuration.md#1-llm-stt-tts)。
- 支持 WebRTC 的客户端。前端在 Chromium 内核浏览器上经过测试。Safari 须配置额外 CORS。

源码安装额外要求：

- Python 3.9 或更新版本（建议 3.11）。
- Node.js 18 或更新版本，用于前端工具链。
- ffmpeg，用于语音合成解码。
- 可选 Redis 6 或更新版本，用于 API/Worker 分离部署。

Docker Compose 是部署打包选项，不是最轻的评估路径。只有在需要可复现镜像、容器化服务
边界或贴近生产运维时，才建议优先使用。

Docker 安装额外要求：

- Docker Engine 20.10 或更新版本，含 Compose v2 插件。
- 运行 GPU profile 时须安装 NVIDIA Container Toolkit。

## 验证

无论何种安装方式，编排服务启动后均可通过以下请求验证：

```bash title="终端"
curl -s http://127.0.0.1:8000/health
# {"status":"ok"}

curl -s http://127.0.0.1:8000/models | jq
# 列出可用的合成后端。
```

## 下一步

- [源码安装](install-from-source.md) —— 从 git checkout 安装。覆盖开发、生产与昇腾变种。
- [Docker Compose](install-with-docker.md) —— 使用打包 Docker 栈进行可复现部署。
- [配置](configuration.md) —— 安装后所需的环境配置。
- [部署](deployment.md) —— 选择运行时拓扑。
