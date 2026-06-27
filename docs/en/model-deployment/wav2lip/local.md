# Wav2Lip Local Deployment

Use this path to run a lightweight lip-sync model on one machine before introducing a separate inference service.

```bash title="Terminal"
export DIGITAL_HUMAN_HOME=/path/to/digital_human
export OPENTALKING_HOME="$DIGITAL_HUMAN_HOME/opentalking"

# Set mirrors first when package downloads are slow.
export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export UV_HTTP_TIMEOUT=300
export UV_LINK_MODE=copy

cd "$OPENTALKING_HOME"
uv sync --extra dev --extra models --python 3.11
source .venv/bin/activate
export OPENTALKING_WAV2LIP_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models/wav2lip"
mkdir -p "$OPENTALKING_WAV2LIP_MODEL_ROOT"

hf download Pypa/wav2lip384 wav2lip384.pth --local-dir "$OPENTALKING_WAV2LIP_MODEL_ROOT"
hf download rippertnt/wav2lip s3fd.pth --local-dir "$OPENTALKING_WAV2LIP_MODEL_ROOT"
```

If Hugging Face is not reachable from the server, download the files on a connected machine and sync them to the same directory. Do not commit these model weights into the OpenTalking repository.

```bash title="Terminal"
export OPENTALKING_WAV2LIP_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models/wav2lip"
export OPENTALKING_WAV2LIP_DEVICE=cuda
export OPENTALKING_WAV2LIP_BATCH_SIZE=16
export OPENTALKING_WAV2LIP_MAX_LONG_EDGE=832
export OPENTALKING_WAV2LIP_FACE_DET_DEVICE=cpu
bash scripts/start_unified.sh --backend local --model wav2lip --api-port 8000 --web-port 5173
```

## Frontend Startup

`scripts/start_unified.sh` starts the WebUI as well as the OpenTalking API. To restart only the frontend while the API is already running on port `8000`, use a second terminal:

```bash title="Terminal"
cd "$OPENTALKING_HOME"
bash scripts/quickstart/start_frontend.sh --api-port 8000 --web-port 5173 --host 0.0.0.0
```

For a remote server, forward your local browser port to the server `5173`, then open `http://127.0.0.1:5173`.

Local Wav2Lip defaults to `easy_improved` post-processing. The frontend exposes `auto`, `basic`, `opentalking_improved`, and `easy_improved`. The backend also accepts `easy_enhanced` for API/env driven tests, but that mode requires GFPGAN to be installed and `OPENTALKING_WAV2LIP_GFPGAN_CHECKPOINT` to point to a checkpoint.
