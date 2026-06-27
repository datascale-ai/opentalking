# CosyVoice 部署

CosyVoice 可通过两种 provider 接入 OpenTalking：

- `local_cosyvoice`：OpenTalking 管理本地 CosyVoice sidecar，适合单机或私有化部署。
- `cosyvoice`：接入已有 CosyVoice WebSocket / HTTP 服务，适合复用团队已有 TTS 服务。

推荐将本地 CosyVoice 作为独立 sidecar 服务启动，OpenTalking 通过 HTTP 获取 PCM 音频流。

## 适用场景

- 需要本地中文 TTS、内置音色或复刻音色。
- 希望 TTS 推理与 OpenTalking 主进程隔离。
- 与 SenseVoice 和 QuickTalk local 组成完整本地语音链路。

## 权重准备

```bash title="终端"
cd "$OPENTALKING_HOME"
uv sync --extra dev --extra models --extra local-audio --python 3.11

python scripts/download_local_audio_models.py \
  --root ./avatar_models/local-audio \
  --model fun-cosyvoice3-0.5b-2512
```

如果需要启用 TensorRT / FP16，再从 Hugging Face 下载额外 ONNX 资产，并放到同一个
CosyVoice3 模型目录：

```bash title="终端"
env HF_ENDPOINT=https://huggingface.co \
  python - <<'PY'
from huggingface_hub import hf_hub_download
repo = "yuekai/Fun-CosyVoice3-0.5B-2512-FP16-ONNX"
target = "./avatar_models/local-audio/FunAudioLLM__Fun-CosyVoice3-0.5B-2512"
for name in [
    "flow.decoder.estimator.autocast_fp16.onnx",
    "flow.decoder.estimator.streaming.autocast_fp16.onnx",
]:
    hf_hub_download(repo_id=repo, filename=name, repo_type="model", local_dir=target)
PY
```

这些资产的用途如下：

| 资产 | 来源 | 用途 |
|------|------|------|
| `flow.decoder.estimator.autocast_fp16.onnx` | Hugging Face `yuekai/Fun-CosyVoice3-0.5B-2512-FP16-ONNX` | `FP16 + LOAD_TRT=1` 必需；首次启动时会生成当前 GPU 对应的 `flow.decoder.estimator.autocast_fp16.mygpu.plan`。 |
| `flow.decoder.estimator.streaming.autocast_fp16.onnx` | Hugging Face `yuekai/Fun-CosyVoice3-0.5B-2512-FP16-ONNX` | 可选 streaming fp16 ONNX 资产；建议和 estimator ONNX 放在一起，保持 runtime 兼容。 |

生成的 `*.mygpu.plan` 是机器相关的 TensorRT engine，不要在不同 GPU / CUDA /
TensorRT 环境之间复制；换机器后应从 ONNX 重新构建。

准备 CosyVoice runtime：

```bash title="终端"
mkdir -p ./avatar_models/local-audio/runtime
git clone https://github.com/FunAudioLLM/CosyVoice.git ./avatar_models/local-audio/runtime/CosyVoice
cd ./avatar_models/local-audio/runtime/CosyVoice
git submodule update --init --recursive
```

创建 sidecar venv：

```bash title="终端"
cd "$OPENTALKING_HOME"
OPENTALKING_COSYVOICE_VENV_DIR=.venv-cosyvoice \
  bash scripts/prepare_cosyvoice_venv.sh
```

如果要启用 TensorRT，把 TRT 依赖装进 CosyVoice sidecar venv，不要装进 OpenTalking
主 `.venv`：

```bash title="终端"
PIP_EXTRA_INDEX_URL=https://pypi.nvidia.com/ \
OPENTALKING_COSYVOICE_INSTALL_TENSORRT=1 \
OPENTALKING_COSYVOICE_VENV_DIR=.venv-cosyvoice \
  bash scripts/prepare_cosyvoice_venv.sh
```

## 配置项

本地 sidecar：

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=local_cosyvoice
OPENTALKING_TTS_ENABLED_PROVIDERS=local_cosyvoice,dashscope,edge
OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL=FunAudioLLM/Fun-CosyVoice3-0.5B-2512
OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL_DIR=./avatar_models/local-audio/FunAudioLLM__Fun-CosyVoice3-0.5B-2512
OPENTALKING_TTS_LOCAL_COSYVOICE_RUNTIME_DIR=./avatar_models/local-audio/runtime/CosyVoice
OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL=http://127.0.0.1:19090/synthesize
OPENTALKING_TTS_LOCAL_COSYVOICE_DEVICE=cuda:0
OPENTALKING_TTS_LOCAL_COSYVOICE_FP16=auto
OPENTALKING_TTS_LOCAL_COSYVOICE_LOAD_TRT=0
```

OpenTalking 主 `.venv` 只负责编排、SenseVoice 和视频后端。CosyVoice 需要独立 sidecar venv，避免它的 runtime 依赖与 OpenTalking 主环境冲突。

已有 CosyVoice 服务：

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=cosyvoice
OPENTALKING_TTS_ENABLED_PROVIDERS=cosyvoice,dashscope,edge
OPENTALKING_TTS_COSYVOICE_URL=http://127.0.0.1:19090/synthesize
```

## 启动命令

默认 FP16（CUDA 上自动启用，不加载 TRT）：

```bash title="终端"
cd "$OPENTALKING_HOME"
bash scripts/quickstart/start_local_cosyvoice.sh --port 19090
```

启用 FP16 + TensorRT：

```bash title="终端"
cd "$OPENTALKING_HOME"
export OPENTALKING_TTS_LOCAL_COSYVOICE_FP16=auto
export OPENTALKING_TTS_LOCAL_COSYVOICE_LOAD_TRT=1
bash scripts/quickstart/start_local_cosyvoice.sh --port 19090
```

首次以 `LOAD_TRT=1` 启动时，如果模型目录存在
`flow.decoder.estimator.autocast_fp16.onnx`，CosyVoice runtime 会生成当前 GPU 对应的
TensorRT plan，启动时间会比普通模式更久。`start_local_cosyvoice.sh` 会自动把 sidecar
venv 中的 `site-packages/tensorrt_libs` 加入 `LD_LIBRARY_PATH`。

另开终端启动 OpenTalking：

```bash title="终端"
bash scripts/start_unified.sh --backend mock --model mock --api-port 8000 --web-port 5173
```

## 验证命令

```bash title="终端"
curl -fsS http://127.0.0.1:19090/health
curl -fsS http://127.0.0.1:8000/health
```

检查 sidecar 是否按预期启用 FP16 / TRT：

```bash title="终端"
curl -fsS http://127.0.0.1:19090/health | python3 -m json.tool
```

健康信息中应看到 `fp16=true`；启用 TRT 时应看到 `load_trt=true`。

创建 `mock` 会话后调用 `/speak`，确认 OpenTalking 能拿到 CosyVoice 音频：

```bash title="终端"
SID=<session-id>
curl -s -X POST "http://127.0.0.1:8000/sessions/$SID/speak" \
  -H 'content-type: application/json' \
  -d '{"text":"你好，这是一次 CosyVoice 本地语音测试。"}'
```

## Benchmark 基线

测试直接请求 sidecar `/synthesize`，TTFB 按第一批 PCM 字节到达时间计算。
3090 基线使用 CosyVoice3 独立 sidecar venv，已加载 `FP16 + LOAD_TRT=1`
和 autocast fp16 TensorRT plan。4090 数据在同一套 OpenTalking sidecar 上测得，
streaming 参数为 `TOKEN_HOP_LEN=8`、`TOKEN_MAX_HOP_LEN=16`、`STREAM_SCALE_FACTOR=1`。

| 设备 | 模式 | 文本长度 | TTFB | 总耗时 | 音频时长 | RTF |
|---|---|---:|---:|---:|---:|---:|
| RTX 3090 | FP16 + TRT autocast | 43 字 | 0.683 s | 6.215 s | 7.200 s | 0.863 |
| RTX 3090 | FP16 + TRT autocast | 42 字 | 0.642 s | 5.858 s | 6.960 s | 0.842 |
| RTX 3090 | FP16 + TRT autocast | 29 字 | 0.639 s | 5.771 s | 6.520 s | 0.885 |
| RTX 3090 | **平均** | **-** | **0.655 s** | **5.948 s** | **6.893 s** | **0.863** |
| RTX 4090 | FP16 CUDA | 39 字 | 1.316 s | 11.662 s | 6.800 s | 1.715 |
| RTX 4090 | FP16 CUDA | 38 字 | 0.895 s | 11.199 s | 7.120 s | 1.573 |
| RTX 4090 | FP16 CUDA | 21 字 | 1.110 s | 9.493 s | 5.640 s | 1.683 |
| RTX 4090 | **FP16 CUDA 平均** | **-** | **1.107 s** | **10.785 s** | **6.520 s** | **1.657** |
| RTX 4090 | FP16 + TRT autocast | 39 字 | 0.772 s | 7.507 s | 6.800 s | 1.104 |
| RTX 4090 | FP16 + TRT autocast | 38 字 | 0.560 s | 5.613 s | 7.120 s | 0.788 |
| RTX 4090 | FP16 + TRT autocast | 21 字 | 0.507 s | 4.435 s | 5.640 s | 0.786 |
| RTX 4090 | **FP16 + TRT autocast 平均** | **-** | **0.613 s** | **5.852 s** | **6.520 s** | **0.893** |

该基线只覆盖 TTS sidecar，不包含 STT、LLM、QuickTalk、WebRTC 或浏览器播放耗时。

## 常见错误

| 现象 | 处理 |
|------|------|
| `transformers` 版本冲突 | CosyVoice 必须使用独立 sidecar venv，不要装进 OpenTalking 主 `.venv`。 |
| 首包延迟高 | 首包取决于模型推理和音色加载；生产环境建议预热。 |
| OpenTalking 调不到服务 | 检查 `OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL` 和 sidecar 端口。 |
