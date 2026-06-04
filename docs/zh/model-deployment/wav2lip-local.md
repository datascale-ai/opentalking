# Wav2Lip Local

Wav2Lip local 教程已经移到 [Wav2Lip / Local](wav2lip/local.md)。

旧链接保留是为了兼容历史文档；新的模型部署目录统一使用：

- [Wav2Lip 概览](wav2lip.md)
- [Wav2Lip Local](wav2lip/local.md)
- [Wav2Lip with OmniRT](wav2lip/omnirt.md)

## 前端入口

模型或后端服务启动后，统一用 OpenTalking WebUI 访问：

```bash title="终端"
cd "$OPENTALKING_HOME"
bash scripts/quickstart/start_frontend.sh --api-port 8000 --web-port 5173 --host 0.0.0.0
```

远程服务器部署时，把本地浏览器端口映射到服务器 `5173`，再打开 `http://127.0.0.1:5173`。
