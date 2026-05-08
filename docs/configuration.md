# Configuration

- Base runtime defaults: `configs/default.yaml`
- FlashTalk inference defaults: `configs/flashtalk.yaml`
- Environment variable overrides: `.env.example`

## FlashHead

FlashHead uses OmniRT's realtime avatar WebSocket endpoint by default:
`OPENTALKING_FLASHHEAD_WS_URL=ws://8.92.7.195:8766/v1/avatar/realtime`.

The same OmniRT server also exposes HTTP `/v1/generate` at
`OPENTALKING_FLASHHEAD_BASE_URL=http://8.92.7.195:8766`; the HTTP client is kept
as a fallback for offline artifact workflows. HTTP fallback writes each audio
chunk to `OPENTALKING_FLASHHEAD_SHARED_LOCAL_DIR` and sends the corresponding
path under `OPENTALKING_FLASHHEAD_SHARED_REMOTE_DIR` to the 195 machine.

## QuickTalk

QuickTalk is a local realtime talking-head adapter. Enable it by selecting a
QuickTalk Avatar (`model_type=quicktalk`) and setting the default model when
needed:

```bash
OPENTALKING_DEFAULT_MODEL=quicktalk
OPENTALKING_TORCH_DEVICE=cuda:0
```

Avatar manifests should provide the model asset directory and template video in
metadata. Environment variables can override those paths for local deployment:

```bash
OPENTALKING_QUICKTALK_ASSET_ROOT=/path/to/quicktalk/assets
OPENTALKING_QUICKTALK_TEMPLATE_VIDEO=/path/to/template.mp4
OPENTALKING_QUICKTALK_FACE_CACHE_DIR=/path/to/.face_cache_quicktalk
```

Runtime tuning:

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENTALKING_QUICKTALK_WORKER_CACHE` | `1` | Reuse built Workers for the same Avatar and adapter settings. |
| `OPENTALKING_PREWARM_AVATARS` | empty | Comma-separated Avatar IDs to warm at unified startup. |
| `OPENTALKING_QUICKTALK_HUBERT_DEVICE` | empty | Optional separate device for audio feature extraction. |
| `OPENTALKING_QUICKTALK_RENDER_CHUNK_MS` | `500` | TTS/render chunk size for QuickTalk sessions. |
| `OPENTALKING_QUICKTALK_PREFETCH` | `1` | Prepare the next render chunk while current frames are emitted. |
| `OPENTALKING_QUICKTALK_AUDIO_DELAY_MS` | `0` | Optional audio delay for deployment-specific A/V alignment. |
| `OPENTALKING_QUICKTALK_IDLE_CACHE_FRAMES` | `1` | Number of idle frames cached per session. |
| `OPENTALKING_QUICKTALK_IDLE_FRAME_INDEX` | `0` | Still frame used for idle output when no range is configured. |
| `OPENTALKING_QUICKTALK_IDLE_FRAME_RANGE` | empty | Optional idle loop range, for example `12:18`. |

For offline measurement, use:

```bash
opentalking-quicktalk-bench \
  --asset-root /path/to/quicktalk/assets \
  --template-video /path/to/template.mp4 \
  --audio /path/to/input.wav \
  --output /path/to/output.mp4 \
  --device cuda:0
```
