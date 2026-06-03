# QuickTalk Local Deployment

Use this path when OpenTalking should load the QuickTalk adapter in-process instead of introducing OmniRT first.

```bash title="Terminal"
export DIGITAL_HUMAN_HOME=/path/to/digital_human
export OPENTALKING_HOME="$DIGITAL_HUMAN_HOME/opentalking"

# Set mirrors first when package downloads are slow.
export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export UV_HTTP_TIMEOUT=300
export UV_LINK_MODE=copy

cd "$OPENTALKING_HOME"
uv sync --extra dev --extra models --extra quicktalk-cuda --python 3.11
source .venv/bin/activate
```

Prepare a QuickTalk local asset root that contains `checkpoints/quicktalk.pth` or `checkpoints/256.onnx`, `checkpoints/repair.npy`, HuBERT files, and InsightFace assets. Then start:

```bash title="Terminal"
export OPENTALKING_QUICKTALK_BACKEND=local
export OPENTALKING_QUICKTALK_ASSET_ROOT=/absolute/path/to/opentalking/models/quicktalk
export OPENTALKING_QUICKTALK_WORKER_CACHE=1
export OPENTALKING_TORCH_DEVICE=cuda:0
cd "$OPENTALKING_HOME"
bash scripts/start_unified.sh --backend local --model quicktalk --api-port 8000 --web-port 5173
```

Verify:

```bash title="Terminal"
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="quicktalk")'
```
