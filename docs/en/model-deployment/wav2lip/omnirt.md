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
source .venv/bin/activate
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
mkdir -p "$OMNIRT_MODEL_ROOT/wav2lip"

hf download Pypa/wav2lip384 wav2lip384.pth --local-dir "$OMNIRT_MODEL_ROOT/wav2lip"
hf download rippertnt/wav2lip s3fd.pth --local-dir "$OMNIRT_MODEL_ROOT/wav2lip"
```

If `scripts/quickstart/env` already sets `OMNIRT_MODEL_ROOT`, the startup script reads that value first. Trust the `models` line printed by the startup log. To run with a different value, update that env file or set `OPENTALKING_QUICKSTART_ENV=/path/to/your-env`.

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

## Frontend Startup

`start_unified.sh` starts the WebUI after the API. To restart only the frontend while the API is already running on port `8000`, use:

```bash title="Terminal"
cd "$OPENTALKING_HOME"
bash scripts/quickstart/start_frontend.sh --api-port 8000 --web-port 5173 --host 0.0.0.0
```

For a remote server, forward your local browser port to the server `5173`, then open `http://127.0.0.1:5173`.
