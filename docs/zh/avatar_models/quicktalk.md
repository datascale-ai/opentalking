# QuickTalk

QuickTalk 是 OpenTalking 中偏实时口播的 talking-head 模型，适合低延迟数字人对话和本地 GPU 快速试跑。本文只做选型导览；具体权重、启动和验证命令见下方部署模式页。

## 支持状态

| 项 | 值 |
|----|----|
| 模型 ID | `quicktalk` |
| Backend | `local` / `omnirt` |
| 证据等级 | local adapter 已内置并验证；OmniRT 服务化路径已文档化 |
| 推荐用途 | 实时口播、低延迟验证、本地或服务化推理 |

## Benchmark 参考

以下数据摘自 [Benchmark](../reference/benchmark.md)。`稳态FPS` 表示模型持续生成吞吐，不等同于完整用户体感延迟；完整链路还会受到 STT、LLM、TTS、队列和 WebRTC 影响。

| 硬件 | Backend | 输出 | 稳态FPS | 首轮总延迟/ms | TTFV/ms | 推理峰值显存/GB |
|------|---------|------|---------|---------------|---------|----------------|
| RTX 3090 | OmniRT | 540×900 / 25fps | 29.23 | 3356.019 | 1800.524 | 1.662 |
| RTX 4090 | OmniRT | 540×900 / 25fps | 46.921 | 2561.146 | 1064.825 | 1.838 |
| NPU 910B2 | OmniRT | 540×900 / 25fps | 29.66 | 3212.053 | 1782.861 | 2.473 |
| RTX 3050 Laptop | OmniRT | 306×512 / 25fps | 20.695 | 4243.26 | 2661 | 1.396 |

## 选择部署模式

| 模式 | 适合场景 | 入口 |
|------|----------|------|
| Local | 单机 CUDA、本地 adapter、最快验证真实链路 | [QuickTalk Local 部署](deployment/quicktalk-local.md) |
| Apple Silicon | Mac 上做权重、manifest、WebUI 流程检查 | [QuickTalk Apple Silicon 部署](deployment/quicktalk-apple-silicon.md) |
| OmniRT | 推理服务与 OpenTalking 解耦，或多模型共用一个服务端点 | [QuickTalk OmniRT 部署](deployment/quicktalk-omnirt.md) |

## 相关页面

- [Support Matrix](../deployment/support-matrix.md)：确认 QuickTalk 与其它模型链路的 backend 差异。
- [Avatar Assets](avatar.md)：了解通用 avatar 资产和会话选择规则。
- [本地语音 + QuickTalk](../recipes/local-quicktalk-audio.md)：组合 SenseVoice、CosyVoice 与 QuickTalk local 的完整链路。
