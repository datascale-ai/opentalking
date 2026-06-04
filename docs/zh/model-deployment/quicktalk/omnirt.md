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

如果 `scripts/quickstart/env` 已经配置了 `OMNIRT_MODEL_ROOT`、`OMNIRT_QUICKTALK_MODEL_ROOT` 或 `OMNIRT_QUICKTALK_DEVICE`，脚本会优先读取这些值；以启动日志里打印的 `model root`、`device` 和 `hubert device` 为准。需要完全按当前终端变量运行时，先更新该 env 文件，或设置 `OPENTALKING_QUICKSTART_ENV=/path/to/your-env`。
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

## 5. 启动或重启前端

上一步的 `scripts/start_unified.sh` 已经会启动 WebUI。若只需要重启前端，或后端已经在 `8000` 端口运行，另开终端执行：

```bash title="终端"
cd "$OPENTALKING_HOME"
bash scripts/quickstart/start_frontend.sh --api-port 8000 --web-port 5173 --host 0.0.0.0
```

远程服务器部署时，把本地浏览器端口映射到服务器 `5173`，再打开 `http://127.0.0.1:5173`。

## 6. 验证

```bash title="终端"
curl -fsS http://127.0.0.1:9000/v1/audio2video/models | python3 -m json.tool
curl -s http://127.0.0.1:8000/models | python3 -m json.tool
```

期望 OpenTalking 返回：

```json
{"id":"quicktalk","backend":"omnirt","connected":true,"reason":"omnirt"}
```
