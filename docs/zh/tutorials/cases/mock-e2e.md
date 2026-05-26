# Mock 端到端案例

## 目标

用 `mock` 合成后端跑通浏览器、API、LLM、STT、TTS、事件流与 WebRTC。该路径不需要 GPU、
NPU 或 talking-head 权重，适合首次验收安装结果。

## 前置条件

- 已完成 [安装](../installation.md)。
- `.env` 中已配置 `OPENTALKING_LLM_API_KEY` 与 `OPENTALKING_STT_DASHSCOPE_API_KEY`。
- 本机可用端口 `8000` 与 `5173`，或准备自定义端口。

## 步骤

```bash title="终端"
cd opentalking
source .venv/bin/activate
bash scripts/quickstart/start_mock.sh
```

打开 <http://localhost:5173>，选择内置 avatar 与 `mock` 模型，点击麦克风开始对话。

## 验证

```bash title="终端"
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="mock")'
```

期望 `mock` 返回 `connected: true`，浏览器能够收到文本事件和占位视频帧。

## 故障排查

| 现象 | 处理方式 |
|------|----------|
| 端口被占用 | 使用 `bash scripts/quickstart/start_mock.sh --api-port 8010 --web-port 5180`。 |
| LLM 返回 401 | 确认 `.env` 中两处 DashScope key 均已设置且没有多余空格。 |
| 浏览器无视频 | 使用 Chromium 内核浏览器，并检查控制台中的 WebRTC 与 CORS 报错。 |
