# Wav2Lip OmniRT 部署

OmniRT 模式把 Wav2Lip 推理服务化，适合让 OpenTalking 与模型依赖解耦，或在同一 OmniRT endpoint 上同时启用多个 talking-head 模型。

## 适用场景

- Web/API 与推理 GPU 分离部署。
- 需要统一通过 `/v1/audio2video/{model}` 管理模型。
- 希望复用 OmniRT 的预加载、批处理和设备配置。

## 权重准备

```bash title="终端"
export DIGITAL_HUMAN_HOME="$HOME/digital-human"
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
mkdir -p "$OMNIRT_MODEL_ROOT/wav2lip"

uv pip install -U "huggingface_hub[cli]"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

hf download Pypa/wav2lip384 \
  wav2lip384.pth \
  --local-dir "$OMNIRT_MODEL_ROOT/wav2lip"
hf download rippertnt/wav2lip \
  s3fd.pth \
  --local-dir "$OMNIRT_MODEL_ROOT/wav2lip"
```

## 启动命令

```bash title="终端"
cd "$OMNIRT_HOME"
uv sync --extra server --extra wav2lip-cuda --python 3.11
source .venv/bin/activate

export OMNIRT_WAV2LIP_RUNTIME=1
export OMNIRT_WAV2LIP_MODELS_DIR="$OMNIRT_MODEL_ROOT"
export OMNIRT_WAV2LIP_CHECKPOINT="$OMNIRT_MODEL_ROOT/wav2lip/wav2lip384.pth"
export OMNIRT_WAV2LIP_DEVICE=cuda
export OMNIRT_WAV2LIP_FACE_DET_DEVICE=cpu
export OMNIRT_WAV2LIP_BATCH_SIZE=16
export OMNIRT_WAV2LIP_MAX_LONG_EDGE=832
export OMNIRT_WAV2LIP_PRELOAD=1

omnirt serve-avatar-ws --host 0.0.0.0 --port 9000 --backend cuda
```

另开终端启动 OpenTalking：

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/start_unified.sh \
  --backend omnirt \
  --model wav2lip \
  --omnirt http://127.0.0.1:9000 \
  --api-port 8310 \
  --web-port 5380
```

## 验证命令

```bash title="终端"
curl -fsS http://127.0.0.1:9000/v1/audio2video/models | jq
curl -s http://127.0.0.1:8310/models | jq '.statuses[] | select(.id=="wav2lip")'
```

## 常见错误

| 现象 | 处理 |
|------|------|
| OmniRT 未加载 Wav2Lip | 检查 `OMNIRT_WAV2LIP_RUNTIME=1` 和 `OMNIRT_WAV2LIP_CHECKPOINT`。 |
| `reason=omnirt_unavailable` | 检查 OpenTalking 的 `--omnirt` 地址和 OmniRT 健康状态。 |
| 端到端延迟高 | 降低 batch size、限制 `MAX_LONG_EDGE`，并启用 `OMNIRT_WAV2LIP_PRELOAD=1`。 |
| avatar 资源不可用 | 确认 avatar 资源可读取，并检查会话配置是否完整。 |
