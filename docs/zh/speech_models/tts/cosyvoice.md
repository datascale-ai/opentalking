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
export DIGITAL_HUMAN_HOME="${DIGITAL_HUMAN_HOME:-$(cd "$OPENTALKING_HOME/.." && pwd)}"
export OPENTALKING_LOCAL_AUDIO_MODEL_ROOT="${OPENTALKING_LOCAL_AUDIO_MODEL_ROOT:-$DIGITAL_HUMAN_HOME/models/local-audio}"

python scripts/download_local_audio_models.py \
  --root "$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT" \
  --model fun-cosyvoice3-0.5b-2512
```

如果需要启用 TensorRT / FP16，再从 Hugging Face 下载额外 ONNX 资产，并放到同一个
CosyVoice3 模型目录：

```bash title="终端"
env HF_ENDPOINT=https://huggingface.co \
  python - <<'PY'
from huggingface_hub import hf_hub_download
import os
repo = "yuekai/Fun-CosyVoice3-0.5B-2512-FP16-ONNX"
target = os.path.join(
    os.environ["OPENTALKING_LOCAL_AUDIO_MODEL_ROOT"],
    "FunAudioLLM__Fun-CosyVoice3-0.5B-2512",
)
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
cd "$OPENTALKING_HOME"
export DIGITAL_HUMAN_HOME="${DIGITAL_HUMAN_HOME:-$(cd "$OPENTALKING_HOME/.." && pwd)}"
export OPENTALKING_TTS_LOCAL_COSYVOICE_RUNTIME_DIR="${OPENTALKING_TTS_LOCAL_COSYVOICE_RUNTIME_DIR:-$DIGITAL_HUMAN_HOME/model-repos/CosyVoice}"
mkdir -p "$(dirname "$OPENTALKING_TTS_LOCAL_COSYVOICE_RUNTIME_DIR")"
# 可选：GitHub 访问慢时，可临时启用代理前缀。
# export GITHUB_PROXY_PREFIX=https://gh-proxy.com/
if [ ! -d "$OPENTALKING_TTS_LOCAL_COSYVOICE_RUNTIME_DIR/.git" ]; then
  git clone "${GITHUB_PROXY_PREFIX:-}https://github.com/FunAudioLLM/CosyVoice.git" "$OPENTALKING_TTS_LOCAL_COSYVOICE_RUNTIME_DIR"
fi
cd "$OPENTALKING_TTS_LOCAL_COSYVOICE_RUNTIME_DIR"
# 可选：submodule 仍然走 GitHub 时，也可以只对当前 runtime repo 设置镜像。
# git config url."https://gh-proxy.com/https://github.com/".insteadOf "https://github.com/"
# git submodule sync --recursive
git submodule update --init --recursive
test -d third_party/Matcha-TTS/matcha
```

如果最后一行失败，说明 `Matcha-TTS` submodule 没拉完整。重新执行
`git submodule update --init --recursive`，直到 `third_party/Matcha-TTS/matcha`
目录存在。

创建 sidecar venv：

```bash title="终端"
cd "$OPENTALKING_HOME"
export DIGITAL_HUMAN_HOME="${DIGITAL_HUMAN_HOME:-$(cd "$OPENTALKING_HOME/.." && pwd)}"
export OPENTALKING_TTS_LOCAL_COSYVOICE_RUNTIME_DIR="${OPENTALKING_TTS_LOCAL_COSYVOICE_RUNTIME_DIR:-$DIGITAL_HUMAN_HOME/model-repos/CosyVoice}"
OPENTALKING_COSYVOICE_VENV_DIR=.venv-cosyvoice \
  bash scripts/prepare_cosyvoice_venv.sh
```

如果要启用 TensorRT，把 TRT 依赖装进 CosyVoice sidecar venv，不要装进 OpenTalking
主 `.venv`：

```bash title="终端"
cd "$OPENTALKING_HOME"
export DIGITAL_HUMAN_HOME="${DIGITAL_HUMAN_HOME:-$(cd "$OPENTALKING_HOME/.." && pwd)}"
export OPENTALKING_TTS_LOCAL_COSYVOICE_RUNTIME_DIR="$DIGITAL_HUMAN_HOME/model-repos/CosyVoice"

export OPENTALKING_COSYVOICE_PIP_RETRIES=20
export OPENTALKING_COSYVOICE_PIP_RESUME_RETRIES=20
export OPENTALKING_COSYVOICE_PIP_TIMEOUT=300
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export PIP_EXTRA_INDEX_URL=https://pypi.nvidia.com/

OPENTALKING_COSYVOICE_INSTALL_TENSORRT=1 \
OPENTALKING_COSYVOICE_VENV_DIR=.venv-cosyvoice \
  bash scripts/prepare_cosyvoice_venv.sh
```

如果网络中途出现 pip SSL 断流，直接重跑上面的命令即可。脚本会复用已有
`.venv-cosyvoice`，不需要删除 venv。

## 配置项

本地 sidecar：

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=local_cosyvoice
OPENTALKING_TTS_ENABLED_PROVIDERS=local_cosyvoice,dashscope,edge
OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL=FunAudioLLM/Fun-CosyVoice3-0.5B-2512
OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL_DIR=$DIGITAL_HUMAN_HOME/models/local-audio/FunAudioLLM__Fun-CosyVoice3-0.5B-2512
OPENTALKING_TTS_LOCAL_COSYVOICE_RUNTIME_DIR=$DIGITAL_HUMAN_HOME/model-repos/CosyVoice
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

确认 CosyVoice sidecar 已启动后，继续启动 OpenTalking + QuickTalk。可以在同一个
终端执行；如果换到新终端，需先恢复 `OPENTALKING_HOME` 和 `DIGITAL_HUMAN_HOME`
等部署环境变量。下面是推荐的真实链路启动方式；它会让 OpenTalking 使用本地
CosyVoice sidecar 作为 TTS，同时用本地 QuickTalk 作为数字人后端：

```bash title="终端"
cd "$OPENTALKING_HOME"

export OPENTALKING_TTS_DEFAULT_PROVIDER=local_cosyvoice
export OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL=http://127.0.0.1:19090/synthesize

export OPENTALKING_TORCH_DEVICE=cuda:0
export OPENTALKING_QUICKTALK_DEVICE=cuda:0
export OPENTALKING_QUICKTALK_ASSET_ROOT="$DIGITAL_HUMAN_HOME/models/quicktalk"
export OPENTALKING_QUICKTALK_WORKER_CACHE=1

bash scripts/start_unified.sh --backend local --model quicktalk --api-port 8210 --web-port 5283
```

## 验证命令

```bash title="终端"
curl -fsS http://127.0.0.1:19090/health
curl -fsS http://127.0.0.1:8210/health
```

检查 sidecar 是否按预期启用 FP16 / TRT：

```bash title="终端"
curl -fsS http://127.0.0.1:19090/health | python3 -m json.tool
```

健康信息中应看到 `fp16=true`；启用 TRT 时应看到 `load_trt=true`。

创建 `quicktalk` 会话后调用 `/speak`，确认 OpenTalking 能拿到 CosyVoice 音频并驱动
QuickTalk：

```bash title="终端"
SID=<session-id>
curl -s -X POST "http://127.0.0.1:8210/sessions/$SID/speak" \
  -H 'content-type: application/json' \
  -d '{"text":"你好，这是一次 CosyVoice 本地语音测试。"}'
```

## Benchmark 基线

测试环境为 NVIDIA RTX 3090 Linux 服务器、CosyVoice3 独立 sidecar venv，已加载
`FP16 + LOAD_TRT=1` 和 autocast fp16 TensorRT plan。测试直接请求 sidecar
`/synthesize`，TTFB 按第一批 PCM 字节到达时间计算。

| 文本长度 | TTFB | 总耗时 | 音频时长 | RTF |
|---:|---:|---:|---:|---:|
| 43 字 | 0.683 s | 6.215 s | 7.200 s | 0.863 |
| 42 字 | 0.642 s | 5.858 s | 6.960 s | 0.842 |
| 29 字 | 0.639 s | 5.771 s | 6.520 s | 0.885 |
| **平均** | **0.655 s** | **5.948 s** | **6.893 s** | **0.863** |

该基线只覆盖 TTS sidecar，不包含 STT、LLM、QuickTalk、WebRTC 或浏览器播放耗时。

## 常见错误

| 现象 | 处理 |
|------|------|
| `transformers` 版本冲突 | CosyVoice 必须使用独立 sidecar venv，不要装进 OpenTalking 主 `.venv`。 |
| 首包延迟高 | 首包取决于模型推理和音色加载；生产环境建议预热。 |
| OpenTalking 调不到服务 | 检查 `OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL` 和 sidecar 端口。 |
