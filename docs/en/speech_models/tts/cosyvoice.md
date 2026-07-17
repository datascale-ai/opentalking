# CosyVoice Deployment

CosyVoice can be integrated through two OpenTalking providers:

- `local_cosyvoice`: OpenTalking manages a local CosyVoice sidecar, useful for
  single-machine or private deployments.
- `cosyvoice`: connect to an existing CosyVoice WebSocket / HTTP service, useful when
  your team already operates a TTS service.

For local deployment, run CosyVoice as a standalone sidecar service and let OpenTalking
consume PCM audio over HTTP.

## Use Cases

- Local Chinese TTS with built-in voices or cloned voices.
- TTS inference should be isolated from the main OpenTalking process.
- SenseVoice, CosyVoice, and QuickTalk local should form a full local audio pipeline.

## Weight Preparation

```bash title="Terminal"
cd "$OPENTALKING_HOME"
uv sync --extra dev --extra models --extra local-audio --python 3.11
export DIGITAL_HUMAN_HOME="${DIGITAL_HUMAN_HOME:-$(cd "$OPENTALKING_HOME/.." && pwd)}"
export OPENTALKING_LOCAL_AUDIO_MODEL_ROOT="${OPENTALKING_LOCAL_AUDIO_MODEL_ROOT:-$DIGITAL_HUMAN_HOME/models/local-audio}"

python scripts/download_local_audio_models.py \
  --root "$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT" \
  --model fun-cosyvoice3-0.5b-2512
```

To enable TensorRT / FP16, download the extra ONNX assets from Hugging Face and place
them in the same CosyVoice3 model directory:

```bash title="Terminal"
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

These assets are used as follows:

| Asset | Source | Required for |
|-------|--------|--------------|
| `flow.decoder.estimator.autocast_fp16.onnx` | Hugging Face `yuekai/Fun-CosyVoice3-0.5B-2512-FP16-ONNX` | `FP16 + LOAD_TRT=1`; first startup builds the GPU-specific `flow.decoder.estimator.autocast_fp16.mygpu.plan`. |
| `flow.decoder.estimator.streaming.autocast_fp16.onnx` | Hugging Face `yuekai/Fun-CosyVoice3-0.5B-2512-FP16-ONNX` | Optional streaming fp16 ONNX asset; keep it beside the estimator ONNX for runtime compatibility. |

Generated `*.mygpu.plan` files are machine-specific TensorRT engines. Do not copy them
between different GPU / CUDA / TensorRT environments; rebuild them from ONNX on the
target host.

Prepare the CosyVoice runtime:

```bash title="Terminal"
cd "$OPENTALKING_HOME"
export DIGITAL_HUMAN_HOME="${DIGITAL_HUMAN_HOME:-$(cd "$OPENTALKING_HOME/.." && pwd)}"
export OPENTALKING_TTS_LOCAL_COSYVOICE_RUNTIME_DIR="${OPENTALKING_TTS_LOCAL_COSYVOICE_RUNTIME_DIR:-$DIGITAL_HUMAN_HOME/model-repos/CosyVoice}"
mkdir -p "$(dirname "$OPENTALKING_TTS_LOCAL_COSYVOICE_RUNTIME_DIR")"
# Optional: use a GitHub proxy prefix when GitHub access is slow.
# export GITHUB_PROXY_PREFIX=https://gh-proxy.com/
if [ ! -d "$OPENTALKING_TTS_LOCAL_COSYVOICE_RUNTIME_DIR/.git" ]; then
  git clone "${GITHUB_PROXY_PREFIX:-}https://github.com/FunAudioLLM/CosyVoice.git" "$OPENTALKING_TTS_LOCAL_COSYVOICE_RUNTIME_DIR"
fi
cd "$OPENTALKING_TTS_LOCAL_COSYVOICE_RUNTIME_DIR"
# Optional: if submodules still fetch from GitHub, set a repo-local mirror rule.
# git config url."https://gh-proxy.com/https://github.com/".insteadOf "https://github.com/"
# git submodule sync --recursive
git submodule update --init --recursive
test -d third_party/Matcha-TTS/matcha
```

If the last command fails, the `Matcha-TTS` submodule is incomplete. Re-run
`git submodule update --init --recursive` until `third_party/Matcha-TTS/matcha`
exists.

Create the sidecar venv:

```bash title="Terminal"
cd "$OPENTALKING_HOME"
export DIGITAL_HUMAN_HOME="${DIGITAL_HUMAN_HOME:-$(cd "$OPENTALKING_HOME/.." && pwd)}"
export OPENTALKING_TTS_LOCAL_COSYVOICE_RUNTIME_DIR="${OPENTALKING_TTS_LOCAL_COSYVOICE_RUNTIME_DIR:-$DIGITAL_HUMAN_HOME/model-repos/CosyVoice}"
OPENTALKING_COSYVOICE_VENV_DIR=.venv-cosyvoice \
  bash scripts/prepare_cosyvoice_venv.sh
```

If TensorRT is required, install TRT dependencies into the CosyVoice sidecar venv, not
into the main OpenTalking `.venv`:

```bash title="Terminal"
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

If pip hits an SSL interruption during download, rerun the same command. The script
reuses the existing `.venv-cosyvoice`; deleting the venv is not required.

## Configuration

Local sidecar:

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

The main OpenTalking `.venv` is for orchestration, SenseVoice, and the video backend. Keep CosyVoice in a separate sidecar venv so its runtime dependencies do not conflict with the main environment.

Existing CosyVoice service:

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=cosyvoice
OPENTALKING_TTS_ENABLED_PROVIDERS=cosyvoice,dashscope,edge
OPENTALKING_TTS_COSYVOICE_URL=http://127.0.0.1:19090/synthesize
```

## Start Command

Default FP16 mode, with CUDA enabling FP16 automatically and TRT disabled:

```bash title="Terminal"
cd "$OPENTALKING_HOME"
bash scripts/quickstart/start_local_cosyvoice.sh --port 19090
```

FP16 + TensorRT mode:

```bash title="Terminal"
cd "$OPENTALKING_HOME"
export OPENTALKING_TTS_LOCAL_COSYVOICE_FP16=auto
export OPENTALKING_TTS_LOCAL_COSYVOICE_LOAD_TRT=1
bash scripts/quickstart/start_local_cosyvoice.sh --port 19090
```

On first startup with `LOAD_TRT=1`, if
`flow.decoder.estimator.autocast_fp16.onnx` exists in the model directory, the
CosyVoice runtime builds a GPU-specific TensorRT plan. Startup can take longer than
the default mode. `start_local_cosyvoice.sh` automatically adds the sidecar venv's
`site-packages/tensorrt_libs` directory to `LD_LIBRARY_PATH`.

After the CosyVoice sidecar is up, start OpenTalking + QuickTalk. You can continue
in the same terminal; if you switch to a new terminal, restore deployment variables
such as `OPENTALKING_HOME` and `DIGITAL_HUMAN_HOME` first. This is the recommended
real pipeline: OpenTalking uses the local CosyVoice sidecar for TTS and local
QuickTalk as the avatar backend.

```bash title="Terminal"
cd "$OPENTALKING_HOME"

export OPENTALKING_TTS_DEFAULT_PROVIDER=local_cosyvoice
export OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL=http://127.0.0.1:19090/synthesize

export OPENTALKING_TORCH_DEVICE=cuda:0
export OPENTALKING_QUICKTALK_DEVICE=cuda:0
export OPENTALKING_QUICKTALK_ASSET_ROOT="$DIGITAL_HUMAN_HOME/models/quicktalk"
export OPENTALKING_QUICKTALK_WORKER_CACHE=1

bash scripts/start_unified.sh --backend local --model quicktalk --api-port 8210 --web-port 5283
```

## Verification

```bash title="Terminal"
curl -fsS http://127.0.0.1:19090/health
curl -fsS http://127.0.0.1:8210/health
```

Check that the sidecar enabled FP16 / TRT as expected:

```bash title="Terminal"
curl -fsS http://127.0.0.1:19090/health | python3 -m json.tool
```

The health payload should show `fp16=true`; when TRT is enabled, it should show
`load_trt=true`.

After creating a `quicktalk` session, call `/speak` to confirm that OpenTalking
receives CosyVoice audio and drives QuickTalk:

```bash title="Terminal"
SID=<session-id>
curl -s -X POST "http://127.0.0.1:8210/sessions/$SID/speak" \
  -H 'content-type: application/json' \
  -d '{"text":"Hello, this is a local CosyVoice speech test."}'
```

## Benchmark Baseline

Test environment: NVIDIA RTX 3090 Linux server, CosyVoice3 standalone sidecar venv,
`FP16 + LOAD_TRT=1`, and the autocast fp16 TensorRT plan loaded. The benchmark called
sidecar `/synthesize` directly and measured TTFB as first PCM-byte arrival.

| Text length | TTFB | Wall time | Audio duration | RTF |
|---:|---:|---:|---:|---:|
| 43 chars | 0.683 s | 6.215 s | 7.200 s | 0.863 |
| 42 chars | 0.642 s | 5.858 s | 6.960 s | 0.842 |
| 29 chars | 0.639 s | 5.771 s | 6.520 s | 0.885 |
| **Average** | **0.655 s** | **5.948 s** | **6.893 s** | **0.863** |

This baseline covers only the TTS sidecar. It does not include STT, LLM, QuickTalk,
WebRTC, or browser playback latency.

## Common Errors

| Symptom | Action |
|---------|--------|
| `transformers` version conflict | Keep CosyVoice in a separate sidecar venv; do not install it into the main OpenTalking `.venv`. |
| High first-chunk latency | First chunk depends on model inference and voice loading; prewarm in production. |
| OpenTalking cannot reach the service | Check `OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL` and the sidecar port. |
