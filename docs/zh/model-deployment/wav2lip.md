# Wav2Lip

Wav2Lip 支持 `local` 和 `omnirt` 两种部署方式。当前推荐把它作为第一个真实 talking-head 验证模型：权重少、启动路径清晰，适合先确认 OpenTalking 的音频到视频链路。

| 项 | 值 |
|----|----|
| 模型 ID | `wav2lip` |
| Backend | `local`、`omnirt`、兼容 `direct_ws` |
| 仓库默认值 | `local` |
| 推荐起步 | [Wav2Lip Local](wav2lip/local.md) |

## 选择哪种模式

| 模式 | 适合场景 | 入口 |
|------|----------|------|
| `local` | 单机消费级 GPU 或 CPU 调试，不想先部署独立推理服务。 | [Wav2Lip Local](wav2lip/local.md) |
| `omnirt` | 希望 Wav2Lip 由独立 OmniRT 进程托管，或者评估 CUDA/NPU 运行时隔离。 | [Wav2Lip with OmniRT](wav2lip/omnirt.md) |

## 权重目录

```text
wav2lip/
  wav2lip384.pth
  s3fd.pth
```

local 模式默认放在 `$OPENTALKING_HOME/models/wav2lip/`；OmniRT 模式默认放在 `$OMNIRT_MODEL_ROOT/wav2lip/`。

## 相关教程

- [Wav2Lip Local](wav2lip/local.md)
- [Wav2Lip with OmniRT](wav2lip/omnirt.md)
- [Talking-head 模型](talking-head/index.md)
