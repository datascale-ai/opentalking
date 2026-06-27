# Benchmark

Benchmark 页面用于说明 OpenTalking 如何记录端到端体验指标，以及如何引用外部模型服务的
推理基线。OpenTalking 是编排层，因此这里区分两类数据：

| 类型 | OpenTalking 是否直接负责 | 示例 |
|------|--------------------------|------|
| 端到端体验指标 | 是 | 首帧延迟、TTS 首包、事件流、WebRTC 播放、音画同步。 |
| 模型推理基线 | 否，来自所选 backend | OmniRT FlashTalk、Wav2Lip、QuickTalk 本地 adapter 的渲染吞吐。 |

## 推荐阅读顺序

1. [指标定义](metrics.md) —— 统一字段和口径。
2. [运行方法](runbook.md) —— 如何采集 QuickTalk 与端到端链路数据。
3. [结果与基线](results.md) —— 当前可引用的数据和结果模板。

## 记录原则

- 每条结果必须写明硬件、模型、backend、分辨率、输入音频时长和启动状态。
- 冷启动、热态、steady chunk 不能混写。
- OmniRT 或其它外部服务的数据必须标注来源，不写成本仓直接推理能力。
- 如果只跑了 `mock`，结果只能证明编排链路可用，不能证明真实 talking-head 性能。
