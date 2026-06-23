# Text-to-Speech

TTS converts LLM output into audio that drives the talking-head backend. Start with Edge TTS for the lightest evaluation, then switch providers when you need production voices, cloning, or higher quality.

## Provider Options

| Provider | Best for | Required configuration |
|----------|----------|----------|
| `edge` | First run, CPU evaluation, no API key | `OPENTALKING_TTS_DEFAULT_PROVIDER=edge` |
| `dashscope` | Chinese realtime TTS and voice cloning | `OPENTALKING_TTS_DASHSCOPE_API_KEY` and DashScope TTS settings |
| `local_cosyvoice` | Local Chinese TTS, built-in voices, and cloned voices | CosyVoice3 weights and local service URL |
| `indextts` | IndexTTS2 controllable voice, emotion control, and cloned voices | `OPENTALKING_TTS_INDEXTTS_BACKEND=local` or `omnirt` |
| `cosyvoice` | Custom CosyVoice service | CosyVoice WebSocket URL/settings |
| `elevenlabs` | Hosted multilingual voices | ElevenLabs API key and voice id |

`indextts` is the only provider name exposed by OpenTalking. Deployment can route it to a same-host HTTP sidecar through the `local` backend or to an OmniRT resident backend. This is similar to avatar video model backend selection: OpenTalking always selects `IndexTTS`, while operators switch the runtime backend through environment variables.

## Edge TTS Default

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=edge
OPENTALKING_TTS_EDGE_VOICE=zh-CN-XiaoxiaoNeural
```

Edge TTS still needs `ffmpeg` because OpenTalking decodes provider audio into PCM before feeding the avatar backend.

## DashScope Qwen Realtime TTS

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=dashscope
OPENTALKING_TTS_DASHSCOPE_API_KEY=<dashscope-api-key>
OPENTALKING_TTS_DASHSCOPE_MODEL=qwen3-tts-flash-realtime
OPENTALKING_QWEN_TTS_REUSE_WS=1
```

DashScope TTS does not read `OPENTALKING_LLM_API_KEY` or `DASHSCOPE_API_KEY`; even if you reuse the same actual key, write it explicitly to `OPENTALKING_TTS_DASHSCOPE_API_KEY`.

## Local CosyVoice3 0.5B

The recommended shape is a standalone local CosyVoice service. OpenTalking uses the `local_cosyvoice` provider to consume its PCM stream over HTTP.

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

Download local audio weights:

```bash title="Terminal"
export UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export UV_INDEX_URL="${UV_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export UV_LINK_MODE=copy
uv sync --extra dev --extra models --extra local-audio --python 3.11
.venv/bin/python scripts/download_local_audio_models.py \
  --root ./models/local-audio \
  --model fun-cosyvoice3-0.5b-2512
```

This downloads the base CosyVoice3 model from ModelScope:

| Asset | Source | Destination |
|---|---|---|
| Base CosyVoice3 weights | ModelScope `FunAudioLLM/Fun-CosyVoice3-0.5B-2512` | `./models/local-audio/FunAudioLLM__Fun-CosyVoice3-0.5B-2512/` |

The base model directory must include the files used by the sidecar runtime,
including `cosyvoice3.yaml`, `llm.pt`, `flow.pt`, `hift.pt`,
`speech_tokenizer_v3.onnx`, `speech_tokenizer_v3.batch.onnx`, `campplus.onnx`,
and `flow.decoder.estimator.fp32.onnx`. The built-in zero-shot voice also needs
a prompt wav configured by `OPENTALKING_TTS_LOCAL_COSYVOICE_PROMPT_AUDIO`; cloned
voices store their own prompt wav under the local voice directory.

For fp16 TensorRT, download the extra ONNX assets from Hugging Face and place
them in the same base model directory:

| Asset | Source | Required for |
|---|---|---|
| `flow.decoder.estimator.autocast_fp16.onnx` | Hugging Face `yuekai/Fun-CosyVoice3-0.5B-2512-FP16-ONNX` | `FP16 + LOAD_TRT=1`; OpenTalking builds `flow.decoder.estimator.autocast_fp16.mygpu.plan` from it. |
| `flow.decoder.estimator.streaming.autocast_fp16.onnx` | Hugging Face `yuekai/Fun-CosyVoice3-0.5B-2512-FP16-ONNX` | Optional streaming fp16 ONNX asset; keep beside the estimator ONNX for runtime compatibility. |

The generated `*.mygpu.plan` files are machine-specific TensorRT engines. Do not
copy them between different GPU / TensorRT / CUDA environments; rebuild them on
the target host from the ONNX files.

This main `.venv` is for OpenTalking, SenseVoice, and the video backend. Keep
CosyVoice in its own sidecar venv so its `transformers==4.51.3` runtime does not
conflict with OpenTalking's `transformers>=4.57,<6`.

Prepare the CosyVoice runtime:

```bash title="Terminal"
mkdir -p ./models/local-audio/runtime
git clone https://github.com/FunAudioLLM/CosyVoice.git ./models/local-audio/runtime/CosyVoice
cd ./models/local-audio/runtime/CosyVoice
git submodule update --init --recursive
```

Create or update the CosyVoice sidecar venv:

```bash title="Terminal"
OPENTALKING_COSYVOICE_VENV_DIR=.venv-cosyvoice \
  bash scripts/prepare_cosyvoice_venv.sh
```

If you need TensorRT, install the TRT dependencies into the CosyVoice sidecar venv, not into OpenTalking's main `.venv`:

```bash title="Terminal"
PIP_EXTRA_INDEX_URL=https://pypi.nvidia.com/ OPENTALKING_COSYVOICE_INSTALL_TENSORRT=1 \
  OPENTALKING_COSYVOICE_VENV_DIR=.venv-cosyvoice bash scripts/prepare_cosyvoice_venv.sh
```

Start the local TTS service:

```bash title="Terminal"
bash scripts/quickstart/start_local_cosyvoice.sh --port 19090
```

In prior GPU validation, the main CosyVoice3 issue was not a single TTFA number but seed-dependent output-length drift. The local CosyVoice service therefore keeps two stability guards on by default: `OPENTALKING_TTS_LOCAL_COSYVOICE_MASK_STOP_TOKENS=1` masks every stop token exposed by the CosyVoice LLM, and `OPENTALKING_TTS_LOCAL_COSYVOICE_MAX_TOKEN_TEXT_RATIO=6` bounds the token/text ratio so long prompts do not occasionally produce runaway audio. Keep these guards enabled for realtime use.

TensorRT is optional. Enable it only after the current CosyVoice runtime, CUDA, onnxruntime-gpu/TensorRT engines, and model directory are compatible:

```bash title="Terminal"
.venv-cosyvoice/bin/python -c "import tensorrt as trt; print(trt.__version__)"
test -f ./models/local-audio/FunAudioLLM__Fun-CosyVoice3-0.5B-2512/flow.decoder.estimator.fp32.onnx
```

For CosyVoice3 fp16 TRT, prefer the official autocast fp16 ONNX asset. A TRT engine can be built from `flow.decoder.estimator.fp32.onnx`, but some GPU/TensorRT combinations can produce NaNs or silent audio. Before enabling `FP16 + LOAD_TRT`, place `flow.decoder.estimator.autocast_fp16.onnx` in the same model directory. If the server needs a proxy for Hugging Face, inject proxy variables only for the download command; do not add them to the OpenTalking service env:

```bash title="Terminal"
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

`start_local_cosyvoice.sh` automatically adds the sidecar venv's `site-packages/tensorrt_libs` directory to `LD_LIBRARY_PATH`. On first startup with `FP16 + LOAD_TRT=1`, if `flow.decoder.estimator.autocast_fp16.onnx` exists in the model directory, OpenTalking builds the GPU-specific `flow.decoder.estimator.autocast_fp16.mygpu.plan` from it; this can take longer than a normal startup. SenseVoice still runs in the OpenTalking main `.venv` and should not follow the CosyVoice TRT settings.

After startup, check the sidecar health payload and verify `runtime_flags.load_trt`, `runtime.trt_autocast_fp16`, `streaming`, `llm_token_ratio`, and `llm_stop_token_patch`:

```bash title="Terminal"
curl -fsS http://127.0.0.1:19090/health | python3 -m json.tool
```

Measured on a Linux server with an NVIDIA RTX 3090, CosyVoice3 sidecar venv,
`FP16 + LOAD_TRT=1`, and the autocast fp16 TensorRT plan loaded. The benchmark
called the sidecar `/synthesize` endpoint directly and measured first PCM byte
arrival as TTFB:

| Text length | TTFB | Wall time | Audio duration | RTF |
|---:|---:|---:|---:|---:|
| 43 chars | 0.683 s | 6.215 s | 7.200 s | 0.863 |
| 42 chars | 0.642 s | 5.858 s | 6.960 s | 0.842 |
| 29 chars | 0.639 s | 5.771 s | 6.520 s | 0.885 |
| **Average** | **0.655 s** | **5.948 s** | **6.893 s** | **0.863** |

For the full local speech input, speech synthesis, and QuickTalk video chain, see [Local STT/TTS + QuickTalk](recipes/local-quicktalk-audio.md).

## IndexTTS Deployment (provider = indextts)

OpenTalking always uses `provider=indextts` for IndexTTS. `OPENTALKING_TTS_INDEXTTS_BACKEND` only selects the runtime topology: `local` means a same-host HTTP sidecar, and `omnirt` means an OmniRT resident service. The frontend, API payloads, and cloned voice metadata do not split this into two providers.

### Option A: Same-host HTTP sidecar (backend = local)

The local backend runs IndexTTS2 in a separate same-host HTTP sidecar. The OpenTalking API process only consumes the sidecar's `audio/L16` PCM stream through `OPENTALKING_TTS_LOCAL_INDEXTTS_SERVICE_URL`. Do not install `index-tts` directly into the OpenTalking `.venv`; the upstream package pins `torch`, `transformers`, `protobuf`, and related dependencies and can break QuickTalk / STT dependencies in the main environment.

Install the OpenTalking main environment and local-audio download dependencies first. Do not install `index-tts` into this environment:

```bash title="Terminal"
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
Large Hugging Face/Xet files may print `Read timed out` or `SSL record layer failure` while resuming. Continue if the command exits with status 0. If it fails, keep the partial model directory and rerun the same command; the downloader reuses the existing cache and resumes the remaining files.


If the machine already has a compatible model root, you can skip the download and set `OPENTALKING_LOCAL_AUDIO_MODEL_ROOT` to that directory. The root must contain at least `IndexTeam__IndexTTS-2/config.yaml`, `facebook__w2v-bert-2.0`, `funasr__campplus`, and `nvidia__bigvgan_v2_22khz_80band_256x`. MaskGCT prefers `amphion__MaskGCT`; an existing `amphion__MaskGCT-ms` directory is also supported as long as it contains `semantic_codec/model.safetensors`.

Create the IndexTTS sidecar runtime next. The upstream repository includes LFS example audio files and some environments may hit LFS quota, so skip smudge; use your own clear 3-15 second prompt audio instead.

```bash title="Terminal"
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

IndexTTS needs a clear 3-15 second human voice prompt. Prepare a default system voice first, or upload a reference audio file in the WebUI voice clone flow.

```bash title="Terminal"
cd "$OPENTALKING_HOME"
mkdir -p ./models/local-audio/voices/system/indextts-default
cp /path/to/reference.wav ./models/local-audio/voices/system/indextts-default/prompt.wav
cat > ./models/local-audio/voices/system/indextts-default/meta.json <<'JSON'
{"voice_id":"indextts-default","display_label":"IndexTTS Default Voice","provider":"indextts","target_model":"IndexTeam/IndexTTS-2","source":"system"}
JSON
```

Start the sidecar service:

```bash title="Terminal"
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

Select `indextts` in OpenTalking `.env` and set the backend to `local`:

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

These `LOCAL_INDEXTTS_*_DIR` variables can be written in the OpenTalking `.env` or passed to the sidecar process. The OpenTalking main process needs the `SERVICE_URL` and voice prompt path; the sidecar needs the model directory, prompt, and local w2v / MaskGCT / campplus / BigVGAN asset directories so it does not reach Hugging Face at runtime.

Start the OpenTalking API and WebUI. This example uses QuickTalk local as the video backend; use `--mock` instead if you only want to validate TTS preview first.

```bash title="Terminal"
cd "$OPENTALKING_HOME"
bash scripts/start_unified.sh --backend local --model quicktalk --api-port 8000 --web-port 5173
```

If `8000` or `5173` is already occupied, choose free values for `--api-port` / `--web-port`; update the API port in the following `curl` commands accordingly.

Verify the sidecar first, then verify the OpenTalking API:

```bash title="Terminal"
curl -fsS http://127.0.0.1:19092/health
curl -fsS -X POST http://127.0.0.1:19092/synthesize \
  -H 'content-type: application/json' \
  -d '{"text":"Hello, this is a local IndexTTS service test.","sample_rate":16000}' \
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
  -d '{"text":"Hello, this is an OpenTalking IndexTTS test.","tts_provider":"indextts","tts_voice":"indextts-default","tts_model":"IndexTeam/IndexTTS-2"}' \
  --output /tmp/opentalking-indextts-preview.wav

.venv/bin/python - <<'PY'
import wave
with wave.open("/tmp/opentalking-indextts-preview.wav", "rb") as wf:
    print("wav", wf.getframerate(), wf.getnchannels(), wf.getsampwidth(), wf.getnframes())
PY
```

You can also inspect runtime status to confirm OpenTalking still exposes `indextts` while routing it to the local backend:

```bash title="Terminal"
curl -fsS http://127.0.0.1:8000/runtime/status | python3 -m json.tool
```

Expected: `tts_provider` is `indextts`, `tts_providers.indextts.backend` is `local`, `tts_providers.indextts.resolved_provider` is `local_indextts`, and `service_url_set=true`.


### Option B: OmniRT resident service (backend = omnirt)

The OmniRT backend keeps IndexTTS resident in a separate service. OpenTalking only consumes the HTTP `audio/L16` PCM stream. The OpenTalking provider is still `indextts`; only the backend changes to `omnirt`.

Start the OmniRT text2audio service first:

```bash title="Terminal"
cd "$OMNIRT_HOME"
OMNIRT_INDEXTTS_RUNTIME=1 \
OMNIRT_INDEXTTS_MODEL_DIR=/data2/zhongyi/model/local-audio/IndexTeam__IndexTTS-2 \
OMNIRT_INDEXTTS_CFG_PATH=/data2/zhongyi/model/local-audio/IndexTeam__IndexTTS-2/config.yaml \
OMNIRT_INDEXTTS_PROMPT_AUDIO=/data2/zhongyi/model/local-audio/voices/system/indextts-default/prompt.wav \
OMNIRT_INDEXTTS_DEVICE=cuda:0 \
uv run omnirt serve-text2audio --host 127.0.0.1 --port 9012
```

Then select the provider and backend in OpenTalking `.env`:

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

`token_window` is token-window streaming at the model-token level: OmniRT decodes and emits PCM once enough speech tokens are available, without waiting for the full text segment. It is not 20 ms waveform-level streaming; short-utterance first-byte latency still depends on IndexTTS GPT token generation and vocoder decoding.

## ElevenLabs

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=elevenlabs
OPENTALKING_TTS_ELEVENLABS_API_KEY=<elevenlabs-api-key>
OPENTALKING_TTS_ELEVENLABS_VOICE_ID=<voice-id>
OPENTALKING_TTS_ELEVENLABS_MODEL_ID=eleven_flash_v2_5
```

## Verification

Create a `mock` session first, then call `/speak`. This verifies TTS without depending on a real talking-head model.

```bash title="Terminal"
SID=<session-id>
curl -s -X POST "http://127.0.0.1:8000/sessions/$SID/speak" \
  -H 'content-type: application/json' \
  -d '{"text":"你好，这是一次 OpenTalking 语音合成测试。","tts_provider":"indextts","tts_voice":"indextts-default","tts_model":"IndexTeam/IndexTTS-2"}'
```

## Frontend Entry

After the model or backend service is running, use the OpenTalking WebUI:

```bash title="Terminal"
cd "$OPENTALKING_HOME"
bash scripts/quickstart/start_frontend.sh --api-port 8000 --web-port 5173 --host 0.0.0.0
```

For a remote server, forward your local browser port to server `5173`, then open `http://127.0.0.1:5173`.
