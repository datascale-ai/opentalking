# Benchmark

The Benchmark section explains how OpenTalking records end-to-end experience metrics and
how it references inference baselines from external model services. OpenTalking is the
orchestration layer, so the documentation separates two data classes:

| Type | Directly owned by OpenTalking | Examples |
|------|-------------------------------|----------|
| End-to-end experience metrics | Yes | First frame latency, TTS first packet, events, WebRTC playback, A/V sync. |
| Model inference baselines | No, owned by the selected backend | OmniRT FlashTalk, Wav2Lip, QuickTalk local adapter throughput. |

## Reading Order

1. [Metrics](metrics.md) — shared field names and measurement boundaries.
2. [Runbook](runbook.md) — how to collect QuickTalk and end-to-end data.
3. [Results and Baselines](results.md) — current reference numbers and the result template.

## Recording Rules

- Every result must include hardware, model, backend, resolution, input audio duration, and startup state.
- Cold start, hot state, and steady chunk measurements must be kept separate.
- OmniRT or other external service results must be labeled as backend data.
- A `mock` run proves orchestration health, not real talking-head performance.
