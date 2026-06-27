# Wav2Lip Local 部署

Local 模式使用 OpenTalking 内置 Wav2Lip adapter，是最轻量的真实口型同步验证路径。它适合单机 GPU、资产验证和低成本 demo。

## 适用场景

- 第一次从 `mock` 切到真实 talking-head 模型。
- 希望在 OpenTalking 进程内完成推理，不额外部署 OmniRT。
- 使用内置或自定义通用 avatar，并让 Wav2Lip 流程按需读取参考图或帧资产。

## 权重准备

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME/opentalking"
mkdir -p models/wav2lip

uv pip install -U "huggingface_hub[cli]"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

hf download Pypa/wav2lip384 \
  wav2lip384.pth \
  --local-dir models/wav2lip
hf download rippertnt/wav2lip \
  s3fd.pth \
  --local-dir models/wav2lip

stat models/wav2lip/wav2lip384.pth
stat models/wav2lip/s3fd.pth
```

## 启动命令

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME/opentalking"
uv sync --extra dev --extra models --python 3.11

export OPENTALKING_WAV2LIP_MODEL_ROOT="$DIGITAL_HUMAN_HOME/opentalking/models/wav2lip"
export OPENTALKING_WAV2LIP_DEVICE=cuda
export OPENTALKING_WAV2LIP_BATCH_SIZE=16
export OPENTALKING_WAV2LIP_MAX_LONG_EDGE=832
export OPENTALKING_WAV2LIP_FACE_DET_DEVICE=cpu

bash scripts/start_unified.sh --backend local --model wav2lip --api-port 8210 --web-port 5280
```

打开 `http://localhost:5280`，选择一个可用 avatar 和 `wav2lip` 模型。

## 验证命令

```bash title="终端"
curl -fsS http://127.0.0.1:8210/health
curl -s http://127.0.0.1:8210/models | jq '.statuses[] | select(.id=="wav2lip")'
```

期望返回 `backend=local`、`connected=true`。首次加载会初始化 checkpoint、S3FD 和 avatar cache，可能需要几十秒。

## 常见错误

| 现象 | 处理 |
|------|------|
| checkpoint 找不到 | 检查 `OPENTALKING_WAV2LIP_MODEL_ROOT` 和两个 `.pth` 文件。 |
| 显存不足 | 降低 `OPENTALKING_WAV2LIP_BATCH_SIZE` 或 `OPENTALKING_WAV2LIP_MAX_LONG_EDGE`。 |
| 首帧慢 | 设置 `OPENTALKING_PREWARM_AVATARS=singer` 预热常用 avatar。 |
| 画质增强报错 | `easy_enhanced` 需要 GFPGAN，并配置 `OPENTALKING_WAV2LIP_GFPGAN_CHECKPOINT`。 |
