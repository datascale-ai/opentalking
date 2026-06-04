# QuickTalk with OmniRT

Use this path when QuickTalk should be hosted by an external OmniRT service and OpenTalking should connect to `/v1/audio2video/quicktalk`.

```bash title="Terminal"
export DIGITAL_HUMAN_HOME=/path/to/digital_human
export OPENTALKING_HOME="$DIGITAL_HUMAN_HOME/opentalking"
export OMNIRT_REPO="$DIGITAL_HUMAN_HOME/omnirt"
export OMNIRT_HOME="$OMNIRT_REPO/.omnirt"
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"

# Set mirrors first when package downloads are slow.
export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export UV_HTTP_TIMEOUT=300
export UV_LINK_MODE=copy

cd "$OMNIRT_REPO"
uv sync --extra server --python 3.11
```

Prepare `$OMNIRT_MODEL_ROOT/quicktalk/quicktalk.pth`, `repair.npy`, `chinese-hubert-large/`, and `auxiliary/models/buffalo_l/`.

If `scripts/quickstart/env` already sets `OMNIRT_MODEL_ROOT`, `OMNIRT_QUICKTALK_MODEL_ROOT`, or `OMNIRT_QUICKTALK_DEVICE`, the startup script reads those values first. Trust the `model root`, `device`, and `hubert device` lines printed by the startup log. To run with a different set of values, update that env file or set `OPENTALKING_QUICKSTART_ENV=/path/to/your-env`.

```bash title="Terminal"
cd "$OPENTALKING_HOME"
bash scripts/quickstart/start_omnirt_quicktalk.sh --device cuda:0 --port 9000
bash scripts/start_unified.sh \
  --backend omnirt \
  --model quicktalk \
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
