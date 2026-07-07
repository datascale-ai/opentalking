# Windows WSL2 部署 OpenTalking + QuickTalk

本文面向 Windows + WSL2 Ubuntu 的单机部署场景。推荐先跑通 QuickTalk local 模式；只有需要把 avatar runtime 服务化、拆分 OpenTalking 与推理后端时，再使用 QuickTalk OmniRT 模式。

## 1. 路线选择

### QuickTalk local 模式

适合单机 WSL2、单 GPU、快速验证实时数字人链路。OpenTalking 进程内加载 QuickTalk adapter，不需要单独启动 OmniRT。

### QuickTalk OmniRT 模式

适合服务化、拆分 avatar runtime、后续多服务扩展。需要额外启动 OmniRT QuickTalk 后端。

## 2. 推荐目录结构

建议把代码、运行时 checkout 和模型权重分开存放。WSL2 推荐目录结构如下：

```text
$DIGITAL_HUMAN_HOME/
├── opentalking/
│   ├── .venv/
│   ├── apps/
│   ├── docs/
│   └── scripts/
├── model-repos/
│   └── omnirt/
│       └── .venv/
├── models/
│   └── quicktalk/
│       └── checkpoints/
│           ├── quicktalk.pth
│           ├── repair.npy
│           ├── chinese-hubert-large/
│           └── auxiliary/models/buffalo_l/
├── logs/
└── run/
```

工作目录建议放在 WSL2 Linux 文件系统中，例如 `$HOME/opentalking-workspace`，不要直接放在 `/mnt/c` 或 `/mnt/d` 下运行。

## 3. 端口约定

| 服务 | 端口 | 使用场景 |
| --- | --- | --- |
| OpenTalking API | `8210` | local 和 OmniRT 路线都使用 |
| OpenTalking Web UI | `5173` | local 和 OmniRT 路线都使用 |
| OmniRT | `9000` | 仅 OmniRT 路线使用 |

WSL2 内部的 OpenTalking / QuickTalk 启动命令和 Linux 部署文档保持同一套 backend、model、权重路径和 OmniRT endpoint 口径。Windows 浏览器访问需要显式绑定 `--host 0.0.0.0`，Web UI 端口统一使用当前前端默认端口 `5173`。

## 4. Windows 侧前置条件

### 4.1 NVIDIA 驱动

在 Windows PowerShell 中确认显卡和驱动正常：

```powershell
nvidia-smi
```

只要能看到 NVIDIA GPU 和驱动支持的 CUDA 版本即可。这里的 CUDA Version 表示驱动能力，不要求在 Windows 上额外安装 CUDA Toolkit。

### 4.2 安装并确认 WSL2

管理员 PowerShell：

```powershell
wsl --version
wsl --status
```

如果还没有 Ubuntu：

```powershell
wsl --install -d Ubuntu-22.04
```

进入 WSL2：

```powershell
wsl -d Ubuntu-22.04
```

在 WSL2 中确认 GPU 可见：

```bash
nvidia-smi
```

## 5. WSL2 网络与浏览器麦克风

推荐使用 WSL2 NAT 模式，并通过 WSL2 IP 从 Windows 浏览器访问 Web UI。

获取 WSL2 IP：

```bash
hostname -I | awk '{print $1}'
```

Windows 浏览器访问：

```text
http://<WSL2-IP>:5173
```

如果当前 WSL2 localhost 转发可用，也可以访问：

```text
http://localhost:5173
```

NAT 模式下，非 localhost 的 HTTP 地址不是浏览器安全上下文，麦克风可能被阻止。需要把当前 Web UI 地址加入浏览器白名单。

Edge：

```text
edge://flags/#unsafely-treat-insecure-origin-as-secure
填入 http://<WSL2-IP>:5173
```

Chrome PowerShell 示例：

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --unsafely-treat-insecure-origin-as-secure="http://<WSL2-IP>:5173" `
  --user-data-dir="%TEMP%\chrome-opentalking"
```

## 6. WSL2 基础依赖

以下命令在 WSL2 Ubuntu 中执行。如果当前是 root 用户，不需要 `sudo`；如果是普通用户，请在 `apt` 前加 `sudo`。

```bash
apt update
apt install -y \
  python3-pip python3-venv python3-dev \
  build-essential pkg-config \
  curl wget git git-lfs rsync unzip \
  ffmpeg nodejs jq \
  iproute2 procps psmisc \
  libgl1 libglib2.0-0

git lfs install
```

如果 `nodejs` 来自 NodeSource，`nodejs` 包通常已经自带 `npm`，不要再同时安装 Ubuntu 仓库里的 `npm` 包，否则可能出现 `nodejs : Conflicts: npm`。基础依赖安装后先检查：

```bash
node --version
npm --version
```

OpenTalking Web UI 使用 Vite 5，Node.js 需要 `18+`。部分 Windows WSL Ubuntu 环境通过系统仓库安装到的默认 Node.js 可能还是 `12.x`，会导致前端依赖安装或启动失败。发现 `node --version` 小于 `v18` 时，先升级 Node.js：

```bash
node -e "const m=Number(process.versions.node.split('.')[0]); if (m < 18) process.exit(1)" \
  || curl -fsSL https://deb.nodesource.com/setup_20.x | bash -

apt install -y nodejs

node --version
npm --version
node -e "const m=Number(process.versions.node.split('.')[0]); if (m < 18) throw new Error('Node.js 18+ required')"
```

只有在 `npm --version` 不存在、且当前使用 Ubuntu 官方 `nodejs` 包时，再单独安装：

```bash
apt install -y npm
```

检查基础工具：

```bash
python3 --version
ffmpeg -version
node --version
npm --version
nvidia-smi
```

## 7. 准备工作目录

优先把运行目录放在 WSL2 Linux 文件系统内，例如 `$HOME/opentalking-workspace`。不建议直接在 Windows 挂载盘下运行项目；如果必须从 Windows 盘复制代码，请只把 `/mnt/<drive>/...` 当作示例来源路径，并最终同步到 WSL2 Linux 文件系统。

先定义后续所有命令会用到的路径变量：

```bash
export DIGITAL_HUMAN_HOME="${DIGITAL_HUMAN_HOME:-$HOME/opentalking-workspace}"
export OPENTALKING_HOME="${OPENTALKING_HOME:-$DIGITAL_HUMAN_HOME/opentalking}"
export OPENTALKING_MODEL_ROOT="${OPENTALKING_MODEL_ROOT:-$DIGITAL_HUMAN_HOME/models}"
export OPENTALKING_MODEL_REPO_ROOT="${OPENTALKING_MODEL_REPO_ROOT:-$DIGITAL_HUMAN_HOME/model-repos}"
export OPENTALKING_QUICKTALK_ASSET_ROOT="${OPENTALKING_QUICKTALK_ASSET_ROOT:-$OPENTALKING_MODEL_ROOT/quicktalk}"
export OMNIRT_REPO="${OMNIRT_REPO:-$OPENTALKING_MODEL_REPO_ROOT/omnirt}"
export OMNIRT_MODEL_ROOT="${OMNIRT_MODEL_ROOT:-$OPENTALKING_MODEL_ROOT}"
export OMNIRT_QUICKTALK_MODEL_ROOT="${OMNIRT_QUICKTALK_MODEL_ROOT:-$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints}"

mkdir -p \
  "$DIGITAL_HUMAN_HOME" \
  "$OPENTALKING_MODEL_ROOT" \
  "$OPENTALKING_MODEL_REPO_ROOT" \
  "$OPENTALKING_QUICKTALK_ASSET_ROOT" \
  "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints"
```

拉取 OpenTalking：

```bash
git clone https://github.com/datascale-ai/opentalking.git "$OPENTALKING_HOME"
cd "$OPENTALKING_HOME"
```

如果已经克隆过仓库，直接进入现有目录：

```bash
cd "$OPENTALKING_HOME"
```

## 8. 安装 uv 并配置镜像

```bash
python3 -m pip install -U uv
```

如果 `uv` 不在 `PATH`：

```bash
export PATH="/usr/local/bin:$HOME/.local/bin:$PATH"
echo 'export PATH="/usr/local/bin:$HOME/.local/bin:$PATH"' >> ~/.bashrc
```

检查：

```bash
uv --version
```

网络较慢时，可按需设置镜像：

```bash
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export UV_INDEX_URL="${UV_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export npm_config_registry="${npm_config_registry:-https://registry.npmmirror.com}"
```

## 9. 准备 QuickTalk 权重

OpenTalking local 资产根目录：

```text
$OPENTALKING_QUICKTALK_ASSET_ROOT
```

QuickTalk 权重文件目录：

```text
$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints
```

下载或放置权重：

```bash
cd "$OPENTALKING_HOME"

export OPENTALKING_MODEL_ROOT="${OPENTALKING_MODEL_ROOT:-$DIGITAL_HUMAN_HOME/models}"
export OPENTALKING_QUICKTALK_ASSET_ROOT="${OPENTALKING_QUICKTALK_ASSET_ROOT:-$OPENTALKING_MODEL_ROOT/quicktalk}"

mkdir -p "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints"

export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

uv tool run --from "huggingface_hub[cli]" hf download datascale-ai/quicktalk \
  --local-dir "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints"
```

关键文件检查：

```bash
test -f "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints/quicktalk.pth"
test -f "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints/repair.npy"
test -d "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints/chinese-hubert-large"
test -d "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints/auxiliary/models/buffalo_l"
```

QuickTalk local 运行真实会话时还需要模板视频。优先使用带 `source_video` / `template_video` 元数据的 avatar，或使用 avatar 目录下已经准备好的 `quicktalk/template_*.mp4`。

```bash
find "$OPENTALKING_HOME/examples/avatars" -type f \( -path '*/quicktalk/template_*.mp4' -o -path '*/source/*.mp4' \) | sort | head
```

不要在服务启动环境里设置 `OPENTALKING_QUICKTALK_TEMPLATE_VIDEO`。它是全局模板覆盖变量，会强制所有 QuickTalk realtime 会话使用同一个视频模板；选择其它形象后，一旦开始生成口型，就可能切回这个全局模板对应的形象。只有在一次性离线排查某个固定模板时，才临时使用单独的命令行参数指定模板。

路径关系：

- OpenTalking local 资产根目录：`$OPENTALKING_QUICKTALK_ASSET_ROOT`
- 权重文件目录：`$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints`
- OmniRT QuickTalk model root：`$OMNIRT_QUICKTALK_MODEL_ROOT`

本指南把 OmniRT QuickTalk model root 指向同一个权重文件目录：

```bash
export OMNIRT_MODEL_ROOT="${OMNIRT_MODEL_ROOT:-$OPENTALKING_MODEL_ROOT}"
export OMNIRT_QUICKTALK_MODEL_ROOT="${OMNIRT_QUICKTALK_MODEL_ROOT:-$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints}"
```

如果不设置 `OMNIRT_QUICKTALK_MODEL_ROOT`，当前 helper 脚本默认使用 `$OMNIRT_MODEL_ROOT/quicktalk`。本 Windows 文档显式设置为 `$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints`，避免用户混淆 `models/quicktalk` 和 `models/quicktalk/checkpoints`。

当前 helper 脚本会检查 `$OMNIRT_QUICKTALK_MODEL_ROOT` 下是否存在 `quicktalk.pth`、`repair.npy`、`chinese-hubert-large/` 和 `auxiliary/models/buffalo_l/`。

## 10. 推荐路线：启动 QuickTalk local

```bash
export DIGITAL_HUMAN_HOME="${DIGITAL_HUMAN_HOME:-$HOME/opentalking-workspace}"
export OPENTALKING_HOME="${OPENTALKING_HOME:-$DIGITAL_HUMAN_HOME/opentalking}"
export OPENTALKING_MODEL_ROOT="${OPENTALKING_MODEL_ROOT:-$DIGITAL_HUMAN_HOME/models}"
export OPENTALKING_QUICKTALK_ASSET_ROOT="${OPENTALKING_QUICKTALK_ASSET_ROOT:-$OPENTALKING_MODEL_ROOT/quicktalk}"

cd "$OPENTALKING_HOME"
uv sync --extra dev --extra models --extra quicktalk-cuda --python 3.11

export OPENTALKING_TORCH_DEVICE="${OPENTALKING_TORCH_DEVICE:-cuda:0}"
export OPENTALKING_MODEL_ROOT="${OPENTALKING_MODEL_ROOT:-$DIGITAL_HUMAN_HOME/models}"
export OPENTALKING_QUICKTALK_ASSET_ROOT="${OPENTALKING_QUICKTALK_ASSET_ROOT:-$OPENTALKING_MODEL_ROOT/quicktalk}"
export OPENTALKING_QUICKTALK_WORKER_CACHE="${OPENTALKING_QUICKTALK_WORKER_CACHE:-1}"

bash scripts/start_unified.sh \
  --backend local \
  --model quicktalk \
  --api-port 8210 \
  --web-port 5173 \
  --host 0.0.0.0
```

验证：

```bash
curl -fsS http://127.0.0.1:8210/health | python3 -m json.tool
curl -fsS http://127.0.0.1:8210/models | python3 -m json.tool
```

确认 `quicktalk` 对应状态为 `backend=local`，且 `connected` / `healthy` 类字段表示可用。实际字段以当前 `/models` 返回为准。

`/health` 和 `/models` 用于确认服务进程、模型权重和 QuickTalk backend 是否可用。完整对话、实时语音识别或端到端 benchmark 还会依赖 LLM / STT / TTS 配置；如果没有配置对应 API key，本地 QuickTalk 仍可通过 `/models` 显示可用，但会话或 benchmark 可能在语音、文本生成阶段失败。

Windows 浏览器打开：

```text
http://<WSL2-IP>:5173
```

如果 localhost 转发可用：

```text
http://localhost:5173
```

## 11. 进阶路线：启动 QuickTalk OmniRT

OmniRT 路线需要额外准备 OmniRT checkout 和虚拟环境。`scripts/quickstart/start_omnirt_quicktalk.sh` 会从 `$OMNIRT_REPO` 启动 OmniRT QuickTalk 后端。

```bash
export DIGITAL_HUMAN_HOME="${DIGITAL_HUMAN_HOME:-$HOME/opentalking-workspace}"
export OPENTALKING_MODEL_REPO_ROOT="${OPENTALKING_MODEL_REPO_ROOT:-$DIGITAL_HUMAN_HOME/model-repos}"
export OMNIRT_REPO="${OMNIRT_REPO:-$OPENTALKING_MODEL_REPO_ROOT/omnirt}"

mkdir -p "$OPENTALKING_MODEL_REPO_ROOT"

git clone https://github.com/datascale-ai/omnirt.git "$OMNIRT_REPO"
cd "$OMNIRT_REPO"
uv sync --extra server --extra quicktalk-cuda --python 3.11
```

这里提前安装 `quicktalk-cuda`，避免首次启动 OmniRT QuickTalk 时才下载和构建 CUDA 依赖。如果只执行了 `uv sync --extra server --python 3.11`，启动脚本仍会在后台补装 `quicktalk-cuda`，全新环境可能超过脚本 180 秒就绪等待时间。

如果已经克隆过 OmniRT，直接进入目录并确认虚拟环境存在；如果还没有安装 QuickTalk CUDA 依赖，补执行一次同步：

```bash
cd "$OMNIRT_REPO"
test -f .venv/bin/activate
uv sync --extra server --extra quicktalk-cuda --python 3.11
```

启动 OmniRT QuickTalk 后端：

```bash
export DIGITAL_HUMAN_HOME="${DIGITAL_HUMAN_HOME:-$HOME/opentalking-workspace}"
export OPENTALKING_HOME="${OPENTALKING_HOME:-$DIGITAL_HUMAN_HOME/opentalking}"
export OPENTALKING_MODEL_ROOT="${OPENTALKING_MODEL_ROOT:-$DIGITAL_HUMAN_HOME/models}"
export OPENTALKING_MODEL_REPO_ROOT="${OPENTALKING_MODEL_REPO_ROOT:-$DIGITAL_HUMAN_HOME/model-repos}"
export OPENTALKING_QUICKTALK_ASSET_ROOT="${OPENTALKING_QUICKTALK_ASSET_ROOT:-$OPENTALKING_MODEL_ROOT/quicktalk}"
export OPENTALKING_AVATARS_DIR="${OPENTALKING_AVATARS_DIR:-$OPENTALKING_HOME/examples/avatars}"
export OMNIRT_REPO="${OMNIRT_REPO:-$OPENTALKING_MODEL_REPO_ROOT/omnirt}"
export OMNIRT_MODEL_ROOT="${OMNIRT_MODEL_ROOT:-$OPENTALKING_MODEL_ROOT}"
export OMNIRT_QUICKTALK_MODEL_ROOT="${OMNIRT_QUICKTALK_MODEL_ROOT:-$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints}"
export OMNIRT_ALLOWED_FRAME_ROOTS="${OMNIRT_ALLOWED_FRAME_ROOTS:-$OPENTALKING_AVATARS_DIR}"

cd "$OPENTALKING_HOME"

bash scripts/quickstart/start_omnirt_quicktalk.sh \
  --device cuda:0 \
  --port 9000 \
  --host 0.0.0.0
```

如果首次启动返回：

```text
OmniRT QuickTalk did not become ready in 180s
```

通常是首次安装 `quicktalk-cuda` 依赖还没有完成，例如内部仍在执行 `uv sync --extra server --extra quicktalk-cuda --python 3.11` 下载或构建 CUDA 相关包。处理方式：

```bash
cd "$OMNIRT_REPO"
uv sync --extra server --extra quicktalk-cuda --python 3.11

cd "$OPENTALKING_HOME"
bash scripts/quickstart/start_omnirt_quicktalk.sh \
  --device cuda:0 \
  --port 9000 \
  --host 0.0.0.0
```

如果上一次启动脚本超时后，日志仍显示依赖安装在继续进行，可以等安装完成后重新执行 `start_omnirt_quicktalk.sh`。依赖安装完成后，再次启动通常会很快进入就绪状态。

再启动 OpenTalking 连接 OmniRT：

```bash
cd "$OPENTALKING_HOME"

bash scripts/start_unified.sh \
  --backend omnirt \
  --model quicktalk \
  --omnirt http://127.0.0.1:9000 \
  --api-port 8210 \
  --web-port 5173 \
  --host 0.0.0.0
```

验证：

```bash
curl -fsS http://127.0.0.1:9000/v1/audio2video/models | python3 -m json.tool
curl -fsS http://127.0.0.1:8210/health | python3 -m json.tool
curl -fsS http://127.0.0.1:8210/models | python3 -m json.tool
```

确认 `quicktalk` 对应状态为 `backend=omnirt`，且 `connected` / `healthy` 类字段表示可用。实际字段以当前 `/models` 返回为准。

如果启动会话时报：

```text
RuntimeError: audio2video init failed: template_video requires configured allowed frame roots.
```

说明 OmniRT 没有配置可读取的 avatar 模板视频目录，或 `OMNIRT_ALLOWED_FRAME_ROOTS` 没有包含 OpenTalking 传给 OmniRT 的 `template_video` 路径。停止 OmniRT 后重新导出并启动：

```bash
cd "$OPENTALKING_HOME"
bash scripts/quickstart/stop_all.sh

export OPENTALKING_AVATARS_DIR="${OPENTALKING_AVATARS_DIR:-$OPENTALKING_HOME/examples/avatars}"
export OMNIRT_ALLOWED_FRAME_ROOTS="$OPENTALKING_AVATARS_DIR"

bash scripts/quickstart/start_omnirt_quicktalk.sh \
  --device cuda:0 \
  --port 9000 \
  --host 0.0.0.0
```

如果你的 avatar 或模板视频放在其它目录，把这些目录也加入 `OMNIRT_ALLOWED_FRAME_ROOTS`，多个目录用英文冒号分隔：

```bash
export OMNIRT_ALLOWED_FRAME_ROOTS="$OPENTALKING_AVATARS_DIR:/path/to/extra/avatar-root"
```

## 12. 常见路径问题说明

| 位置 | 正确做法 |
| --- | --- |
| 代码目录 | OpenTalking 放在 `$OPENTALKING_HOME`，通常是 `$DIGITAL_HUMAN_HOME/opentalking`。 |
| OmniRT checkout | OmniRT 放在 `$OMNIRT_REPO`，通常是 `$DIGITAL_HUMAN_HOME/model-repos/omnirt`。 |
| OpenTalking 虚拟环境 | 使用 `$OPENTALKING_HOME/.venv`，不要和 OmniRT 共用虚拟环境。 |
| OmniRT 虚拟环境 | 使用 `$OMNIRT_REPO/.venv`，在这里安装 OmniRT server 依赖。 |
| 模型根目录 | 大模型文件放在 `$OPENTALKING_MODEL_ROOT`，通常是 `$DIGITAL_HUMAN_HOME/models`。 |
| QuickTalk 资产根目录 | 使用 `$OPENTALKING_QUICKTALK_ASSET_ROOT`，通常是 `$OPENTALKING_MODEL_ROOT/quicktalk`。 |
| QuickTalk 权重目录 | 把 `quicktalk.pth`、`repair.npy`、`chinese-hubert-large/` 和 `auxiliary/models/buffalo_l/` 放在 `$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints` 下。 |
| OmniRT QuickTalk root | 使用 OmniRT 路线时，把 `$OMNIRT_QUICKTALK_MODEL_ROOT` 指向同一个 `checkpoints` 目录。 |
| OmniRT 模板视频白名单 | 使用 OmniRT 路线时，`$OMNIRT_ALLOWED_FRAME_ROOTS` 必须包含当前 avatar 根目录，通常是 `$OPENTALKING_HOME/examples/avatars` 或 `$OPENTALKING_AVATARS_DIR`，否则会报 `template_video requires configured allowed frame roots`。 |
| Windows 挂载盘路径 | 不建议直接在 `/mnt/c` 或 `/mnt/d` 下运行，先复制或同步到 WSL2 Linux 文件系统。 |
| Web UI 访问 | 优先使用 `http://<WSL2-IP>:5173`；只有 localhost 转发可用时再用 `http://localhost:5173`。 |

如果命令提示缺少 `repair.npy`、`quicktalk.pth`、HuBERT 或 `buffalo_l`，先确认当前命令需要的是资产根目录 `models/quicktalk`，还是权重目录 `models/quicktalk/checkpoints`。

如果前端依赖安装或启动阶段提示 Node 版本过低，先执行第 6 节的 NodeSource 升级步骤，确认 `node --version` 是 `v18` 或更高版本。

## 13. 停止服务

停止由 quickstart 脚本或 `scripts/start_unified.sh` 启动的 OpenTalking API、Web UI 和 OmniRT 进程：

```bash
cd "$OPENTALKING_HOME"
bash scripts/quickstart/stop_all.sh
```

需要彻底重启 WSL2 时，可在 Windows PowerShell 中执行：

```powershell
wsl --shutdown
```

## 14. 最终检查清单

服务健康检查通过后，建议先跑一次 QuickTalk 离线生成验证。这个检查只依赖 QuickTalk 权重、模板视频、CUDA、HuBERT 和 ffmpeg，不依赖 LLM / STT / TTS API key：

```bash
cd "$OPENTALKING_HOME"
mkdir -p "$DIGITAL_HUMAN_HOME/run/quicktalk-bench"

QUICKTALK_BENCH_TEMPLATE_VIDEO="${QUICKTALK_BENCH_TEMPLATE_VIDEO:-$(find "$OPENTALKING_HOME/examples/avatars" -type f \( -path '*/quicktalk/template_*.mp4' -o -path '*/source/*.mp4' \) | sort | head -n 1)}"
test -f "$QUICKTALK_BENCH_TEMPLATE_VIDEO"

ffmpeg -y -hide_banner -loglevel error \
  -i configs/benchmark/input/ttsmaker-file.mp3 \
  -ac 1 -ar 16000 -sample_fmt s16 \
  "$DIGITAL_HUMAN_HOME/run/quicktalk-bench/input.wav"

"$OPENTALKING_HOME/.venv/bin/python" -m apps.cli.quicktalk_bench \
  --asset-root "$OPENTALKING_QUICKTALK_ASSET_ROOT" \
  --template-video "$QUICKTALK_BENCH_TEMPLATE_VIDEO" \
  --audio "$DIGITAL_HUMAN_HOME/run/quicktalk-bench/input.wav" \
  --output "$DIGITAL_HUMAN_HOME/run/quicktalk-bench/output.mp4" \
  --device cuda:0
```

输出文件应存在：

```bash
test -f "$DIGITAL_HUMAN_HOME/run/quicktalk-bench/output.mp4"
```

如果已经配置好 LLM / STT / TTS 凭证，再跑端到端 benchmark，验证真实 OpenTalking + QuickTalk 链路，而不只是进程启动成功。当前脚本需要 `--tester`，API 地址参数使用 `--api-base-url`：

```bash
cd "$OPENTALKING_HOME"
bash scripts/run_opentalking_e2e_benchmark.sh \
  --tester "$USER" \
  --model quicktalk \
  --backend local \
  --api-base-url http://127.0.0.1:8210
```

如果启动的是 OmniRT 路线，把 `--backend local` 改成 `--backend omnirt`。如果 benchmark 配置文件中的 `models.quicktalk.backend` 与命令行不一致，以配置文件中的模型级 backend 为准；需要保持它和命令行一致。

```bash
# WSL2 GPU
nvidia-smi

# OpenTalking 仓库
cd "$OPENTALKING_HOME"
uv --version

# QuickTalk 权重
test -f "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints/quicktalk.pth"
test -f "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints/repair.npy"
test -d "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints/chinese-hubert-large"
test -d "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints/auxiliary/models/buffalo_l"
test -z "${OPENTALKING_QUICKTALK_TEMPLATE_VIDEO:-}"

# local 或 OmniRT 路线启动后
curl -fsS http://127.0.0.1:8210/health | python3 -m json.tool
curl -fsS http://127.0.0.1:8210/models | python3 -m json.tool

# OmniRT 路线启动后
curl -fsS http://127.0.0.1:9000/v1/audio2video/models | python3 -m json.tool
```

Windows Web UI 最终访问地址：

```text
http://<WSL2-IP>:5173
```

localhost 转发可用时：

```text
http://localhost:5173
```

## 15. 总结

首次在 Windows + WSL2 部署时，推荐使用 QuickTalk local 路线：OpenTalking、QuickTalk 和 Web UI 由同一套启动流程拉起，更容易排查问题。需要独立推理服务、服务隔离或后续多服务扩展时，再使用 OmniRT 路线。代码、虚拟环境和模型权重应分开存放，并且在跑 benchmark 前先确认 `/models` 和 Web UI 都可用。
