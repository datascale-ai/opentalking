# Mock Backend

Mock Backend 是 OpenTalking 内置的无模型后端。它不会加载真实权重，也不会生成真实口型，只用于验证应用链路。

Mock 可以验证：

- WebUI、API 和会话创建流程。
- Avatar 列表、模型列表和 TTS 配置是否可用。
- 端口、CORS、反向代理和基础网络访问。
- 前后端状态展示和错误提示。

## 配置

命令行启动：

```bash
bash scripts/start_unified.sh --mock
```

或显式设置模型后端：

```bash
export OPENTALKING_MOCK_BACKEND=mock
```

## 启动

Mock 模式会同时启动 OpenTalking 后端和 WebUI：

```bash
bash scripts/start_unified.sh --mock
```

默认 WebUI 地址为 `http://127.0.0.1:5173`。

## 验证

```bash
bash scripts/quickstart/status.sh
```

然后在 WebUI 中选择 Mock / driverless 相关模型，创建会话并发送短文本。

## 故障排查

如果 Mock 模式也无法创建会话，优先排查 OpenTalking API、WebUI 端口、浏览器控制台和服务日志。此时问题通常不在模型层。
