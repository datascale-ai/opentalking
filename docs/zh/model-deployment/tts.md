# 语音合成

TTS 将 LLM 输出转为音频，并驱动 talking-head backend。首次评估建议使用 Edge TTS；需要生产音色、复刻或更高质量时，再切换 provider。

## Provider 选项

| Provider | 适用场景 | 必要配置 |
|----------|----------|----------|
| `edge` | 首次运行、CPU 评估、无需 API key | `OPENTALKING_TTS_DEFAULT_PROVIDER=edge` |
| `dashscope` | 中文实时 TTS 与声音复刻 | `OPENTALKING_TTS_DASHSCOPE_API_KEY` 及 DashScope TTS 配置 |
| `local_cosyvoice` | 本地中文 TTS、内置音色和复刻音色 | CosyVoice3 权重和本地 service URL |
| `indextts` | IndexTTS2 可控配音、情绪控制和复刻音色 | `OPENTALKING_TTS_INDEXTTS_BACKEND=local` 或 `omnirt` |
| `cosyvoice` | 自托管 CosyVoice 服务 | CosyVoice WebSocket URL/settings |
| `elevenlabs` | 托管多语言音色 | ElevenLabs API key 和 voice id |

`indextts` 是 OpenTalking 对外暴露的唯一 provider 名称。部署时可以让它走同机 HTTP sidecar 的 `local` backend，也可以走 OmniRT 常驻 backend。这和视频驱动模型的 backend 选择类似：OpenTalking 侧始终选择 `IndexTTS`，部署者只在环境变量中切换运行 backend。

## Edge TTS 默认配置

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=edge
OPENTALKING_TTS_EDGE_VOICE=zh-CN-XiaoxiaoNeural
```

Edge TTS 仍需要 `ffmpeg`，因为 OpenTalking 会将 provider 音频解码为 PCM 再送入合成 backend。

## DashScope Qwen realtime TTS

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=dashscope
OPENTALKING_TTS_DASHSCOPE_API_KEY=<dashscope-api-key>
OPENTALKING_TTS_DASHSCOPE_MODEL=qwen3-tts-flash-realtime
OPENTALKING_QWEN_TTS_REUSE_WS=1
```

DashScope TTS 不读取 `OPENTALKING_LLM_API_KEY` 或 `DASHSCOPE_API_KEY`；即使和 LLM 使用同一把实际 key，也要显式写入 `OPENTALKING_TTS_DASHSCOPE_API_KEY`。

## 本地 CosyVoice3 0.5B

推荐把 CosyVoice 作为独立本地服务启动，再由 OpenTalking 的 `local_cosyvoice` provider 通过 HTTP 读取 PCM 音频流。

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=local_cosyvoice
OPENTALKING_TTS_ENABLED_PROVIDERS=local_cosyvoice,dashscope,edge
OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL=FunAudioLLM/Fun-CosyVoice3-0.5B-2512
OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL_DIR=./models/local-audio/FunAudioLLM__Fun-CosyVoice3-0.5B-2512
OPENTALKING_TTS_LOCAL_COSYVOICE_RUNTIME_DIR=./models/local-audio/runtime/CosyVoice
OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL=http://127.0.0.1:19090/synthesize
OPENTALKING_TTS_LOCAL_COSYVOICE_DEVICE=cuda:0
OPENTALKING_TTS_LOCAL_COSYVOICE_FP16=auto
OPENTALKING_TTS_LOCAL_COSYVOICE_LOAD_TRT=0
OPENTALKING_TTS_LOCAL_COSYVOICE_MAX_TOKEN_TEXT_RATIO=6
OPENTALKING_TTS_LOCAL_COSYVOICE_MASK_STOP_TOKENS=1
```

下载本地音频权重：

```bash title="终端"
export UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export UV_INDEX_URL="${UV_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export UV_LINK_MODE=copy
uv sync --extra dev --extra models --extra local-audio --python 3.11
.venv/bin/python scripts/download_local_audio_models.py \
  --root ./models/local-audio \
  --model fun-cosyvoice3-0.5b-2512
```

这一步会从 ModelScope 下载 CosyVoice3 主模型：

| 资产 | 来源 | 目标目录 |
|---|---|---|
| CosyVoice3 主权重 | ModelScope `FunAudioLLM/Fun-CosyVoice3-0.5B-2512` | `./models/local-audio/FunAudioLLM__Fun-CosyVoice3-0.5B-2512/` |

主模型目录至少需要包含 sidecar runtime 会加载的文件，包括 `cosyvoice3.yaml`、
`llm.pt`、`flow.pt`、`hift.pt`、`speech_tokenizer_v3.onnx`、
`speech_tokenizer_v3.batch.onnx`、`campplus.onnx` 和
`flow.decoder.estimator.fp32.onnx`。内置 zero-shot 音色还需要
`OPENTALKING_TTS_LOCAL_COSYVOICE_PROMPT_AUDIO` 指向一段 prompt wav；复刻音色会把
自己的 prompt wav 保存在本地音色目录。

如果要启用 fp16 TensorRT，再从 Hugging Face 下载额外 ONNX 资产，并放到同一个主模型目录：

| 资产 | 来源 | 用途 |
|---|---|---|
| `flow.decoder.estimator.autocast_fp16.onnx` | Hugging Face `yuekai/Fun-CosyVoice3-0.5B-2512-FP16-ONNX` | `FP16 + LOAD_TRT=1` 必需；OpenTalking 会由它生成 `flow.decoder.estimator.autocast_fp16.mygpu.plan`。 |
| `flow.decoder.estimator.streaming.autocast_fp16.onnx` | Hugging Face `yuekai/Fun-CosyVoice3-0.5B-2512-FP16-ONNX` | 可选 streaming fp16 ONNX 资产；建议和 estimator ONNX 放在一起，保持 runtime 兼容。 |

生成的 `*.mygpu.plan` 是和机器绑定的 TensorRT engine，不要跨 GPU / TensorRT /
CUDA 环境复制；在目标机器上由 ONNX 重新构建。

这个主 `.venv` 负责 OpenTalking、SenseVoice 和视频后端。CosyVoice 需要独立
sidecar venv，避免它的 `transformers==4.51.3` runtime 与 OpenTalking 的
`transformers>=4.57,<6` 冲突。

准备 CosyVoice runtime：

```bash title="终端"
mkdir -p ./models/local-audio/runtime
git clone https://github.com/FunAudioLLM/CosyVoice.git ./models/local-audio/runtime/CosyVoice
cd ./models/local-audio/runtime/CosyVoice
git submodule update --init --recursive
```

创建或更新 CosyVoice 专用 sidecar venv：

```bash title="终端"
OPENTALKING_COSYVOICE_VENV_DIR=.venv-cosyvoice \
  bash scripts/prepare_cosyvoice_venv.sh
```

如果要启用 TensorRT，把 TRT 依赖安装在 CosyVoice sidecar venv 中，不要安装进 OpenTalking 主 `.venv`：

```bash title="终端"
PIP_EXTRA_INDEX_URL=https://pypi.nvidia.com/ OPENTALKING_COSYVOICE_INSTALL_TENSORRT=1 \
  OPENTALKING_COSYVOICE_VENV_DIR=.venv-cosyvoice bash scripts/prepare_cosyvoice_venv.sh
```

启动本地 TTS service：

```bash title="终端"
bash scripts/quickstart/start_local_cosyvoice.sh --port 19090
```

在既有 GPU 验证中，CosyVoice3 的关键问题不是单次 TTFA，而是随机种子导致的生成长度漂移。OpenTalking 的本地 CosyVoice service 因此默认保留两类稳定性保护：`OPENTALKING_TTS_LOCAL_COSYVOICE_MASK_STOP_TOKENS=1` 会屏蔽 CosyVoice LLM 暴露的全部 stop token，`OPENTALKING_TTS_LOCAL_COSYVOICE_MAX_TOKEN_TEXT_RATIO=6` 会限制 token/text 比例，避免长文本偶发生成过长音频。不要为了追求更快首包把这两个保护关掉。

TensorRT 是可选加速。只有当当前 CosyVoice runtime、CUDA、onnxruntime-gpu/TensorRT engine 与模型目录匹配时再开启：

```bash title="终端"
.venv-cosyvoice/bin/python -c "import tensorrt as trt; print(trt.__version__)"
test -f ./models/local-audio/FunAudioLLM__Fun-CosyVoice3-0.5B-2512/flow.decoder.estimator.fp32.onnx
```

CosyVoice3 的 fp16 TRT 推荐使用官方 autocast fp16 ONNX 资产。普通 `flow.decoder.estimator.fp32.onnx` 可以生成 TRT engine，但在部分 GPU/TensorRT 组合上会出现 NaN 或静音；如果要开启 `FP16 + LOAD_TRT`，先把 `flow.decoder.estimator.autocast_fp16.onnx` 放到同一个模型目录。服务器需要代理访问 Hugging Face 时，只给下载命令临时注入代理变量即可，不要写入 OpenTalking 主服务环境：

```bash title="终端"
env ALL_PROXY=socks5h://127.0.0.1:7890 HTTPS_PROXY=socks5h://127.0.0.1:7890 \
  HF_ENDPOINT=https://huggingface.co .venv-cosyvoice/bin/python - <<'PY'
from huggingface_hub import hf_hub_download
repo = "yuekai/Fun-CosyVoice3-0.5B-2512-FP16-ONNX"
target = "./models/local-audio/FunAudioLLM__Fun-CosyVoice3-0.5B-2512"
for name in ["flow.decoder.estimator.autocast_fp16.onnx", "flow.decoder.estimator.streaming.autocast_fp16.onnx"]:
    hf_hub_download(repo_id=repo, filename=name, repo_type="model", local_dir=target)
PY
```

```env title="scripts/quickstart/env"
OPENTALKING_TTS_LOCAL_COSYVOICE_FP16=auto
OPENTALKING_TTS_LOCAL_COSYVOICE_LOAD_TRT=1
OPENTALKING_TTS_LOCAL_COSYVOICE_TRT_CONCURRENT=1
OPENTALKING_TTS_LOCAL_COSYVOICE_TOKEN_HOP_LEN=8
OPENTALKING_TTS_LOCAL_COSYVOICE_TOKEN_MAX_HOP_LEN=16
OPENTALKING_TTS_LOCAL_COSYVOICE_STREAM_SCALE_FACTOR=1
```

`start_local_cosyvoice.sh` 会自动把 sidecar venv 里的 `site-packages/tensorrt_libs` 加入 `LD_LIBRARY_PATH`。首次启动 `FP16 + LOAD_TRT=1` 时，如果模型目录里存在 `flow.decoder.estimator.autocast_fp16.onnx`，OpenTalking 会从它生成当前 GPU 对应的 `flow.decoder.estimator.autocast_fp16.mygpu.plan`；这个步骤可能比普通启动更久。SenseVoice 仍然运行在 OpenTalking 主 `.venv`，不需要也不应该跟随 CosyVoice TRT 配置。

启动后先检查 sidecar 健康信息，确认 `runtime_flags.load_trt`、`runtime.trt_autocast_fp16`、`streaming`、`llm_token_ratio` 和 `llm_stop_token_patch` 符合预期：

```bash title="终端"
curl -fsS http://127.0.0.1:19090/health | python3 -m json.tool
```

在 NVIDIA RTX 3090 Linux 服务器上实测，CosyVoice3 使用独立 sidecar venv，已加载
`FP16 + LOAD_TRT=1` 和 autocast fp16 TensorRT plan。测试直接请求 sidecar 的
`/synthesize`，TTFB 按第一批 PCM 字节到达时间计算：

| 文本长度 | TTFB | 总耗时 | 音频时长 | RTF |
|---:|---:|---:|---:|---:|
| 43 字 | 0.683 s | 6.215 s | 7.200 s | 0.863 |
| 42 字 | 0.642 s | 5.858 s | 6.960 s | 0.842 |
| 29 字 | 0.639 s | 5.771 s | 6.520 s | 0.885 |
| **平均** | **0.655 s** | **5.948 s** | **6.893 s** | **0.863** |

完整本地语音输入、语音合成和 QuickTalk 视频链路见 [本地 STT/TTS + QuickTalk](recipes/local-quicktalk-audio.md)。

## IndexTTS 部署（provider = indextts）

IndexTTS 在 OpenTalking 侧始终使用 `provider=indextts`。`OPENTALKING_TTS_INDEXTTS_BACKEND` 只决定运行拓扑：`local` 表示同机 HTTP sidecar，`omnirt` 表示 OmniRT 常驻服务。前端、API payload 和复刻音色元数据都不需要拆成两个 provider。

### 方式 A：同机 HTTP sidecar（backend = local）

local backend 采用独立的同机 HTTP sidecar：IndexTTS2 在单独 venv 里加载，OpenTalking API 进程只通过 `OPENTALKING_TTS_LOCAL_INDEXTTS_SERVICE_URL` 消费 `audio/L16` PCM。不要把 `index-tts` 直接安装到 OpenTalking 主 `.venv`；IndexTTS 官方依赖会固定 `torch`、`transformers`、`protobuf` 等版本，容易破坏 QuickTalk / STT 依赖。

先安装 OpenTalking 主环境和本地音频下载依赖。这个环境不要安装 `index-tts`：

```bash title="终端"
cd "$OPENTALKING_HOME"
export UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export UV_INDEX_URL="${UV_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export UV_LINK_MODE=copy
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

uv sync --extra dev --extra models --extra local-audio --python 3.11
.venv/bin/python scripts/download_local_audio_models.py \
  --root ./models/local-audio \
  --model indextts2 \
  --model indextts2-w2v-bert \
  --model indextts2-maskgct \
  --model indextts2-campplus \
  --model indextts2-bigvgan
```
Hugging Face/Xet 大文件下载偶尔会出现 `Read timed out`、`SSL record layer failure` 等日志；脚本会尝试断点续传。只要命令最终退出码为 0 即可继续。如果命令失败，保持已下载目录不变，重新执行同一条命令即可复用缓存并继续下载。


如果机器上已经有同样结构的权重目录，也可以不重复下载，只把 `OPENTALKING_LOCAL_AUDIO_MODEL_ROOT` 指向已有目录。该目录至少需要包含 `IndexTeam__IndexTTS-2/config.yaml`、`facebook__w2v-bert-2.0`、`funasr__campplus`、`nvidia__bigvgan_v2_22khz_80band_256x`。MaskGCT 目录优先使用 `amphion__MaskGCT`；如果已有资产目录叫 `amphion__MaskGCT-ms`，只要其中存在 `semantic_codec/model.safetensors`，sidecar 也会自动兼容。

再创建 IndexTTS sidecar 运行时。官方仓包含 LFS 示例音频，部分环境会遇到 LFS quota，因此建议跳过 smudge；实际 prompt 音频使用你自己的 3-15 秒清晰人声。

```bash title="终端"
cd "$OPENTALKING_HOME"
mkdir -p ./models/local-audio/runtime
INDEXTTS_RUNTIME_REPO="${INDEXTTS_RUNTIME_REPO:-https://github.com/index-tts/index-tts.git}"
if [ ! -d ./models/local-audio/runtime/index-tts/.git ]; then
  for i in 1 2 3; do
    GIT_LFS_SKIP_SMUDGE=1 git clone "$INDEXTTS_RUNTIME_REPO" ./models/local-audio/runtime/index-tts && break
    rm -rf ./models/local-audio/runtime/index-tts
    sleep 3
  done
fi
test -d ./models/local-audio/runtime/index-tts/.git
cd ./models/local-audio/runtime/index-tts
export UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export UV_INDEX_URL="${UV_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export UV_LINK_MODE=copy
uv sync --python 3.11
uv pip install fastapi "uvicorn[standard]" soundfile
```

IndexTTS 需要一段 3-15 秒清晰人声作为 prompt。可以先准备系统默认音色，也可以在 WebUI 的“音色复刻”里上传参考音频。

```bash title="终端"
cd "$OPENTALKING_HOME"
mkdir -p ./models/local-audio/voices/system/indextts-default
cp /path/to/reference.wav ./models/local-audio/voices/system/indextts-default/prompt.wav
cat > ./models/local-audio/voices/system/indextts-default/meta.json <<'JSON'
{"voice_id":"indextts-default","display_label":"IndexTTS 默认音色","provider":"indextts","target_model":"IndexTeam/IndexTTS-2","source":"system"}
JSON
```

启动 sidecar 服务：

```bash title="终端"
cd "$OPENTALKING_HOME"
OPENTALKING_LOCAL_AUDIO_MODEL_ROOT=./models/local-audio \
OPENTALKING_TTS_LOCAL_INDEXTTS_MODEL_DIR=./models/local-audio/IndexTeam__IndexTTS-2 \
OPENTALKING_TTS_LOCAL_INDEXTTS_CFG_PATH=./models/local-audio/IndexTeam__IndexTTS-2/config.yaml \
OPENTALKING_TTS_LOCAL_INDEXTTS_PROMPT_AUDIO=./models/local-audio/voices/system/indextts-default/prompt.wav \
OPENTALKING_TTS_LOCAL_INDEXTTS_W2V_BERT_DIR=./models/local-audio/facebook__w2v-bert-2.0 \
OPENTALKING_TTS_LOCAL_INDEXTTS_MASKGCT_DIR=./models/local-audio/amphion__MaskGCT \
OPENTALKING_TTS_LOCAL_INDEXTTS_CAMPPLUS_DIR=./models/local-audio/funasr__campplus \
OPENTALKING_TTS_LOCAL_INDEXTTS_BIGVGAN_DIR=./models/local-audio/nvidia__bigvgan_v2_22khz_80band_256x \
OPENTALKING_TTS_LOCAL_INDEXTTS_DEVICE=cuda:0 \
./models/local-audio/runtime/index-tts/.venv/bin/python scripts/local_indextts_service.py --host 127.0.0.1 --port 19092
```

OpenTalking `.env` 中选择 `indextts`，并把 backend 设置为 `local`：

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=indextts
OPENTALKING_TTS_ENABLED_PROVIDERS=edge,dashscope,local_cosyvoice,indextts
OPENTALKING_TTS_INDEXTTS_BACKEND=local
OPENTALKING_LOCAL_AUDIO_MODEL_ROOT=./models/local-audio
OPENTALKING_TTS_LOCAL_INDEXTTS_MODEL=IndexTeam/IndexTTS-2
OPENTALKING_TTS_LOCAL_INDEXTTS_MODEL_DIR=./models/local-audio/IndexTeam__IndexTTS-2
OPENTALKING_TTS_LOCAL_INDEXTTS_CFG_PATH=./models/local-audio/IndexTeam__IndexTTS-2/config.yaml
OPENTALKING_TTS_LOCAL_INDEXTTS_SERVICE_URL=http://127.0.0.1:19092/synthesize
OPENTALKING_TTS_LOCAL_INDEXTTS_PROMPT_AUDIO=./models/local-audio/voices/system/indextts-default/prompt.wav
OPENTALKING_TTS_LOCAL_INDEXTTS_W2V_BERT_DIR=./models/local-audio/facebook__w2v-bert-2.0
OPENTALKING_TTS_LOCAL_INDEXTTS_MASKGCT_DIR=./models/local-audio/amphion__MaskGCT
OPENTALKING_TTS_LOCAL_INDEXTTS_CAMPPLUS_DIR=./models/local-audio/funasr__campplus
OPENTALKING_TTS_LOCAL_INDEXTTS_BIGVGAN_DIR=./models/local-audio/nvidia__bigvgan_v2_22khz_80band_256x
OPENTALKING_TTS_LOCAL_INDEXTTS_DEVICE=auto
```

这些 `LOCAL_INDEXTTS_*_DIR` 变量既可以写在 OpenTalking `.env` 中，也可以在启动 sidecar 时作为环境变量传入。OpenTalking 主进程需要 `SERVICE_URL` 和音色 prompt 路径；sidecar 需要模型目录、prompt、w2v / MaskGCT / campplus / BigVGAN 等本地资产目录，避免运行时再次访问 Hugging Face。

启动 OpenTalking API 和 WebUI。这里用 QuickTalk local 作为示例 video backend；如果你只想验证 TTS preview，也可以先用 `--mock` 启动。

```bash title="终端"
cd "$OPENTALKING_HOME"
bash scripts/start_unified.sh --backend local --model quicktalk --api-port 8000 --web-port 5173
```

如果 `8000` 或 `5173` 已被其他服务占用，可以把 `--api-port` / `--web-port` 换成空闲端口；下面的 `curl` 地址也要同步替换对应 API 端口。

先验证 sidecar，再验证 OpenTalking API：

```bash title="终端"
curl -fsS http://127.0.0.1:19092/health
curl -fsS -X POST http://127.0.0.1:19092/synthesize \
  -H 'content-type: application/json' \
  -d '{"text":"你好，这是一次 IndexTTS 本地服务测试。","sample_rate":16000}' \
  --output /tmp/indextts-local.pcm

.venv/bin/python - <<'PY'
from pathlib import Path
pcm = Path("/tmp/indextts-local.pcm").read_bytes()
assert len(pcm) > 0 and len(pcm) % 2 == 0, len(pcm)
print("pcm_bytes", len(pcm), "sample_rate", 16000, "channels", 1)
PY

curl -fsS -X POST http://127.0.0.1:8000/tts/preview \
  --max-time 300 \
  -H 'content-type: application/json' \
  -d '{"text":"你好，这是一次 OpenTalking IndexTTS 测试。","tts_provider":"indextts","tts_voice":"indextts-default","tts_model":"IndexTeam/IndexTTS-2"}' \
  --output /tmp/opentalking-indextts-preview.wav

.venv/bin/python - <<'PY'
import wave
with wave.open("/tmp/opentalking-indextts-preview.wav", "rb") as wf:
    print("wav", wf.getframerate(), wf.getnchannels(), wf.getsampwidth(), wf.getnframes())
PY
```

也可以检查运行状态，确认 OpenTalking 对外仍是 `indextts`，同时 backend 解析为 `local`：

```bash title="终端"
curl -fsS http://127.0.0.1:8000/runtime/status | python3 -m json.tool
```

期望 `tts_provider` 为 `indextts`，`tts_providers.indextts.backend` 为 `local`，`tts_providers.indextts.resolved_provider` 为 `local_indextts`，并且 `service_url_set=true`。


### 方式 B：OmniRT 常驻服务（backend = omnirt）

OmniRT backend 适合把 IndexTTS 常驻在独立服务里，OpenTalking 只通过 HTTP stream 消费 `audio/L16` PCM。OpenTalking 侧 provider 仍然是 `indextts`，只把 backend 切到 `omnirt`。

先在 OmniRT 仓启动 text2audio 服务：

```bash title="终端"
cd "$OMNIRT_HOME"
OMNIRT_INDEXTTS_RUNTIME=1 \
OMNIRT_INDEXTTS_MODEL_DIR=/data2/zhongyi/model/local-audio/IndexTeam__IndexTTS-2 \
OMNIRT_INDEXTTS_CFG_PATH=/data2/zhongyi/model/local-audio/IndexTeam__IndexTTS-2/config.yaml \
OMNIRT_INDEXTTS_PROMPT_AUDIO=/data2/zhongyi/model/local-audio/voices/system/indextts-default/prompt.wav \
OMNIRT_INDEXTTS_DEVICE=cuda:0 \
uv run omnirt serve-text2audio --host 127.0.0.1 --port 9012
```

再在 OpenTalking `.env` 中选择 provider 和 backend：

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=indextts
OPENTALKING_TTS_ENABLED_PROVIDERS=edge,dashscope,local_cosyvoice,indextts
OPENTALKING_TTS_INDEXTTS_BACKEND=omnirt
OPENTALKING_TTS_OMNIRT_INDEXTTS_SERVICE_URL=http://127.0.0.1:9012/v1/text2audio/indextts
OPENTALKING_TTS_OMNIRT_INDEXTTS_MODEL=IndexTeam/IndexTTS-2
OPENTALKING_TTS_OMNIRT_INDEXTTS_STREAMING=1
OPENTALKING_TTS_OMNIRT_INDEXTTS_STREAMING_MODE=token_window
OPENTALKING_TTS_OMNIRT_INDEXTTS_MAX_TEXT_TOKENS_PER_SEGMENT=80
OPENTALKING_TTS_OMNIRT_INDEXTTS_QUICK_STREAMING_TOKENS=4
OPENTALKING_TTS_OMNIRT_INDEXTTS_INTERVAL_SILENCE_MS=0
OPENTALKING_TTS_OMNIRT_INDEXTTS_TOKEN_WINDOW_SIZE=40
OPENTALKING_TTS_OMNIRT_INDEXTTS_TOKEN_WINDOW_HOP=96
OPENTALKING_TTS_OMNIRT_INDEXTTS_TOKEN_WINDOW_CONTEXT=8
OPENTALKING_TTS_OMNIRT_INDEXTTS_TOKEN_WINDOW_OVERLAP_MS=60
```

`token_window` 是模型 token 级的分窗流式：OmniRT 会在语音 token 累积到窗口后先解码并返回 PCM，不必等待整段文本完成；它不是 20ms 波形级真流式，短句首包延迟仍取决于 IndexTTS GPT 首批语音 token 和 vocoder 解码耗时。

## ElevenLabs

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=elevenlabs
OPENTALKING_TTS_ELEVENLABS_API_KEY=<elevenlabs-api-key>
OPENTALKING_TTS_ELEVENLABS_VOICE_ID=<voice-id>
OPENTALKING_TTS_ELEVENLABS_MODEL_ID=eleven_flash_v2_5
```

## 验证

先创建 `mock` 会话，再调用 `/speak`。这样可以验证 TTS，不依赖真实 talking-head 模型。

```bash title="终端"
SID=<session-id>
curl -s -X POST "http://127.0.0.1:8000/sessions/$SID/speak" \
  -H 'content-type: application/json' \
  -d '{"text":"你好，这是一次 OpenTalking 语音合成测试。","tts_provider":"indextts","tts_voice":"indextts-default","tts_model":"IndexTeam/IndexTTS-2"}'
```

## 前端入口

模型或后端服务启动后，统一用 OpenTalking WebUI 访问：

```bash title="终端"
cd "$OPENTALKING_HOME"
bash scripts/quickstart/start_frontend.sh --api-port 8000 --web-port 5173 --host 0.0.0.0
```

远程服务器部署时，把本地浏览器端口映射到服务器 `5173`，再打开 `http://127.0.0.1:5173`。
