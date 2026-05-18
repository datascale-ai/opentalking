# 平台说明

本页说明不同系统环境下运行 OpenTalking 的推荐方式。第一次使用时，建议优先跑通
[快速开始](index.md) 中的 Mock 模式；当需要真实数字人渲染模型时，再根据 GPU/NPU
环境选择对应路径。

## 支持矩阵

| 平台 | 推荐用途 | 可用路径 | 说明 |
| --- | --- | --- | --- |
| macOS | 文档、前端、API、Mock 验证 | `mock` | 适合快速体验，不建议作为真实模型推理环境。 |
| Linux + CUDA | 真实模型验证与部署 | `mock`、`quicktalk`、`wav2lip`、`musetalk`、`omnirt` | 主要推荐环境。 |
| Linux + Ascend NPU | 私有化和 NPU 评估 | `mock`、部分 OmniRT / FlashTalk 路线 | 依赖 CANN、驱动和 `torch_npu` |

## macOS 注意事项

### 适合 mock / 前端 / API 开发

macOS 适合运行 Mock 模式、开发 WebUI、调试 API 和阅读文档。你可以用它验证 LLM、TTS、
字幕事件和 WebRTC 播放链路。

```bash
brew install python@3.11 node ffmpeg
uv sync --extra dev --python 3.11
```

### 不适合真实数字人模型

QuickTalk、MuseTalk、FlashTalk 等模型主要面向 CUDA GPU 或专用推理服务。macOS 上即使可以安装
部分 Python 依赖，也不建议作为真实视频生成路径；更推荐把模型部署到 Linux GPU 机器，
再通过 OpenTalking 连接远端推理服务。

### ffmpeg 安装

OpenTalking 会在 TTS 解码、音频处理和视频处理阶段使用 FFmpeg。macOS 上安装：

```bash
brew install ffmpeg
ffmpeg -version
```

## Linux + CUDA 注意事项

### 推荐用于真实模型

Linux + NVIDIA GPU 是当前最推荐的真实模型验证环境。Mock 跑通后，可以继续验证 QuickTalk、
Wav2Lip、本地模型 adapter 或 OmniRT 远端推理。

### CUDA / Driver / PyTorch 注意事项

先确认宿主机能看到 GPU：

```bash
nvidia-smi
```

再确认 Python 环境中的 PyTorch 是否可用：

```bash
python - <<'PY'
import torch
print("cuda available:", torch.cuda.is_available())
print("device count:", torch.cuda.device_count())
PY
```

如果 `torch.cuda.is_available()` 返回 `False`，通常需要检查 NVIDIA driver、CUDA runtime、
PyTorch wheel 和当前虚拟环境是否匹配。

### GPU 显存建议

| 路径 | 建议资源 | 说明 |
| --- | --- | --- |
| QuickTalk | 推荐 3090 / 4090 级别 | 适合作为第一条真实视频渲染路径。 |
| Wav2Lip | 8 GB+ 显存起步 | 适合轻量口型同步验证。 |
| FlashTalk / FlashHead | 4090 / A100 或多卡 | 推荐通过 OmniRT 或专用推理服务部署。 |

## Linux + Ascend NPU 注意事项

### CANN 环境

Ascend NPU 路径依赖宿主机驱动和 CANN。通常需要先 source 环境：

```bash
test -f /usr/local/Ascend/ascend-toolkit/set_env.sh && echo "CANN 已就绪"
source /usr/local/Ascend/ascend-toolkit/set_env.sh
npu-smi info
```

### torch_npu

`torch_npu` 需要与 PyTorch、驱动和 CANN 版本匹配。若导入失败，先确认 CANN 环境变量已生效：

```bash
python - <<'PY'
import torch
import torch_npu
print("torch:", torch.__version__)
print("torch_npu imported")
PY
```

### 适合的模型路线

Ascend 环境更适合企业私有化和高质量模型服务验证。目前建议把 OpenTalking 作为编排层运行，
把重型模型放在 OmniRT 或专用模型服务中。首次拉起和排错建议使用源码安装方式，让驱动、CANN、
模型日志和权重路径直接暴露在宿主机上。

## Windows / WSL 注意事项

### 推荐 WSL2

Windows 用户建议使用 WSL2 + Ubuntu。这样可以复用 Linux 下的 Python、Node.js、FFmpeg 和
Docker 生态，路径和命令也更接近文档。

原生 Windows 可以尝试 Mock 模式和前端开发，但不作为当前主要验证环境。真实模型相关依赖、
FFmpeg、GPU runtime 和部分 Python 包在 Windows 上更容易遇到兼容性问题。

## 国内源配置

### Python 镜像源

使用 `uv` 时可以配置：

```bash
export UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
uv sync --extra dev --python 3.11
```

使用 `pip` 时可以配置：

```bash
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
pip install -e ".[dev]"
```

### npm 镜像源

如果前端依赖安装较慢：

```bash
npm config set registry https://registry.npmmirror.com
cd apps/web
npm ci
```

### Hugging Face / ModelScope

Hugging Face 下载较慢时，可以临时设置镜像：

```bash
export HF_ENDPOINT=https://hf-mirror.com
```

如果模型在 ModelScope 有同步版本，也可以使用 ModelScope 下载后手动整理到文档要求的目录结构。

### 模型权重下载

模型权重建议放在仓库根目录的 `models/` 下，例如：

```text
models/
  quicktalk/
    checkpoints/
```

离线环境中，只要最终目录结构和文件名与对应模型文档一致，就不要求一定通过命令行下载。

## 常见平台问题

| 现象 | 可能原因 | 处理方式 |
| --- | --- | --- |
| `ffmpeg: not found` | 未安装 FFmpeg | macOS 使用 `brew install ffmpeg`；Ubuntu 使用 `apt install ffmpeg`。 |
| `npm ci` 失败 | Node.js 版本过低或网络不稳定 | 使用 Node.js 18+，必要时切换 npm 镜像。 |
| `torch.cuda.is_available()` 为 `False` | CUDA / driver / PyTorch 不匹配 | 检查 `nvidia-smi`、虚拟环境和 PyTorch 安装来源。 |
| `npu-smi: command not found` | CANN 环境未加载 | 执行 `source /usr/local/Ascend/ascend-toolkit/set_env.sh`。 |
| 模型权重找不到 | 路径或文件名不一致 | 对照模型文档运行 `stat` 检查关键文件。 |
