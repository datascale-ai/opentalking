# MuseTalk with OmniRT

Use this path when the MuseTalk runtime, MuseTalk WebSocket backend, and OmniRT gateway should run outside the OpenTalking process. OpenTalking only connects to the OmniRT endpoint.

## 1. Prepare OmniRT

```bash title="Terminal"
export DIGITAL_HUMAN_HOME=/path/to/digital_human
export OMNIRT_REPO="$DIGITAL_HUMAN_HOME/omnirt"
export OMNIRT_HOME="$DIGITAL_HUMAN_HOME/omnirt/.omnirt"

# Set mirrors first when package downloads are slow. Keep caches and temp files
# on the same data disk to avoid cross-device copies and small /tmp partitions.
export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export UV_HTTP_TIMEOUT=300
export UV_CACHE_DIR="$DIGITAL_HUMAN_HOME/.cache/uv"
export PIP_CACHE_DIR="$DIGITAL_HUMAN_HOME/.cache/pip"
export TMPDIR="$DIGITAL_HUMAN_HOME/tmp"
mkdir -p "$UV_CACHE_DIR" "$PIP_CACHE_DIR" "$TMPDIR"

cd "$OMNIRT_REPO"
uv sync --extra server --python 3.11
```

The first `uv sync` can download several GB of CUDA PyTorch, cuDNN, cuBLAS, NCCL, Triton, and related wheels. Later venv rebuilds reuse `$UV_CACHE_DIR` and are much faster than the first deployment.

## 2. Prepare weights

`start_omnirt_musetalk.sh` reads `$OMNIRT_MODEL_ROOT` by default:

```bash title="Terminal"
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models/musetalk-v15"
# If the global OMNIRT_MODEL_ROOT is already used by other models, override
# only MuseTalk instead:
# export OMNIRT_MUSETALK_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models/musetalk-v15"
```

`$OMNIRT_MODEL_ROOT` must directly contain the subdirectories below. If your weights live in a directory such as `/opt/models/MuseTalk1.5`, point `OMNIRT_MODEL_ROOT` at that directory, not at its parent.

The layout is the same as the local mode:

```text
$OMNIRT_MODEL_ROOT/
  musetalk/
    musetalk.json
    pytorch_model.bin
  sd-vae-ft-mse/
    config.json
    diffusion_pytorch_model.bin or diffusion_pytorch_model.safetensors
  whisper/
    tiny.pt
  dwpose/
    dw-ll_ucoco_384.pth
  face-parse-bisenet/
    79999_iter.pth
```

If you use the official MuseTalk `download_weights.sh`, arrange `sd-vae` as `sd-vae-ft-mse` and `face-parse-bisent` as `face-parse-bisenet`:

```bash title="Terminal"
cd "$OMNIRT_MODEL_ROOT"
ln -s sd-vae sd-vae-ft-mse 2>/dev/null || true
ln -s face-parse-bisent face-parse-bisenet 2>/dev/null || true
```

`whisper/tiny.pt` must be the OpenAI `openai-whisper` checkpoint. Do not rename the Hugging Face `pytorch_model.bin` file as a replacement.

## 3. Prepare the MuseTalk source checkout

On first startup, OmniRT tries to clone the official MuseTalk repository into `$OMNIRT_HOME/model-repos/MuseTalk`. If the server cannot reach GitHub reliably, clone it on a connected machine and sync it over, or symlink that path to an existing official MuseTalk checkout:

```bash title="Terminal"
mkdir -p "$OMNIRT_HOME/model-repos"
ln -s /path/to/MuseTalk "$OMNIRT_HOME/model-repos/MuseTalk"
# The directory must contain the musetalk/ Python package.
```

Do not point `$OMNIRT_HOME/model-repos/MuseTalk` at the weight directory. The source checkout and `$OMNIRT_MODEL_ROOT` are different directories.

## 4. Start OmniRT MuseTalk

```bash title="Terminal"
export OPENTALKING_HOME="$DIGITAL_HUMAN_HOME/opentalking"
# On multi-GPU hosts, optionally pin the visible GPU.
export CUDA_VISIBLE_DEVICES=0

cd "$OPENTALKING_HOME"
bash scripts/quickstart/start_omnirt_musetalk.sh --device cuda --port 9000 --musetalk-port 8766
```

If `$OMNIRT_HOME/model-repos/MuseTalk` already points to a usable source checkout and the server cannot reach GitHub reliably, add `--no-update` to skip `git fetch`:

```bash title="Terminal"
bash scripts/quickstart/start_omnirt_musetalk.sh --device cuda --port 9000 --musetalk-port 8766 --no-update
```

The script installs the MuseTalk runtime, starts the MuseTalk WebSocket backend, starts the OmniRT audio2video gateway, and waits until `/v1/audio2video/models` reports `musetalk`. The first install creates `$OMNIRT_HOME/runtimes/musetalk/cuda/venv`. The MuseTalk CUDA runtime is pinned to Python 3.10, PyTorch 2.0.1 + cu118, diffusers 0.30.2, transformers 4.39.2, and accelerate 0.28.0, matching the official MuseTalk 1.5 dependency set. Do not upgrade diffusers or transformers here; newer releases can import torch APIs such as `torch.xpu` or `torch.float8_e4m3fn` that do not exist in torch 2.0.1. If `download.pytorch.org` is unstable, prepare a wheel cache on a connected machine or reuse a verified runtime venv, then run this step again.

The script also inherits `UV_CACHE_DIR`, `PIP_CACHE_DIR`, and `TMPDIR` from section 1. Do not put these caches on a small system `/tmp`; the MuseTalk runtime install downloads PyTorch cu118, Triton, OpenMMLab, and related wheels, which can be slow on weak network paths.

## 5. Start OpenTalking

```bash title="Terminal"
cd "$OPENTALKING_HOME"
bash scripts/start_unified.sh \
  --backend omnirt \
  --model musetalk \
  --omnirt http://127.0.0.1:9000 \
  --api-port 8000 \
  --web-port 5173
```

## Frontend Startup

`start_unified.sh` starts the WebUI after the API. To restart only the frontend while the API is already running on port `8000`, use:

```bash title="Terminal"
cd "$OPENTALKING_HOME"
bash scripts/quickstart/start_frontend.sh --api-port 8000 --web-port 5173 --host 0.0.0.0
```

For a remote server, forward your local browser port to the server `5173`, then open `http://127.0.0.1:5173`.


## 6. Verify

```bash title="Terminal"
curl -fsS http://127.0.0.1:9000/v1/audio2video/models | python3 -m json.tool
curl -s http://127.0.0.1:8000/models | python3 -m json.tool
```

Expected OpenTalking status:

```json
{"id":"musetalk","backend":"omnirt","connected":true,"reason":"omnirt"}
```
