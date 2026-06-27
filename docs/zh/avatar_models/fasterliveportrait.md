# FasterLivePortrait / JoyVASA
## 支持状态

| 项 | 值 |
|----|----|
| 模型 ID | `fasterliveportrait` |
| Backend | `omnirt` |
| 证据等级 | 已文档化；实时链路通过 OmniRT runtime 暴露 |
| 推荐用途 | 单卡实时音频驱动头像、贴回原始资产图、前端幅度热更新 |

## 常见问题

| 现象 | 处理 |
|------|------|
| `/models` 中是 `runtime_not_enabled` | 确认 OmniRT 启动时设置了 `OMNIRT_FASTLIVEPORTRAIT_RUNTIME=1`，并检查 checkpoint 路径和 `logs/omnirt`。 |
| 音频驱动没有口型 | 检查 `JoyVASA/motion_generator`、`JoyVASA/motion_template` 和 `chinese-hubert-base/pytorch_model.bin`。 |
| 生成报 ONNXRuntime `GridSample` 错误 | 重新执行 `uv sync --extra server --extra fasterliveportrait --python 3.11`，确认 `import tensorrt` 成功，并使用 `OMNIRT_FASTLIVEPORTRAIT_CFG=configs/trt_infer.yaml`。 |
| 浏览器能看到模型但创建会话失败 | 选择 `model_type` 匹配 `fasterliveportrait` 的 avatar，或准备对应 avatar bundle。 |


FasterLivePortrait 当前也走 OmniRT `audio2video` 兼容路径。OpenTalking 负责会话、TTS/音频流、WebRTC 播放和前端参数下发；OmniRT 常驻加载 FasterLivePortrait 与 JoyVASA，统一暴露 `/v1/audio2video/fasterliveportrait`。

该路径适合单卡实时数字人：默认使用 25fps、1 秒音频 chunk、448 宽实时档，并把动头贴回原始资产图。上传整身图时仍以 FasterLivePortrait 检测到的人脸区域驱动，身体本身不会生成新动作。

## 1. 准备代码和权重

需要两个目录：FasterLivePortrait 源码 checkout，以及真实 checkpoint 目录。不要用软链接时，直接复制或下载到模型根目录即可。

```bash title="终端"
if [ ! -d "$FASTERLIVEPORTRAIT_HOME/.git" ]; then
  git clone https://github.com/KlingAIResearch/LivePortrait.git "$FASTERLIVEPORTRAIT_HOME"
fi

mkdir -p "$OMNIRT_MODEL_ROOT/FasterLivePortrait/checkpoints"
```

最终 checkpoint 目录至少包含：

```text
$OMNIRT_MODEL_ROOT/FasterLivePortrait/checkpoints/
  JoyVASA/
    motion_generator/motion_generator_hubert_chinese.pt
    motion_template/motion_template.pkl
  chinese-hubert-base/
    config.json
    preprocessor_config.json
    pytorch_model.bin
  liveportrait/ 或 appearance_feature_extractor.onnx 等 FasterLivePortrait ONNX/TRT 文件
```

如果你已经在别的机器或目录下载好模型，建议用 `rsync` 复制真实文件：

```bash title="终端"
rsync -a /path/to/FasterLivePortrait/checkpoints/ \
  "$OMNIRT_MODEL_ROOT/FasterLivePortrait/checkpoints/"
```

部署前先检查关键文件：

```bash title="终端"
test -f "$OMNIRT_MODEL_ROOT/FasterLivePortrait/checkpoints/JoyVASA/motion_generator/motion_generator_hubert_chinese.pt"
test -f "$OMNIRT_MODEL_ROOT/FasterLivePortrait/checkpoints/JoyVASA/motion_template/motion_template.pkl"
test -f "$OMNIRT_MODEL_ROOT/FasterLivePortrait/checkpoints/chinese-hubert-base/pytorch_model.bin"
```

## 2. 准备 OmniRT 环境

```bash title="终端"
cd "$OMNIRT_HOME"
export UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$DIGITAL_HUMAN_HOME/.uv-cache}"
uv sync --extra server --extra fasterliveportrait --python 3.11
```

FasterLivePortrait 实时路径默认使用 TensorRT。`fasterliveportrait` extra 会安装 `onnxruntime-gpu`、`tensorrt-cu12`、`tensorrt-cu12-bindings` 和 `tensorrt-cu12-libs`。TensorRT libs wheel 约 4GB，必须确保 `UV_CACHE_DIR` 指向空间充足的数据盘；不要让它落到空间很小的 `/root/.cache/uv`。

部署前可确认 `uv run python -c "import tensorrt as trt; print(trt.__version__)"` 能正常输出版本号。

## 3. 启动 OmniRT FasterLivePortrait runtime

```bash title="终端"
cd "$OMNIRT_HOME"
OMNIRT_FASTLIVEPORTRAIT_RUNTIME=1 \
OMNIRT_FASTLIVEPORTRAIT_LOAD_MODELS=1 \
OMNIRT_FASTLIVEPORTRAIT_ROOT="$FASTERLIVEPORTRAIT_HOME" \
OMNIRT_FASTLIVEPORTRAIT_CHECKPOINTS_DIR="$OMNIRT_MODEL_ROOT/FasterLivePortrait/checkpoints" \
OMNIRT_FASTLIVEPORTRAIT_CFG=configs/trt_infer.yaml \
OMNIRT_FASTLIVEPORTRAIT_DEVICE=cuda:0 \
OMNIRT_FASTLIVEPORTRAIT_JPEG_QUALITY=85 \
uv run omnirt serve-avatar-ws --host 0.0.0.0 --port 9000 --backend cuda
```

服务启动后验证 OmniRT 是否报告模型：

```bash title="终端"
curl -s http://127.0.0.1:9000/v1/audio2video/models | jq '.statuses[] | select(.id=="fasterliveportrait")'
```

期望状态类似：

```json
{"id":"fasterliveportrait","connected":true,"reason":"fasterliveportrait_runtime"}
```

## 4. 配置并启动 OpenTalking

OpenTalking 默认把 `fasterliveportrait` 配成 `backend: omnirt`。实时档参数位于 `configs/synthesis/fasterliveportrait.yaml`，常用默认值：

```yaml title="configs/synthesis/fasterliveportrait.yaml"
width: 448
fps: 25
chunk_samples: 16000
emit_frames_per_chunk: 25
head_motion_multiplier: 0.3
pose_motion_multiplier: 0.35
yaw_multiplier: 0.85
pitch_multiplier: 1.0
roll_multiplier: 0.85
animation_region: lip
expression_multiplier: 1.0
mouth_open_multiplier: 1.25
mouth_corner_multiplier: 0.85
cheek_jaw_multiplier: 0.9
driving_multiplier: 1.0
cfg_scale: 4.0
flag_relative_motion: true
flag_stitching: true
head_only_pasteback: false
```

启动 OpenTalking 并指向 OmniRT：

```bash title="终端"
cd "$OPENTALKING_HOME"
OMNIRT_ENDPOINT=http://127.0.0.1:9000 \
OPENTALKING_OMNIRT_ENDPOINT=http://127.0.0.1:9000 \
uv run opentalking-unified --host 0.0.0.0 --port 8000
```

前端：

```bash title="终端"
cd "$OPENTALKING_HOME/apps/web"
npm ci
VITE_BACKEND_PORT=8000 npm run dev -- --host 0.0.0.0 --port 5173
```

验证 OpenTalking 能看到模型：

```bash title="终端"
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="fasterliveportrait")'
```

期望：

```json
{"id":"fasterliveportrait","backend":"omnirt","connected":true,"reason":"omnirt"}
```

## 5. 前端参数和热更新

在前端选择 `FasterLivePortrait` 后，会出现“FasterLivePortrait 幅度”配置区。未启动会话时，点击“应用配置”会保存到下一次会话；会话运行中点击“实时应用”，下一块音频 chunk 开始生效，无需重启会话。

| 参数 | 作用 | 建议范围 |
|------|------|----------|
| `head_motion_multiplier` | 整体头部运动幅度 | 默认 0.3，常调 0.2-0.8 |
| `pose_motion_multiplier` | pitch/yaw/roll 姿态幅度，想减少左右晃先调它 | 0.2-0.5 |
| `yaw_multiplier` | 单独控制左右摇头幅度 | 默认 0.85，常调 0.6-1.0 |
| `pitch_multiplier` | 单独控制上下点头幅度 | 默认 1.0，常调 0.7-1.1 |
| `roll_multiplier` | 单独控制左右歪头幅度 | 默认 0.85，常调 0.6-1.0 |
| `animation_region` | FLP 驱动区域；实时默认只驱动嘴部，减少瞪眼和全脸夸张 | 默认 `lip`，需要全表情时改 `all` |
| `expression_multiplier` | 整体表情和口型幅度 | 默认 1.0，常调 0.9-1.2 |
| `mouth_open_multiplier` | 张嘴开合幅度 | 默认 1.25，常调 1.0-1.4 |
| `mouth_corner_multiplier` | 嘴角牵动幅度 | 默认 0.85，常调 0.7-1.0 |
| `cheek_jaw_multiplier` | 脸颊和下颌幅度 | 默认 0.9，常调 0.7-1.1 |
| `driving_multiplier` | 整体关键点驱动幅度 | 0.8-1.2 |
| `cfg_scale` | JoyVASA 音频跟随强度 | 默认 4.0，常调 3.5-4.5 |

推荐先用 `head_motion_multiplier=0.3`、`pose_motion_multiplier=0.35`、`yaw_multiplier=0.85`、`roll_multiplier=0.85`、`animation_region=lip`、`expression_multiplier=1.0`、`mouth_open_multiplier=1.25`、`mouth_corner_multiplier=0.85`、`cheek_jaw_multiplier=0.9`、`cfg_scale=4.0`，并保持 `flag_relative_motion=true`。如果头左右晃动明显，先把 `yaw_multiplier` 降到 `0.7`；如果嘴型偏嘟或笑得过大，先把 `mouth_corner_multiplier` 降到 `0.75`；如果需要更丰富表情，再把驱动区域从 `lip` 切到 `all`。不要用抽帧来提速。

## 6. 性能验收

```bash title="终端"
cd "$OMNIRT_HOME"
uv run python scripts/bench_fasterliveportrait_ws.py \
  --url ws://127.0.0.1:9000/v1/audio2video/fasterliveportrait \
  --duration 30 \
  --chunk-samples 16000
```

单卡实时优先看：首包耗时、每 chunk 生成耗时、输出 fps、浏览器队列是否持续积压。若 `448` 宽不能稳定超过 25fps，再降低到 `416`；如果质量优先可把 `width` 调到 `480` 或 `540`，但不建议作为实时默认。
