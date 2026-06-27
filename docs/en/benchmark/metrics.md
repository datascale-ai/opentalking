# Metrics

| Metric | Meaning | Owner |
|--------|---------|-------|
| `session_create_ms` | Time from session creation request to API response. | OpenTalking |
| `asr_partial_latency_ms` | Delay from user speech to first partial transcript. | OpenTalking + STT provider |
| `llm_first_token_ms` | Delay from text request to first LLM token. | OpenTalking + LLM endpoint |
| `tts_first_pcm_ms` | Delay from sentence submission to first PCM/audio bytes. | OpenTalking + TTS provider |
| `avatar_first_frame_ms` | Delay from audio submission to first avatar video frame. | OpenTalking + synthesis backend |
| `render_fps` | Video generation throughput of the synthesis backend. | synthesis backend |
| `webrtc_first_frame_ms` | Time until the browser receives the first playable video frame. | OpenTalking + WebRTC |
| `av_drift_ms` | Offset between audio and video playback timelines. | OpenTalking |
| `queue_depth` | Queue depth in the Worker or external model service. | OpenTalking / backend |
| `steady_chunk_ms` | Steady-state chunk inference time. | synthesis backend |

## Boundaries

- First-response metrics must state their start and end points.
- `render_fps` describes the synthesis backend only; it is not the full user-perceived FPS.
- Multi-card, NPU, or remote model-service runs must also record topology and queue state.
