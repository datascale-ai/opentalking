# Wav2Lip with OmniRT

Use this path when Wav2Lip inference should run in a separate OmniRT service.

```bash title="Terminal"
export DIGITAL_HUMAN_HOME=/path/to/digital_human
export OPENTALKING_HOME="$DIGITAL_HUMAN_HOME/opentalking"
export OMNIRT_REPO="$DIGITAL_HUMAN_HOME/omnirt"
export OMNIRT_HOME="$OMNIRT_REPO/.omnirt"

# Set mirrors first when package downloads are slow.
export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export UV_HTTP_TIMEOUT=300
export UV_LINK_MODE=copy

cd "$OMNIRT_REPO"
uv sync --extra server --python 3.11
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
mkdir -p "$OMNIRT_MODEL_ROOT/wav2lip"
uv pip install -U "huggingface_hub[cli]"
hf download Pypa/wav2lip384 wav2lip384.pth --local-dir "$OMNIRT_MODEL_ROOT/wav2lip"
hf download rippertnt/wav2lip s3fd.pth --local-dir "$OMNIRT_MODEL_ROOT/wav2lip"
```

```bash title="Terminal"
cd "$OPENTALKING_HOME"
bash scripts/quickstart/start_omnirt_wav2lip.sh --device cuda --port 9000
bash scripts/start_unified.sh \
  --backend omnirt \
  --model wav2lip \
  --omnirt http://127.0.0.1:9000 \
  --api-port 8000 \
  --web-port 5173
```
