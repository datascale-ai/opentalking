# Configuration

- Base runtime defaults: `configs/default.yaml`
- FlashTalk inference defaults: `configs/flashtalk.yaml`
- Environment variable overrides: `.env.example`

## QuickTalk

QuickTalk is a local realtime talking-head adapter. Use it by selecting
`model=quicktalk` with an avatar whose `manifest.json` has
`model_type=quicktalk`.

Minimal environment:

```bash
OPENTALKING_TORCH_DEVICE=cuda:0
OPENTALKING_QUICKTALK_ASSET_ROOT=/path/to/quicktalk/assets
OPENTALKING_QUICKTALK_TEMPLATE_VIDEO=/path/to/template.mp4
```

Common tuning knobs:

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENTALKING_QUICKTALK_WORKER_CACHE` | `1` | Reuse built Workers for the same avatar and adapter settings. |
| `OPENTALKING_PREWARM_AVATARS` | empty | Comma-separated avatar IDs to warm at unified startup. |
| `OPENTALKING_QUICKTALK_HUBERT_DEVICE` | empty | Optional separate device for audio feature extraction. |
| `OPENTALKING_QUICKTALK_RENDER_CHUNK_MS` | `500` | TTS/render chunk size for QuickTalk sessions. |
| `OPENTALKING_QUICKTALK_PREFETCH` | `1` | Prepare the next render chunk while current frames are emitted. |
| `OPENTALKING_QUICKTALK_AUDIO_DELAY_MS` | `0` | Optional audio delay for deployment-specific A/V alignment. |
| `OPENTALKING_QUICKTALK_IDLE_CACHE_FRAMES` | `1` | Number of idle frames cached per session. |
| `OPENTALKING_QUICKTALK_IDLE_FRAME_INDEX` | `0` | Still frame used for idle output when no range is configured. |
| `OPENTALKING_QUICKTALK_IDLE_FRAME_RANGE` | empty | Optional idle loop range, for example `12:18`. |

## FlashHead

FlashHead uses OmniRT's realtime avatar WebSocket endpoint:
`OPENTALKING_FLASHHEAD_WS_URL=ws://<omnirt-host>:8766/v1/avatar/realtime`.

The same OmniRT server also exposes HTTP `/v1/generate` at
`OPENTALKING_FLASHHEAD_BASE_URL=http://<omnirt-host>:8766`; the HTTP client is kept
as a fallback for offline artifact workflows. HTTP fallback writes each audio
chunk to `OPENTALKING_FLASHHEAD_SHARED_LOCAL_DIR` and sends the corresponding
path under `OPENTALKING_FLASHHEAD_SHARED_REMOTE_DIR` to the OmniRT host.
