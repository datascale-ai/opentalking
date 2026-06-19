# Wav2Lip Local 单机部署

适用：你希望在单机消费级 GPU 上先跑通更轻量的口型同步效果，并且不想一开始就引入独立推理服务。OpenTalking 内置 `wav2lip` local adapter 和 runtime。

## 1. 安装本地模型依赖

```bash title="终端"
export DIGITAL_HUMAN_HOME=/path/to/digital_human
export OPENTALKING_HOME="$DIGITAL_HUMAN_HOME/opentalking"

# 网络较慢时先设置镜像。
export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export UV_HTTP_TIMEOUT=300
export UV_LINK_MODE=copy

cd "$OPENTALKING_HOME"
uv sync --extra dev --extra models --python 3.11
source .venv/bin/activate
```

## 2. 准备 Wav2Lip 权重

```bash title="终端"
export OPENTALKING_WAV2LIP_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models/wav2lip"
mkdir -p "$OPENTALKING_WAV2LIP_MODEL_ROOT"

hf download Pypa/wav2lip384 wav2lip384.pth --local-dir "$OPENTALKING_WAV2LIP_MODEL_ROOT"
hf download rippertnt/wav2lip s3fd.pth --local-dir "$OPENTALKING_WAV2LIP_MODEL_ROOT"
```

无法直连 Hugging Face 时，可以先在可联网机器下载，再同步到同样目录。不要把大模型权重提交到 OpenTalking 仓库。

## 3. 启动 OpenTalking

```bash title="终端"
export OPENTALKING_WAV2LIP_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models/wav2lip"
export OPENTALKING_WAV2LIP_DEVICE=cuda
export OPENTALKING_WAV2LIP_BATCH_SIZE=16
export OPENTALKING_WAV2LIP_MAX_LONG_EDGE=832
export OPENTALKING_WAV2LIP_FACE_DET_DEVICE=cpu

cd "$OPENTALKING_HOME"
bash scripts/start_unified.sh --backend local --model wav2lip --api-port 8000 --web-port 5173
```

打开 `http://localhost:5173`，选择内置 Wav2Lip 形象和 `wav2lip` 模型。首次加载会初始化 checkpoint、S3FD 人脸检测器和形象缓存，可能需要几十秒。

local Wav2Lip 默认使用 `easy_improved` 后处理。前端提供 `auto`、`basic`、`opentalking_improved`、`easy_improved` 四个普通选项；后端仍接受 `easy_enhanced` 用于 API/env 测试，但该模式需要安装 GFPGAN 并通过 `OPENTALKING_WAV2LIP_GFPGAN_CHECKPOINT` 指向 checkpoint。

## 4. 启动或重启前端

上一步的 `scripts/start_unified.sh` 已经会启动 WebUI。若只需要重启前端，或后端已经在 `8000` 端口运行，另开终端执行：

```bash title="终端"
cd "$OPENTALKING_HOME"
bash scripts/quickstart/start_frontend.sh --api-port 8000 --web-port 5173 --host 0.0.0.0
```

远程服务器部署时，把本地浏览器端口映射到服务器 `5173`，再打开 `http://127.0.0.1:5173`。

## 5. 调优参数

| 参数 | 默认建议 | 作用 |
|------|----------|------|
| `OPENTALKING_WAV2LIP_DEVICE` | `cuda` | 指定 runtime 设备；调试时可设 `cpu`。 |
| `OPENTALKING_WAV2LIP_BATCH_SIZE` | `16` | 显存紧张时调低。 |
| `OPENTALKING_WAV2LIP_MAX_LONG_EDGE` | `832` | 控制输入帧长边，降低延迟。 |
| `OPENTALKING_WAV2LIP_JPEG_QUALITY` | `85` | 输出帧 JPEG 质量。 |
| `OPENTALKING_PREWARM_AVATARS` | `singer` | 服务启动时提前预热形象。 |

## 6. 验证

```bash title="终端"
curl -s http://127.0.0.1:8000/models | python3 -m json.tool
```

期望：

```json
{"id":"wav2lip","backend":"local","connected":true,"reason":"local_runtime"}
```
