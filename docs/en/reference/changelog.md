# Changelog

This page tracks OpenTalking capability progress, roadmap items, and compatibility notes.

## May 2026

### 2026/05/17

- **QuickTalk integration**
  QuickTalk / Wav2Lip now have easier startup paths and can be launched directly through OpenTalking for digital-human generation.

### 2026/05/15

- **MuseTalk WebRTC playback optimization**
  Added MuseTalk media backpressure to improve WebRTC playback stability.

### 2026/05/14

- **MuseTalk adaptation**
  Added the MuseTalk talking-head path for lightweight full-frame digital-human validation.

### 2026/05/13

- **Model backend decoupling**
  Decoupled `mock`, `local`, `direct_ws`, and `omnirt` at the architecture level so different models can choose different deployment backends.

### 2026/05/08

- **QuickTalk local adapter**
  Added the QuickTalk model adapter, configuration notes, and async initialization.

* * *

## April 2026

### 2026/04/16

- **Baseline real-time digital-human experience**
  Built the main Web console, LLM conversation, TTS, subtitle events, and WebRTC audio/video playback pipeline.

* * *

## Compatibility Notes

- This changelog currently tracks capability progress rather than formal release versions.
- Model integration, runtime backends, and configuration keys are still evolving quickly. Check “Model Support” and “Usage Guide” before upgrading.
- Benchmark data must include hardware, model, backend, startup state, and input assets; numbers should not be compared across environments without context.
