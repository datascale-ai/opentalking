# 支持矩阵

本页用于汇总当前 OpenTalking 中哪些能力已经内置，哪些只是给出了接入路径，哪些在仓库文档
里已经有明确验证依据。适合作为进入详细部署文档前的决策页。

## 如何阅读这张矩阵

| 状态 | 含义 |
|------|------|
| 已内置 | 能力已在本仓库中实现，可直接在当前产品表面选择。 |
| 已文档化 | 接入路径已经写清楚，但运行是否可用仍取决于你的外部服务或模型权重。 |
| 已验证 | 仓库文档、测试或 benchmark 中已有明确验证证据。 |
| 规划中 | 架构边界已经预留，但本地 runtime 还没有随仓库一起提供。 |

## 全链路能力矩阵

| 层级 | 选项 | 接入方式 | 默认 / 推荐 | 状态 | 说明 |
|------|------|----------|-------------|------|------|
| LLM | DashScope `qwen-flash` | OpenAI-compatible endpoint | 默认首跑路径 | 已内置，已验证 | 当前 quickstart 默认路径。 |
| LLM | OpenAI-compatible endpoints | `OPENTALKING_LLM_BASE_URL` | 环境里已有标准服务时使用 | 已内置，已文档化 | 覆盖 OpenAI、vLLM、Ollama、DeepSeek 等。 |
| STT | DashScope Paraformer realtime | Provider adapter | 默认麦克风路径 | 已内置，已验证 | 默认语音输入流程依赖它。 |
| TTS | Edge TTS | 本地 provider adapter | 默认首跑路径 | 已内置，已验证 | 最轻量，不需要 API key。 |
| TTS | DashScope Qwen realtime TTS | Provider adapter | 需要托管中文实时 TTS 时推荐 | 已内置，已文档化 | 也用于部分声音复刻相关流程。 |
| TTS | CosyVoice service | Provider adapter / 远端服务 | 自建音色服务场景 | 已内置，已文档化 | 某些流程需要 `OPENTALKING_PUBLIC_BASE_URL`。 |
| TTS | ElevenLabs | Provider adapter | 托管多语言音色 | 已内置，已文档化 | 需要 API key 和 voice id。 |
| Avatar | 内置示例 avatar | 本地资产包 | 默认首跑路径 | 已内置，已验证 | 适合 `mock`、Wav2Lip 等文档路径。 |
| Avatar | 自定义上传形象 | `/avatars/custom` | 快速接入自定义形象 | 已内置，已文档化 | 当前最佳兼容路径是 Wav2Lip 风格图片 avatar。 |
| Avatar | 模型特定 manifest | 本地资产包 | QuickTalk / FlashHead / FlashTalk 必需 | 已内置，已文档化 | `model_type` 必须与所选合成模型一致。 |

## Talking-head 模型矩阵

| 模型 | backend 选择 | 仓库默认值 | 验证级别 | 推荐硬件路径 | 当前建议 |
|------|--------------|------------|----------|--------------|----------|
| `mock` | `mock` | `mock` | 已内置，已验证 | CPU | 最快的全链路自测路径，不需要模型权重。 |
| `wav2lip` | `omnirt`、`local`、`direct_ws` | 为兼容默认 `omnirt` | OmniRT 路径已验证；local 路径规划中 | 单 GPU 或 Ascend 910B | 最推荐的第一个真实模型。方向上应 local-first，但当前可直接跑通的是 OmniRT。 |
| `musetalk` | `omnirt`、`direct_ws`、`local` | `omnirt` | 已文档化；local adapter 缺失 | 单 GPU 或远端模型服务 | 框架已就位，但仓库内未附带本地 runtime。 |
| `quicktalk` | `local` | `local` | 已内置，已验证 | 本地 CUDA GPU | 本地实时 adapter 的参考实现，也是解耦架构的最佳示例。 |
| `flashtalk` | `omnirt`、legacy `direct_ws` fallback | `omnirt` | OmniRT 路径已文档化，Ascend 路径已验证 | 4090 级 GPU 或 Ascend 910B 多卡 | 高质量重模型路径。 |
| `flashhead` | `direct_ws` | `direct_ws` | 已文档化 | 外部 FlashHead 服务 | OpenTalking 负责编排和客户端接入，不负责托管模型。 |

## Backend 行为矩阵

| Backend | OpenTalking 期望什么 | 何时视为 connected | 典型模型 |
|---------|----------------------|--------------------|----------|
| `mock` | 无外部 runtime | 始终可用 | `mock` |
| `local` | 进程内 adapter/runtime | adapter 可 import 且依赖满足 | `quicktalk`，未来的本地 Wav2Lip / MuseTalk |
| `direct_ws` | 模型自带远端服务 | 已配置模型专属 WebSocket URL | `flashhead`、自定义单模型服务 |
| `omnirt` | OmniRT `/v1/audio2video/{model}` | OmniRT 可达且返回该模型 | `wav2lip`、`musetalk`、`flashtalk` |

## 验证说明

| 路径 | 仓库中的证据 |
|------|--------------|
| `mock` | quickstart 与 `/models` 示例都覆盖了完整自测路径。 |
| `wav2lip + omnirt` | 有启动脚本、`/models` 状态语义，以及 README 中 3090 / Ascend 910B 的 benchmark 与连通性示例。 |
| `quicktalk + local` | `/models` 测试明确覆盖 `reason=local_runtime`，对应本地 adapter 路径。 |
| `flashtalk + omnirt` | 有启动脚本、legacy fallback 说明，以及 README 中 Ascend 910B2 x8 的验证记录。 |
| `flashhead + direct_ws` | 有配置接入路径，以及 Talking-head 文档中的 `/models` `reason=direct_ws` 示例。 |

## 推荐起步路径

1. 先用 `mock` 验证浏览器、API、LLM、STT、TTS 和 WebRTC。
2. 想接入最轻量的真实 talking-head，先用 `wav2lip`。
3. 明确要本地进程内实时 adapter 时，选 `quicktalk`。
4. 质量优先、可接受部署重量时，选 `flashtalk`。
5. 已经有独立 FlashHead 服务时，再选 `flashhead`。

## 下一步

- [概览](index.md)
- [LLM 与 STT](llm-stt.md)
- [语音合成](tts.md)
- [Avatar 资产](avatar.md)
- [Talking-head 模型](talking-head.md)
