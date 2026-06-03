# QuickTalk Local 单机部署

适用：你希望 OpenTalking 直接在本进程内加载 QuickTalk adapter，不先引入独立 OmniRT 服务。这是验证自定义 avatar、本地 STT/TTS 和实时数字人链路的推荐起点。

## 1. 安装依赖

```bash title="终端"
export DIGITAL_HUMAN_HOME=/path/to/digital_human
export OPENTALKING_HOME="$DIGITAL_HUMAN_HOME/opentalking"

# 网络较慢时先设置镜像。
export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export UV_HTTP_TIMEOUT=300
export UV_LINK_MODE=copy

cd "$OPENTALKING_HOME"
uv sync --extra dev --extra models --extra quicktalk-cuda --python 3.11
source .venv/bin/activate
```

## 2. 准备权重

local adapter 的资产根必须包含 `checkpoints/` 目录。推荐放在仓库内 `models/quicktalk/`，也可以用绝对路径放到共享模型目录。

```text
models/quicktalk/
  checkpoints/
    quicktalk.pth 或 256.onnx
    repair.npy
    chinese-hubert-large/
      pytorch_model.bin
    auxiliary/models/buffalo_l/ 或 auxiliary_min/
      det_10g.onnx
```

如果已有旧资产包以 `hdModule/checkpoints/` 组织，可以把 `OPENTALKING_QUICKTALK_ASSET_ROOT` 指向 `hdModule` 的父目录或 `hdModule` 本身，adapter 会自动归一化到实际包含 `checkpoints/` 的目录。

## 3. 配置

```env title=".env"
OPENTALKING_QUICKTALK_BACKEND=local
OPENTALKING_QUICKTALK_ASSET_ROOT=/absolute/path/to/opentalking/models/quicktalk
OPENTALKING_QUICKTALK_WORKER_CACHE=1
OPENTALKING_TORCH_DEVICE=cuda:0
```

Avatar manifest 也应声明：

```json title="manifest.json"
{
  "model_type": "quicktalk",
  "metadata": {
    "asset_root": "/absolute/path/to/opentalking/models/quicktalk",
    "template_video": "/absolute/path/to/template.mp4"
  }
}
```

## 4. 启动

```bash title="终端"
cd "$OPENTALKING_HOME"
bash scripts/start_unified.sh --backend local --model quicktalk --api-port 8000 --web-port 5173
```

打开 `http://localhost:5173`，选择 QuickTalk avatar 和 `quicktalk` 模型。

## 5. 准备 Avatar Cache

QuickTalk 会为每个 avatar 生成运行缓存：

- `examples/avatars/<avatar>/quicktalk/template_<width>x<height>.mp4`
- `examples/avatars/<avatar>/quicktalk/face_cache_v3_<width>x<height>.npz`

需要提前准备时运行：

```bash title="终端"
cd "$OPENTALKING_HOME"
opentalking-prepare-cache \
  --model quicktalk \
  --avatars-root examples/avatars \
  --quicktalk-model-root models/quicktalk \
  --device cuda:0 \
  --model-backend pth \
  --verify
```

## 6. 验证

```bash title="终端"
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="quicktalk")'
```

期望：

```json
{"id":"quicktalk","backend":"local","connected":true,"reason":"local_runtime"}
```
