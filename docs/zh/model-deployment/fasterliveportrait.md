# FasterLivePortrait / JoyVASA
## 支持状态

| 项 | 值 |
|----|----|
| 模型 ID | `fasterliveportrait` |
| Backend | `omnirt` |
| 证据等级 | 已文档化；实时链路通过 OmniRT runtime 暴露 |
| 推荐用途 | 单卡实时音频驱动头像、贴回原始资产图、视频克隆、前端幅度热更新 |

## 常见问题

| 现象 | 处理 |
|------|------|
| `/models` 中是 `runtime_not_enabled` | 确认 OmniRT 启动时设置了 `OMNIRT_FASTLIVEPORTRAIT_RUNTIME=1`，并检查 checkpoint 路径和 `logs/omnirt`。 |
| 音频驱动没有口型 | 检查 `JoyVASA/motion_generator`、`JoyVASA/motion_template` 和 `chinese-hubert-base/pytorch_model.bin`。 |
| 生成报 ONNXRuntime `GridSample` 错误 | 重新执行 `uv sync --extra server --extra fasterliveportrait --python 3.11`，确认 `import tensorrt` 成功，并使用 `OMNIRT_FASTLIVEPORTRAIT_CFG=configs/trt_infer.yaml`。 |
| 浏览器能看到模型但创建会话失败 | 选择 `model_type` 匹配 `fasterliveportrait` 的 avatar，或准备对应 avatar bundle。 |


FasterLivePortrait 当前也走 OmniRT `audio2video` 兼容路径。OpenTalking 负责会话、TTS/音频流、WebRTC 播放和前端参数下发；OmniRT 常驻加载 FasterLivePortrait 与 JoyVASA，统一暴露 `/v1/audio2video/fasterliveportrait`。

该路径适合单卡实时数字人：默认使用 25fps、1 秒音频 chunk、448 宽实时档，并把动头贴回原始资产图。上传整身图时仍以 FasterLivePortrait 检测到的人脸区域驱动，身体本身不会生成新动作。

同一个 runtime 也可以服务“视频克隆”工作流：OpenTalking 固定形象库中的数字人图片作为 source，把浏览器摄像头或上传视频逐帧作为 driving input，转发到 OmniRT `/v1/avatar/video-clone/fasterliveportrait`。这条链路不经过 LLM、STT、TTS，也不会复用实时对话的 `speak` 队列。

## 1. 准备代码和权重

需要先准备几个目录变量。`FASTERLIVEPORTRAIT_HOME` 是 FasterLivePortrait 源码 checkout；`OMNIRT_MODEL_ROOT` 是模型权重根目录。权重不要放进 OpenTalking 或 OmniRT 仓库。

```bash title="终端"
export DIGITAL_HUMAN_HOME="${DIGITAL_HUMAN_HOME:-/path/to/digital_human}"
export OPENTALKING_HOME="${OPENTALKING_HOME:-$DIGITAL_HUMAN_HOME/opentalking}"
export OMNIRT_HOME="${OMNIRT_HOME:-$DIGITAL_HUMAN_HOME/omnirt}"
export FASTERLIVEPORTRAIT_HOME="${FASTERLIVEPORTRAIT_HOME:-$DIGITAL_HUMAN_HOME/FasterLivePortrait}"
export OMNIRT_MODEL_ROOT="${OMNIRT_MODEL_ROOT:-/path/to/model}"
export FASTERLIVEPORTRAIT_REF="${FASTERLIVEPORTRAIT_REF:-5dcf03aa2e6b2eb2a55b971efdc28fc0afdb1494}"
```

当前 OpenTalking 视频克隆和 OmniRT runtime 依赖 FasterLivePortrait 的细粒度动作控制、TRT 输出顺序修正和 PyTorch 新版本 checkpoint 加载修正。部署时先固定使用 `zyairehhh/FasterLivePortrait` fork；等这些 patch 进入官方稳定包后，再切换到上游包。

```bash title="终端"
if [ ! -d "$FASTERLIVEPORTRAIT_HOME/.git" ]; then
  git clone https://github.com/zyairehhh/FasterLivePortrait.git "$FASTERLIVEPORTRAIT_HOME"
fi

git -C "$FASTERLIVEPORTRAIT_HOME" fetch origin master
git -C "$FASTERLIVEPORTRAIT_HOME" checkout "$FASTERLIVEPORTRAIT_REF"

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

服务器上建议把 `uv` 缓存放到数据盘，并通过 PyPI 镜像加速依赖安装。`PIP_INDEX_URL` 是给少数仍读取 pip 配置的构建步骤兜底。

```bash title="终端"
cd "$OMNIRT_HOME"
export UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export PIP_INDEX_URL="${PIP_INDEX_URL:-$UV_DEFAULT_INDEX}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$DIGITAL_HUMAN_HOME/.uv-cache}"
uv sync --extra server --extra fasterliveportrait --python 3.11
```

FasterLivePortrait 实时路径默认使用 TensorRT。`fasterliveportrait` extra 会安装 `onnxruntime-gpu`、`tensorrt-cu12`、`tensorrt-cu12-bindings` 和 `tensorrt-cu12-libs`。TensorRT libs wheel 约 4GB，必须确保 `UV_CACHE_DIR` 指向空间充足的数据盘；不要让它落到空间很小的 `/root/.cache/uv`。

部署前可确认 `uv run python -c "import tensorrt as trt; print(trt.__version__)"` 能正常输出版本号。

## 3. 启动 OmniRT FasterLivePortrait runtime

```bash title="终端"
cd "$OMNIRT_HOME"
mkdir -p "$DIGITAL_HUMAN_HOME/logs"
nohup env \
  OMNIRT_FASTLIVEPORTRAIT_RUNTIME=1 \
  OMNIRT_FASTLIVEPORTRAIT_LOAD_MODELS=1 \
  OMNIRT_FASTLIVEPORTRAIT_ROOT="$FASTERLIVEPORTRAIT_HOME" \
  OMNIRT_FASTLIVEPORTRAIT_CHECKPOINTS_DIR="$OMNIRT_MODEL_ROOT/FasterLivePortrait/checkpoints" \
  OMNIRT_FASTLIVEPORTRAIT_CFG=configs/trt_infer.yaml \
  OMNIRT_FASTLIVEPORTRAIT_DEVICE=cuda:0 \
  OMNIRT_FASTLIVEPORTRAIT_JPEG_QUALITY=85 \
  uv run omnirt serve-avatar-ws --host 0.0.0.0 --port 9000 --backend cuda \
  > "$DIGITAL_HUMAN_HOME/logs/omnirt-fasterliveportrait-9000.log" 2>&1 &
echo $! > "$DIGITAL_HUMAN_HOME/logs/omnirt-fasterliveportrait-9000.pid"
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

先同步 OpenTalking 环境。这里继续使用与 OmniRT 相同的 uv 镜像和缓存目录。

```bash title="终端"
cd "$OPENTALKING_HOME"
export UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export PIP_INDEX_URL="${PIP_INDEX_URL:-$UV_DEFAULT_INDEX}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$DIGITAL_HUMAN_HOME/.uv-cache}"
uv sync --extra dev --python 3.11
```

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
mkdir -p "$DIGITAL_HUMAN_HOME/logs"
nohup env \
  OMNIRT_ENDPOINT=http://127.0.0.1:9000 \
  OPENTALKING_OMNIRT_ENDPOINT=http://127.0.0.1:9000 \
  uv run opentalking-unified --host 0.0.0.0 --port 8000 \
  > "$DIGITAL_HUMAN_HOME/logs/opentalking-8000.log" 2>&1 &
echo $! > "$DIGITAL_HUMAN_HOME/logs/opentalking-8000.pid"
```

前端：

```bash title="终端"
cd "$OPENTALKING_HOME/apps/web"
npm ci --registry=https://registry.npmmirror.com
mkdir -p "$DIGITAL_HUMAN_HOME/logs"
nohup env VITE_BACKEND_PORT=8000 \
  npm run dev -- --host 0.0.0.0 --port 5282 \
  > "$DIGITAL_HUMAN_HOME/logs/opentalking-web-5282.log" 2>&1 &
echo $! > "$DIGITAL_HUMAN_HOME/logs/opentalking-web-5282.pid"
```

验证 OpenTalking 能看到模型：

```bash title="终端"
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="fasterliveportrait")'
```

期望：

```json
{"id":"fasterliveportrait","backend":"omnirt","connected":true,"reason":"omnirt"}
```

同时验证视频克隆入口：

```bash title="终端"
curl -s http://127.0.0.1:8000/video-clone/status | jq
```

期望：

```json
{"model":"fasterliveportrait","connected":true,"reason":"omnirt"}
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

## 6. 视频克隆模式

视频克隆在 WebUI 顶部与“实时对话”并列。进入“视频克隆”后：

- Source：左侧选择已有数字人，或上传新的 source 图片。source 是被驱动的数字人资产。
- Driving：右侧选择摄像头，或上传 driving video。driving 只提供表情、头动和嘴部运动。
- Output：中间显示实时输出，状态条展示发送帧、接收帧、丢帧和延迟。

前端会连接 OpenTalking：

```text
ws://<opentalking-host>/video-clone/fasterliveportrait/ws
```

OpenTalking 再把 source 图片和 driving 帧流转发到 OmniRT：

```text
ws://<omnirt-host>/v1/avatar/video-clone/fasterliveportrait
```

常用调试建议：

- 想保持原图构图时，打开“拼回原图”。
- 上传 driving video 嘴张不开时，先调高“张嘴开合”；如果嘴部变成单纯上下开合，降低“唇形重定向”。
- 感觉嘴鼓或位置不对时，先关闭“裁剪 driving 人脸”，确认 driving 输入没有被过度裁剪。
- 摄像头权限失败时，确认页面通过 `localhost` / `127.0.0.1` 或 HTTPS 打开；也可以先上传 driving video 验证后端服务。

停止或切页后，前端会释放摄像头 track、WebSocket 和当前 video-clone session。

## 7. 性能验收

```bash title="终端"
cd "$OMNIRT_HOME"
uv run python scripts/bench_fasterliveportrait_ws.py \
  --url ws://127.0.0.1:9000/v1/audio2video/fasterliveportrait \
  --duration 30 \
  --chunk-samples 16000
```

单卡实时优先看：首包耗时、每 chunk 生成耗时、输出 fps、浏览器队列是否持续积压。若 `448` 宽不能稳定超过 25fps，再降低到 `416`；如果质量优先可把 `width` 调到 `480` 或 `540`，但不建议作为实时默认。
