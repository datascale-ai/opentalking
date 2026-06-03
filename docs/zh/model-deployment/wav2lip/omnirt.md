# Wav2Lip with OmniRT

适用：你希望 Wav2Lip 推理由独立 OmniRT 服务承载，OpenTalking 只连接 OmniRT audio2video gateway。

## 1. 准备 OmniRT 环境

```bash title="终端"
export DIGITAL_HUMAN_HOME=/path/to/digital_human
export OPENTALKING_HOME="$DIGITAL_HUMAN_HOME/opentalking"
export OMNIRT_REPO="$DIGITAL_HUMAN_HOME/omnirt"
export OMNIRT_HOME="$OMNIRT_REPO/.omnirt"

# 网络较慢时先设置镜像。
export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export UV_HTTP_TIMEOUT=300
export UV_LINK_MODE=copy

cd "$OMNIRT_REPO"
uv sync --extra server --python 3.11
```

## 2. 准备权重

```bash title="终端"
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
mkdir -p "$OMNIRT_MODEL_ROOT/wav2lip"
uv pip install -U "huggingface_hub[cli]"
hf download Pypa/wav2lip384 wav2lip384.pth --local-dir "$OMNIRT_MODEL_ROOT/wav2lip"
hf download rippertnt/wav2lip s3fd.pth --local-dir "$OMNIRT_MODEL_ROOT/wav2lip"
```

## 3. 启动 OmniRT Wav2Lip

```bash title="终端"
cd "$OPENTALKING_HOME"
bash scripts/quickstart/start_omnirt_wav2lip.sh --device cuda --port 9000
```

Ascend 评估环境可以使用：

```bash title="终端"
source /usr/local/Ascend/ascend-toolkit/set_env.sh
bash scripts/quickstart/start_omnirt_wav2lip.sh --device npu --port 9000
```

## 4. 启动 OpenTalking

```bash title="终端"
cd "$OPENTALKING_HOME"
bash scripts/start_unified.sh \
  --backend omnirt \
  --model wav2lip \
  --omnirt http://127.0.0.1:9000 \
  --api-port 8000 \
  --web-port 5173
```

## 5. 验证

```bash title="终端"
curl -fsS http://127.0.0.1:9000/v1/audio2video/models | jq
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="wav2lip")'
```

期望：

```json
{"id":"wav2lip","backend":"omnirt","connected":true,"reason":"omnirt"}
```
