# MuseTalk

MuseTalk 支持 `local`、`omnirt` 和高级 `direct_ws` 接入。当前文档把最常用的 `local` 与 `omnirt` 拆开：local 由 OpenTalking 主进程加载 adapter 并在会话初始化前执行官方预处理；OmniRT 由独立服务托管 MuseTalk runtime。

| 项 | 值 |
|----|----|
| 模型 ID | `musetalk` |
| Backend | `local`、`omnirt`、`direct_ws` |
| 仓库默认值 | `omnirt` |
| 推荐起步 | 已能安装 OpenMMLab 依赖时可用 `local`；需要服务隔离时用 `omnirt` |

## 选择哪种模式

| 模式 | 适合场景 | 入口 |
|------|----------|------|
| `local` | 单机验证 MuseTalk 质量，接受 OpenTalking `.venv` 和官方预处理依赖较重。 | [MuseTalk Local](musetalk/local.md) |
| `omnirt` | 将 MuseTalk WS backend 和 OmniRT gateway 独立出来，OpenTalking 只连接 OmniRT。 | [MuseTalk with OmniRT](musetalk/omnirt.md) |
| `direct_ws` | 已经有 MuseTalk 兼容 WebSocket 服务，只想让 OpenTalking 连接它。 | 参考 [Backend 模式](backends/index.md) 和配置项。 |

## 权重目录

```text
models/
  musetalk/
    musetalk.json
    pytorch_model.bin
  sd-vae-ft-mse/
  whisper/
    tiny.pt
  dwpose/
    dw-ll_ucoco_384.pth
  face-parse-bisenet/
    79999_iter.pth
```

local 模式还需要 MuseTalk 官方源码和预处理 Python；OmniRT 模式会通过 OmniRT runtime 管理 MuseTalk 源码环境。

## 相关教程

- [MuseTalk Local](musetalk/local.md)
- [MuseTalk with OmniRT](musetalk/omnirt.md)
- [支持矩阵](support-matrix.md)
