# IndexTTS Local Deployment

IndexTTS is integrated through OpenTalking's `indextts` provider. Use it for controllable dubbing, emotion control, and cloned voices. This page covers the same-machine HTTP sidecar shape.

## Use Cases

- More voice control than the default Edge TTS path.
- IndexTTS runtime should be isolated from the main OpenTalking process.
- TTS must run locally instead of through a hosted API.

## Deployment Root

Run the following commands in the same terminal. Enter the OpenTalking repository
directory and define the deployment root once:

```bash title="Terminal"
cd /path/to/digital_human/opentalking
export OPENTALKING_HOME="$(pwd)"
case "${DIGITAL_HUMAN_HOME:-}" in
  ""|/path/to/digital_human) export DIGITAL_HUMAN_HOME="$(cd "$OPENTALKING_HOME/.." && pwd)" ;;
esac
export OPENTALKING_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
export OPENTALKING_MODEL_REPO_ROOT="$DIGITAL_HUMAN_HOME/model-repos"
export OPENTALKING_RUNTIME_ROOT="$DIGITAL_HUMAN_HOME/runtimes"
export OPENTALKING_LOCAL_AUDIO_MODEL_ROOT="$OPENTALKING_MODEL_ROOT/local-audio"
export OPENTALKING_TTS_LOCAL_INDEXTTS_RUNTIME_DIR="$OPENTALKING_MODEL_REPO_ROOT/index-tts"
export OPENTALKING_INDEXTTS_VENV_DIR="$OPENTALKING_RUNTIME_ROOT/index-tts/venv"
```

## Weight Preparation

Use consistent deployment directories: weights under `$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT`,
the IndexTTS source checkout under `$OPENTALKING_MODEL_REPO_ROOT`, and the sidecar
venv under `$OPENTALKING_RUNTIME_ROOT`.

```bash title="Terminal"
cd "$OPENTALKING_HOME"
mkdir -p "$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT"

export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
# Some networks repeatedly fail on the HF Xet/CAS path; prefer plain HTTP downloads.
export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-1}"
uv sync --extra dev --extra models --extra local-audio --extra quicktalk-cuda --python 3.11

python scripts/download_local_audio_models.py \
  --root "$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT" \
  --model indextts2 \
  --model indextts2-w2v-bert \
  --model indextts2-maskgct \
  --model indextts2-campplus \
  --model indextts2-bigvgan
```

Prepare the runtime:

```bash title="Terminal"
cd "$DIGITAL_HUMAN_HOME"
mkdir -p "$OPENTALKING_MODEL_REPO_ROOT" "$OPENTALKING_RUNTIME_ROOT/index-tts"
# Optional: use a GitHub proxy prefix when GitHub access is slow.
# export GITHUB_PROXY_PREFIX=https://gh-proxy.com/
# Optional: use the Tsinghua PyPI mirror when PyPI access is slow.
export UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export PIP_INDEX_URL="${PIP_INDEX_URL:-$UV_DEFAULT_INDEX}"
# Avoid failures when ~/.cache/uv or ~/.cache/pip was previously written by root.
export UV_CACHE_DIR="${UV_CACHE_DIR:-$OPENTALKING_RUNTIME_ROOT/.uv-cache}"
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$OPENTALKING_RUNTIME_ROOT/.pip-cache}"
if [ ! -d "$OPENTALKING_MODEL_REPO_ROOT/index-tts/.git" ]; then
  GIT_LFS_SKIP_SMUDGE=1 git clone "${GITHUB_PROXY_PREFIX:-}https://github.com/index-tts/index-tts.git" "$OPENTALKING_MODEL_REPO_ROOT/index-tts"
fi

mkdir -p "$UV_CACHE_DIR" "$PIP_CACHE_DIR"
uv venv --seed --python 3.11 "$OPENTALKING_RUNTIME_ROOT/index-tts/venv"
"$OPENTALKING_RUNTIME_ROOT/index-tts/venv/bin/python" -m pip install -U pip wheel setuptools
cd "$OPENTALKING_MODEL_REPO_ROOT/index-tts"
"$OPENTALKING_RUNTIME_ROOT/index-tts/venv/bin/python" -m pip install -e .
cd "$DIGITAL_HUMAN_HOME"
"$OPENTALKING_RUNTIME_ROOT/index-tts/venv/bin/python" -m pip install fastapi "uvicorn[standard]" soundfile
```

Do not install `index-tts` into OpenTalking's main `.venv`; OpenTalking calls the
sidecar over HTTP.

## Configuration

```env title=".env"
DIGITAL_HUMAN_HOME=/path/to/digital_human
OPENTALKING_TTS_DEFAULT_PROVIDER=indextts
OPENTALKING_TTS_INDEXTTS_BACKEND=local
OPENTALKING_TTS_LOCAL_INDEXTTS_SERVICE_URL=http://127.0.0.1:19092/synthesize
OPENTALKING_TTS_LOCAL_INDEXTTS_DEVICE=cuda:0
OPENTALKING_TTS_VOICE=indextts-xiaoxiao-cn
```

Only replace `DIGITAL_HUMAN_HOME` with the real deployment root. The model,
runtime, and venv paths below are derived from it in the start command, which
avoids stale absolute paths in `.env`.

When OmniRT hosts the IndexTTS runtime, OpenTalking still uses
`provider=indextts`; set the backend to `omnirt` and point it at the resident
OmniRT service. OmniRT owns model loading, segmented streaming, and
token-window streaming:

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=indextts
OPENTALKING_TTS_INDEXTTS_BACKEND=omnirt
OPENTALKING_TTS_OMNIRT_INDEXTTS_SERVICE_URL=http://127.0.0.1:9012/v1/text2audio/indextts
OPENTALKING_TTS_OMNIRT_INDEXTTS_STREAMING_MODE=token_window
OPENTALKING_TTS_OMNIRT_INDEXTTS_TOKEN_WINDOW_SIZE=40
```

## Start Command

Start the IndexTTS sidecar first, then start OpenTalking + QuickTalk. The sidecar
HTTP path and port must match `OPENTALKING_TTS_LOCAL_INDEXTTS_SERVICE_URL`.

```bash title="Terminal"
cd "$OPENTALKING_HOME"

bash scripts/quickstart/start_local_indextts.sh --port 19092 --device cuda:0

export OPENTALKING_TTS_DEFAULT_PROVIDER=indextts
export OPENTALKING_TTS_INDEXTTS_BACKEND=local
export OPENTALKING_TTS_LOCAL_INDEXTTS_SERVICE_URL=http://127.0.0.1:19092/synthesize
export OPENTALKING_TTS_VOICE=indextts-xiaoxiao-cn

export OPENTALKING_TORCH_DEVICE=cuda:0
export OPENTALKING_QUICKTALK_DEVICE=cuda:0
export OPENTALKING_QUICKTALK_ASSET_ROOT="$OPENTALKING_MODEL_ROOT/quicktalk"
export OPENTALKING_QUICKTALK_WORKER_CACHE=1

bash scripts/start_unified.sh --backend local --model quicktalk --api-port 8210 --web-port 5283
```

## Verification

```bash title="Terminal"
curl -fsS http://127.0.0.1:19092/health
curl -fsS http://127.0.0.1:8210/health
curl -fsS http://127.0.0.1:8210/runtime/status | jq '.tts_providers.indextts.service_url_set'
```

The status value should be `true`. After creating a `quicktalk` session, call
`/speak` to verify that the TTS provider returns audio and drives QuickTalk.

## Stop Services

```bash title="Terminal"
cd "$OPENTALKING_HOME"
bash scripts/quickstart/stop_all.sh --api-port 8210 --web-port 5283
```

This stops the OpenTalking API, WebUI, and the IndexTTS sidecar started above
with a pid file.

## Common Errors

| Symptom | Action |
|---------|--------|
| `service_url_set=false` | Use `OPENTALKING_TTS_LOCAL_INDEXTTS_SERVICE_URL`, not `OPENTALKING_TTS_INDEXTTS_SERVICE_URL`. |
| Sidecar API path mismatch | Check that the sidecar port and path match `OPENTALKING_TTS_LOCAL_INDEXTTS_SERVICE_URL`; the default port is `19092`. |
| Downloads repeatedly mention `cas-bridge.xethub.hf.co` or SSL resume | Keep `HF_HUB_DISABLE_XET=1` and rerun the same download command; the script reuses fully downloaded model directories. If needed, temporarily use `HF_ENDPOINT=https://huggingface.co`. |
| Missing downloaded files | Re-run the download script and confirm all five `indextts2*` model directories exist. |
| QuickTalk reports `onnxruntime` has no `InferenceSession` | Re-run `uv sync --extra dev --extra models --extra local-audio --extra quicktalk-cuda --python 3.11`; on CPU replace `quicktalk-cuda` with `quicktalk-cpu`. |
| Dependency conflicts | Keep the IndexTTS runtime in its own venv and do not install it into OpenTalking's main `.venv`. |
