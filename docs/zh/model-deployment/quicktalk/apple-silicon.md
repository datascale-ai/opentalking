# Apple Silicon 上运行 QuickTalk

本页用于在 Apple Silicon macOS 上本地运行 QuickTalk。它适合开发、演示和集成验证；如果需要稳定 25fps 实时输出，仍建议使用 [QuickTalk Local 单机部署](local.md) 中的 Linux CUDA 路径，或把 QuickTalk 放到 OmniRT 后面运行。

## 1. 安装依赖

```bash title="终端"
brew install python@3.11 node uv

# 可选。不安装时 OpenTalking 可以回退到 imageio-ffmpeg。
brew install ffmpeg
```

拉取 OpenTalking，并使用 CPU/macOS extra 创建环境：

```bash title="终端"
git clone https://github.com/OpenTalker/opentalking.git
cd opentalking

export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export UV_HTTP_TIMEOUT=300
export UV_LINK_MODE=copy

uv sync --extra dev --extra models --extra quicktalk-cpu --python 3.11
source .venv/bin/activate
```

不要在 Apple Silicon 上安装 `quicktalk-cuda`。`onnxruntime-gpu` 没有 macOS arm64 wheel。

## 2. 下载 QuickTalk 资产

下载 QuickTalk 权重和 HuBERT 文件：

```bash title="终端"
mkdir -p models/quicktalk/checkpoints

hf download datascale-ai/quicktalk \
  quicktalk.pth \
  repair.npy \
  chinese-hubert-large/config.json \
  chinese-hubert-large/preprocessor_config.json \
  chinese-hubert-large/pytorch_model.bin \
  --local-dir models/quicktalk/checkpoints
```

下载 InsightFace `buffalo_l` 到 QuickTalk auxiliary 目录：

```bash title="终端"
mkdir -p /tmp/opentalking-insightface \
  models/quicktalk/checkpoints/auxiliary/models/buffalo_l

curl -L \
  -o /tmp/opentalking-insightface/buffalo_l.zip \
  https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip

unzip -q -o /tmp/opentalking-insightface/buffalo_l.zip \
  -d /tmp/opentalking-insightface
rsync -a /tmp/opentalking-insightface/buffalo_l/ \
  models/quicktalk/checkpoints/auxiliary/models/buffalo_l/
```

最终目录应为：

```text
models/quicktalk/
  checkpoints/
    quicktalk.pth
    repair.npy
    chinese-hubert-large/
      config.json
      preprocessor_config.json
      pytorch_model.bin
    auxiliary/models/buffalo_l/
      *.onnx
```

检查必需文件：

```bash title="终端"
stat models/quicktalk/checkpoints/quicktalk.pth
stat models/quicktalk/checkpoints/repair.npy
stat models/quicktalk/checkpoints/chinese-hubert-large/pytorch_model.bin
stat models/quicktalk/checkpoints/auxiliary/models/buffalo_l/det_10g.onnx
```

## 3. 配置 `.env`

如果还没有 `.env`，先创建：

```bash title="终端"
cp .env.example .env
```

设置这些值：

```env title=".env"
OPENTALKING_DEFAULT_MODEL=quicktalk
OPENTALKING_FFMPEG_BIN=
OPENTALKING_QUICKTALK_BACKEND=local
OPENTALKING_QUICKTALK_ASSET_ROOT=./models/quicktalk
OPENTALKING_QUICKTALK_MODEL_BACKEND=auto
OPENTALKING_QUICKTALK_WORKER_CACHE=1

# 可选。不设置时 OpenTalking 会在 PyTorch MPS 可用时选择 mps，
# 否则回退 cpu。
OPENTALKING_QUICKTALK_DEVICE=mps

# Apple Silicon 默认值。保持 12，让每个生成 chunk 有足够音频预算。
OPENTALKING_QUICKTALK_SLICE_LEN=12

# 长文本可选。把输出从模型原生 25fps 降到 14fps，
# 让 MPS 生成速度更接近播放速度。
OPENTALKING_QUICKTALK_FPS=14
```

`OPENTALKING_FFMPEG_BIN=` 保持为空时，OpenTalking 会先找系统 `ffmpeg`，找不到再回退到 `imageio-ffmpeg`。

## 4. 检查本地环境

```bash title="终端"
python - <<'PY'
from pathlib import Path
import torch
import onnxruntime as ort
from opentalking.models.quicktalk.runtime_v2 import ensure_ffmpeg

root = Path("models/quicktalk/checkpoints")
for path in [
    root / "quicktalk.pth",
    root / "repair.npy",
    root / "chinese-hubert-large/pytorch_model.bin",
    root / "auxiliary/models/buffalo_l/det_10g.onnx",
]:
    print(path, path.exists())
print("mps:", torch.backends.mps.is_available())
print("onnxruntime providers:", ort.get_available_providers())
print("ffmpeg:", ensure_ffmpeg())
PY
```

每个文件路径都应该输出 `True`。健康的 Apple Silicon PyTorch 环境里 `mps` 应该是 `True`；如果不可用，OpenTalking 可以回退到 CPU。

## 5. 启动 OpenTalking

```bash title="终端"
bash scripts/start_unified.sh \
  --backend local \
  --model quicktalk \
  --api-port 8210 \
  --web-port 5280
```

打开 `http://127.0.0.1:5280`，选择正脸清晰的 avatar，例如内置 `singer`，模型选择 `quicktalk`。首次运行会构建 avatar cache，后续可复用。

## 6. 验证实时数字人链路

```bash title="终端"
curl -s http://127.0.0.1:8210/health | python -m json.tool
curl -s http://127.0.0.1:8210/models | python -m json.tool
```

QuickTalk 模型应返回 `connected: true`，原因是 `local_runtime`。

创建会话并发送一句短文本：

```bash title="终端"
curl -s -X POST http://127.0.0.1:8210/sessions \
  -H 'Content-Type: application/json' \
  -d '{"avatar_id":"singer","model":"quicktalk","tts_provider":"edge"}' \
  | tee /tmp/opentalking-session.json | python -m json.tool

sid=$(python - <<'PY'
import json
print(json.load(open("/tmp/opentalking-session.json"))["session_id"])
PY
)

curl -s -X POST "http://127.0.0.1:8210/sessions/$sid/start" \
  -H 'Content-Type: application/json' \
  -d '{}' | python -m json.tool

curl -s -X POST "http://127.0.0.1:8210/sessions/$sid/speak" \
  -H 'Content-Type: application/json' \
  -d '{"text":"请用一句话确认 QuickTalk 已在 Mac 本地运行。","tts_provider":"edge"}' \
  | python -m json.tool
```

当 session 状态从 `speaking` 回到 `ready`，且 WebUI 中能看到所选 avatar 生成音频和视频帧，就表示本地实时数字人链路已经跑通。

## 性能说明

Apple Silicon 可以跑通本地链路，但不是推荐的实时生产目标。如果长文本卡顿，优先尝试：

```env title=".env"
OPENTALKING_QUICKTALK_SLICE_LEN=12
OPENTALKING_QUICKTALK_FPS=14
OPENTALKING_QUICKTALK_MAX_LONG_EDGE=720
```

这会用动作帧率或画面尺寸换取更顺滑的播放。需要稳定 25fps 实时输出时，请使用 Linux CUDA 或 OmniRT。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| `onnxruntime-gpu` 安装失败 | Apple Silicon 使用 `quicktalk-cpu`，不要安装 `quicktalk-cuda`。 |
| `ffmpeg` 找不到 | `.env` 中保持 `OPENTALKING_FFMPEG_BIN=`，或运行 `brew install ffmpeg`。 |
| MPS 出现 SVD CPU fallback 警告 | 属于 PyTorch MPS 的算子覆盖限制，可能影响速度，但通常不阻塞运行。 |
| 首次启动很慢 | 首次会加载 HuBERT、QuickTalk 和 avatar face cache；同一 avatar 后续会更快。 |
