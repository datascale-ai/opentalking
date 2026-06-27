# Windows 上部署 OpenTalking + OmniRT + QuickTalk

> 本文面向 Windows 笔记本部署场景，目标是从 `git clone` 开始，在 WSL2 Ubuntu 中跑通 OpenTalking + OmniRT + QuickTalk，并完成 E2E Benchmark。

---

## 0. 最终部署结构

```text
Windows Host
  └── WSL2 Ubuntu
        ├── OpenTalking：Web / API / 会话编排
        ├── OmniRT：QuickTalk 推理后端
        └── CUDA：RTX 3050 Laptop GPU
```

推荐目录结构：

```text
$DIGITAL_HUMAN_HOME/
├── opentalking/
│   ├── .venv/
│   ├── apps/
│   ├── configs/
│   ├── scripts/
│   └── models/quicktalk/checkpoints/
├── omnirt/
│   ├── .venv/
│   └── models/quicktalk/
└── models/
    └── quicktalk -> $DIGITAL_HUMAN_HOME/opentalking/models/quicktalk
```

建议把代码放在 WSL2 自己的 Linux 文件系统中，例如 `$WSL_HOME/test` 或 `/home/<user>/test`，不要直接在 `/mnt/d/...` 下跑 benchmark。

---

## 1. Windows 侧前置条件

### 1.1 NVIDIA 驱动

Windows 上先确认显卡和驱动正常：

```powershell
nvidia-smi
```

期望能看到类似：

```text
NVIDIA GeForce RTX 3050 Laptop GPU
CUDA Version: 13.0
```

说明：这里的 `CUDA Version` 表示驱动支持的最高 CUDA 版本，不等于必须安装 CUDA Toolkit。后续 PyTorch 直接安装 CUDA wheel 即可。

---

### 1.2 安装并确认 WSL2

管理员 PowerShell：

```powershell
wsl --version
wsl --status
```

期望：

```text
默认版本: 2
```

如果还没有 Ubuntu，可以安装：

```powershell
wsl --install -d Ubuntu-22.04
```

如果使用手动导入的 Ubuntu，也可以使用类似：

```powershell
wsl --import Ubuntu-22.04 D:\wsl\Ubuntu-22.04 D:\wsl\downloads\ubuntu-22.04-wsl.rootfs.tar.gz --version 2
```

进入 WSL2：

```powershell
wsl -d Ubuntu-22.04
```

在 WSL2 中确认 GPU：

```bash
nvidia-smi
```

只要 WSL2 中能看到 RTX 3050，就说明 CUDA 推理基础条件具备。

---

## 2. WSL2 基础依赖

以下命令在 WSL2 Ubuntu 中执行。如果当前是 root 用户，不需要 `sudo`；如果是普通用户，请在 `apt` 前加 `sudo`。

```bash
apt update
apt install -y \
  python3-pip python3-venv python3-dev \
  build-essential pkg-config \
  curl wget git git-lfs rsync unzip \
  ffmpeg nodejs npm jq \
  iproute2 procps psmisc \
  libgl1 libglib2.0-0

git lfs install
```

检查基础工具：

```bash
python3 --version
ffmpeg -version
node --version
npm --version
nvidia-smi
```

---

## 3. 从 GitHub 拉取代码

进入工作目录：

```bash
mkdir -p $WSL_HOME/test
cd $WSL_HOME/test
```

拉取两个仓库：

```bash
git clone https://github.com/datascale-ai/opentalking.git
git clone https://github.com/datascale-ai/omnirt.git
```

最终结构应为：

```text
$DIGITAL_HUMAN_HOME/opentalking
$DIGITAL_HUMAN_HOME/omnirt
```

检查：

```bash
ls $DIGITAL_HUMAN_HOME/opentalking
ls $DIGITAL_HUMAN_HOME/omnirt
```

### 路径说明

如果 Windows 上已经有代码，也可以复制到 WSL2：

```bash
rsync -a --info=progress2 /mnt/d/test_opentalking/opentalking/ $DIGITAL_HUMAN_HOME/opentalking/
rsync -a --info=progress2 /mnt/d/test_opentalking/omnirt/ $DIGITAL_HUMAN_HOME/omnirt/
```

如果服务器上已经下载好代码，也可以同步到 WSL2：

```bash
rsync -avP <user>@<server-host>:$DIGITAL_HUMAN_HOME/opentalking/ $DIGITAL_HUMAN_HOME/opentalking/
rsync -avP <user>@<server-host>:$DIGITAL_HUMAN_HOME/omnirt/ $DIGITAL_HUMAN_HOME/omnirt/
```

---

## 4. 安装 uv 并配置镜像

在 WSL2 中安装 uv：

```bash
python3 -m pip install -U uv -i https://pypi.tuna.tsinghua.edu.cn/simple
```

如果 `uv` 不在 PATH：

```bash
export PATH="/usr/local/bin:$HOME/.local/bin:$PATH"
echo 'export PATH="/usr/local/bin:$HOME/.local/bin:$PATH"' >> ~/.bashrc
```

检查：

```bash
uv --version
```

建议写入常用镜像环境变量：

```bash
cat >> ~/.bashrc <<'EOF'
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
export UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export HF_ENDPOINT=https://hf-mirror.com
export npm_config_registry=https://registry.npmmirror.com
export CUDA_VISIBLE_DEVICES=0
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,max_split_size_mb:128
EOF

source ~/.bashrc
```

---

## 5. 配置 OpenTalking 环境

进入 OpenTalking：

```bash
cd $DIGITAL_HUMAN_HOME/opentalking
```

创建独立虚拟环境：

```bash
uv venv --python python3 .venv
source .venv/bin/activate
```

确认 Python 路径：

```bash
which python
```

期望：

```text
$DIGITAL_HUMAN_HOME/opentalking/.venv/bin/python
```

安装基础包：

```bash
uv pip install -U pip setuptools wheel \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

安装 OpenTalking 依赖：

```bash
uv pip install -e ".[dev,models]" \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

安装 CUDA 版 PyTorch：

```bash
uv pip install \
  torch==2.9.1+cu128 \
  torchvision==0.24.1+cu128 \
  torchaudio==2.9.1+cu128 \
  --find-links https://mirrors.aliyun.com/pytorch-wheels/cu128/ \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

验证 CUDA：

```bash
python -c "import torch; print('torch=', torch.__version__); print('torch cuda=', torch.version.cuda); print('cuda=', torch.cuda.is_available()); print('gpu=', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO CUDA')"
```

期望输出：

```text
torch= 2.9.1+cu128
torch cuda= 12.8
cuda= True
gpu= NVIDIA GeForce RTX 3050 Laptop GPU
```

### 说明

Linux / WSL2 下安装 CUDA 版 PyTorch 会拉取 `nvidia-cudnn-cu12`、`nvidia-cublas-cu12`、`triton` 等依赖，体积较大，这是正常现象。重点是最终必须确认 `cuda=True`。

---

## 6. 准备 QuickTalk 权重

QuickTalk 权重需要放在：

```text
$DIGITAL_HUMAN_HOME/opentalking/models/quicktalk/checkpoints/
```

完整结构应类似：

```text
checkpoints/
├── quicktalk.pth
├── repair.npy
├── chinese-hubert-large/
│   ├── config.json
│   ├── preprocessor_config.json
│   └── pytorch_model.bin
└── auxiliary/models/buffalo_l/
    ├── det_10g.onnx
    ├── w600k_r50.onnx
    ├── 2d106det.onnx
    └── ...
```

检查关键文件：

```bash
cd $DIGITAL_HUMAN_HOME/opentalking

ls -lh models/quicktalk/checkpoints/quicktalk.pth
ls -lh models/quicktalk/checkpoints/repair.npy
ls -lh models/quicktalk/checkpoints/chinese-hubert-large/pytorch_model.bin
ls -lh models/quicktalk/checkpoints/auxiliary/models/buffalo_l/det_10g.onnx
ls -lh models/quicktalk/checkpoints/auxiliary/models/buffalo_l/w600k_r50.onnx
ls -lh models/quicktalk/checkpoints/auxiliary/models/buffalo_l/2d106det.onnx
```

### 路径要点

OmniRT 启动 QuickTalk 时，推荐直接指向 `checkpoints` 目录：

```bash
export OMNIRT_QUICKTALK_MODEL_ROOT=$DIGITAL_HUMAN_HOME/opentalking/models/quicktalk/checkpoints
```

benchmark 脚本如果需要 `$DIGITAL_HUMAN_HOME/models/quicktalk`，可以建立符号链接：

```bash
mkdir -p $DIGITAL_HUMAN_HOME/models
ln -sfn $DIGITAL_HUMAN_HOME/opentalking/models/quicktalk $DIGITAL_HUMAN_HOME/models/quicktalk
```

---

## 7. 配置 OmniRT 环境

进入 OmniRT：

```bash
cd $DIGITAL_HUMAN_HOME/omnirt
```

创建独立虚拟环境：

```bash
uv venv --python python3 .venv
source .venv/bin/activate
```

确认 Python 路径：

```bash
which python
```

期望：

```text
$DIGITAL_HUMAN_HOME/omnirt/.venv/bin/python
```

安装依赖：

```bash
uv pip install -U pip setuptools wheel \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple

uv pip install -e ".[dev,server,quicktalk-cuda]" \
  --find-links https://mirrors.aliyun.com/pytorch-wheels/cu128/ \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

如果需要，重新确认 CUDA torch：

```bash
uv pip install \
  torch==2.9.1+cu128 \
  torchvision==0.24.1+cu128 \
  torchaudio==2.9.1+cu128 \
  --find-links https://mirrors.aliyun.com/pytorch-wheels/cu128/ \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

检查：

```bash
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
which omnirt
omnirt --help
```

期望：

```text
$DIGITAL_HUMAN_HOME/omnirt/.venv/bin/omnirt
```

同步模型到 OmniRT：

```bash
mkdir -p $DIGITAL_HUMAN_HOME/omnirt/models/quicktalk
rsync -a --info=progress2 \
  $DIGITAL_HUMAN_HOME/opentalking/models/quicktalk/ \
  $DIGITAL_HUMAN_HOME/omnirt/models/quicktalk/
```

---

## 8. 配置 OpenTalking .env

进入 OpenTalking：

```bash
cd $DIGITAL_HUMAN_HOME/opentalking
cp -n .env.example .env
```

建议重点配置：

```bash
cat >> .env <<'EOF'
OPENTALKING_TTS_DEFAULT_PROVIDER=edge
OPENTALKING_REDIS_MODE=memory
OMNIRT_ENDPOINT=http://127.0.0.1:9000
EOF
```

如果需要接入 LLM / STT，再单独配置对应 key：

```bash
OPENTALKING_LLM_API_KEY=你的LLM_API_KEY
OPENTALKING_STT_DASHSCOPE_API_KEY=你的STT_API_KEY
```

### 说明

LLM、TTS、STT 是独立 provider。Edge TTS 不需要 key，最适合先跑通链路；DashScope key 如果欠费或无效，会影响 LLM / STT，但不代表 QuickTalk 推理不可用。

---

## 9. 启动 OmniRT QuickTalk 后端

新开一个 WSL2 终端，进入 OmniRT：

```bash
cd $DIGITAL_HUMAN_HOME/omnirt
source .venv/bin/activate
```

设置环境变量：

```bash
export CUDA_VISIBLE_DEVICES=0
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,max_split_size_mb:128

export OMNIRT_QUICKTALK_RUNTIME=1
export OMNIRT_QUICKTALK_MODEL_ROOT=$DIGITAL_HUMAN_HOME/opentalking/models/quicktalk/checkpoints
export OMNIRT_QUICKTALK_DEVICE=cuda:0
export OMNIRT_QUICKTALK_HUBERT_DEVICE=cuda:0
```

启动：

```bash
.venv/bin/python -m omnirt.cli.main serve-avatar-ws \
  --host 0.0.0.0 \
  --port 9000 \
  --compat flashtalk \
  --backend cuda \
  --avatar-runtime fake
```

关键参数：

| 参数                                          | 作用                                                      |
| --------------------------------------------- | --------------------------------------------------------- |
| `OMNIRT_QUICKTALK_RUNTIME=1`                  | 启用 QuickTalk runtime                                    |
| `OMNIRT_QUICKTALK_MODEL_ROOT=.../checkpoints` | 指向 QuickTalk 权重目录                                   |
| `--compat flashtalk`                          | 兼容 OpenTalking 侧 WebSocket 协议                        |
| `--avatar-runtime fake`                       | 让 QuickTalk runtime 生效，避免走 FlashTalk resident 路径 |

---

## 10. 启动 OpenTalking

再开一个 WSL2 终端，进入 OpenTalking：

```bash
cd $DIGITAL_HUMAN_HOME/opentalking
source .venv/bin/activate
```

启动：

```bash
bash scripts/start_unified.sh \
  --backend omnirt \
  --model quicktalk \
  --omnirt http://127.0.0.1:9000 \
  --host 0.0.0.0
```

前端地址：

```text
http://127.0.0.1:5173
```

验证 QuickTalk 连接状态：

```bash
curl -s http://127.0.0.1:8000/models \
  | python3 -c "import sys,json; [print(s) for s in json.load(sys.stdin)['statuses'] if s['id']=='quicktalk']"
```

期望看到：

```text
connected=true
reason=omnirt
```

检查 GPU 显存：

```bash
nvidia-smi --query-gpu=memory.used --format=csv,noheader
```

---

## 11. 常见路径问题说明

| 位置                  | 正确做法                                                     |
| --------------------- | ------------------------------------------------------------ |
| 代码目录              | 放在 `$DIGITAL_HUMAN_HOME/opentalking` 和 `$DIGITAL_HUMAN_HOME/omnirt`         |
| OpenTalking venv      | `$DIGITAL_HUMAN_HOME/opentalking/.venv`                               |
| OmniRT venv           | `$DIGITAL_HUMAN_HOME/omnirt/.venv`                                    |
| QuickTalk 权重        | `$DIGITAL_HUMAN_HOME/opentalking/models/quicktalk/checkpoints`        |
| OmniRT QuickTalk root | 指向 `.../checkpoints`                                       |
| benchmark 兼容路径    | `ln -sfn $DIGITAL_HUMAN_HOME/opentalking/models/quicktalk $DIGITAL_HUMAN_HOME/models/quicktalk` |
| 低显存配置            | `resolution=160/128`、`batch=1`、`HuBERT=cpu`                |

---

## 12. 最终检查清单

跑 benchmark 前，建议逐项检查：

```bash
# WSL2 GPU
nvidia-smi

# OpenTalking 环境
cd $DIGITAL_HUMAN_HOME/opentalking
source .venv/bin/activate
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"

# QuickTalk 权重
ls -lh models/quicktalk/checkpoints/quicktalk.pth
ls -lh models/quicktalk/checkpoints/chinese-hubert-large/pytorch_model.bin
ls -lh models/quicktalk/checkpoints/auxiliary/models/buffalo_l/det_10g.onnx

# OmniRT 环境
cd $DIGITAL_HUMAN_HOME/omnirt
source .venv/bin/activate
which omnirt
omnirt --help

# 前端/基础工具
ffmpeg -version
node --version
npm --version
```

如果这些都通过，再运行：

```bash
cd $DIGITAL_HUMAN_HOME/opentalking
source .venv/bin/activate
bash scripts/run_opentalking_e2e_benchmark.sh \
  --tester lyf \
  --model quicktalk \
  --backend omnirt \
  --gpu-index 0 \
  --timeout 300
```

---

## 13. 总结

Windows 上部署 OpenTalking + OmniRT + QuickTalk，推荐把运行环境放在 WSL2 中：

```text
Windows Host
  └── WSL2 Ubuntu
        ├── OpenTalking .venv
        ├── OmniRT .venv
        ├── QuickTalk checkpoints
        ├── OmniRT QuickTalk runtime
        └── E2E Benchmark
```

这条路线的优点是：

- 与官方 bash 脚本更兼容；
- 方便使用 Linux 工具链；
- CUDA 可以通过 WSL2 正常访问 RTX 3050；
- OpenTalking 和 OmniRT 环境相互隔离，排错更清晰；
- 从环境配置到完整 E2E benchmark 的路径完整可复现。
