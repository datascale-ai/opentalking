---
title: OpenTalking
---

# OpenTalking

<p align="center">
  <img src="/opentalking/assets/images/logo_white.png" alt="OpenTalking logo" width="200">
</p>

<p align="center">
  <a href="https://github.com/datascale-ai/opentalking/stargazers"><img src="https://img.shields.io/github/stars/datascale-ai/opentalking?style=flat&label=stars" alt="GitHub stars"></a>
  <a href="https://github.com/datascale-ai/opentalking/forks"><img src="https://img.shields.io/github/forks/datascale-ai/opentalking?style=flat&label=forks" alt="GitHub forks"></a>
  <a href="https://github.com/datascale-ai/opentalking/issues"><img src="https://img.shields.io/github/issues/datascale-ai/opentalking?style=flat&label=open%20issues" alt="Open issues"></a>
  <a href="https://github.com/datascale-ai/opentalking/issues?q=is%3Aissue+is%3Aclosed"><img src="https://img.shields.io/github/issues-closed/datascale-ai/opentalking?style=flat&label=issue%20resolution" alt="Issue resolution"></a>
  <img src="https://img.shields.io/badge/PyPI-planned-lightgrey?style=flat" alt="PyPI planned">
  <img src="https://img.shields.io/badge/python-%3E%3D3.10-blue?style=flat" alt="Python >= 3.10">
  <a href="https://github.com/datascale-ai/opentalking/releases"><img src="https://img.shields.io/github/downloads/datascale-ai/opentalking/total?style=flat&label=downloads" alt="GitHub downloads"></a>
  <img src="https://img.shields.io/badge/downloads-source-lightgrey?style=flat" alt="Source downloads">
  <a href="https://modelscope.cn/models?name=OpenTalking"><img src="https://img.shields.io/badge/ModelScope-models-624aff?style=flat" alt="ModelScope"></a>
  <a href="https://huggingface.co/models?search=OpenTalking"><img src="https://img.shields.io/badge/HuggingFace-models-ffcc4d?style=flat" alt="Hugging Face"></a>
</p>

## 项目简介

OpenTalking 是一个面向实时数字人应用的开源编排框架，负责连接前端交互、会话状态、
LLM 回复、TTS/音色、字幕事件、WebRTC 音视频播放，以及本地或远端的数字人合成后端。

OpenTalking 的定位不是部署的 talking-head 模型服务，而是数字人产品和模型服务之间的实时编排层。
它将 LLM、语音识别、语音合成、Avatar 渲染、事件流和播放链路组织为统一的运行时，
使开发者可以从 Mock 验证开始，逐步切换到 Wav2Lip、QuickTalk、MuseTalk、FlashTalk 或
OmniRT 等真实模型和推理后端。

项目适用于 AI 客服、商品讲解、课程口播、新闻播报、陪伴角色和企业私有化数字人等场景。
如果你是第一次使用，建议先从 [Quick Start](quick-start/index.md) 跑通 Mock 链路；
如果你已经关注模型能力、推理后端或 GPU/NPU 部署，可以继续阅读 [模型支持](model-support/index.md)。

### 演示视频

<video src="https://github.com/user-attachments/assets/a3abce76-12c0-4b8b-844f-bbc5c3227dc7" controls width="100%"></video>

## 主要功能

- **实时对话链路**：统一管理语音输入、LLM 回复、TTS 合成、字幕事件、Avatar 渲染和 WebRTC 播放。
- **可插拔模型后端**：支持 `mock`、`local`、`direct_ws`、`omnirt` 等后端形态，便于从本地验证扩展到远端推理服务。
- **多模型接入路径**：面向 Wav2Lip、QuickTalk、MuseTalk、FlashTalk、FlashHead 等模型提供逐步完善的接入规划。
- **开放的 LLM/TTS 配置**：支持 OpenAI-compatible LLM endpoint，可接入 DashScope、DeepSeek、Ollama、vLLM 或企业内部模型服务。
- **WebUI 与命令行工具**：提供 WebUI 完成会话验证、Avatar 选择、音色配置和模型状态查看，也提供命令行入口用于启动服务和调试。
- **工程化运行形态**：支持本地开发、Mock 验证、Docker、API / Worker 分离，以及外部推理服务集成。

## 使用指南

- [Quick Start](quick-start/index.md)：首次运行 OpenTalking，使用 `mock` backend 跑通最小链路。
- [Usage](usage/index.md)：学习命令行启动、WebUI 使用、Avatar 配置和音色/TTS 配置。
- [Examples](examples/index.md)：从 AI 客服、商品讲解、课程口播等场景理解 OpenTalking 的应用方式。
- [Model Support](model-support/index.md)：了解模型、推理后端和生产拓扑，例如 Wav2Lip、QuickTalk、FlashTalk 和 OmniRT。
- [参考资料](reference/index.md)：查看 Benchmark、性能指标和更新日志。
- [FAQ](faq.md)：排查安装、配置、WebRTC、模型 backend 和运行问题。

## 许可证信息

OpenTalking 采用 Apache License 2.0。项目中接入或引用的 talking-head 模型、模型权重、TTS 服务、
LLM 服务和外部推理 backend 可能有各自的许可证或使用条款。部署、分发或商用前，请确认对应项目、
模型和服务的授权范围。
