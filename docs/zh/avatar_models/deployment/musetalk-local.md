# MuseTalk Local 部署

Local 模式由 OpenTalking 启动 MuseTalk adapter，并在创建会话前调用官方预处理流程。它适合希望使用 MuseTalk 质量、但暂时不独立部署 OmniRT 的团队。

## 适用场景

- 单机 CUDA 环境，Web/API 与 MuseTalk runtime 在同一机器。
- 需要 OpenTalking 自动生成 avatar 的 `prepared/` 产物。
- 能接受首次会话前加载 DWPose、face parsing、VAE 的额外耗时。

## 权重准备

MuseTalk local 需要模型权重、官方源码和预处理 Python：

```bash title="终端"
export DIGITAL_HUMAN_HOME="$HOME/digital-human"
export OPENTALKING_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
mkdir -p "$OPENTALKING_MODEL_ROOT" "$DIGITAL_HUMAN_HOME/model-repos"

uv pip install -U "huggingface_hub[cli]"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

hf download TMElyralab/MuseTalk \
  --local-dir "$OPENTALKING_MODEL_ROOT"

git clone https://github.com/TMElyralab/MuseTalk.git \
  "$DIGITAL_HUMAN_HOME/model-repos/MuseTalk"
```

最终需要能在模型根目录找到 `musetalk/`、`sd-vae-ft-mse/`、`whisper/`、`dwpose/`、`face-parse-bisenet/` 等目录。推荐使用仓库脚本检查预处理环境：

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/prepare_local_musetalk.sh
```

## 启动命令

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME/opentalking"
uv sync --extra dev --extra models --python 3.11

export OPENTALKING_MUSETALK_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
export OPENTALKING_MUSETALK_REPO="$DIGITAL_HUMAN_HOME/model-repos/MuseTalk"
export OPENTALKING_MUSETALK_PREPROCESS_PYTHON="$DIGITAL_HUMAN_HOME/runtimes/musetalk-preprocess/venv/bin/python"

bash scripts/start_unified.sh --backend local --model musetalk --api-port 18000 --web-port 18173
```

创建会话时，如果 avatar 缺少 `prepared/prepared_info.json`，OpenTalking 会先运行 MuseTalk 官方预处理，然后再加载会话。

## 验证命令

```bash title="终端"
curl -fsS http://127.0.0.1:18000/health
curl -s http://127.0.0.1:18000/models | jq '.statuses[] | select(.id=="musetalk")'
```

期望返回 `backend=local`、`connected=true`。

## 常见错误

| 现象 | 处理 |
|------|------|
| `No module named 'mmcv._ext'` | 预处理 Python 需要 full `mmcv`，不能只装 `mmcv-lite`。 |
| 预处理失败 | 检查 `OPENTALKING_MUSETALK_REPO`、`dwpose`、`face-parse-bisenet`。 |
| 首次会话慢 | 预处理和 VAE 加载耗时正常；可提前为常用 avatar 生成 `prepared/`。 |
| avatar 资源不可用 | 检查 avatar 是否已上传、可读取，并确认会话配置完整。 |
