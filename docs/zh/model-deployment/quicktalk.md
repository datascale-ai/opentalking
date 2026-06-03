# QuickTalk

QuickTalk 在当前仓库里支持两种部署模式：`local` 和 `omnirt`。commit 历史里已有 QuickTalk 通过 OmniRT audio2video 的接入，当前脚本也保留了 `scripts/quickstart/start_omnirt_quicktalk.sh`；因此它不是 local-only 模型。

| 项 | 值 |
|----|----|
| 模型 ID | `quicktalk` |
| Backend | `local`、`omnirt` |
| 仓库默认值 | `omnirt` |
| 推荐起步 | 单机验证用 `local`；需要推理服务隔离时用 `omnirt` |

## 选择哪种模式

| 模式 | 适合场景 | 入口 |
|------|----------|------|
| `local` | OpenTalking 单机直接加载 QuickTalk，调试自定义头像、本地 STT/TTS 和实时链路。 | [QuickTalk Local](quicktalk/local.md) |
| `omnirt` | 希望 QuickTalk 由独立 OmniRT 服务托管，OpenTalking 只做编排和 WebRTC。 | [QuickTalk with OmniRT](quicktalk/omnirt.md) |

## 权重目录

两种模式都需要 QuickTalk 权重、HuBERT 和 InsightFace 资产，但读取的资产根不同：local adapter 读取包含 `checkpoints/` 的资产目录，OmniRT quickstart 脚本读取 `$OMNIRT_MODEL_ROOT/quicktalk` 下的顶层文件。

```text
$OMNIRT_MODEL_ROOT/quicktalk/          # OmniRT 默认读取
  quicktalk.pth
  repair.npy
  chinese-hubert-large/
    config.json
    preprocessor_config.json
    pytorch_model.bin
  auxiliary/models/buffalo_l/
    det_10g.onnx
```

```text
$OPENTALKING_QUICKTALK_ASSET_ROOT/    # local adapter 默认读取
  checkpoints/
    quicktalk.pth 或 256.onnx
    repair.npy
    chinese-hubert-large/
      pytorch_model.bin
    auxiliary/models/buffalo_l/ 或 auxiliary_min/
      det_10g.onnx
```

如果本地 adapter 使用旧资产包结构，也可以将 `OPENTALKING_QUICKTALK_ASSET_ROOT` 指到包含 `checkpoints/` 的目录；详见 local 页面。

## 相关教程

- [QuickTalk Local](quicktalk/local.md)
- [QuickTalk with OmniRT](quicktalk/omnirt.md)
- [本地语音 + QuickTalk](recipes/local-quicktalk-audio.md)
- [支持矩阵](support-matrix.md)
