# QuickTalk OmniRT 部署

OmniRT 模式把 QuickTalk 推理放到 OpenTalking 进程外，适合多模型共用一个服务端点、隔离 GPU 依赖，或把推理服务部署到独立机器。

## 适用场景

- OpenTalking 只负责会话、TTS 和 WebRTC，QuickTalk 由独立服务承载。
- 同一个 OmniRT endpoint 需要同时暴露 `quicktalk`、`wav2lip` 等模型。
- 需要更清晰地区分 Web 服务资源和推理 GPU 资源。

## 权重准备

OmniRT 默认读取 `$OMNIRT_MODEL_ROOT/quicktalk`：

```bash title="终端"
export DIGITAL_HUMAN_HOME="$HOME/digital-human"
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
mkdir -p "$OMNIRT_MODEL_ROOT/quicktalk/checkpoints"

uv pip install -U "huggingface_hub[cli]"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

hf download datascale-ai/quicktalk \
  quicktalk.pth \
  repair.npy \
  chinese-hubert-large/config.json \
  chinese-hubert-large/preprocessor_config.json \
  chinese-hubert-large/pytorch_model.bin \
  --local-dir "$OMNIRT_MODEL_ROOT/quicktalk/checkpoints"
```

确认 `quicktalk.pth`、`repair.npy`、HuBERT 和 InsightFace `buffalo_l` 都在 QuickTalk 模型目录下；InsightFace 准备方式见 [Local](quicktalk-local.md)。

## 启动命令

先启动 OmniRT：

```bash title="终端"
cd "$OMNIRT_HOME"
uv sync --extra server --extra quicktalk-cuda --python 3.11
source .venv/bin/activate

export OMNIRT_QUICKTALK_RUNTIME=1
export OMNIRT_QUICKTALK_MODEL_ROOT="$OMNIRT_MODEL_ROOT/quicktalk"
export OMNIRT_QUICKTALK_CHECKPOINT="$OMNIRT_MODEL_ROOT/quicktalk/checkpoints/quicktalk.pth"
export OMNIRT_QUICKTALK_DEVICE=cuda:0
export OMNIRT_QUICKTALK_HUBERT_DEVICE=cuda:0
export OMNIRT_QUICKTALK_MAX_LONG_EDGE=900
export OMNIRT_QUICKTALK_MAX_TEMPLATE_SECONDS=1

omnirt serve-avatar-ws --host 0.0.0.0 --port 9000 --backend cuda
```

再启动 OpenTalking：

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/start_unified.sh \
  --backend omnirt \
  --model quicktalk \
  --omnirt http://127.0.0.1:9000 \
  --api-port 8310 \
  --web-port 5380
```

## 验证命令

```bash title="终端"
curl -fsS http://127.0.0.1:9000/v1/audio2video/models | jq
curl -s http://127.0.0.1:8310/models | jq '.statuses[] | select(.id=="quicktalk")'
```

OpenTalking 侧期望 `backend=omnirt`、`connected=true`。

## 常见错误

| 现象 | 处理 |
|------|------|
| `reason=omnirt_unavailable` | 检查 OmniRT 端口、`OMNIRT_ENDPOINT` 和 `/v1/audio2video/models`。 |
| OmniRT 未列出 `quicktalk` | 检查 `OMNIRT_QUICKTALK_RUNTIME=1`、checkpoint 路径和启动日志。 |
| 首帧慢或显存高 | 调整 `OMNIRT_QUICKTALK_MAX_LONG_EDGE`、HuBERT device 或预热策略。 |
| avatar 资源不可用 | 检查所选 avatar 是否已上传、可读取，并确认会话配置完整。 |
