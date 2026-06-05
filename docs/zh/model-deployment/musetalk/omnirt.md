# MuseTalk with OmniRT

适用：你希望 MuseTalk runtime、MuseTalk WebSocket backend 和 OmniRT gateway 独立于 OpenTalking 主进程运行。OpenTalking 只连接 OmniRT endpoint。

## 1. 准备 OmniRT 环境

```bash title="终端"
export DIGITAL_HUMAN_HOME=/path/to/digital_human
export OMNIRT_REPO="$DIGITAL_HUMAN_HOME/omnirt"
export OMNIRT_HOME="$DIGITAL_HUMAN_HOME/omnirt/.omnirt"

# 网络较慢时先设置镜像；缓存和临时目录放在同一个数据盘，避免跨盘拷贝和 /tmp 空间不足。
export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export UV_HTTP_TIMEOUT=300
export UV_CACHE_DIR="$DIGITAL_HUMAN_HOME/.cache/uv"
export PIP_CACHE_DIR="$DIGITAL_HUMAN_HOME/.cache/pip"
export TMPDIR="$DIGITAL_HUMAN_HOME/tmp"
mkdir -p "$UV_CACHE_DIR" "$PIP_CACHE_DIR" "$TMPDIR"

cd "$OMNIRT_REPO"
uv sync --extra server --python 3.11
```

首次 `uv sync` 可能下载 CUDA 版 PyTorch、cuDNN、cuBLAS、NCCL、Triton 等数 GB 依赖。后续重建 venv 会复用 `$UV_CACHE_DIR`，明显快于首次部署。

## 2. 准备权重

`start_omnirt_musetalk.sh` 默认读取 `$OMNIRT_MODEL_ROOT`：

```bash title="终端"
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models/musetalk-v15"
# 如果全局 OMNIRT_MODEL_ROOT 已经用于其它模型，也可以只为 MuseTalk 覆盖：
# export OMNIRT_MUSETALK_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models/musetalk-v15"
```

`$OMNIRT_MODEL_ROOT` 必须直接包含下面这些子目录。如果你的权重放在 `/opt/models/MuseTalk1.5` 这种目录，就把 `OMNIRT_MODEL_ROOT` 指到这一层，而不是它的父目录。

目录结构与 local 模式一致：

```text
$OMNIRT_MODEL_ROOT/
  musetalk/
    musetalk.json
    pytorch_model.bin
  sd-vae-ft-mse/
    config.json
    diffusion_pytorch_model.bin 或 diffusion_pytorch_model.safetensors
  whisper/
    tiny.pt
  dwpose/
    dw-ll_ucoco_384.pth
  face-parse-bisenet/
    79999_iter.pth
```

如果你用官方 MuseTalk `download_weights.sh` 下载权重，通常需要把 `sd-vae` 整理为 `sd-vae-ft-mse`，把 `face-parse-bisent` 整理为 `face-parse-bisenet`：

```bash title="终端"
cd "$OMNIRT_MODEL_ROOT"
ln -s sd-vae sd-vae-ft-mse 2>/dev/null || true
ln -s face-parse-bisent face-parse-bisenet 2>/dev/null || true
```

Whisper 这里要求 OpenAI `openai-whisper` 的 `tiny.pt` 文件，不要把 Hugging Face `pytorch_model.bin` 直接改名顶替。

## 3. 准备 MuseTalk 源码 checkout

首次执行启动脚本时，OmniRT 会尝试把官方 MuseTalk 仓克隆到 `$OMNIRT_HOME/model-repos/MuseTalk`。如果服务器访问 GitHub 不稳定，可以先在有网络的机器 clone 后同步过来，或直接把该路径软链到已有官方 MuseTalk checkout：

```bash title="终端"
mkdir -p "$OMNIRT_HOME/model-repos"
ln -s /path/to/MuseTalk "$OMNIRT_HOME/model-repos/MuseTalk"
# 该目录下必须包含 musetalk/ Python package。
```

不要把 `$OMNIRT_HOME/model-repos/MuseTalk` 指向权重目录；源码 checkout 和 `$OMNIRT_MODEL_ROOT` 是两个不同目录。

## 4. 启动 OmniRT MuseTalk

```bash title="终端"
export OPENTALKING_HOME="$DIGITAL_HUMAN_HOME/opentalking"
# 多卡机器可按需限制可见卡，避免误选不可用 GPU。
export CUDA_VISIBLE_DEVICES=0

cd "$OPENTALKING_HOME"
bash scripts/quickstart/start_omnirt_musetalk.sh --device cuda --port 9000 --musetalk-port 8766
```

如果 `$OMNIRT_HOME/model-repos/MuseTalk` 已经指向可用源码 checkout，且服务器访问 GitHub 不稳定，可以加 `--no-update` 跳过 `git fetch`：

```bash title="终端"
bash scripts/quickstart/start_omnirt_musetalk.sh --device cuda --port 9000 --musetalk-port 8766 --no-update
```

脚本会安装 MuseTalk runtime、启动 MuseTalk WS backend、启动 OmniRT audio2video gateway，并等待 `/v1/audio2video/models` 报告 `musetalk`。首次安装会创建 `$OMNIRT_HOME/runtimes/musetalk/cuda/venv`。MuseTalk CUDA runtime 固定使用 Python 3.10、PyTorch 2.0.1 + cu118、diffusers 0.30.2、transformers 4.39.2、accelerate 0.28.0 这组与官方 MuseTalk 1.5 兼容的依赖；不要升级到较新的 diffusers / transformers，否则会触发 `torch.xpu` 或 `torch.float8_e4m3fn` 这类与 torch 2.0.1 不兼容的导入错误。如果 `download.pytorch.org` 访问不稳定，先在可联网机器准备 wheel cache 或复用已验证的 runtime venv，再重新执行本步骤。

脚本也会继承第 1 节的 `UV_CACHE_DIR`、`PIP_CACHE_DIR` 和 `TMPDIR`。不要把这些缓存放到空间紧张的系统盘 `/tmp`；MuseTalk runtime 首次安装会下载 PyTorch cu118、Triton、OpenMMLab 等 wheel，网络差时可能耗时较久。

## 5. 启动 OpenTalking

```bash title="终端"
cd "$OPENTALKING_HOME"
bash scripts/start_unified.sh \
  --backend omnirt \
  --model musetalk \
  --omnirt http://127.0.0.1:9000 \
  --api-port 8000 \
  --web-port 5173
```

## 6. 启动或重启前端

上一步的 `scripts/start_unified.sh` 已经会启动 WebUI。若只需要重启前端，或后端已经在 `8000` 端口运行，另开终端执行：

```bash title="终端"
cd "$OPENTALKING_HOME"
bash scripts/quickstart/start_frontend.sh --api-port 8000 --web-port 5173 --host 0.0.0.0
```

远程服务器部署时，把本地浏览器端口映射到服务器 `5173`，再打开 `http://127.0.0.1:5173`。

## 7. 验证

```bash title="终端"
curl -fsS http://127.0.0.1:9000/v1/audio2video/models | python3 -m json.tool
curl -s http://127.0.0.1:8000/models | python3 -m json.tool
```

期望 OpenTalking 侧状态为：

```json
{"id":"musetalk","backend":"omnirt","connected":true,"reason":"omnirt"}
```
