# MuseTalk with OmniRT

适用：你希望 MuseTalk runtime、MuseTalk WebSocket backend 和 OmniRT gateway 独立于 OpenTalking 主进程运行。OpenTalking 只连接 OmniRT endpoint。

## 1. 准备 OmniRT 环境

```bash title="终端"
export DIGITAL_HUMAN_HOME=/path/to/digital_human
export OMNIRT_REPO="$DIGITAL_HUMAN_HOME/omnirt"
export OMNIRT_HOME="$DIGITAL_HUMAN_HOME/omnirt/.omnirt"

# 网络较慢时先设置镜像。
export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export UV_HTTP_TIMEOUT=300

cd "$OMNIRT_REPO"
uv sync --extra server --python 3.11
```

## 2. 准备权重

`start_omnirt_musetalk.sh` 默认读取 `$OMNIRT_MODEL_ROOT`：

```bash title="终端"
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models/musetalk-v15"
```

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

脚本会安装 MuseTalk runtime、启动 MuseTalk WS backend、启动 OmniRT audio2video gateway，并等待 `/v1/audio2video/models` 报告 `musetalk`。首次安装会创建 `$OMNIRT_HOME/runtimes/musetalk/cuda/venv`，并从 PyPI 镜像和 PyTorch CUDA wheel 源（当前 CUDA 文档路径使用 cu124）安装依赖。如果 `download.pytorch.org` 访问不稳定，先在可联网机器准备 wheel cache 或复用已验证的 runtime venv，再重新执行本步骤。

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

## 6. 验证

```bash title="终端"
curl -fsS http://127.0.0.1:9000/v1/audio2video/models | jq
curl -s http://127.0.0.1:8000/models | jq ".statuses[] | select(.id==\"musetalk\")"
```

期望 OpenTalking 侧状态为：

```json
{"id":"musetalk","backend":"omnirt","connected":true,"reason":"omnirt"}
```
