# 概念与 API

本区面向开发者和集成方，说明 OpenTalking 的内部概念、接口边界和扩展方式。若目标是“先跑起来”，
请从 [教程](../tutorials/index.md) 开始；若目标是“了解能做什么业务场景”，请从
[场景案例](../cases/index.md) 开始；若目标是“部署模型”，请从 [模型部署](../model-deployment/index.md)
开始。

## 理解概念

- [架构设计](architecture.md) —— 组件、部署拓扑、会话生命周期、事件总线和 backend 边界。
- [渲染管线](render-pipeline.md) —— LLM、TTS、合成 backend 和 WebRTC 如何串起来。
- [Avatar 格式](avatar-format.md) —— avatar bundle、manifest 字段和模型匹配规则。

## 查询 API

- [API 接口概览](api/index.md) —— Base URL、错误约定、端点总表和典型请求顺序。
- [健康检查与模型](api/health.md) —— `/health`、`/models`、队列状态。
- [会话](api/sessions.md) —— 创建会话、对话、WebRTC、录制与离线 bundle。
- [事件与流式接口](api/events.md) —— SSE 与音频 WebSocket 协议。

## 扩展实现

- [模型适配器](model-adapter.md) —— 新 talking-head backend 的集成契约。
- [开发流程](developing.md) —— 本地运行、测试、调试和仓库结构。

## 调试贡献

贡献前建议先跑 `python -m mkdocs build --strict --clean`，并根据改动范围补充 API 文档、
模型部署文档或 Benchmark 记录。社区参与路径见 [社区](../community/index.md)。
