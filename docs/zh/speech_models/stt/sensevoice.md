# SenseVoice 本地部署

SenseVoiceSmall 是 OpenTalking 当前推荐的本地语音识别模型，适合私有化部署、短句实时交互，以及本地语音 + QuickTalk 链路。

## 适用场景

- 不希望麦克风语音上传到外部 STT 服务。
- 需要 CPU 可运行的短句实时识别。
- 与本地 TTS、QuickTalk local 组成单机验证链路。

## 权重准备

```bash title="终端"
cd "$OPENTALKING_HOME"
uv sync --extra dev --extra models --extra local-audio --python 3.11

python scripts/download_local_audio_models.py \
  --root ./avatar_models/local-audio \
  --model sensevoice-small
```

## 配置项

```env title=".env"
OPENTALKING_STT_DEFAULT_PROVIDER=sensevoice
OPENTALKING_STT_ENABLED_PROVIDERS=sensevoice,dashscope
OPENTALKING_STT_SENSEVOICE_MODEL=iic/SenseVoiceSmall
OPENTALKING_STT_SENSEVOICE_MODEL_DIR=./avatar_models/local-audio/iic__SenseVoiceSmall
OPENTALKING_STT_SENSEVOICE_DEVICE=cpu
```

## 启动命令

```bash title="终端"
cd "$OPENTALKING_HOME"
bash scripts/start_unified.sh --backend mock --model mock --api-port 8000 --web-port 5173
```

## 验证命令

```bash title="终端"
curl -fsS http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/api/runtime/status | jq
```

然后在 WebUI 中选择麦克风输入，确认事件流里出现 STT 结果和 LLM 回复。

## 常见错误

| 现象 | 处理 |
|------|------|
| 模型目录找不到 | 检查 `OPENTALKING_STT_SENSEVOICE_MODEL_DIR` 是否指向下载目录。 |
| 识别延迟高 | 先使用 CPU 短句验证；长音频或高并发建议拆成独立 STT 服务。 |
| API STT key 报错 | 本地 SenseVoice 不读取 DashScope key；确认前端选择的是本地 STT。 |
