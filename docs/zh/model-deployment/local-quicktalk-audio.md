# 本地语音 + QuickTalk

完整教程已经移到 [模型部署 / 部署配方 / 本地语音 + QuickTalk](recipes/local-quicktalk-audio.md)。

旧链接保留是为了兼容历史文档。新的模型部署目录把模型页面和组合教程分开：

- [QuickTalk 概览](quicktalk.md)
- [QuickTalk Local](quicktalk/local.md)
- [本地语音 + QuickTalk](recipes/local-quicktalk-audio.md)

## 前端入口

模型或后端服务启动后，统一用 OpenTalking WebUI 访问：

```bash title="终端"
cd "$OPENTALKING_HOME"
bash scripts/quickstart/start_frontend.sh --api-port 8000 --web-port 5173 --host 0.0.0.0
```

远程服务器部署时，把本地浏览器端口映射到服务器 `5173`，再打开 `http://127.0.0.1:5173`。
