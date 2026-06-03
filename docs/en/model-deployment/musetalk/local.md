# MuseTalk Local Deployment

Use this path when OpenTalking should load the MuseTalk local adapter in-process and run the official MuseTalk avatar preprocessing before a session is created. This mode is useful for single-machine validation, but it has heavier dependencies than Wav2Lip or QuickTalk.

## 1. Prepare OpenTalking

```bash title="Terminal"
export DIGITAL_HUMAN_HOME=/path/to/digital_human
export OPENTALKING_HOME="$DIGITAL_HUMAN_HOME/opentalking"

# Set mirrors first when package downloads are slow.
export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export UV_HTTP_TIMEOUT=300

cd "$OPENTALKING_HOME"
uv sync --extra dev --extra models --python 3.11
uv pip install --python .venv/bin/python pip "setuptools<81" openmim
```

## 2. Prepare MuseTalk weights

The local adapter reads `$OPENTALKING_MUSETALK_MODEL_ROOT`. Put the MuseTalk-related weights under one root, for example:

```bash title="Terminal"
export OPENTALKING_MUSETALK_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models/musetalk-v15"
mkdir -p "$OPENTALKING_MUSETALK_MODEL_ROOT"
```

OpenTalking expects this layout:

```text
$OPENTALKING_MUSETALK_MODEL_ROOT/
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

You can download the assets with the official MuseTalk `download_weights.sh` and then arrange the directories. Note two naming differences:

- The official script often uses `sd-vae`; arrange or symlink it as `sd-vae-ft-mse`.
- The official script often uses `face-parse-bisent`; arrange or symlink it as `face-parse-bisenet`.

For example, if you already have the official downloaded `models/` layout:

```bash title="Terminal"
cd "$OPENTALKING_MUSETALK_MODEL_ROOT"
ln -s sd-vae sd-vae-ft-mse 2>/dev/null || true
ln -s face-parse-bisent face-parse-bisenet 2>/dev/null || true
```

`whisper/tiny.pt` must be the OpenAI `openai-whisper` checkpoint. Do not rename the Hugging Face `pytorch_model.bin` file as a replacement.

## 3. Prepare MuseTalk source and preprocessing dependencies

The local runtime uses OpenTalking's own `.venv` for both inference and official MuseTalk preprocessing by default. This reuses the torch / torchvision / cv2 packages from `uv sync --extra models` and avoids downloading the large PyTorch build from the official MuseTalk `requirements.txt` again.

```bash title="Terminal"
mkdir -p "$DIGITAL_HUMAN_HOME/model-repos"

git clone https://github.com/TMElyralab/MuseTalk.git "$DIGITAL_HUMAN_HOME/model-repos/MuseTalk"
# If the server already has an official MuseTalk checkout, point OPENTALKING_MUSETALK_REPO to it.

export OPENTALKING_MUSETALK_REPO="$DIGITAL_HUMAN_HOME/model-repos/MuseTalk"
export OPENTALKING_MUSETALK_PREPROCESS_PYTHON="$OPENTALKING_HOME/.venv/bin/python"

"$OPENTALKING_MUSETALK_PREPROCESS_PYTHON" -m pip install json-tricks munkres pycocotools shapely terminaltables xtcocotools
"$OPENTALKING_MUSETALK_PREPROCESS_PYTHON" -m pip install --no-build-isolation chumpy
"$OPENTALKING_MUSETALK_PREPROCESS_PYTHON" -m mim install mmengine
"$OPENTALKING_MUSETALK_PREPROCESS_PYTHON" -m pip install "mmcv-lite==2.0.1"
"$OPENTALKING_MUSETALK_PREPROCESS_PYTHON" -m mim install "mmdet==3.1.0"
"$OPENTALKING_MUSETALK_PREPROCESS_PYTHON" -m mim install "mmpose==1.1.0"
```

`start_unified.sh --backend local --model musetalk` calls `scripts/quickstart/prepare_local_musetalk.sh` and checks the same dependencies again; the commands above are useful when you want to install them explicitly before startup.

## 4. Start OpenTalking

```bash title="Terminal"
export OPENTALKING_MUSETALK_REPO="$DIGITAL_HUMAN_HOME/model-repos/MuseTalk"
export OPENTALKING_MUSETALK_PREPROCESS_PYTHON="$OPENTALKING_HOME/.venv/bin/python"
export OPENTALKING_MUSETALK_DEVICE=cuda:0
export OPENTALKING_TORCH_DEVICE=cuda:0
# On multi-GPU hosts, optionally pin the visible GPU.
export CUDA_VISIBLE_DEVICES=0

cd "$OPENTALKING_HOME"
bash scripts/start_unified.sh --backend local --model musetalk --api-port 8000 --web-port 5173
```

`start_unified.sh` calls `scripts/quickstart/prepare_local_musetalk.sh` to check and install the MuseTalk local runtime packages in the OpenTalking `.venv`. If an avatar does not already contain `prepared/prepared_info.json` with `source_preprocess=musetalk_official`, OpenTalking runs the official preprocessing step first.

## 5. Verify

```bash title="Terminal"
curl -s http://127.0.0.1:8000/models | jq ".statuses[] | select(.id==\"musetalk\")"
```

Expected status:

```json
{"id":"musetalk","backend":"local","connected":true,"reason":"local_runtime"}
```

Open the WebUI, select a MuseTalk-capable avatar, and start one realtime conversation. The first session for an unprepared custom avatar can be slower than Wav2Lip or QuickTalk.
