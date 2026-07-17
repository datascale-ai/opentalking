# Wav2Lip

Wav2Lip 是 OpenTalking 推荐的第一个真实口型同步模型路径。它比重型 talking-head 模型更轻，适合从 `mock` 过渡到真实视频输出，并评估端到端音频驱动视频链路。

## 支持状态

| 项 | 值 |
|----|----|
| 模型 ID | `wav2lip` |
| Backend | `local` / `omnirt` |
| 证据等级 | local adapter 已内置；OmniRT 兼容路径已文档化 |
| 推荐用途 | 第一个真实唇形模型、轻量 demo、低成本链路验证 |

## Benchmark 参考

以下数据摘自 [Benchmark](../reference/benchmark.md)。`稳态FPS` 表示模型持续生成吞吐，不等同于完整用户体感延迟；完整链路还会受到 STT、LLM、TTS、队列和 WebRTC 影响。

| 硬件 | Backend | 输出 | 稳态FPS | 首轮总延迟/ms | TTFV/ms | 推理峰值显存/GB |
|------|---------|------|---------|---------------|---------|----------------|
| RTX 3090 | OmniRT | 498×832 / 30fps | 37.269 | 3002.526 | 1625.962 | 7.928 |
| RTX 4090 | OmniRT | 498×832 / 30fps | 31.542 | 3689.764 | 1955.629 | 8.133 |
| NPU 910B2 | OmniRT | 498×832 / 30fps | 23.945 | 4019.564 | 2615.322 | 9.113 |

## 选择部署模式

| 模式 | 适合场景 | 入口 |
|------|----------|------|
| Local | 单机部署、依赖最少、先跑通真实唇形同步 | [Wav2Lip Local 部署](deployment/wav2lip-local.md) |
| OmniRT | 推理服务独立部署、复用 OmniRT 的预加载和设备配置 | [Wav2Lip OmniRT 部署](deployment/wav2lip-omnirt.md) |

## 何时换其它模型

- 需要更低延迟实时口播：看 [QuickTalk](quicktalk.md)。
- 需要更高质量或 MuseTalk 官方预处理效果：看 [MuseTalk](musetalk.md)。
- 需要高质量重模型或服务化私有部署：看 [FlashTalk](flashtalk.md)。

## 相关页面

- [Support Matrix](../deployment/support-matrix.md)
- [Avatar Assets](avatar.md)
- [Talking-head Model Deployment](index.md)
