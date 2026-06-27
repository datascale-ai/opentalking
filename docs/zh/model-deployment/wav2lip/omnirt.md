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
source .venv/bin/activate
```

## 2. 准备权重

```bash title="终端"
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
mkdir -p "$OMNIRT_MODEL_ROOT/wav2lip"

hf download Pypa/wav2lip384 wav2lip384.pth --local-dir "$OMNIRT_MODEL_ROOT/wav2lip"
hf download rippertnt/wav2lip s3fd.pth --local-dir "$OMNIRT_MODEL_ROOT/wav2lip"
```

如果 `scripts/quickstart/env` 已经配置了 `OMNIRT_MODEL_ROOT`，启动脚本会优先读取该值；以启动日志里打印的 `models` 路径为准。需要完全按当前终端变量运行时，先更新该 env 文件，或设置 `OPENTALKING_QUICKSTART_ENV=/path/to/your-env`。

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

期望：

```json
{"id":"wav2lip","backend":"omnirt","connected":true,"reason":"omnirt"}
```
