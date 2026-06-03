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
