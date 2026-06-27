# FlashHead

## Model Introduction

FlashHead is integrated in OpenTalking primarily through an external generative service. The adapter writes audio chunks as WAV, calls the FlashHead HTTP generation endpoint, then decodes the returned video fragments back into frames for the existing WebRTC playback path.

## Suitable Scenarios

- Higher visual quality with fragment-style generation latency.
- HTTP service integration instead of WebSocket streaming.
- Saving generation results as video clips.

## Recommended Runtime Backend

Use a standalone FlashHead HTTP service and connect it through the `direct_ws` / adapter path. If OmniRT later provides a unified FlashHead audio2video endpoint, the backend can be switched there.

## Hardware Requirements

Hardware requirements are driven mainly by the FlashHead service. OpenTalking handles audio upload, result retrieval, and video decoding, so the heavy model should stay outside the API process.

## Weights and Asset Requirements

Weights live on the FlashHead service side. OpenTalking needs:

- A reachable FlashHead base URL.
- A shared directory or downloadable output URL.
- An avatar reference image.
- Input audio chunks.

## Avatar Requirements

Use a clear front-facing reference image. The FlashHead HTTP client writes the reference image into the shared directory and passes it to the model service in the generation request.

## OpenTalking Configuration

```bash
export OPENTALKING_FLASHHEAD_BACKEND=direct_ws
export OPENTALKING_FLASHHEAD_BASE_URL=http://127.0.0.1:8766
```

## Start and Verify

1. Start the FlashHead HTTP service.
2. Configure `OPENTALKING_FLASHHEAD_BASE_URL`.
3. Start OpenTalking.
4. In the WebUI, select the `flashhead` model and create a session.

## Common Issues

### OpenTalking receives a video but cannot read it

Configure `OPENTALKING_FLASHHEAD_OUTPUT_LOCAL_DIR` / `OPENTALKING_FLASHHEAD_OUTPUT_REMOTE_DIR`, or provide `OPENTALKING_FLASHHEAD_OUTPUT_BASE_URL`.

### Latency is higher than streaming models

FlashHead currently uses fragment-style HTTP generation. Lower `frame_num`, tune the preset, or deploy stronger hardware; it is fundamentally different from frame-by-frame streaming WebSocket models.
