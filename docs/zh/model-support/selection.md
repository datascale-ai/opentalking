# 模型与后端选择

选型时不要只看“模型效果”，还要同时考虑延迟、显存、Avatar 资产准备成本、部署复杂度和团队是否需要扩展多个模型。下面给出一套推荐判断路径。

## 按目标选择

### 最快验证

选择 `mock`。

适合验证：

- WebUI 是否能打开。
- API、会话、TTS、播放链路是否正常。
- 前后端端口和代理配置是否正确。

Mock 不代表真实模型效果，也不能用于评估口型质量和推理延迟。

### 第一个真实 Avatar

优先选择 `wav2lip` 或 `quicktalk`。

- 想快速验证一张图片或短视频 Avatar：从 Wav2Lip 开始。
- 想验证更接近实时口播的链路：从 QuickTalk 开始。
- 想同时验证本地语音识别、本地语音合成和 QuickTalk：看[模型部署 / 本地语音 + QuickTalk](../model-deployment/local-quicktalk-audio.md)。

建议先用内置 Avatar 跑通，再替换为自定义 Avatar。

### 高质量模型

优先选择 `musetalk`、`flashtalk` 或 `flashhead`。

MuseTalk 可以用 `local` 在单机 CUDA 环境中验证效果，OpenTalking 会在会话初始化前运行官方头像预处理。
如果需要服务隔离或生产化部署，仍建议通过 OmniRT 或独立服务接入。FlashTalk 和 FlashHead 通常更适合独立推理服务。

### 生产服务化

生产环境推荐拆分：

- OpenTalking API / WebUI：处理用户入口和会话编排。
- Worker：处理音频切片、推理调用和媒体输出。
- OmniRT / direct_ws 模型服务：承载真实模型推理。
- Redis：承载会话状态和任务队列。

## 按硬件选择

### CPU

只推荐 Mock 或非常轻量的流程验证。真实口型同步模型通常不适合 CPU 实时推理。

### 单张 NVIDIA GPU

适合：

- Wav2Lip local。
- QuickTalk local。
- MuseTalk local。
- MuseTalk / Wav2Lip / QuickTalk 的 OmniRT 单模型服务。

如果显存有限，优先减少分辨率、batch size、缓存窗口和并发会话数。

### 多卡 GPU

适合：

- FlashTalk 这类更重的模型。
- 多个模型服务分别绑定不同 GPU。
- QuickTalk 中 HuBERT 和主模型分卡。

例如 QuickTalk 可用 `OPENTALKING_QUICKTALK_HUBERT_DEVICE` 把 HuBERT 放到另一张卡。

### Ascend NPU

适合通过 OmniRT 接入已适配 NPU 的模型。OpenTalking 侧主要关注 endpoint、模型名、Avatar 路径和服务健康状态。

### 远端推理服务

当推理服务部署在另一台机器时，推荐使用 `omnirt` 或 `direct_ws`。这样 OpenTalking 不需要持有模型权重，也不会被模型依赖污染。

## 按服务形态选择

### 进程内 local

优点：

- 启动链路简单。
- 调试方便。
- 适合单机 Demo 和开发验证。

限制：

- API 进程和模型资源耦合。
- 多模型、多并发时容易互相影响。
- 模型依赖会增加环境复杂度。

### 独立 WebSocket

优点：

- 模型服务和 OpenTalking 解耦。
- 适合已有模型服务直接接入。

限制：

- 协议需要和 OpenTalking 约定一致。
- 健康检查、重连、鉴权和版本管理需要额外设计。

### OmniRT

优点：

- 统一管理多模型 audio2video 服务。
- OpenTalking 只需要配置 `OMNIRT_ENDPOINT` 和模型后端。
- 更适合生产服务化。

限制：

- 需要单独部署和维护 OmniRT。
- 模型权重、GPU/NPU、资产路径需要在 OmniRT 侧准备。

## 推荐路线

| 阶段 | 推荐模型 | 推荐后端 | 目标 |
| --- | --- | --- | --- |
| 安装验证 | Mock | `mock` | 确认环境和页面 |
| 第一条真实链路 | Wav2Lip / QuickTalk | `local` | 验证 Avatar 和口型 |
| 本地语音验证 | SenseVoiceSmall + CosyVoice3 + QuickTalk | `local` | 验证本地 STT/TTS/Video |
| 单机效果验证 | QuickTalk / MuseTalk | `local` 或 `omnirt` | 评估延迟和效果 |
| 高质量演示 | FlashTalk / FlashHead | `omnirt` / `direct_ws` | 验证高质量输出 |
| 生产部署 | 多模型组合 | `omnirt` + Worker | 稳定、可扩展、可监控 |

如果当前目标是文档读者快速上手，推荐路线是：Mock -> QuickTalk 或 Wav2Lip -> OmniRT。
