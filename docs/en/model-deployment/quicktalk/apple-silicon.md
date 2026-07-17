# QuickTalk on Apple Silicon

This page is for running QuickTalk locally on Apple Silicon macOS. It is intended for development, demos, and integration checks. For stable realtime 25fps output, use the Linux CUDA path in [QuickTalk Local Deployment](local.md) or run QuickTalk behind OmniRT.

## 1. Install Dependencies

```bash title="Terminal"
brew install python@3.11 node uv

# Optional. OpenTalking can fall back to imageio-ffmpeg when this is absent.
brew install ffmpeg
```

Clone OpenTalking and create the environment with the CPU/macOS extra:

```bash title="Terminal"
git clone https://github.com/datascale-ai/opentalking.git
cd opentalking

export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export UV_HTTP_TIMEOUT=300
export UV_LINK_MODE=copy

uv sync --extra dev --extra models --extra quicktalk-cpu --python 3.11
source .venv/bin/activate
```

Do not install `quicktalk-cuda` on Apple Silicon. `onnxruntime-gpu` does not provide a macOS arm64 wheel.

## 2. Download QuickTalk Assets

Download the QuickTalk weights and HuBERT files:

```bash title="Terminal"
export OPENTALKING_MODEL_ROOT="${OPENTALKING_MODEL_ROOT:-$DIGITAL_HUMAN_HOME/models}"
export OPENTALKING_QUICKTALK_ASSET_ROOT="${OPENTALKING_QUICKTALK_ASSET_ROOT:-$OPENTALKING_MODEL_ROOT/quicktalk}"
mkdir -p "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints"

hf download datascale-ai/quicktalk \
  --local-dir "$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints"
```

`datascale-ai/quicktalk` already includes QuickTalk, HuBERT, and InsightFace `buffalo_l`. After download, `$OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints/auxiliary/models/buffalo_l/` should exist.

The final layout should be:

```text
$OPENTALKING_QUICKTALK_ASSET_ROOT/
  checkpoints/
    quicktalk.pth
    repair.npy
    chinese-hubert-large/
      config.json
      preprocessor_config.json
      pytorch_model.bin
    auxiliary/models/buffalo_l/
      *.onnx
```

Check the required files:

```bash title="Terminal"
stat $OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints/quicktalk.pth
stat $OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints/repair.npy
stat $OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints/chinese-hubert-large/pytorch_model.bin
stat $OPENTALKING_QUICKTALK_ASSET_ROOT/checkpoints/auxiliary/models/buffalo_l/det_10g.onnx
```

## 3. Configure `.env`

Create `.env` if it does not exist:

```bash title="Terminal"
cp .env.example .env
```

Set these values:

```env title=".env"
OPENTALKING_DEFAULT_MODEL=quicktalk
OPENTALKING_FFMPEG_BIN=
OPENTALKING_QUICKTALK_BACKEND=local
OPENTALKING_QUICKTALK_ASSET_ROOT=$OPENTALKING_MODEL_ROOT/quicktalk
OPENTALKING_QUICKTALK_MODEL_BACKEND=auto
OPENTALKING_QUICKTALK_WORKER_CACHE=1

# Optional. If unset, OpenTalking selects mps when PyTorch MPS is available,
# then falls back to cpu.
OPENTALKING_QUICKTALK_DEVICE=mps

# Apple Silicon default. Keep 12 so each generated chunk has enough audio budget.
OPENTALKING_QUICKTALK_SLICE_LEN=12

# Optional for long text. This lowers output cadence from model-native 25fps
# to 14fps so MPS generation can stay closer to playback.
OPENTALKING_QUICKTALK_FPS=14
```

Leaving `OPENTALKING_FFMPEG_BIN=` empty lets OpenTalking find system `ffmpeg` first and fall back to `imageio-ffmpeg`.

## 4. Check the Environment

```bash title="Terminal"
python - <<'PY'
from pathlib import Path
import os
import torch
import onnxruntime as ort
from opentalking.models.quicktalk.runtime_v2 import ensure_ffmpeg

root = Path(os.environ["OPENTALKING_QUICKTALK_ASSET_ROOT"]) / "checkpoints"
for path in [
    root / "quicktalk.pth",
    root / "repair.npy",
    root / "chinese-hubert-large/pytorch_model.bin",
    root / "auxiliary/models/buffalo_l/det_10g.onnx",
]:
    print(path, path.exists())
print("mps:", torch.backends.mps.is_available())
print("onnxruntime providers:", ort.get_available_providers())
print("ffmpeg:", ensure_ffmpeg())
PY
```

Every printed file path should be `True`. `mps` should be `True` on a healthy Apple Silicon PyTorch install, though OpenTalking can fall back to CPU.

## 5. Start OpenTalking

```bash title="Terminal"
bash scripts/start_unified.sh \
  --backend local \
  --model quicktalk \
  --api-port 8210 \
  --web-port 5280
```

Open `http://127.0.0.1:5280`, choose a front-facing avatar such as the built-in `singer`, and select `quicktalk`. The first run builds the avatar cache; later runs reuse it.

## 6. Verify the Realtime Digital Human Path

```bash title="Terminal"
curl -s http://127.0.0.1:8210/health | python -m json.tool
curl -s http://127.0.0.1:8210/models | python -m json.tool
```

The QuickTalk model should report `connected: true` with reason `local_runtime`.

Create a session and send a short sentence:

```bash title="Terminal"
curl -s -X POST http://127.0.0.1:8210/sessions \
  -H 'Content-Type: application/json' \
  -d '{"avatar_id":"singer","model":"quicktalk","tts_provider":"edge"}' \
  | tee /tmp/opentalking-session.json | python -m json.tool

sid=$(python - <<'PY'
import json
print(json.load(open("/tmp/opentalking-session.json"))["session_id"])
PY
)

curl -s -X POST "http://127.0.0.1:8210/sessions/$sid/start" \
  -H 'Content-Type: application/json' \
  -d '{}' | python -m json.tool

curl -s -X POST "http://127.0.0.1:8210/sessions/$sid/speak" \
  -H 'Content-Type: application/json' \
  -d '{"text":"Please confirm in one sentence that QuickTalk is running locally on this Mac.","tts_provider":"edge"}' \
  | python -m json.tool
```

When the session state returns from `speaking` to `ready`, and the WebUI shows generated audio and video frames for the selected avatar, the local realtime digital human path is working.

## Performance Notes

Apple Silicon can run the local path, but it is not the recommended realtime production target. If long text stalls, try:

```env title=".env"
OPENTALKING_QUICKTALK_SLICE_LEN=12
OPENTALKING_QUICKTALK_FPS=14
OPENTALKING_QUICKTALK_MAX_LONG_EDGE=720
```

This trades motion FPS or image size for smoother playback. Use Linux CUDA or OmniRT when stable 25fps realtime output matters.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `onnxruntime-gpu` fails to install | Use `quicktalk-cpu`; do not install `quicktalk-cuda` on Apple Silicon. |
| `ffmpeg` is missing | Keep `OPENTALKING_FFMPEG_BIN=` empty, or run `brew install ffmpeg`. |
| MPS shows an SVD CPU fallback warning | This is a PyTorch MPS operator coverage limitation. It can affect speed but usually does not block execution. |
| First startup is slow | The first run loads HuBERT, QuickTalk, and the avatar face cache. Reusing the same avatar is faster. |
