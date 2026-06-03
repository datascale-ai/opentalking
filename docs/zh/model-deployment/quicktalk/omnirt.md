# QuickTalk with OmniRT

适用：你希望 QuickTalk 由独立 OmniRT 服务托管，OpenTalking 只连接 `/v1/audio2video/quicktalk` 并负责会话、TTS 和 WebRTC。

## 1. 准备仓库和环境

```bash title="终端"
export DIGITAL_HUMAN_HOME=/path/to/digital_human
export OPENTALKING_HOME="$DIGITAL_HUMAN_HOME/opentalking"
export OMNIRT_REPO="$DIGITAL_HUMAN_HOME/omnirt"
export OMNIRT_HOME="$OMNIRT_REPO/.omnirt"
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"

# 网络较慢时先设置镜像。
export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export UV_HTTP_TIMEOUT=300
export UV_LINK_MODE=copy

cd "$DIGITAL_HUMAN_HOME"
git clone https://github.com/datascale-ai/opentalking.git opentalking
git clone https://github.com/datascale-ai/omnirt.git omnirt

cd "$OMNIRT_REPO"
uv sync --extra server --python 3.11
```

## 2. 准备权重

`start_omnirt_quicktalk.sh` 默认读取 `$OMNIRT_MODEL_ROOT/quicktalk`：

```text
$OMNIRT_MODEL_ROOT/quicktalk/
  quicktalk.pth
  repair.npy
  chinese-hubert-large/
    config.json
    preprocessor_config.json
    pytorch_model.bin
  auxiliary/models/buffalo_l/
    det_10g.onnx
```

## 3. 启动 OmniRT QuickTalk

```bash title="终端"
cd "$OPENTALKING_HOME"
bash scripts/quickstart/start_omnirt_quicktalk.sh --device cuda:0 --port 9000
```

脚本会在 OmniRT `.venv` 中同步 `server` 和 `quicktalk-cuda` 依赖，并设置 `OMNIRT_QUICKTALK_RUNTIME=1`。
如果你要复用已有仓库，跳过 `git clone`，只要保证上面的 `OPENTALKING_HOME`、`OMNIRT_REPO`、`OMNIRT_MODEL_ROOT` 指向实际路径即可。

## 4. 启动 OpenTalking

```bash title="终端"
cd "$OPENTALKING_HOME"
bash scripts/start_unified.sh \
  --backend omnirt \
  --model quicktalk \
  --omnirt http://127.0.0.1:9000 \
  --api-port 8000 \
  --web-port 5173
```

## 5. 验证

```bash title="终端"
curl -fsS http://127.0.0.1:9000/v1/audio2video/models | jq
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="quicktalk")'
```

期望 OpenTalking 返回：

```json
{"id":"quicktalk","backend":"omnirt","connected":true,"reason":"omnirt"}
```
