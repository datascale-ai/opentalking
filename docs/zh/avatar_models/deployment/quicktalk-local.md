# QuickTalk Local 部署

Local 模式把 QuickTalk adapter 加载在 OpenTalking 进程内，适合单机 CUDA 机器验证实时口播、调试 avatar cache，以及在引入 OmniRT 前确认前后端链路。

## 适用场景

- 已经跑通 `mock`，现在需要真实 talking-head 输出。
- 单机部署，GPU、WebUI、API 都在同一台机器。
- 需要使用 `opentalking-prepare-cache` 为常用通用 avatar 预热 QuickTalk 缓存。

## 权重准备

权重统一放在部署根目录 `models/quicktalk/`。网络慢时可以设置 `HF_ENDPOINT`。

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME/opentalking"
export OPENTALKING_MODEL_ROOT="${OPENTALKING_MODEL_ROOT:-$DIGITAL_HUMAN_HOME/models}"
export OPENTALKING_QUICKTALK_ASSET_ROOT="${OPENTALKING_QUICKTALK_ASSET_ROOT:-$OPENTALKING_MODEL_ROOT/quicktalk}"
mkdir -p "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints"

uv pip install -U "huggingface_hub[cli]"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

hf download datascale-ai/quicktalk \
  --local-dir "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints"
```

`datascale-ai/quicktalk` 已包含 QuickTalk、HuBERT 和 InsightFace `buffalo_l`。如果使用的是旧镜像或离线包，缺少 `auxiliary/models/buffalo_l/` 时再按下面方式手动补齐：

```bash title="终端"
TMP_DIR="$OPENTALKING_QUICKTALK_ASSET_ROOT/_tmp/insightface"
mkdir -p "$TMP_DIR" "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints/auxiliary/models"
curl -L \
  -o "$TMP_DIR/buffalo_l.zip" \
  https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip
unzip -q -o "$TMP_DIR/buffalo_l.zip" \
  -d "$TMP_DIR"
rsync -a "$TMP_DIR/buffalo_l/" \
  "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints/auxiliary/models/buffalo_l/"
```

## 启动命令

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME/opentalking"
uv sync --extra dev --extra models --extra quicktalk-cuda --python 3.11

export OPENTALKING_TORCH_DEVICE=cuda:0
export OPENTALKING_MODEL_ROOT="${OPENTALKING_MODEL_ROOT:-$DIGITAL_HUMAN_HOME/models}"
export OPENTALKING_QUICKTALK_ASSET_ROOT="${OPENTALKING_QUICKTALK_ASSET_ROOT:-$OPENTALKING_MODEL_ROOT/quicktalk}"
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
| `connected=false` | 检查 `OPENTALKING_QUICKTALK_ASSET_ROOT`、CUDA 设备和 `$DIGITAL_HUMAN_HOME/models/quicktalk/checkpoints`。 |
| 首轮等待很久 | 开启 `OPENTALKING_QUICKTALK_WORKER_CACHE=1` 或提前执行 `opentalking-prepare-cache`。 |
| avatar 加载失败 | 检查 avatar 是否能被服务读取；如配置了固定模板视频，确认路径可访问。 |
| Hugging Face 下载失败 | 配置 `HF_ENDPOINT` 或先离线下载后同步到同样目录。 |

## 关闭服务

停止由 `scripts/start_unified.sh` 或 quickstart 辅助脚本启动的 OpenTalking API、WebUI 和本地模型进程：

```bash title="终端"
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/stop_all.sh
```
