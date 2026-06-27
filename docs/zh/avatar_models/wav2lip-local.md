# Wav2Lip Local 单机部署

适用：你希望在单机消费级 GPU 上先跑通更轻量的口型同步效果，并且不想一开始就引入独立推理服务。当前 OpenTalking 内置 `wav2lip` local adapter 和 runtime，只需要安装模型依赖并准备 Wav2Lip 权重。

#### 1. 安装本地模型依赖

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
uv sync --extra dev --extra models --python 3.11
source .venv/bin/activate
```

#### 2. 准备 Wav2Lip 权重

权重建议放在仓库根目录 `models/wav2lip/` 下：

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
mkdir -p models/wav2lip

# 安装 Hugging Face CLI（如果前面已经安装过，可跳过）。
uv pip install -U "huggingface_hub[cli]"

# Wav2Lip 384 主模型。
hf download Pypa/wav2lip384 \
  wav2lip384.pth \
  --local-dir models/wav2lip

# S3FD 人脸检测模型。
hf download rippertnt/wav2lip \
  s3fd.pth \
  --local-dir models/wav2lip
```

整理后目录应类似：

```text
models/
  wav2lip/
    wav2lip384.pth
    s3fd.pth
```

检查关键文件：

```bash
stat models/wav2lip/wav2lip384.pth
stat models/wav2lip/s3fd.pth
```

如果服务器无法直连 Hugging Face，也可以先在可联网机器下载，再通过 `rsync` 或离线包同步到同样的 `models/wav2lip/` 目录。

#### 3. 启动 OpenTalking（推理后端为 Wav2Lip）

```bash
export OPENTALKING_WAV2LIP_MODEL_ROOT="$DIGITAL_HUMAN_HOME/opentalking/models/wav2lip"
export OPENTALKING_WAV2LIP_DEVICE=cuda
export OPENTALKING_WAV2LIP_BATCH_SIZE=16
export OPENTALKING_WAV2LIP_MAX_LONG_EDGE=832
export OPENTALKING_WAV2LIP_FACE_DET_DEVICE=cpu

cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/start_unified.sh --backend local --model wav2lip --api-port 8210 --web-port 5280
```

打开 `http://localhost:5280`，选择一个可用形象和 `wav2lip` 模型，然后开始对话。若不指定 `--web-port`，默认前端地址为 `http://localhost:5173`。首次加载会初始化 Wav2Lip checkpoint、S3FD 人脸检测器和形象缓存，可能需要几十秒。

local Wav2Lip 默认使用 `easy_improved` 后处理。前端提供 `auto`、`basic`、`opentalking_improved`、`easy_improved` 四个普通选项；后端仍接受 `easy_enhanced` 用于 API/env 测试，但该模式需要安装 GFPGAN 并通过 `OPENTALKING_WAV2LIP_GFPGAN_CHECKPOINT` 指向 checkpoint。

#### 4. Wav2Lip 单机调优

如果显存紧张或首帧太慢，优先调这些参数：

| 参数 | 默认建议 | 作用 |
| --- | --- | --- |
| `OPENTALKING_WAV2LIP_DEVICE` | `cuda` | 指定 Wav2Lip runtime 设备；调试时可设 `cpu` |
| `OPENTALKING_WAV2LIP_BATCH_SIZE` | `16` | 与 OmniRT CUDA quickstart 默认值一致；显存紧张时再调低 |
| `OPENTALKING_WAV2LIP_MAX_LONG_EDGE` | `832` | 与 OmniRT CUDA quickstart 默认值一致，让渲染延迟更接近实时；只有优先保留原始分辨率时才设 `0` |
| `OPENTALKING_WAV2LIP_JPEG_QUALITY` | `85` | 输出帧 JPEG 质量，越高画面越好但带宽更大 |
| `OPENTALKING_PREWARM_AVATARS` | `singer` | 服务启动时提前预热常用形象 |
