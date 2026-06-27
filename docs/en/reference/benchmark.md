# Benchmark

This page explains how OpenTalking records end-to-end experience metrics and how it references inference baselines from external model backends. OpenTalking is the orchestration layer, so benchmark data is separated into two categories:

| Type | Directly owned by OpenTalking | Examples |
|------|-------------------------------|----------|
| End-to-end experience metrics | Yes | First-frame latency, TTS first packet, event stream, WebRTC playback, audio/video sync. |
| Model inference baseline | No, provided by the selected backend | OmniRT FlashTalk, Wav2Lip, QuickTalk local adapter render throughput. |

The current content follows the benchmark conventions from `docs/zh/benchmark` on the main branch.

## Running the Full E2E Benchmark

Use the following script for the full end-to-end benchmark:

```bash
scripts/run_opentalking_e2e_benchmark.sh
```

This script reads input assets according to the benchmark configuration, starts the relevant services, and collects results.

Enter OpenTalking:

```bash
cd $DIGITAL_HUMAN_HOME/opentalking
source .venv/bin/activate
```

Prepare script permissions:

```bash
chmod +x scripts/run_opentalking_e2e_benchmark.sh
chmod +x scripts/start_unified.sh
chmod +x scripts/quickstart/start_omnirt_quicktalk.sh
```

Confirm default benchmark inputs exist:

```bash
ls -lh configs/benchmark/input/reference.png
ls -lh configs/benchmark/input/ttsmaker-file.mp3
```

To replace the test avatar or audio, simply replace the two files above, or modify the input paths in `configs/benchmark/opentalking-e2e.yaml`. For general deployment verification, the repository's built-in benchmark inputs are sufficient.

Set low-VRAM environment variables:

```bash
export CUDA_VISIBLE_DEVICES=0
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,max_split_size_mb:128
export OPENTALKING_BENCHMARK_PYTHON="$PWD/.venv/bin/python"

export OPENTALKING_QUICKTALK_HUBERT_DEVICE=cpu
export OPENTALKING_QUICKTALK_RESOLUTION=160
export OPENTALKING_PREWARM_AVATARS=0

export OMNIRT_QUICKTALK_RUNTIME=1
export OMNIRT_QUICKTALK_DEVICE=cuda:0
export OMNIRT_QUICKTALK_HUBERT_DEVICE=cpu
export OMNIRT_QUICKTALK_BATCH_SIZE=1
export OMNIRT_QUICKTALK_WORKER_CACHE_MAX=1
```

Run the benchmark:

```bash
bash scripts/run_opentalking_e2e_benchmark.sh \
  --tester xxx \
  --model quicktalk \
  --backend omnirt \
  --gpu-index 0 \
  --timeout 300
```

Find results:

```bash
find $DIGITAL_HUMAN_HOME/opentalking -name "result.json" -o -name "result.csv" -o -name "report.md" -o -name "*.tar.gz"
```

### Notes

`run_opentalking_e2e_benchmark.sh` is the full end-to-end entry point. It is more suitable for final deployment verification than running model benchmarks individually, as it covers OpenTalking, OmniRT, QuickTalk runtime, input processing, service startup, request pipeline, and result statistics.

---

## WSL2 VRAM Statistics Fix

On WSL2, the following command may not return per-process VRAM usage:

```bash
nvidia-smi --query-compute-apps=pid,used_memory
```

As a result, the benchmark may show:

```text
idle VRAM: 0.0
peak inference VRAM: 0.0
```

Recommended approach: when PID-level queries return empty, fall back to full-GPU VRAM:

```bash
nvidia-smi --id=0 --query-gpu=memory.used --format=csv,noheader,nounits
```

Calculation:

```text
peak inference VRAM = max(current memory.used - baseline memory.used)
```

Notes:

- This is not per-process VRAM;
- This is the delta of full-GPU VRAM relative to baseline during the benchmark run;
- Do not run other CUDA programs during the benchmark.

---

## Metrics

| Metric | Meaning | Owner |
|------|------|------|
| `session_create_ms` | Time from session creation request to API response. | OpenTalking |
| `asr_partial_latency_ms` | Latency from user speech to the first partial transcript. | OpenTalking + STT provider |
| `llm_first_token_ms` | Latency from text request to first LLM token. | OpenTalking + LLM endpoint |
| `tts_first_pcm_ms` | Latency from sentence submission to first PCM/audio bytes. | OpenTalking + TTS provider |
| `avatar_first_frame_ms` | Latency from audio submission to first available avatar frame. | OpenTalking + synthesis backend |
| `render_fps` | Video-frame generation throughput of the synthesis backend. | synthesis backend |
| `webrtc_first_frame_ms` | Time until the browser receives the first playable video frame. | OpenTalking + WebRTC |
| `av_drift_ms` | Audio/video timeline offset during playback. | OpenTalking |
| `queue_depth` | Worker or external model-service queue depth. | OpenTalking / backend |
| `steady_chunk_ms` | Steady-state chunk inference time. | synthesis backend |

## Tested Combinations

| Path | Hardware / state | Data | Notes |
|------|------------------|------|------|
| Wav2Lip quickstart | NVIDIA 3090 path | `singer` example around `28` frames / `0.83-0.85s`, about `33 FPS` | From README quickstart notes; useful as a lightweight model reference. |
| QuickTalk local adapter | RTX 3090 | 720x900 / 25fps, about `35 FPS`, about `3.8 GiB` GPU memory | From README consumer-GPU reference. |
| FlashTalk via OmniRT | Ascend 910B2 x8, warm full-audio | `937` frames / `37.377s`, about `25 FPS` | External OmniRT/model-service baseline, not direct OpenTalking inference. |
| FlashTalk steady chunk | Ascend 910B2 x8, warm chunk | 29-frame chunk around `30 FPS` equivalent | External inference baseline; should be separated from end-to-end first-response latency. |

## FPS

FPS should be split into:

- `render_fps`: frame-generation throughput of the model or synthesis backend.
- Playback FPS: actual browser or WebRTC playback frame rate.

High model FPS does not guarantee a good end-to-end experience. TTS, queueing, network, WebRTC, and browser decoding also matter.

## First-frame Latency

Record first-frame latency in stages:

- `session_create_ms`
- `tts_first_pcm_ms`
- `avatar_first_frame_ms`
- `webrtc_first_frame_ms`

One single “first-frame latency” number is not enough to locate bottlenecks.

## Startup Time

Always label startup state:

- Cold start: process startup, model load, weight load, avatar preprocessing, and cache build.
- Warm state: model and cache are ready.
- Steady chunk: continuous generation throughput after initialization.

## End-to-end Latency

End-to-end latency should be measured from user input to visible browser output. Text, speech, and uploaded-audio tests have different starting points, so record the exact boundary.

## Resource Usage

Record GPU/NPU model, driver version, peak and steady memory usage, CPU limits, model version, quantization, caching, and warmup state.

## Test Method

### QuickTalk Local Adapter

```bash title="Terminal"
source .venv/bin/activate
python apps/cli/quicktalk_bench.py \
  --asset-root /path/to/quicktalk/assets \
  --template-video /path/to/template.mp4 \
  --audio /path/to/input.wav \
  --output outputs/benchmarks/quicktalk-output.mp4 \
  --device cuda:0
```

The output JSON includes:

- `init_seconds`
- `audio_feature_seconds`
- `first_frame_seconds`
- `render_seconds`
- `render_fps`
- `mux_seconds`

### OpenTalking End-to-end Flow

```bash title="Terminal"
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/models | jq
```

Record the OpenTalking commit, non-secret config, hardware, selected `avatar_id`, `model`, `backend`, input audio, first token, TTS first packet, avatar first frame, browser first frame, and audio/video sync result.

### External Model Services

OmniRT, FlashHead direct WebSocket, or other model-service data should be generated by their own benchmark tools. OpenTalking documentation only references those results and records OpenTalking-side orchestration, queueing, and playback behavior.

## Result Template

```markdown
### <model> / <backend> / <hardware> / <date>

- OpenTalking commit:
- backend commit or service version:
- hardware:
- model and weights:
- avatar:
- input audio:
- cold start or warm state:
- `session_create_ms`:
- `llm_first_token_ms`:
- `tts_first_pcm_ms`:
- `avatar_first_frame_ms`:
- `webrtc_first_frame_ms`:
- `render_fps`:
- `av_drift_ms`:
- notes:
```

## How to Interpret Results

- For user experience, prioritize first response and audio/video sync, not only model FPS.
- For model-service throughput, prioritize steady chunks and queue depth, not only one cold run.
- External backend benchmarks must be clearly labeled as external.
- A Mock run only proves orchestration works; it does not prove talking-head performance.

---

## Benchmark Results Reference

Key metrics to focus on:

| Metric | RTX 3050 Laptop Reference | Meaning |
| --- | ---: | --- |
| Output resolution | 540×900 / 25fps | Final output spec |
| Cold start | 6.0 s | Service and model initialization time |
| Warmup | 20.8 s | First load and inference preparation time |
| TTFA | 1661 ms | Time to first audio |
| TTFV | 2833 ms | Time to first video frame |
| First-turn total latency | 4109 ms | User input to first-turn response completion |
| Steady FPS | 19.1 | Steady-state video generation frame rate |
| RTF | 1.17 | Greater than 1 means slightly slower than real-time |
| VRAM usage | 1.4 GiB | VRAM after WSL2 fallback |

Conclusion: RTX 3050 Laptop can run the QuickTalk pipeline, but real-time performance is limited. It is suitable for deployment verification and feature demos; for stable 25fps+, use RTX 3060 / 4060 or higher.

---

## Test Results

| Date | Model | Technique | Backend | Hardware | OS | Driver | commit (opentalking + omnirt) | Input | Resolution | FPS | Chunk size | Cold start/s | Warmup/s | TTFA/ms | TTFV/ms | First-turn total/ms | Steady FPS | Idle VRAM/GB | Peak VRAM/GB |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026/5/20 | wav2lip | mouth inpainting | omnirt | RTX 3090 | Linux x86_64 glibc2.31 | driver 570.133.07 | a3047eab + 64c92ed1 | audio+image | 498×832 | 30 | 933ms | 4.096 | 12.043 | 1374.507 | 1625.962 | 3002.526 | 37.269 | 7.928 | 7.928 |
| 2026/5/20 | quicktalk | mouth inpainting | omnirt | RTX 3090 | Linux x86_64 glibc2.31 | driver 570.133.07 | a3047eab + 64c92ed1 | audio+image | 540×900 | 25 | 1120ms | 5.702 | 17.856 | 1551.773 | 1800.524 | 3356.019 | 29.23 | 1.662 | 1.662 |
| 2026/5/20 | musetalk | mouth inpainting | omnirt | RTX 3090 | Linux x86_64 glibc2.31 | driver 570.133.07 | a3047eab + 64c92ed1 | audio+image | 512×512 | 25 | 1000ms | 21.927 | 10.233 | 1464.464 | 1769.484 | 3235.518 | 28.868 | 5.078 | 5.078 |
| 2026/5/22 | wav2lip | mouth inpainting | omnirt | RTX 4090 | Linux x86_64 glibc2.39 | driver 570.211.01 | f16f7868 + 9a35e675 | audio+image | 498×832 | 30 | 933ms | 4.23 | 27.321 | 1730.871 | 1955.629 | 3689.764 | 31.542 | 8.133 | 8.133 |
| 2026/5/22 | quicktalk | mouth inpainting | omnirt | RTX 4090 | Linux x86_64 glibc2.39 | driver 570.211.01 | f16f7868 + 9a35e675 | audio+image | 540×900 | 25 | 1120ms | 4.319 | 15.871 | 1493.164 | 1064.825 | 2561.146 | 46.921 | 1.838 | 1.838 |
| 2026/5/22 | musetalk | mouth inpainting | omnirt | RTX 4090 | Linux x86_64 glibc2.39 | driver 570.211.01 | f16f7868 + 9a35e675 | audio+image | 512×512 | 25 | 1000ms | 18.309 | 13.866 | 1506.636 | 2095.522 | 3605.564 | 24.767 | 5.203 | 5.203 |
| 2026/5/22 | wav2lip | mouth inpainting | omnirt | NPU 910B2 | Linux aarch64 glibc2.35 | cann driver | f3532c19 + 5f24f56f | audio+image | 498×832 | 30 | 933ms | 9.478 | 35.931 | 1401.98 | 2615.322 | 4019.564 | 23.945 | 9.113 | 9.113 |
| 2026/5/22 | quicktalk | mouth inpainting | omnirt | NPU 910B2 | Linux aarch64 glibc2.35 | cann driver | f3532c19 + 5f24f56f | audio+image | 540×900 | 25 | 1120ms | 9.471 | 39.142 | 1427.894 | 1782.861 | 3212.053 | 29.66 | 2.473 | 2.473 |
| 2026/5/22 | musetalk | mouth inpainting | omnirt | NPU 910B2 | Linux aarch64 glibc2.35 | cann driver | f3532c19 + 5f24f56f | audio+image | 512×512 | 25 | 1000ms | 27.177 | 65.282 | 1566.821 | 4211.721 | 5781.453 | 12.276 | 8.754 | 8.754 |
| 2026/5/27 | quicktalk | mouth inpainting | omnirt | RTX 3050 Laptop | WSL2 glibc2.35 | driver 581.57 | 3c893c52 + 5f24f56f | audio+image | 540×900 | 25 | 1120ms | 5.98 | 20.77 | 1661 | 2833 | 4109 | 19.06 | 1.41 | 1.41 |
| 2026/5/27 | quicktalk | mouth inpainting | omnirt | RTX 3050 Laptop | WSL2 glibc2.35 | driver 581.57 | 3c893c52 + 5f24f56f | audio+image | 306×512 | 25 | 1120ms | 6.282 | 20.78 | 1580.28 | 2661 | 4243.26 | 20.695 | 1.385 | 1.396 |
