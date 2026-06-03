# 使用概览

使用指南说明 OpenTalking 的日常操作方式：如何从命令行启动和调试服务，如何在 WebUI 中选择 Avatar、切换模型、配置音色并完成一次会话。

如果你还没有把项目跑起来，建议先完成[快速开始](../quick-start/index.md)；如果你已经能打开 WebUI，本章可以作为后续使用和排查问题的入口。

## 本章适合谁

本章面向已经完成基础安装、希望进一步使用 OpenTalking 的开发者和集成者。你可以在这里找到：

- 启动 OpenTalking 服务、前端页面和相关脚本的方法。
- 在 WebUI 中完成 Avatar、模型、音色和会话配置的流程。
- 准备自定义 Avatar、试听或复刻音色的操作路径。
- 常见参数、端口、后端和环境变量的说明。

本章不会把所有模型能力、业务案例和 API 字段混在一起。它只回答一个问题：当前版本应该怎么用。

## 主要使用方式

### 命令行工具

命令行工具更适合开发、联调、部署前验证和自动化脚本。你可以用它启动 unified 服务、切换推理后端、指定模型、检查服务状态、准备 Avatar 资产，以及运行 QuickTalk 性能测试。

推荐先看[命令行工具](./cli.md)，再根据需要进入[命令行进阶参数](./cli-advanced.md)。

### WebUI

WebUI 更适合交互式验证。它提供 Avatar 选择、模型选择、TTS Provider 和音色配置、文字/语音会话、视频创作、视频克隆、状态提示等能力。产品、算法、解决方案同学也可以通过 WebUI 快速确认一个 Avatar、音色或离线视频结果是否符合预期。

推荐先看[WebUI 基础使用](./webui/basic.md)，再按需求查看[自定义 Avatar](./webui/custom-avatar.md)、[音色与 TTS](./webui/voice-and-tts.md)、[视频创作](./webui/video-creation.md)和[视频克隆](./webui/video-clone.md)。

## 推荐路径

### 我想快速体验界面

1. 按照[快速开始](../quick-start/index.md)启动 Mock 模式。
2. 打开 WebUI。
3. 阅读[WebUI 基础使用](./webui/basic.md)，完成 Avatar、模型、音色和会话配置。

Mock 模式不依赖模型权重，适合确认前后端流程、页面交互和基础链路是否正常。

### 我想自定义 Avatar

1. 先用内置 Avatar 跑通一次会话。
2. 阅读[自定义 Avatar](./webui/custom-avatar.md)，确认图片、视频素材和模型兼容性。
3. 在 WebUI 上传图片，或使用脚本生成 Wav2Lip 资产。
4. 回到 WebUI 选择新 Avatar 进行验证。

### 我想配置音色 / TTS

1. 阅读[音色与 TTS](./webui/voice-and-tts.md)，确认当前要使用的 TTS Provider。
2. 在 WebUI 中选择默认音色或试听音色。
3. 如需声音复刻，再补充 Provider Key、样本音频和公开访问地址等配置。

### 我想制作一段数字人口播视频

1. 先确认 WebUI 能打开，并至少有一个可用 Avatar。
2. 阅读[视频创作](./webui/video-creation.md)，选择 `quicktalk` 或 `wav2lip` 作为离线生成模型。
3. 选择音频来源：上传音频、文本合成，或先复刻音色再生成口播。
4. 生成后在右侧预览结果，或进入资产库下载生成视频。

视频创作是离线/准实时生成流程，不需要进入实时对话会话，也不会占用 WebRTC 会话。

### 我想用摄像头驱动数字人表情

1. 先按 FasterLivePortrait 部署文档启动 OmniRT runtime。
2. 阅读[视频克隆](./webui/video-clone.md)，选择 source 数字人形象。
3. 使用摄像头或上传 driving video 作为表情和头动输入。
4. 根据画面效果调整拼回原图、裁剪 driving、驱动区域和嘴部参数。

### 我想用命令行启动服务

1. 阅读[命令行工具](./cli.md)，了解统一入口和常用脚本。
2. 使用 `scripts/start_unified.sh` 启动 Mock、本地模型或 OmniRT 模式。
3. 需要改端口、host、后端地址时，再查[命令行进阶参数](./cli-advanced.md)。

## 本章不包含什么

### 业务场景案例

客服数字人、直播导购、课程口播、私有助手等内容会放在[案例教程](../tutorials/index.md)中。使用指南只保留通用操作流程。

### 模型与推理后端选择

不同模型、推理后端、生产拓扑和后续支持计划会放在[模型支持](../model-support/index.md)中。使用指南只说明如何在当前工具中选择和传递这些配置。

### API Schema

当前推荐的上手路径仍以 WebUI 和命令行工具为主。详细 API 字段、事件协议和资产格式会在后续参考资料中整理。

## 下一步

- 想通过脚本启动和调试服务：继续阅读[命令行工具](./cli.md)。
- 想配置页面交互流程：继续阅读[WebUI 基础使用](./webui/basic.md)。
- 想补充自己的形象：继续阅读[自定义 Avatar](./webui/custom-avatar.md)。
- 想调整声音效果：继续阅读[音色与 TTS](./webui/voice-and-tts.md)。
- 想生成离线口播视频：继续阅读[视频创作](./webui/video-creation.md)。
- 想用摄像头或自拍视频驱动数字人：继续阅读[视频克隆](./webui/video-clone.md)。
