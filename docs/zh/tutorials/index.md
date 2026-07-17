# 教程

教程按任务路径组织，适合从零开始跑通 OpenTalking，或在已有环境上接入真实模型、Avatar
和开发调试流程。

## 首次运行

1. [安装](installation.md) —— 确认 Python、Node.js、ffmpeg、DashScope key 和硬件要求。
2. [快速上手](quickstart.md) —— 用 `mock` 合成路径跑通浏览器、API、LLM、STT、TTS 和 WebRTC。
3. [配置](configuration.md) —— 理解 `.env`、YAML 配置、provider 和 backend 优先级。
4. [Mock 端到端案例](cases/mock-e2e.md) —— 用最小链路验证本机环境。

## 接入真实模型

先用 `mock` 确认编排链路健康，再接入真实 talking-head backend：

| 场景 | 推荐教程 |
|------|----------|
| 第一个真实唇形模型 | [Wav2Lip 接入](cases/wav2lip.md) |
| 高质量 FlashTalk/OmniRT 路径 | [FlashTalk 接入](cases/flashtalk.md) |
| 选择模型、权重和部署拓扑 | [模型部署](../deployment/index.md) |

这些页面偏底层接入步骤；如果想先看“能用在哪些业务场景”，请看
[场景案例](../cases/index.md)。

## 自定义 Avatar

从 [自定义 Avatar 案例](cases/custom-avatar.md) 开始，了解图片、视频和 `manifest.json` 如何
组合成可被 OpenTalking 发现的 avatar bundle。字段细节见 [Avatar 格式](../docs/avatar-format.md)。

## 开发调试

| 目标 | 入口 |
|------|------|
| 修改 API、会话或 Worker 行为 | [开发流程](../docs/developing.md) |
| 理解系统组件和数据流 | [架构设计](../docs/architecture.md) |
| 接入新的 talking-head backend | [模型适配器](../docs/model-adapter.md) |
| 排查性能与首帧延迟 | [Benchmark](../benchmark/index.md) |
