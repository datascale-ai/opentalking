# Talking-head Models

This page is the selection overview for talking-head backends. OpenTalking owns session
orchestration, TTS, events, and WebRTC; model weight loading, GPU/NPU scheduling, and
inference throughput belong to the selected backend.

## Recommended Paths

| Model | Backend | Best for | Evidence level | Details |
|-------|---------|----------|----------------|---------|
| `mock` | `mock` | First run, CI, API/WebRTC debugging | Built in, verified | [Mock](mock.md) |
| `wav2lip` | `local` / `omnirt` | First real lip-sync model | Local adapter is built in; OmniRT path verified | [Local](deployment/wav2lip-local.md) / [OmniRT](deployment/wav2lip-omnirt.md) |
| `musetalk` | `local` / `omnirt` / `direct_ws` | MuseTalk quality with either in-process startup or an external service | Local adapter is built in; OmniRT/direct_ws paths documented | [Local](deployment/musetalk-local.md) / [OmniRT](deployment/musetalk-omnirt.md) |
| `quicktalk` | `local` / `omnirt` | Local realtime adapter and service deployment reference | Local is built in; OmniRT path documented | [Local](deployment/quicktalk-local.md) / [Apple Silicon](deployment/quicktalk-apple-silicon.md) / [OmniRT](deployment/quicktalk-omnirt.md) |
| `fasterliveportrait` | `omnirt` | Single-GPU realtime audio-driven portrait with pasteback | Documented | [FasterLivePortrait](fasterliveportrait.md) |
| `flashtalk` | `omnirt` | High-quality private GPU/NPU deployment | OmniRT/Ascend path verified | [FlashTalk](flashtalk.md) |
| `flashhead` | `direct_ws` | Existing standalone FlashHead service | Documented | [FlashHead](flashhead.md) |

## Backend Behavior

| Backend | What OpenTalking expects | Typical models |
|---------|--------------------------|----------------|
| `mock` | No external runtime; always available. | `mock` |
| `local` | Adapter can be imported in-process and dependencies are satisfied. | `wav2lip`, `quicktalk`, `musetalk` |
| `direct_ws` | The model service exposes its own WebSocket URL. | `flashhead`, custom single-model services |
| `omnirt` | OmniRT exposes `/v1/audio2video/{model}`. | `wav2lip`, `musetalk`, `fasterliveportrait`, `flashtalk` |

## Common Setup

```bash title="Terminal"
export DIGITAL_HUMAN_HOME="$HOME/digital-human"
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
export OPENTALKING_HOME="${OPENTALKING_HOME:-$DIGITAL_HUMAN_HOME/opentalking}"
export OMNIRT_HOME="${OMNIRT_HOME:-$DIGITAL_HUMAN_HOME/omnirt}"
export FASTERLIVEPORTRAIT_HOME="${FASTERLIVEPORTRAIT_HOME:-$DIGITAL_HUMAN_HOME/FasterLivePortrait}"

mkdir -p "$DIGITAL_HUMAN_HOME" "$OMNIRT_MODEL_ROOT"
cd "$DIGITAL_HUMAN_HOME"
```

Recommended layout:

```text
$DIGITAL_HUMAN_HOME/
├── opentalking/
├── omnirt/                  # Optional, only for backend: omnirt
├── models/
│   ├── wav2lip/
│   ├── SoulX-FlashTalk-14B/
│   ├── chinese-wav2vec2-base/
│   ├── quicktalk/
│   └── FasterLivePortrait/
├── logs/
└── run/
```

Download tools:

```bash title="Terminal"
uv pip install -U "huggingface_hub[cli]" modelscope
```

Common model sources:

- [ModelScope](https://modelscope.cn/models)
- [Modelers](https://modelers.cn/models)
- [Hugging Face](https://huggingface.co/models)

## Common Startup Combinations

The commands below only use existing repository entrypoints. No additional scripts are
required.

### OpenTalking local: QuickTalk and Wav2Lip in one frontend

In the default configuration, `wav2lip` already uses the `local` backend. The command
below only overrides `quicktalk` to `local`, so the same frontend can select both
`quicktalk` and `wav2lip`:

```bash title="Terminal"
cd "$OPENTALKING_HOME"
uv sync --extra dev --extra models --python 3.11

export OPENTALKING_TORCH_DEVICE=cuda:0
export OPENTALKING_QUICKTALK_ASSET_ROOT="$OPENTALKING_HOME/models/quicktalk"
export OPENTALKING_QUICKTALK_WORKER_CACHE=1
export OPENTALKING_WAV2LIP_MODEL_ROOT="$OPENTALKING_HOME/models/wav2lip"
export OPENTALKING_WAV2LIP_DEVICE=cuda
export OPENTALKING_WAV2LIP_BATCH_SIZE=16
export OPENTALKING_WAV2LIP_MAX_LONG_EDGE=832
export OPENTALKING_WAV2LIP_FACE_DET_DEVICE=cpu

bash scripts/start_unified.sh --backend local --model quicktalk --api-port 8210 --web-port 5280
```

### OmniRT: QuickTalk and Wav2Lip behind one endpoint

OpenTalking configures a single `OMNIRT_ENDPOINT`. To use both `quicktalk` and
`wav2lip` through OmniRT from the same frontend, enable both runtimes in the same
OmniRT process:

```bash title="Terminal"
cd "$OMNIRT_HOME"
uv sync --extra server --extra wav2lip-cuda --extra quicktalk-cuda --python 3.11
source .venv/bin/activate

export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
export OMNIRT_ALLOWED_FRAME_ROOTS="$OPENTALKING_HOME/examples/avatars"

export OMNIRT_WAV2LIP_RUNTIME=1
export OMNIRT_WAV2LIP_MODELS_DIR="$OMNIRT_MODEL_ROOT"
export OMNIRT_WAV2LIP_CHECKPOINT="$OMNIRT_MODEL_ROOT/wav2lip/wav2lip384.pth"
export OMNIRT_WAV2LIP_DEVICE=cuda
export OMNIRT_WAV2LIP_FACE_DET_DEVICE=cpu
export OMNIRT_WAV2LIP_BATCH_SIZE=16
export OMNIRT_WAV2LIP_MAX_LONG_EDGE=832
export OMNIRT_WAV2LIP_PRELOAD=1

export OMNIRT_QUICKTALK_RUNTIME=1
export OMNIRT_QUICKTALK_MODEL_ROOT="$OMNIRT_MODEL_ROOT/quicktalk"
export OMNIRT_QUICKTALK_CHECKPOINT="$OMNIRT_MODEL_ROOT/quicktalk/checkpoints/quicktalk.pth"
export OMNIRT_QUICKTALK_DEVICE=cuda:0
export OMNIRT_QUICKTALK_HUBERT_DEVICE=cuda:0
export OMNIRT_QUICKTALK_MAX_LONG_EDGE=900
export OMNIRT_QUICKTALK_MAX_TEMPLATE_SECONDS=1

omnirt serve-avatar-ws --host 0.0.0.0 --port 9000 --backend cuda
```

Then start OpenTalking from another terminal. In the default configuration,
`quicktalk` already uses the `omnirt` backend. The command below only overrides
`wav2lip` to `omnirt`:

```bash title="Terminal"
cd "$OPENTALKING_HOME"
bash scripts/start_unified.sh \
  --backend omnirt \
  --model wav2lip \
  --omnirt http://127.0.0.1:9000 \
  --api-port 8310 \
  --web-port 5380
```

## Common Verification

```bash title="Terminal"
curl -fsS http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/models | jq
```

For OmniRT-backed models:

```bash title="Terminal"
curl -fsS http://127.0.0.1:9000/v1/audio2video/models | jq
```

## Common Status Values

| Status | Meaning | Action |
|--------|---------|--------|
| `connected=true` | The backend is usable for sessions. | Choose a matching avatar and model in the browser. |
| `reason=not_configured` | Endpoint or WebSocket URL is empty. | Configure `OMNIRT_ENDPOINT` or the model-specific `WS_URL`. |
| `reason=omnirt_unavailable` | OmniRT reachability or model registration issue. | Check OmniRT `/v1/audio2video/models`, model list, and logs. |
| `reason=local_adapter_missing` | Configured as `local`, but no local adapter is registered. | Switch backend or add a local adapter. |
