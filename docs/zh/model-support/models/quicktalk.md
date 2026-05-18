# QuickTalk

## 什么时候使用 QuickTalk

QuickTalk 适合快速实时口播、低延迟验证和从图片快速生成数字人模板的场景。相比 Wav2Lip，它更强调实时 worker、模板视频和音频特征提取链路。

如果你希望在本地快速拉起一个真实模型，而不是只跑 Mock，QuickTalk 是推荐路径之一。

## 要求

- 推荐 NVIDIA GPU。
- QuickTalk 本地资产目录需要包含 `checkpoints/`。
- 至少需要 `quicktalk.pth` 或 `256.onnx`、`repair.npy`、`chinese-hubert-large/` 和 `auxiliary/` 或 `auxiliary_min/`。
- Avatar 需要 `quicktalk.template_video` 或可由上传图片生成模板视频。

## 准备权重

本地模式需要指定 QuickTalk asset root：

```bash
export OPENTALKING_QUICKTALK_ASSET_ROOT=/path/to/quicktalk
```

目录通常类似：

```text
quicktalk/
  checkpoints/
    quicktalk.pth
    repair.npy
    chinese-hubert-large/
    auxiliary/
```

## 准备 Avatar

Avatar manifest 中可以提供：

```json
{
  "metadata": {
    "quicktalk": {
      "asset_root": "/path/to/quicktalk",
      "template_video": "quicktalk/template_900.mp4"
    }
  }
}
```

WebUI 上传自定义图片时，OpenTalking 可以为 QuickTalk 生成静态模板视频，并移除旧 face cache。

## 可调整参数

### 运行时参数

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `OPENTALKING_QUICKTALK_BACKEND` | `omnirt` | 模型后端，可设为 `local` / `omnirt` |
| `OPENTALKING_TORCH_DEVICE` | `cuda:0` | 主推理设备 |
| `OPENTALKING_QUICKTALK_HUBERT_DEVICE` | 空 | HuBERT 单独使用的设备 |
| `OPENTALKING_QUICKTALK_ASSET_ROOT` | 从 Avatar metadata 读取 | QuickTalk 资产根目录 |
| `OPENTALKING_QUICKTALK_TEMPLATE_VIDEO` | 从 Avatar metadata 读取 | 模板视频路径 |
| `OPENTALKING_QUICKTALK_FACE_CACHE_DIR` | `asset_root/.face_cache_v3` | 人脸缓存目录 |
| `OPENTALKING_QUICKTALK_WORKER_CACHE` | `1` | 是否启用 worker 缓存 |

### 画面与模板参数

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `OPENTALKING_QUICKTALK_OUTPUT_TRANSFORM` | `bgr` | 输出帧格式转换 |
| `OPENTALKING_QUICKTALK_SCALE_H` | `1.6` | 人脸区域高度缩放 |
| `OPENTALKING_QUICKTALK_SCALE_W` | `3.6` | 人脸区域宽度缩放 |
| `OPENTALKING_QUICKTALK_RESOLUTION` | `256` | 模型输入分辨率 |
| `OPENTALKING_QUICKTALK_MAX_TEMPLATE_SECONDS` | 空 | 限制模板视频读取时长 |
| `OPENTALKING_QUICKTALK_NECK_FADE_START` | `0.72` | 颈部融合开始位置 |
| `OPENTALKING_QUICKTALK_NECK_FADE_END` | `0.88` | 颈部融合结束位置 |

### Idle 参数

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `OPENTALKING_QUICKTALK_IDLE_FRAME_INDEX` | `0` | 空闲时固定使用的模板帧 |
| `OPENTALKING_QUICKTALK_IDLE_FRAME_RANGE` | 空 | 空闲帧循环范围，如 `10:20` |

### 模型后端参数

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `OPENTALKING_QUICKTALK_MODEL_BACKEND` | `auto` | QuickTalk 内部模型加载策略 |

## 配置 Backend

local：

```bash
bash scripts/start_unified.sh --backend local --model quicktalk
```

OmniRT：

```bash
bash scripts/start_unified.sh \
  --backend omnirt \
  --model quicktalk \
  --omnirt http://127.0.0.1:9000
```

## 启动服务

```bash
bash scripts/start_unified.sh --backend local --model quicktalk
```

## 验证

可以用 benchmark 检查模型性能：

```bash
uv run opentalking-quicktalk-bench \
  --asset-root ./examples/avatars/quicktalk-daytime \
  --template-video ./examples/avatars/quicktalk-daytime/quicktalk/template_900.mp4 \
  --audio ./assets/test.wav \
  --output ./outputs/quicktalk-bench.mp4 \
  --device cuda:0
```

也可以在 WebUI 中选择 `quicktalk` 模型并发送短文本验证。

## 故障排查

### 提示资产不完整

检查 `checkpoints/quicktalk.pth` 或 `checkpoints/256.onnx`、`repair.npy`、`chinese-hubert-large/`、`auxiliary/` 是否存在。

### 首次创建会话很慢

QuickTalk worker 构建和 face cache 生成可能耗时较长。后续命中 worker cache 会明显变快。

### 空闲时嘴部仍在动

调整 `OPENTALKING_QUICKTALK_IDLE_FRAME_INDEX` 或 `OPENTALKING_QUICKTALK_IDLE_FRAME_RANGE`，选择闭嘴状态更自然的模板帧。
