# MuseTalk

## 什么时候使用 MuseTalk

MuseTalk 适合追求较高口型同步质量、使用视频 Avatar、希望模型服务与 OpenTalking 解耦的场景。当前更推荐通过 OmniRT 或 direct_ws 接入。

## 要求

- 推荐 NVIDIA GPU。
- 模型权重和依赖建议放在独立推理服务中。
- Avatar 需要清晰参考图或预处理视频帧。
- 需要稳定的 WebSocket / OmniRT 服务。

## 准备权重

MuseTalk 权重通常在 OmniRT 或独立模型服务中准备。OpenTalking 侧主要配置模型后端和 endpoint。

## 准备 Avatar

建议使用清晰、稳定的人脸素材。若 Avatar 包含预处理帧，应确保 `manifest.json` 中的帧路径、FPS 和尺寸信息正确。

## 可调整参数

这些参数可写入 `configs/default.yaml` 的 `models.musetalk`，也可以使用环境变量覆盖。

| 配置项 | 环境变量 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `context_ms` | `OPENTALKING_MUSETALK_CONTEXT_MS` | `320.0` | 音频上下文窗口 |
| `overlap_frames` | `OPENTALKING_MUSETALK_OVERLAP_FRAMES` | `0` | 分块帧重叠 |
| `silence_gate` | `OPENTALKING_MUSETALK_SILENCE_GATE` | `0.04` | 静音门限 |
| `smooth_crop` | `OPENTALKING_MUSETALK_SMOOTH_CROP` | `false` | 是否平滑裁剪区域 |
| `energy_gain` | `OPENTALKING_MUSETALK_ENERGY_GAIN` | `0.0` | 音频能量增益 |
| `energy_attack` | `OPENTALKING_MUSETALK_ENERGY_ATTACK` | `0.28` | 能量上升平滑 |
| `energy_release` | `OPENTALKING_MUSETALK_ENERGY_RELEASE` | `0.16` | 能量下降平滑 |
| `eye_align` | `OPENTALKING_MUSETALK_EYE_ALIGN` | `false` | 是否启用眼部对齐 |
| `prepared_compose` | `OPENTALKING_MUSETALK_PREPARED_COMPOSE` | 空 | 预处理合成配置 |
| `prebuffer_chunks` | `OPENTALKING_MUSETALK_PREBUFFER_CHUNKS` | `3` | 播放前预缓冲块数 |

## 配置 Backend

OmniRT：

```bash
bash scripts/start_unified.sh \
  --backend omnirt \
  --model musetalk \
  --omnirt http://127.0.0.1:9000
```

Direct WebSocket：

```yaml
models:
  musetalk:
    backend: direct_ws
    ws_url: ws://127.0.0.1:8765
```

## 启动服务

先启动 MuseTalk 推理服务或 OmniRT，再启动 OpenTalking：

```bash
bash scripts/start_unified.sh --backend omnirt --model musetalk --omnirt http://127.0.0.1:9000
```

## 验证

WebUI 中选择 MuseTalk 兼容 Avatar 和 `musetalk` 模型，发送短文本，观察首帧时间、口型同步和帧稳定性。

## 故障排查

### 模型显示未连接

检查 OmniRT 模型列表或 direct_ws endpoint 是否可访问。

### 画面抖动

检查 Avatar 素材、裁剪区域和 `smooth_crop`、`overlap_frames`、`prebuffer_chunks` 等配置。
