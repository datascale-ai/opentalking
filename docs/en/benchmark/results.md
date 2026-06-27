# Results and Baselines

This page records only currently citable public baselines. New results should keep full
context instead of reporting FPS alone.

## Current Reference Data

| Path | Hardware / State | Data | Notes |
|------|------------------|------|-------|
| Wav2Lip quickstart | NVIDIA 3090 path | `singer` example: about `28` frames / `0.83-0.85s`, about `33 FPS` | README quickstart configuration record; useful as a lightweight-model reference. |
| FlashTalk via OmniRT | Ascend 910B2 x8, hot full-audio | `937` frames / `37.377s`, about `25 FPS` | External OmniRT/model-service inference baseline, not direct OpenTalking inference. |
| FlashTalk steady chunk | Ascend 910B2 x8, hot chunk | 29-frame chunks around `30 FPS` equivalent | External steady-state inference data; keep separate from end-to-end first response. |

## Result Template

```markdown
### <model> / <backend> / <hardware> / <date>

- OpenTalking commit:
- backend commit or service version:
- hardware:
- model and weights:
- avatar:
- input audio:
- cold start or hot state:
- `session_create_ms`:
- `llm_first_token_ms`:
- `tts_first_pcm_ms`:
- `avatar_first_frame_ms`:
- `webrtc_first_frame_ms`:
- `render_fps`:
- `av_drift_ms`:
- notes:
```

## Interpretation Rules

- For end-to-end experience, prioritize first response and A/V sync over model FPS alone.
- For model-service throughput, prioritize steady chunks and queue depth over one cold run.
- Public references to external benchmarks must label the source as an external backend.
