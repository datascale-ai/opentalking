# MuseTalk with OmniRT

Use this path when the MuseTalk runtime, MuseTalk WebSocket backend, and OmniRT gateway should run outside the OpenTalking process. OpenTalking only connects to the OmniRT endpoint.

## 1. Prepare OmniRT

```bash title="Terminal"
export DIGITAL_HUMAN_HOME=/path/to/digital_human
export OMNIRT_REPO="$DIGITAL_HUMAN_HOME/omnirt"
export OMNIRT_HOME="$DIGITAL_HUMAN_HOME/omnirt/.omnirt"

# Set mirrors first when package downloads are slow.
export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export UV_HTTP_TIMEOUT=300

cd "$OMNIRT_REPO"
uv sync --extra server --python 3.11
```

## 2. Prepare weights

`start_omnirt_musetalk.sh` reads `$OMNIRT_MODEL_ROOT` by default:

```bash title="Terminal"
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models/musetalk-v15"
```

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

The script installs the MuseTalk runtime, starts the MuseTalk WebSocket backend, starts the OmniRT audio2video gateway, and waits until `/v1/audio2video/models` reports `musetalk`. The first install creates `$OMNIRT_HOME/runtimes/musetalk/cuda/venv` and installs packages from the PyPI mirror plus the PyTorch CUDA wheel index (the current CUDA docs path uses cu124). If `download.pytorch.org` is unstable, prepare a wheel cache on a connected machine or reuse a verified runtime venv, then run this step again.

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

## 6. Verify

```bash title="Terminal"
curl -fsS http://127.0.0.1:9000/v1/audio2video/models | jq
curl -s http://127.0.0.1:8000/models | jq ".statuses[] | select(.id==\"musetalk\")"
```

Expected OpenTalking status:

```json
{"id":"musetalk","backend":"omnirt","connected":true,"reason":"omnirt"}
```
