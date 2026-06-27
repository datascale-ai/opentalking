# MuseTalk OmniRT 部署

OmniRT 模式让外部 MuseTalk 服务负责权重加载、官方 runtime 和 GPU 调度，OpenTalking 只连接统一的 `/v1/audio2video/musetalk` 接口。

## 适用场景

- MuseTalk 依赖较重，希望与 OpenTalking 主进程隔离。
- Web/API 和推理 GPU 分开部署。
- 需要与 Wav2Lip、QuickTalk 等模型共用 OmniRT 服务入口。

## 权重准备

```bash title="终端"
export DIGITAL_HUMAN_HOME="$HOME/digital-human"
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
mkdir -p "$OMNIRT_MODEL_ROOT" "$DIGITAL_HUMAN_HOME/model-repos"

uv pip install -U "huggingface_hub[cli]"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

hf download TMElyralab/MuseTalk \
  --local-dir "$OMNIRT_MODEL_ROOT"

git clone https://github.com/TMElyralab/MuseTalk.git \
  "$DIGITAL_HUMAN_HOME/model-repos/MuseTalk"
```

确认 `musetalk/`、`sd-vae-ft-mse/`、`whisper/`、`dwpose/`、`face-parse-bisenet/` 均在 `$OMNIRT_MODEL_ROOT` 下。

## 启动命令

使用 quickstart 脚本准备并启动 MuseTalk runtime：

```bash title="终端"
cd "$OMNIRT_HOME"
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
export OMNIRT_MUSETALK_REPO="$DIGITAL_HUMAN_HOME/model-repos/MuseTalk"
export OMNIRT_MUSETALK_DEVICE=cuda
export OMNIRT_MUSETALK_PORT=8766

bash scripts/quickstart/start_omnirt_musetalk.sh
```

然后启动 OpenTalking：

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/start_unified.sh \
  --backend omnirt \
  --model musetalk \
  --omnirt http://127.0.0.1:9000 \
  --api-port 8310 \
  --web-port 5380
```

## 验证命令

```bash title="终端"
curl -fsS http://127.0.0.1:9000/v1/audio2video/models | jq
curl -s http://127.0.0.1:8310/models | jq '.statuses[] | select(.id=="musetalk")'
```

## 常见错误

| 现象 | 处理 |
|------|------|
| OmniRT 未列出 `musetalk` | 检查 `OMNIRT_MUSETALK_REPO`、模型目录和启动脚本日志。 |
| `reason=omnirt_unavailable` | 检查 OpenTalking `--omnirt` 地址和 OmniRT 端口。 |
| MuseTalk 子服务端口冲突 | 调整 `OMNIRT_MUSETALK_PORT`。 |
| 首次加载慢 | MuseTalk 预加载和 avatar 预处理耗时较长，生产环境建议预热。 |
