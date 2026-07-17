# Wav2Lip

## 什么时候使用 Wav2Lip

Wav2Lip 适合快速验证口型同步、图片 Avatar、短视频 Avatar 和本地轻量 Demo。它的部署成本相对低，资产准备路径清晰，是 OpenTalking 中最适合做第一条真实模型链路的模型之一。

不建议把 Wav2Lip 作为高质量直播数字人的唯一选择。它更适合验证链路、轻量口播、低成本 Avatar 预览。

## 要求

- Python 依赖中包含 Wav2Lip 相关 extra。
- 模型权重包含 `wav2lip384.pth` 或兼容 checkpoint。
- 需要 `s3fd.pth` 做人脸检测。
- 推荐 NVIDIA GPU；CPU 只适合功能验证。
- Avatar 使用 OpenTalking 通用形象流程；Wav2Lip 推理时会按需使用参考图、预处理帧或可检测的人脸区域。

## 准备权重

默认模型目录：

```text
./avatar_models/wav2lip
```

可调整：

```bash
export OPENTALKING_WAV2LIP_MODEL_ROOT=./avatar_models/wav2lip
export OPENTALKING_WAV2LIP_CHECKPOINT=./avatar_models/wav2lip/wav2lip384.pth
```

`s3fd.pth` 可以放在：

```text
./avatar_models/wav2lip/s3fd.pth
```

## 准备 Avatar 派生产物

如需提前为 Wav2Lip 生成图片帧资产：

```bash
uv run python scripts/prepare_wav2lip_image_asset.py \
  --source-image ./assets/avatar.png \
  --out ./examples/avatars/my-wav2lip \
  --avatar-id my-wav2lip \
  --name "My Wav2Lip Avatar"
```

如需提前为 Wav2Lip 生成视频帧资产：

```bash
uv run python scripts/prepare_wav2lip_video_asset.py \
  --source-video ./assets/avatar.mp4 \
  --out ./examples/avatars/my-wav2lip-video \
  --avatar-id my-wav2lip-video \
  --name "My Wav2Lip Video Avatar"
```

## 可调整参数

### 运行时参数

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `OPENTALKING_WAV2LIP_BACKEND` | `local` | 模型后端，可设为 `local` 或 `omnirt` |
| `OPENTALKING_WAV2LIP_DEVICE` | `cuda` | Wav2Lip 推理设备 |
| `OPENTALKING_WAV2LIP_MODEL_ROOT` | `./avatar_models/wav2lip` | 权重目录 |
| `OPENTALKING_WAV2LIP_CHECKPOINT` | `wav2lip384.pth` | 指定 checkpoint |
| `OPENTALKING_WAV2LIP_WORK_DIR` | 系统临时目录 | 中间文件目录 |
| `OPENTALKING_WAV2LIP_CPU_THREADS` | `4` | CPU / OpenCV 线程数 |
| `OPENTALKING_WAV2LIP_INTEROP_THREADS` | `1` | PyTorch interop 线程数 |

### 性能与画质参数

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `OPENTALKING_WAV2LIP_BATCH_SIZE` | `8` | 推理 batch size，增大可能提升吞吐但占用显存 |
| `OPENTALKING_WAV2LIP_JPEG_QUALITY` | `85` | 帧编码质量 |
| `OPENTALKING_WAV2LIP_PADS` | `0,10,0,0` | 人脸裁剪 padding |
| `OPENTALKING_WAV2LIP_POSTPROCESS_MODE` | `easy_improved` | 后处理模式 |
| `OPENTALKING_WAV2LIP_EASY_MASK_DILATION` | `2.5` | easy 后处理遮罩扩张 |
| `OPENTALKING_WAV2LIP_EASY_MASK_FEATHERING` | `2.0` | easy 后处理羽化 |

支持的后处理模式：

- `basic`
- `opentalking_improved`
- `easy_improved`
- `easy_enhanced`

### 口型平滑参数

这些参数来自模型 runtime config，可写在 `configs/default.yaml` 的 `models.wav2lip` 下，或用环境变量覆盖：

| 配置项 | 环境变量 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `use_neural` | `OPENTALKING_WAV2LIP_USE_NEURAL` | `true` | 是否使用神经网络推理 |
| `force_static` | `OPENTALKING_WAV2LIP_FORCE_STATIC` | `true` | 是否强制静态参考 |
| `min_context_frames` | `OPENTALKING_WAV2LIP_MIN_CONTEXT_FRAMES` | `8` | 最小上下文帧数 |
| `stream_batch_size` | `OPENTALKING_WAV2LIP_STREAM_BATCH_SIZE` | `8` | 流式处理 batch |
| `infer_frame_stride` | `OPENTALKING_WAV2LIP_INFER_FRAME_STRIDE` | `1` | 推理帧步长 |
| `face_box_scale` | `OPENTALKING_WAV2LIP_FACE_BOX_SCALE` | `0.86` | 人脸框缩放 |
| `attack` | `OPENTALKING_WAV2LIP_ATTACK` | `0.72` | 口型能量上升平滑 |
| `release` | `OPENTALKING_WAV2LIP_RELEASE` | `0.38` | 口型能量下降平滑 |

## 配置 Backend

### local

```bash
bash scripts/start_unified.sh --backend local --model wav2lip
```

或：

```bash
export OPENTALKING_WAV2LIP_BACKEND=local
```

### omnirt

```bash
bash scripts/start_unified.sh \
  --backend omnirt \
  --model wav2lip \
  --omnirt http://127.0.0.1:9000
```

## 启动服务

```bash
bash scripts/start_unified.sh --backend local --model wav2lip
```

## 验证

1. 打开 WebUI。
2. 选择 Wav2Lip Avatar。
3. 选择 `wav2lip` 模型。
4. 发送短文本，确认首帧、音频和口型输出。

## 故障排查

### 提示缺少 checkpoint

检查 `OPENTALKING_WAV2LIP_MODEL_ROOT` 和 `OPENTALKING_WAV2LIP_CHECKPOINT`。

### 提示缺少 `s3fd.pth`

把 `s3fd.pth` 放到 `models/wav2lip/` 下。

### 嘴部区域不自然

尝试调整 `OPENTALKING_WAV2LIP_PADS`、后处理模式和 Avatar 参考图。参考图越清晰、脸部角度越正，效果越稳定。
