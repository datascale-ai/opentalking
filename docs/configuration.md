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
