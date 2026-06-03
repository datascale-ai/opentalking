# Talking-Head Model Deployment

This page is the selection overview for talking-head backends. OpenTalking owns session
orchestration, TTS, events, and WebRTC; model weight loading, GPU/NPU scheduling, and
inference throughput belong to the selected backend.

## Recommended Paths

| Model | Backend | Best for | Evidence level | Details |
|-------|---------|----------|----------------|---------|
| `mock` | `mock` | First run, CI, API/WebRTC debugging | Built in, verified | [Mock](../mock.md) |
| `wav2lip` | `local` / `omnirt` | First real lip-sync model | Local adapter is built in; OmniRT path verified | [Local](../wav2lip/local.md) / [OmniRT](../wav2lip/omnirt.md) |
| `musetalk` | `local` / `omnirt` / `direct_ws` | MuseTalk quality with either in-process startup or an external service | Local adapter is built in; OmniRT/direct_ws paths documented | [Local](../musetalk/local.md) / [OmniRT](../musetalk/omnirt.md) |
| `quicktalk` | `local` / `omnirt` | Local realtime adapter or OmniRT-hosted deployment | Local path is built in; OmniRT path is integrated | [Local](../quicktalk/local.md) / [OmniRT](../quicktalk/omnirt.md) |
| `fasterliveportrait` | `omnirt` | Single-GPU realtime audio-driven portrait with pasteback | Documented | [FasterLivePortrait](../fasterliveportrait.md) |
| `flashtalk` | `omnirt` | High-quality private GPU/NPU deployment | OmniRT/Ascend path verified | [FlashTalk](../flashtalk.md) |
| `flashhead` | `direct_ws` | Existing standalone FlashHead service | Documented | [FlashHead](../flashhead.md) |

## Backend Behavior

| Backend | What OpenTalking expects | Typical models |
|---------|--------------------------|----------------|
| `mock` | No external runtime; always available. | `mock` |
| `local` | Adapter can be imported in-process and dependencies are satisfied. | `wav2lip`, `quicktalk`, `musetalk` |
| `direct_ws` | The model service exposes its own WebSocket URL. | `flashhead`, custom single-model services |
| `omnirt` | OmniRT exposes `/v1/audio2video/{model}`. | `wav2lip`, `musetalk`, `quicktalk`, `fasterliveportrait`, `flashtalk` |

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
