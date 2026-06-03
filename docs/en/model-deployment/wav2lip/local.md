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
mkdir -p models/wav2lip
uv pip install -U "huggingface_hub[cli]"
hf download Pypa/wav2lip384 wav2lip384.pth --local-dir models/wav2lip
hf download rippertnt/wav2lip s3fd.pth --local-dir models/wav2lip
```

```bash title="Terminal"
export OPENTALKING_WAV2LIP_MODEL_ROOT="$OPENTALKING_HOME/models/wav2lip"
export OPENTALKING_WAV2LIP_DEVICE=cuda
export OPENTALKING_WAV2LIP_BATCH_SIZE=16
export OPENTALKING_WAV2LIP_MAX_LONG_EDGE=832
export OPENTALKING_WAV2LIP_FACE_DET_DEVICE=cpu
bash scripts/start_unified.sh --backend local --model wav2lip --api-port 8000 --web-port 5173
```

Local Wav2Lip defaults to `easy_improved` post-processing. The frontend exposes `auto`, `basic`, `opentalking_improved`, and `easy_improved`. The backend also accepts `easy_enhanced` for API/env driven tests, but that mode requires GFPGAN to be installed and `OPENTALKING_WAV2LIP_GFPGAN_CHECKPOINT` to point to a checkpoint.
