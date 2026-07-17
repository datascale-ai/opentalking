# QuickTalk

## 什么时候使用 QuickTalk

QuickTalk 适合快速实时口播和低延迟验证场景。相比 Wav2Lip，它更强调实时 worker
和音频特征提取链路。

如果你希望在本地快速拉起一个真实模型，而不是只跑 Mock，QuickTalk 是推荐路径之一。

## 要求

- 推荐 NVIDIA GPU。
- QuickTalk 本地资产目录需要包含 `checkpoints/`。
- 至少需要 `quicktalk.pth`、`repair.npy`、`chinese-hubert-large/` 和 InsightFace `auxiliary/models/buffalo_l/`。
- Avatar 走 OpenTalking 通用形象流程；QuickTalk 运行时需要的模板或缓存由部署命令、上传流程或会话初始化生成。

## 准备权重

完整下载命令见 [QuickTalk Local 部署](../../avatar_models/deployment/quicktalk-local.md)。本页只保留目录和配置要点。

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
      pytorch_model.bin
    auxiliary/models/buffalo_l/
      det_10g.onnx
```

## 准备 Avatar

使用 [Avatar 资产](../../avatar_models/avatar.md) 中的通用流程准备形象。QuickTalk 不要求
avatar manifest 绑定为专属类型；如果运行时需要固定模板视频，应在部署配置或会话初始化时
确保模板资源可访问。

## 可调整参数

### 运行时参数

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `OPENTALKING_QUICKTALK_BACKEND` | `omnirt` | 模型后端，可设为 `local` / `omnirt` |
| `OPENTALKING_TORCH_DEVICE` | `cuda:0` | 主推理设备 |
| `OPENTALKING_QUICKTALK_HUBERT_DEVICE` | 空 | HuBERT 单独使用的设备 |
| `OPENTALKING_QUICKTALK_ASSET_ROOT` | `models/quicktalk` | QuickTalk 权重资产根目录 |
| `OPENTALKING_QUICKTALK_TEMPLATE_VIDEO` | 空 | 可选固定模板视频路径 |
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

检查 `checkpoints/quicktalk.pth`、`repair.npy`、`chinese-hubert-large/pytorch_model.bin`、`auxiliary/models/buffalo_l/det_10g.onnx` 是否存在。

### 首次创建会话很慢

QuickTalk worker 构建和 face cache 生成可能耗时较长。后续命中 worker cache 会明显变快。

### 空闲时嘴部仍在动

调整 `OPENTALKING_QUICKTALK_IDLE_FRAME_INDEX` 或 `OPENTALKING_QUICKTALK_IDLE_FRAME_RANGE`，选择闭嘴状态更自然的模板帧。
