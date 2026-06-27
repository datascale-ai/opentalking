# Qwen3-TTS 本地部署

Qwen3-TTS 通过 OpenTalking 的 `local_qwen3_tts` provider 接入。它以本地 HTTP sidecar 运行，适合需要 Qwen3-TTS Base 复刻音色能力的私有化场景。

## 适用场景

- 需要本地 Qwen3-TTS Base 生成或复刻音色。
- 希望 TTS runtime 与 OpenTalking 主进程隔离。
- 已准备参考音频和参考文本，能够满足 Base 模型的 voice clone 输入要求。

## 权重准备

```bash title="终端"
cd "$OPENTALKING_HOME"
mkdir -p ./avatar_models/local-audio

uv pip install -U "huggingface_hub[cli]"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

hf download Qwen/Qwen3-TTS-12Hz-0.6B-Base \
  --local-dir ./avatar_models/local-audio/Qwen__Qwen3-TTS-12Hz-0.6B-Base
```

## Sidecar 环境

Qwen3-TTS 建议使用独立 venv，避免与 OpenTalking 主环境的依赖冲突：

```bash title="终端"
cd "$OPENTALKING_HOME"
uv venv .venv-qwen3-tts --python 3.11
source .venv-qwen3-tts/bin/activate
uv pip install -e ".[local-qwen3-tts-service]"
```

## 配置项

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=local_qwen3_tts
OPENTALKING_LOCAL_QWEN3_TTS_SERVICE_URL=http://127.0.0.1:19091/synthesize
OPENTALKING_LOCAL_QWEN3_TTS_MODEL_DIR=./avatar_models/local-audio/Qwen__Qwen3-TTS-12Hz-0.6B-Base
OPENTALKING_LOCAL_QWEN3_TTS_DEVICE=cuda:0
OPENTALKING_LOCAL_QWEN3_TTS_DTYPE=bfloat16
OPENTALKING_LOCAL_QWEN3_TTS_REF_AUDIO=/path/to/reference.wav
OPENTALKING_LOCAL_QWEN3_TTS_REF_TEXT=参考音频对应的文本
```

## 启动命令

先启动 Qwen3-TTS sidecar：

```bash title="终端"
cd "$OPENTALKING_HOME"
source .venv-qwen3-tts/bin/activate
python scripts/local_qwen3_tts_service.py --host 127.0.0.1 --port 19091
```

另开终端启动 OpenTalking：

```bash title="终端"
cd "$OPENTALKING_HOME"
bash scripts/start_unified.sh --backend mock --model mock --api-port 8000 --web-port 5173
```

## 验证命令

```bash title="终端"
curl -fsS http://127.0.0.1:19091/health
curl -s -X POST http://127.0.0.1:19091/synthesize \
  -H 'content-type: application/json' \
  -d '{"text":"你好，这是一次 Qwen3-TTS 本地测试。"}' \
  --output /tmp/qwen3-tts-test.wav
```

## 常见错误

| 现象 | 处理 |
|------|------|
| `reference audio and reference text` 报错 | Base 模型需要参考音频和参考文本；配置 `REF_AUDIO` 与 `REF_TEXT`。 |
| 模型目录找不到 | 检查 `OPENTALKING_LOCAL_QWEN3_TTS_MODEL_DIR` 是否指向下载目录。 |
| 依赖冲突 | 使用独立 `.venv-qwen3-tts`，不要把 sidecar 依赖装进主 `.venv`。 |
