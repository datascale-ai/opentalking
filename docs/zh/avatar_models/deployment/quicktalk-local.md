# QuickTalk Local 部署

Local 模式把 QuickTalk adapter 加载在 OpenTalking 进程内，适合单机 CUDA 机器验证实时口播、调试 avatar cache，以及在引入 OmniRT 前确认前后端链路。

## 适用场景

- 已经跑通 `mock`，现在需要真实 talking-head 输出。
- 单机部署，GPU、WebUI、API 都在同一台机器。
- 需要使用 `opentalking-prepare-cache` 为常用通用 avatar 预热 QuickTalk 缓存。

## 权重准备

权重统一放在仓库根目录 `models/quicktalk/`。网络慢时可以设置 `HF_ENDPOINT`。

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME/opentalking"
mkdir -p models/quicktalk/checkpoints

uv pip install -U "huggingface_hub[cli]"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

hf download datascale-ai/quicktalk \
  quicktalk.pth \
  repair.npy \
  chinese-hubert-large/config.json \
  chinese-hubert-large/preprocessor_config.json \
  chinese-hubert-large/pytorch_model.bin \
  --local-dir models/quicktalk/checkpoints
```

InsightFace `buffalo_l` 需要单独准备：

```bash title="终端"
mkdir -p /tmp/opentalking-insightface models/quicktalk/checkpoints/auxiliary/models
curl -L \
  -o /tmp/opentalking-insightface/buffalo_l.zip \
  https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip
unzip -q -o /tmp/opentalking-insightface/buffalo_l.zip \
  -d /tmp/opentalking-insightface
rsync -a /tmp/opentalking-insightface/buffalo_l/ \
  models/quicktalk/checkpoints/auxiliary/models/buffalo_l/
```

## 启动命令

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME/opentalking"
uv sync --extra dev --extra models --extra quicktalk-cuda --python 3.11

export OPENTALKING_TORCH_DEVICE=cuda:0
export OPENTALKING_QUICKTALK_ASSET_ROOT="$DIGITAL_HUMAN_HOME/opentalking/models/quicktalk"
export OPENTALKING_QUICKTALK_WORKER_CACHE=1

bash scripts/start_unified.sh --backend local --model quicktalk --api-port 8210 --web-port 5280
```

打开 `http://localhost:5280`，选择通用 avatar 和 `quicktalk` 模型。如果需要固定模板视频，
请在会话或部署配置中确认模板资源可访问。

## 验证命令

```bash title="终端"
curl -fsS http://127.0.0.1:8210/health
curl -s http://127.0.0.1:8210/models | jq '.statuses[] | select(.id=="quicktalk")'
```

期望返回 `backend=local`、`connected=true`。如需提前生成缓存：

```bash title="终端"
opentalking-prepare-cache \
  --model quicktalk \
  --avatars-root examples/avatars \
  --quicktalk-model-root models/quicktalk \
  --device cuda:0 \
  --model-backend pth \
  --verify
```

## 常见错误

| 现象 | 处理 |
|------|------|
| `connected=false` | 检查 `OPENTALKING_QUICKTALK_ASSET_ROOT`、CUDA 设备和 `models/quicktalk/checkpoints`。 |
| 首轮等待很久 | 开启 `OPENTALKING_QUICKTALK_WORKER_CACHE=1` 或提前执行 `opentalking-prepare-cache`。 |
| avatar 加载失败 | 检查 avatar 是否能被服务读取；如配置了固定模板视频，确认路径可访问。 |
| Hugging Face 下载失败 | 配置 `HF_ENDPOINT` 或先离线下载后同步到同样目录。 |
