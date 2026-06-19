# QuickTalk

## 支持状态

| 项 | 值 |
|----|----|
| 模型 ID | `quicktalk` |
| Backend | `local` |
| 证据等级 | 已内置，已验证 |
| 推荐用途 | 本地实时 adapter、开发参考、QuickTalk 资产验证 |

## 推荐硬件

本地 CUDA GPU。`mock` 路径通过后，再接入 QuickTalk 资产包和模板视频。

## 权重下载

QuickTalk local adapter 直接在 OpenTalking 进程内加载权重，不需要 OmniRT。本地权重、第三方 HuBERT / InsightFace 依赖和缓存统一放到仓库根目录 `models/quicktalk/`。

下载 QuickTalk 权重和 HuBERT 文件：

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
mkdir -p models/quicktalk/checkpoints

# 可选：网络慢时使用镜像
export HF_ENDPOINT=https://hf-mirror.com

hf download datascale-ai/quicktalk \
  quicktalk.pth \
  repair.npy \
  chinese-hubert-large/config.json \
  chinese-hubert-large/preprocessor_config.json \
  chinese-hubert-large/pytorch_model.bin \
  --local-dir models/quicktalk/checkpoints
```

QuickTalk 权重和 HuBERT 文件已经包含在 `datascale-ai/quicktalk` 中。QuickTalk 仍需要单独准备 InsightFace `buffalo_l` 依赖权重：

```bash
# 下载并解压 InsightFace buffalo_l 到 QuickTalk auxiliary 目录。
mkdir -p /tmp/opentalking-insightface models/quicktalk/checkpoints/auxiliary/models
curl -L \
  -o /tmp/opentalking-insightface/buffalo_l.zip \
  https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip
unzip -q -o /tmp/opentalking-insightface/buffalo_l.zip \
  -d /tmp/opentalking-insightface
rsync -a /tmp/opentalking-insightface/buffalo_l/ \
  models/quicktalk/checkpoints/auxiliary/models/buffalo_l/
```

## 目录结构

```text
models/
  quicktalk/
    checkpoints/
      quicktalk.pth
      repair.npy
      chinese-hubert-large/
        config.json
        preprocessor_config.json
        pytorch_model.bin
      auxiliary/models/buffalo_l/
        *.onnx
```

检查必需文件：

```bash
stat models/quicktalk/checkpoints/quicktalk.pth
stat models/quicktalk/checkpoints/repair.npy
stat models/quicktalk/checkpoints/chinese-hubert-large/pytorch_model.bin
stat models/quicktalk/checkpoints/auxiliary/models/buffalo_l/det_10g.onnx
```

如果已有旧资产包以 `hdModule/checkpoints/` 组织，也可以把 `OPENTALKING_QUICKTALK_ASSET_ROOT` 指向 `hdModule` 的父目录或 `hdModule` 本身，adapter 会自动归一化到实际包含 `checkpoints/` 的目录。

## 配置项

```env title=".env"
OPENTALKING_QUICKTALK_ASSET_ROOT=/absolute/path/to/opentalking/models/quicktalk
# 可选：内置 QuickTalk avatar 已在 manifest 中声明 template_video；自定义 avatar 可用该变量覆盖。
# OPENTALKING_QUICKTALK_TEMPLATE_VIDEO=/absolute/path/to/template.mp4
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

## 启动命令

```bash
export OPENTALKING_TORCH_DEVICE=cuda:0
export OPENTALKING_QUICKTALK_ASSET_ROOT="$DIGITAL_HUMAN_HOME/opentalking/models/quicktalk"
export OPENTALKING_QUICKTALK_WORKER_CACHE=1

cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/start_unified.sh --backend local --model quicktalk --api-port 8210 --web-port 5280
```

打开 `http://localhost:5280`，选择 `QuickTalk Local` 形象和 `quicktalk` 模型。若不指定 `--web-port`，默认前端地址为 `http://localhost:5173`。

## 准备 Avatar Cache

QuickTalk 会为每个 avatar 生成运行缓存：

- `examples/avatars/<avatar>/quicktalk/template_<width>x<height>.mp4`
- `examples/avatars/<avatar>/quicktalk/face_cache_v3_<width>x<height>.npz`

这些文件由本机模型和 avatar 共同决定，属于部署环境生成物，不建议提交到代码仓。需要提前准备时，运行：

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"

opentalking-prepare-cache \
  --model quicktalk \
  --avatars-root examples/avatars \
  --quicktalk-model-root models/quicktalk \
  --device cuda:0 \
  --model-backend pth \
  --verify
```

只准备单个 avatar：

```bash
opentalking-prepare-cache \
  --model quicktalk \
  --avatars-root examples/avatars \
  --avatar singer \
  --quicktalk-model-root models/quicktalk \
  --device cuda:0 \
  --model-backend pth \
  --verify
```

## `/models` 验证

```bash
curl -s http://127.0.0.1:8210/models | jq '.statuses[] | select(.id=="quicktalk")'
```

期望：

```json
{"id":"quicktalk","backend":"local","connected":true,"reason":"local_runtime"}
```

## 常见错误

| 现象 | 处理 |
|------|------|
| `connected=false` | 检查 QuickTalk 依赖、资产路径和 `OPENTALKING_TORCH_DEVICE`。 |
| 首轮等待较长 | 开启 `OPENTALKING_QUICKTALK_WORKER_CACHE=1`。 |
| Avatar 加载失败 | manifest 中 `asset_root`、`template_video` 必须是可访问绝对路径。 |
