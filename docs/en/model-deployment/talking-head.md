# Talking-Head Models

This page turns the talking-head backend abstraction into runnable model paths.
It covers where weights belong, how to download them from international and
China-friendly sources, how to start each backend, and how to verify that
OpenTalking can create a session.

OpenTalking is the orchestration layer. Model execution is selected per model:

| Model | Backend status | Recommended first path | Weight requirement |
|-------|----------------|------------------------|--------------------|
| `mock` | `mock` | Built-in self-test | None |
| `wav2lip` | `omnirt` for compatibility; local-first target | Lightweight local or direct backend; OmniRT is the current runnable compatibility path | Wav2Lip + S3FD checkpoints |
| `musetalk` | `omnirt` | OmniRT or a future local adapter | MuseTalk 1.5 weights |
| `quicktalk` | `local` | Local adapter | QuickTalk `hdModule` asset bundle |
| `flashtalk` | `omnirt` | OmniRT on CUDA or Ascend | SoulX-FlashTalk-14B + wav2vec2 |
| `flashhead` | `direct_ws` | External FlashHead WebSocket service | Managed by the FlashHead service |

## Shared layout

Use one parent directory for OpenTalking, optional backend services, models, logs, and
runtime files. OmniRT is needed only for models configured with `backend: omnirt`.

```bash title="terminal"
export DIGITAL_HUMAN_HOME="$HOME/digital-human"
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"

mkdir -p "$DIGITAL_HUMAN_HOME" "$OMNIRT_MODEL_ROOT"
cd "$DIGITAL_HUMAN_HOME"
```

Expected layout:

```text
$DIGITAL_HUMAN_HOME/
├── opentalking/
├── omnirt/                  # optional, for backend: omnirt
├── models/
│   ├── wav2lip/
│   ├── SoulX-FlashTalk-14B/
│   ├── chinese-wav2vec2-base/
│   └── quicktalk/
├── logs/
└── run/
```

Install OpenTalking first:

```bash title="terminal"
git clone https://github.com/datascale-ai/opentalking.git
cd opentalking
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Set at least the LLM/STT credentials in `.env`:

```env title=".env"
OPENTALKING_LLM_API_KEY=<dashscope-api-key>
DASHSCOPE_API_KEY=<dashscope-api-key>
```

## Download tools

International environments can use Hugging Face directly:

```bash title="terminal"
pip install -U "huggingface_hub[cli]"
hf auth login  # optional, required for gated/private models
```

China-friendly environments can use ModelScope when the model is mirrored there:

```bash title="terminal"
pip install -U modelscope
modelscope login  # optional
```

ModelScope examples:

```bash title="terminal"
# Snapshot-style download.
modelscope download --model <namespace>/<model> --local_dir "$OMNIRT_MODEL_ROOT/<target>"

# Python fallback when the CLI version differs.
python - <<'PY'
from modelscope.hub.snapshot_download import snapshot_download
snapshot_download("<namespace>/<model>", local_dir="<target-dir>")
PY
```

MagicLego/Modelers mirrors are also useful in China when a community or vendor mirror
exists. Use the model page or Git/LFS instructions provided by that page, and keep the
same target directory names used below. Start from:

- [ModelScope model hub](https://modelscope.cn/models)
- [Modelers model hub](https://modelers.cn/models)
- [Hugging Face model hub](https://huggingface.co/models)

## Mock

`mock` is the fastest end-to-end path. It exercises the API, frontend, LLM, STT, TTS,
events, and WebRTC without model weights.

```bash title="terminal"
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_mock.sh
```

Open <http://127.0.0.1:5173>, select `demo-avatar`, then select `mock`.

Verify:

```bash title="terminal"
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="mock")'
```

Expected status:

```json
{"id":"mock","backend":"mock","connected":true,"reason":"local_self_test"}
```

## Wav2Lip

Wav2Lip is the recommended first real model because it is lightweight and easy to
debug. The product default should be local or a single-model direct backend, not a
mandatory OmniRT dependency. The current release keeps `backend: omnirt` as a
compatibility default because the bundled local Wav2Lip adapter is not complete yet;
the steps below are the runnable compatibility path.

### 1. Download weights

Primary Hugging Face sources:

- [Pypa/wav2lip384](https://huggingface.co/Pypa/wav2lip384)
- [rippertnt/wav2lip](https://huggingface.co/rippertnt/wav2lip)

```bash title="terminal"
mkdir -p "$OMNIRT_MODEL_ROOT/wav2lip"

hf download Pypa/wav2lip384 \
  wav2lip384.pth \
  --local-dir "$OMNIRT_MODEL_ROOT/wav2lip"

hf download rippertnt/wav2lip \
  s3fd.pth \
  --local-dir "$OMNIRT_MODEL_ROOT/wav2lip"
```

China-friendly options:

- Search [ModelScope for wav2lip384](https://modelscope.cn/models?name=wav2lip384)
- Search [ModelScope for s3fd wav2lip](https://modelscope.cn/models?name=s3fd%20wav2lip)
- Search [Modelers for wav2lip384](https://modelers.cn/models?name=wav2lip384)

Keep the final files in:

```text
$OMNIRT_MODEL_ROOT/wav2lip/wav2lip384.pth
$OMNIRT_MODEL_ROOT/wav2lip/s3fd.pth
```

### 2. Choose the backend

Recommended target deployment:

```yaml title="configs/default.yaml"
models:
  wav2lip:
    backend: local      # recommended once a local adapter is installed
```

Current runnable compatibility path:

```yaml title="configs/default.yaml"
models:
  wav2lip:
    backend: omnirt
```

If you set `OPENTALKING_WAV2LIP_BACKEND=local` before installing a local adapter,
`/models` intentionally reports `connected=false` with `reason=local_adapter_missing`.
This is expected and prevents a silent fallback to OmniRT.

### 3. Prepare OmniRT for the compatibility path

```bash title="terminal"
cd "$DIGITAL_HUMAN_HOME"
git clone https://github.com/datascale-ai/omnirt.git
cd omnirt
uv sync --extra server
```

### 4. Start Wav2Lip through OmniRT

CUDA:

```bash title="terminal"
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_omnirt_wav2lip.sh --device cuda
```

Ascend:

```bash title="terminal"
source /usr/local/Ascend/ascend-toolkit/set_env.sh
bash scripts/quickstart/start_omnirt_wav2lip.sh --device npu
```

### 5. Start OpenTalking

```bash title="terminal"
bash scripts/quickstart/start_all.sh --omnirt http://127.0.0.1:9000
```

Verify:

```bash title="terminal"
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="wav2lip")'
```

Expected when OmniRT reports Wav2Lip:

```json
{"id":"wav2lip","backend":"omnirt","connected":true,"reason":"omnirt"}
```

Then select a Wav2Lip avatar such as `singer`, `office-woman`, or `laozi`.

## MuseTalk 1.5

MuseTalk is configured as a pluggable model, but this repository currently provides
the backend framework rather than a bundled local MuseTalk runtime. Use one of these
paths:

- `backend: omnirt` when OmniRT serves `musetalk` through `/v1/audio2video/musetalk`.
- `backend: direct_ws` when you run a standalone MuseTalk-compatible WebSocket service.
- `backend: local` only after adding a local adapter under `opentalking/models/musetalk/`.

Primary upstream sources:

- [TMElyralab/MuseTalk](https://github.com/TMElyralab/MuseTalk)
- [MuseTalk 1.5 on Hugging Face](https://huggingface.co/TMElyralab/MuseTalk)
- Search [ModelScope for MuseTalk](https://modelscope.cn/models?name=MuseTalk)
- Search [Modelers for MuseTalk](https://modelers.cn/models?name=MuseTalk)

Example OmniRT configuration:

```yaml title="configs/default.yaml"
models:
  musetalk:
    backend: omnirt
```

Start OpenTalking against an OmniRT instance that already serves MuseTalk:

```bash title="terminal"
bash scripts/quickstart/start_all.sh --omnirt http://127.0.0.1:9000
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="musetalk")'
```

If you intentionally test a local adapter before implementing it:

```bash title="terminal"
OPENTALKING_MUSETALK_BACKEND=local bash scripts/quickstart/start_all.sh
```

Expected failure mode:

```json
{"id":"musetalk","backend":"local","connected":false,"reason":"local_adapter_missing"}
```

## QuickTalk

QuickTalk is the reference local adapter. It does not use OmniRT. The adapter imports
from `opentalking/models/quicktalk/` and loads a QuickTalk asset bundle at runtime.

Required asset shape:

```text
$OMNIRT_MODEL_ROOT/quicktalk/hdModule/
└── checkpoints/
    ├── 256.onnx
    ├── repair.npy
    ├── chinese-hubert-large/
    └── auxiliary_min/ or auxiliary/
```

Avatar metadata must point to both the QuickTalk asset root and a template video:

```json title="examples/avatars/quicktalk-demo/manifest.json"
{
  "id": "quicktalk-demo",
  "name": "QuickTalk Demo",
  "model_type": "quicktalk",
  "fps": 25,
  "sample_rate": 16000,
  "width": 512,
  "height": 512,
  "metadata": {
    "asset_root": "/absolute/path/to/models/quicktalk/hdModule",
    "template_video": "/absolute/path/to/template.mp4"
  }
}
```

Runtime environment:

```env title=".env"
OPENTALKING_QUICKTALK_ASSET_ROOT=/absolute/path/to/models/quicktalk/hdModule
OPENTALKING_QUICKTALK_TEMPLATE_VIDEO=/absolute/path/to/template.mp4
OPENTALKING_QUICKTALK_WORKER_CACHE=1
OPENTALKING_TORCH_DEVICE=cuda:0
```

Start:

```bash title="terminal"
OPENTALKING_QUICKTALK_BACKEND=local bash scripts/quickstart/start_all.sh
```

Verify:

```bash title="terminal"
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="quicktalk")'
```

Expected:

```json
{"id":"quicktalk","backend":"local","connected":true,"reason":"local_runtime"}
```

## FlashTalk

FlashTalk is the high-quality path. It is heavier than Wav2Lip and is best deployed
through OmniRT on a dedicated GPU/NPU host.

### 1. Download weights

Primary Hugging Face sources:

- [Soul-AILab/SoulX-FlashTalk-14B](https://huggingface.co/Soul-AILab/SoulX-FlashTalk-14B)
- [TencentGameMate/chinese-wav2vec2-base](https://huggingface.co/TencentGameMate/chinese-wav2vec2-base)

```bash title="terminal"
hf download Soul-AILab/SoulX-FlashTalk-14B \
  --local-dir "$OMNIRT_MODEL_ROOT/SoulX-FlashTalk-14B"

hf download TencentGameMate/chinese-wav2vec2-base \
  --local-dir "$OMNIRT_MODEL_ROOT/chinese-wav2vec2-base"
```

China-friendly options:

- Search [ModelScope for SoulX-FlashTalk-14B](https://modelscope.cn/models?name=SoulX-FlashTalk-14B)
- Search [ModelScope for chinese-wav2vec2-base](https://modelscope.cn/models?name=chinese-wav2vec2-base)
- Search [Modelers for SoulX-FlashTalk-14B](https://modelers.cn/models?name=SoulX-FlashTalk-14B)

Optional source checkout used by the CUDA helper:

```bash title="terminal"
git clone https://github.com/Soul-AILab/SoulX-FlashTalk.git \
  "$OMNIRT_MODEL_ROOT/SoulX-FlashTalk"
```

### 2. Start FlashTalk through OmniRT

CUDA single process:

```bash title="terminal"
cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/quickstart/start_omnirt_flashtalk.sh --device cuda --nproc 1
```

Ascend multi-process:

```bash title="terminal"
source /usr/local/Ascend/ascend-toolkit/set_env.sh
bash scripts/quickstart/start_omnirt_flashtalk.sh --device npu --nproc 8
```

The helper starts the FlashTalk worker service, points OmniRT at it, and exposes
OpenTalking-compatible audio2video routes on port `9000`.

### 3. Start OpenTalking

```bash title="terminal"
bash scripts/quickstart/start_all.sh --omnirt http://127.0.0.1:9000
```

Verify:

```bash title="terminal"
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="flashtalk")'
```

Expected:

```json
{"id":"flashtalk","backend":"omnirt","connected":true,"reason":"omnirt"}
```

Legacy direct WebSocket fallback remains available for existing deployments:

```env title=".env"
OPENTALKING_FLASHTALK_WS_URL=ws://127.0.0.1:8765
```

Use the explicit `direct_ws` backend for new single-model services:

```yaml title="configs/default.yaml"
models:
  flashtalk:
    backend: direct_ws
    ws_url: ws://127.0.0.1:8765
```

## FlashHead

FlashHead uses a model-specific WebSocket protocol, so OpenTalking treats it as
`backend: direct_ws`. Start the FlashHead service separately, then point OpenTalking
at its realtime endpoint.

Upstream/project links:

- Search [Hugging Face for SoulX FlashHead](https://huggingface.co/models?search=SoulX%20FlashHead)
- Search [ModelScope for FlashHead](https://modelscope.cn/models?name=FlashHead)
- Search [Modelers for FlashHead](https://modelers.cn/models?name=FlashHead)

OpenTalking configuration:

```env title=".env"
OPENTALKING_FLASHHEAD_WS_URL=ws://<flashhead-host>:8766/v1/avatar/realtime
OPENTALKING_FLASHHEAD_BASE_URL=http://<flashhead-host>:8766
OPENTALKING_FLASHHEAD_MODEL=soulx-flashhead-1.3b
```

YAML:

```yaml title="configs/default.yaml"
models:
  flashhead:
    backend: direct_ws
```

Start OpenTalking:

```bash title="terminal"
bash scripts/quickstart/start_all.sh
```

Verify:

```bash title="terminal"
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="flashhead")'
```

Expected when the WebSocket URL is configured:

```json
{"id":"flashhead","backend":"direct_ws","connected":true,"reason":"direct_ws"}
```

Use an avatar whose manifest has `model_type: "flashhead"`, such as `anchor`.

## Common verification

Check OpenTalking:

```bash title="terminal"
curl -fsS http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/models | jq
```

Check OmniRT-backed models:

```bash title="terminal"
curl -fsS http://127.0.0.1:9000/v1/audio2video/models | jq
```

Start the UI:

```bash title="terminal"
bash scripts/quickstart/start_all.sh --omnirt http://127.0.0.1:9000
open http://127.0.0.1:5173
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `reason=not_configured` | Required endpoint or WebSocket URL is empty. | Set `OMNIRT_ENDPOINT` for `omnirt` models, or `OPENTALKING_<MODEL>_WS_URL` for `direct_ws`. |
| `reason=omnirt_unavailable` | OmniRT is reachable but does not report the selected model. | Check `curl http://127.0.0.1:9000/v1/audio2video/models`, model root paths, and OmniRT logs. |
| `reason=local_adapter_missing` | The model is configured as `local` but no adapter is registered. | Add `opentalking/models/<name>/adapter.py` and register it, or switch backend to `omnirt`/`direct_ws`. |
| Wav2Lip helper reports missing checkpoints | Files are not under `$OMNIRT_MODEL_ROOT/wav2lip/`. | Move or re-download `wav2lip384.pth` and `s3fd.pth`. |
| FlashTalk helper reports missing directories | FlashTalk weights or wav2vec2 weights are missing. | Ensure `$OMNIRT_MODEL_ROOT/SoulX-FlashTalk-14B/` and `$OMNIRT_MODEL_ROOT/chinese-wav2vec2-base/` exist. |
| Browser shows model but session creation fails | Avatar `model_type` does not match the selected model. | Select an avatar whose manifest matches the model, or prepare a matching avatar bundle. |
