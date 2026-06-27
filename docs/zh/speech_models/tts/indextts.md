# IndexTTS 本地部署

IndexTTS 通过 OpenTalking 的 `indextts` provider 接入，适合可控配音、情绪控制和复刻音色。本文覆盖同机 HTTP sidecar 方式。

## 适用场景

- 需要比默认 Edge TTS 更强的音色控制。
- 希望把 IndexTTS runtime 与 OpenTalking 主进程隔离。
- 需要本地部署而不是托管 TTS API。

## 权重准备

```bash title="终端"
cd "$OPENTALKING_HOME"
mkdir -p ./avatar_models/local-audio

export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
uv sync --extra dev --extra models --extra local-audio --python 3.11

python scripts/download_local_audio_models.py \
  --root ./avatar_models/local-audio \
  --model indextts2 \
  --model indextts2-w2v-bert \
  --model indextts2-maskgct \
  --model indextts2-campplus \
  --model indextts2-bigvgan
```

准备 runtime：

```bash title="终端"
mkdir -p ./avatar_models/local-audio/runtime
GIT_LFS_SKIP_SMUDGE=1 git clone https://github.com/index-tts/index-tts.git ./avatar_models/local-audio/runtime/index-tts
cd ./avatar_models/local-audio/runtime/index-tts
uv sync --python 3.11
uv pip install fastapi "uvicorn[standard]" soundfile
```

## 配置项

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=indextts
OPENTALKING_TTS_INDEXTTS_BACKEND=local
OPENTALKING_TTS_INDEXTTS_SERVICE_URL=http://127.0.0.1:19190/synthesize
```

如果使用 OmniRT 承载 IndexTTS runtime，OpenTalking 仍只暴露
`provider=indextts`，由 `backend=omnirt` 切换到远端 resident service。
OmniRT 负责模型加载、分窗流式和 token-window streaming：

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=indextts
OPENTALKING_TTS_INDEXTTS_BACKEND=omnirt
OPENTALKING_TTS_OMNIRT_INDEXTTS_SERVICE_URL=http://127.0.0.1:9012/v1/text2audio/indextts
OPENTALKING_TTS_OMNIRT_INDEXTTS_STREAMING_MODE=token_window
OPENTALKING_TTS_OMNIRT_INDEXTTS_TOKEN_WINDOW_SIZE=40
```

## 启动命令

先启动 IndexTTS sidecar，再启动 OpenTalking。具体 sidecar 命令取决于 IndexTTS runtime 版本；确保它暴露与 `OPENTALKING_TTS_INDEXTTS_SERVICE_URL` 匹配的 HTTP 接口。

```bash title="终端"
cd "$OPENTALKING_HOME"
cd ./models/local-audio/runtime/index-tts
cd "$OPENTALKING_HOME"
./models/local-audio/runtime/index-tts/.venv/bin/python scripts/local_indextts_service.py --host 127.0.0.1 --port 19092
```

再启动 OpenTalking：

```bash title="终端"
cd "$OPENTALKING_HOME"
bash scripts/start_unified.sh --backend local --model quicktalk --api-port 8000 --web-port 5173
```

## 验证命令

```bash title="终端"
curl -fsS http://127.0.0.1:8000/health
curl -fsS --max-time 300 http://127.0.0.1:8000/runtime/status | jq '.tts_providers.indextts.backend, .tts_providers.indextts.resolved_provider'
```

创建 `mock` 会话后调用 `/speak` 验证 TTS provider 是否返回音频。

## 常见错误

| 现象 | 处理 |
|------|------|
| sidecar 接口不匹配 | 检查 IndexTTS runtime 暴露的路径是否与 `SERVICE_URL` 一致。 |
| 下载缺文件 | 重新运行下载脚本，确认五个 `indextts2*` 模型目录都存在。 |
| 依赖冲突 | 将 IndexTTS runtime 保持在独立 venv 中。 |
| 首次启动慢 | 下载脚本支持断点续传；确认模型目录完整后重启 sidecar。 |
