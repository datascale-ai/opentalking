# MuseTalk

MuseTalk 是面向更高质量口型生成的视频 avatar 路径。相比 Wav2Lip，它的依赖和预处理更重；相比 QuickTalk，它更偏质量验证和已有 MuseTalk runtime 接入。本文只说明何时选择 MuseTalk，以及选择哪种部署模式。

## 支持状态

| 项 | 值 |
|----|----|
| 模型 ID | `musetalk` |
| Backend | `local` / `omnirt` / `direct_ws` |
| 证据等级 | local adapter 已接入；local 模式会在会话初始化前运行 MuseTalk 官方预处理 |
| 推荐用途 | 更高质量口型同步、视频 avatar、已有 MuseTalk runtime 接入 |

## Benchmark 参考

以下数据摘自 [Benchmark](../reference/benchmark.md)。`稳态FPS` 表示模型持续生成吞吐，不等同于完整用户体感延迟；完整链路还会受到 STT、LLM、TTS、队列和 WebRTC 影响。

| 硬件 | Backend | 输出 | 稳态FPS | 首轮总延迟/ms | TTFV/ms | 推理峰值显存/GB |
|------|---------|------|---------|---------------|---------|----------------|
| RTX 3090 | OmniRT | 512×512 / 25fps | 28.868 | 3235.518 | 1769.484 | 5.078 |
| RTX 4090 | OmniRT | 512×512 / 25fps | 24.767 | 3605.564 | 2095.522 | 5.203 |
| NPU 910B2 | OmniRT | 512×512 / 25fps | 12.276 | 5781.453 | 4211.721 | 8.754 |

## 选择部署模式

| 模式 | 适合场景 | 入口 |
|------|----------|------|
| Local | 单机 CUDA，OpenTalking 负责运行官方 avatar 预处理 | [MuseTalk Local 部署](deployment/musetalk-local.md) |
| OmniRT | MuseTalk 依赖与 OpenTalking 主进程隔离，生产部署更清晰 | [MuseTalk OmniRT 部署](deployment/musetalk-omnirt.md) |
| Direct WebSocket | 已有独立 MuseTalk 兼容服务，需要直接接入 | 参考 [Runtime Backends](../model-support/runtime-backends/direct-websocket.md) |

## 何时换其它模型

- 需要最轻量真实唇形验证：看 [Wav2Lip](wav2lip.md)。
- 需要更低延迟实时口播：看 [QuickTalk](quicktalk.md)。
- 需要高质量服务化重模型：看 [FlashTalk](flashtalk.md)。

## 相关页面

- [Support Matrix](../deployment/support-matrix.md)
- [Avatar Assets](avatar.md)
- [Talking-head Model Deployment](index.md)
