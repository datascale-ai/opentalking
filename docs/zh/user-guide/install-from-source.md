# 源码安装

源码安装提供最高的灵活性，是开发场景与昇腾 NPU 部署的必要方式。具体步骤随目标场景
而变；本页文档列出各变种的完整流程。

若部署环境与 Docker 支持的配置相符，[Docker Compose 安装](install-with-docker.md)
也是可行选择，运维上可能更为简化。

## 通用步骤

下述步骤为所有源码安装共用。

### 1. 克隆仓库

```bash title="终端"
git clone https://github.com/datascale-ai/opentalking.git
cd opentalking
```

仓库假定父目录同时包含 OmniRT 的 checkout，用于使用真实 talking-head 模型的部署。
推荐目录结构：

```text
$DIGITAL_HUMAN_HOME/
├── opentalking/
├── omnirt/
└── models/
    ├── wav2lip/
    ├── SoulX-FlashTalk-14B/
    └── chinese-wav2vec2-base/
```

设置环境变量：

```bash title="终端"
export DIGITAL_HUMAN_HOME=/opt/digital_human   # 或自定义路径
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
```

### 2. 安装 Python 依赖

```bash title="终端"
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

`[dev]` extra 安装运行时依赖与 `ruff`、`pytest`、`pytest-asyncio`、`pytest-cov` 等
开发工具。

PyPI 源较慢时可使用镜像：

```bash title="终端"
pip install --index-url https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
```

### 3. 安装前端依赖

```bash title="终端"
cd apps/web
npm ci
cd ../..
```

### 4. 配置环境

```bash title="终端"
cp .env.example .env
```

编辑 `.env` 并配置最小必填变量：

```env title=".env"
OPENTALKING_LLM_API_KEY=<dashscope-api-key>
DASHSCOPE_API_KEY=<dashscope-api-key>
```

两个变量须配置为同一把 DashScope API Key。完整配置参考见 [配置](configuration.md)。

### 5. 验证安装

```bash title="终端"
opentalking --help
```

## 场景：开发（CPU + mock 合成） {#development-cpu-mock-synthesis}

适用于无 GPU 的工作站上进行前端开发、API 迭代与编排修改。

### 启动单进程服务

```bash title="终端"
bash scripts/quickstart/start_all.sh --mock
```

该命令启动 OpenTalking 单进程服务（`http://127.0.0.1:8000`）与 Vite 开发服务器
（`http://localhost:5173`）。mock 合成路径返回占位帧，无须推理服务。

后端开发热重载：

```bash title="终端"
uvicorn apps.unified.main:app --reload --port 8000
```

前端单独启动：

```bash title="终端"
cd apps/web
npm run dev -- --host 0.0.0.0
```

资源占用：

- 单进程内存 1–2 GB。
- 无 GPU。
- 需访问已配置的语言模型与 TTS 端点。

## 场景：单 GPU + Wav2Lip {#scenario-single-gpu-with-wav2lip}

适用于单张 NVIDIA 3090 或同级 24 GB GPU 上使用轻量级 `wav2lip` 模型评估。

### 安装 OmniRT

OmniRT 为推理运行时，在 OpenTalking 同级目录 clone：

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME"
git clone https://github.com/datascale-ai/omnirt.git
cd omnirt
uv sync --extra server
```

### 下载模型权重

```bash title="终端"
mkdir -p "$OMNIRT_MODEL_ROOT/wav2lip"
# 将 wav2lip384.pth 与 s3fd.pth 放入 $OMNIRT_MODEL_ROOT/wav2lip/
# 当前下载位置请参阅 OmniRT 文档。
```

### 启动 OmniRT

```bash title="终端"
bash "$DIGITAL_HUMAN_HOME/opentalking/scripts/quickstart/start_omnirt_wav2lip.sh" --device cuda
```

脚本完成依赖安装、环境变量配置，并在 `http://127.0.0.1:9000` 启动 OmniRT。进程 PID
写入 `$DIGITAL_HUMAN_HOME/run/omnirt-wav2lip.pid`，日志位于
`$DIGITAL_HUMAN_HOME/logs/omnirt-wav2lip.log`。

### 配置 OpenTalking

在 `.env` 中追加：

```env
OMNIRT_ENDPOINT=http://127.0.0.1:9000
```

### 启动 OpenTalking

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_all.sh
```

前端创建会话时选择 `wav2lip` 模型。

资源占用：

- 1 张 24 GB 显存的 NVIDIA GPU。
- 16 GB 内存。
- 5 GB 磁盘空间用于 wav2lip 权重。

## 场景：单 GPU + FlashTalk

适用于单张 NVIDIA 4090 或 A100 上使用 SoulX FlashTalk-14B 模型评估。

步骤与 wav2lip 场景一致，差异如下：

```bash title="终端：启动 OmniRT"
bash "$DIGITAL_HUMAN_HOME/opentalking/scripts/quickstart/start_omnirt_flashtalk.sh" --device cuda
```

模型权重：

- `SoulX-FlashTalk-14B/`（约 28 GB），位于 `$OMNIRT_MODEL_ROOT/`。
- `chinese-wav2vec2-base/`（约 400 MB），位于 `$OMNIRT_MODEL_ROOT/`。

资源占用：

- 1 张至少 22 GB 可用显存的 NVIDIA GPU（4090 24 GB 或 A100 40 GB）。
- 32 GB 内存。
- 35 GB 磁盘空间用于 FlashTalk 与 wav2vec2 权重。

如显存受限，可通过 [配置 → FlashTalk 渲染参数](configuration.md#flashtalk) 中的参数
调低消耗。

## 场景：昇腾 910B {#ascend-910b}

NPU 生产部署，须 CANN 8.0 或更新版本。

### 验证 CANN 安装

```bash title="终端"
test -f /usr/local/Ascend/ascend-toolkit/set_env.sh && echo "CANN 已就绪"
source /usr/local/Ascend/ascend-toolkit/set_env.sh
npu-smi info
```

### 安装 Python 依赖

OpenTalking 的安装流程与通用步骤一致。OmniRT 需要 NPU 专用的 PyTorch wheel，
由部署脚本完成。

### 部署

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/deploy_ascend_910b.sh
```

脚本执行：

1. source CANN 环境文件。
2. 配置 NPU 专属环境变量（`OMNIRT_WAV2LIP_DEVICE=npu`、`OMNIRT_WAV2LIP_FACE_DET_DEVICE=cpu`）。
3. 通过 `scripts/quickstart/start_omnirt_wav2lip.sh --device npu` 启动 OmniRT。

### 支持的模型

| 模型 | 在昇腾 910B 上的状态 |
|------|------------------|
| `mock` | 支持 |
| `wav2lip` | 通过 OmniRT `--backend ascend` 支持 |
| `flashtalk` | 支持 |
| `musetalk` | 当前未移植 |

资源占用：

- 1 张昇腾 910B 卡（Atlas 800T 或同级服务器）。
- CANN 8.0 或更新版本。
- `torch-npu` 包，由部署脚本安装。

## 场景：API 与 Worker 分离 {#api-and-worker-split}

适用于需要 Worker 横向扩展或组件隔离的生产部署。架构与运行特性详见
[部署 → API 与 Worker 分离](deployment.md#api-worker)。

### 前置条件

在通用安装之外，另需：

- Redis 6 或更新版本，API 与 Worker 进程均能访问。
- 进程管理器（systemd、supervisor、Kubernetes Deployment）。

### 配置

相关环境变量（详见 [配置 §3](configuration.md#3)）：

```env title=".env"
OPENTALKING_REDIS_URL=redis://<redis-host>:6379/0
OPENTALKING_API_HOST=0.0.0.0
OPENTALKING_API_PORT=8000
OPENTALKING_WORKER_HOST=0.0.0.0
OPENTALKING_WORKER_PORT=9001
OPENTALKING_WORKER_URL=http://<worker-host>:9001
```

### 启动

API 与 Worker 进程分别启动：

```bash title="终端：API"
uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
```

```bash title="终端：Worker"
python -m apps.worker.main --host 0.0.0.0 --port 9001
```

可在多台主机上启动多个 Worker 进程；每个 Worker 订阅同一 Redis 总线。

## 场景：生产部署 {#production-deployment}

源码安装下的单机生产部署：

1. 按目标硬件场景完成 OpenTalking 与 OmniRT 安装。
2. 按 [配置 → 生产部署](configuration.md#3) 配置 `.env`。
3. 将相关命令封装到进程管理器中。systemd unit 示例：

   ```ini title="/etc/systemd/system/opentalking.service"
   [Unit]
   Description=OpenTalking unified server
   After=network.target redis.service
   Requires=redis.service

   [Service]
   Type=simple
   User=opentalking
   WorkingDirectory=/opt/digital_human/opentalking
   EnvironmentFile=/opt/digital_human/opentalking/.env
   ExecStart=/opt/digital_human/opentalking/.venv/bin/opentalking-unified
   Restart=on-failure
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

4. 按 [部署 → 生产部署清单](deployment.md#production-checklist) 完成上线前的配置项。

## 更新

更新已有源码安装：

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME/opentalking"
git pull
source .venv/bin/activate
pip install -e ".[dev]"
cd apps/web && npm ci && cd ../..
```

数据库 schema 迁移在进程启动时自动执行。

## 故障排查

| 现象 | 处理方式 |
|------|---------|
| `ModuleNotFoundError: opentalking` | 通过 `source .venv/bin/activate` 激活虚拟环境，或执行 `pip install -e ".[dev]"`。 |
| TTS 解码时报 `ffmpeg: not found` | 安装 ffmpeg。macOS：`brew install ffmpeg`；Debian/Ubuntu：`apt install ffmpeg`。 |
| `torch.cuda.is_available()` 返回 False | 检查 NVIDIA driver、CUDA Toolkit，以及 `torch` 包是否与 CUDA 版本匹配。 |
| OmniRT 因 `CUDA out of memory` 退出 | 降低 `OPENTALKING_FLASHTALK_FRAME_NUM`、`OPENTALKING_FLASHTALK_SAMPLE_STEPS` 或输出分辨率，参见 [配置 → FlashTalk 渲染参数](configuration.md#flashtalk)。 |
| `npu-smi: command not found` | CANN toolkit 未加入 PATH，执行 `source /usr/local/Ascend/ascend-toolkit/set_env.sh`。 |
| 端口 8000 被占用 | 通过启动脚本的 `--api-port` 或 `.env` 中的 `OPENTALKING_API_PORT` 覆盖。 |

## 卸载

移除源码安装：

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME"
rm -rf opentalking omnirt models
# 可选：移除日志与 PID 目录
rm -rf "$DIGITAL_HUMAN_HOME/logs" "$DIGITAL_HUMAN_HOME/run"
```

`OPENTALKING_SQLITE_PATH` 指向的本地 SQLite 数据库若位于仓库内，也将一并移除。
