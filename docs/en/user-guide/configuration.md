# Configuration

OpenTalking applies configuration from two sources, in order of decreasing precedence:

1. **Environment variables** — provided via `.env` files or the process environment.
2. **YAML files** — `configs/default.yaml` and optional overlays from `configs/profiles/*.yaml`
   and `configs/synthesis/*.yaml`.

The reference `.env.example` file is organized into four tiers. Each tier corresponds
to a deployment scenario; only the sections relevant to the target scenario need to be
configured.

| Tier | Sections to configure | Use case |
|------|----------------------|----------|
| 1 — Evaluation | §1 | Mock synthesis only, no inference service. |
| 2 — Lightweight model | §1 + §2 | wav2lip, musetalk, or flashtalk via OmniRT. |
| 3 — Production deployment | §1 + §2 + §3 | API/Worker split with Redis and hardware profile selection. |
| 4 — Advanced tuning | + §4 | Frame budget, JPEG quality, idle frames, voice cloning. |

## 1. Language model, speech recognition, and text-to-speech

The minimum configuration required for any deployment. The synthesis backend (mock,
wav2lip, flashtalk, etc.) is selected by the client when a session is created and is not
configured here.

### Language model

Any OpenAI-compatible chat completion endpoint is supported.

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENTALKING_LLM_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | Base URL of the chat completion endpoint. DashScope, OpenAI, vLLM, Ollama, and DeepSeek are supported. |
| `OPENTALKING_LLM_API_KEY` | _empty_ | Bearer token used for authentication. |
| `OPENTALKING_LLM_MODEL` | `qwen-flash` | Model identifier passed to the endpoint. |
| `OPENTALKING_LLM_SYSTEM_PROMPT` | _conversational default_ | System prompt. The default instructs the model to respond in plain spoken text without markdown formatting. |

### Speech recognition

The default speech recognition backend is DashScope Paraformer realtime.

| Variable | Default | Description |
|----------|---------|-------------|
| `DASHSCOPE_API_KEY` | _empty_ | Consumed directly by the DashScope SDK. When the language model also runs on DashScope, this variable must be set to the same value as `OPENTALKING_LLM_API_KEY`. |
| `OPENTALKING_STT_MODEL` | `paraformer-realtime-v2` | DashScope realtime speech recognition model. |

### Text-to-speech

The default text-to-speech backend is Edge TTS, which decodes locally through ffmpeg
and does not require an API key.

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENTALKING_TTS_PROVIDER` | `edge` | One of `edge`, `dashscope`, `cosyvoice`, `elevenlabs`. |
| `OPENTALKING_TTS_VOICE` | `zh-CN-XiaoxiaoNeural` | Voice identifier. Format depends on the provider. |

Configuration for DashScope realtime TTS and ElevenLabs is documented in
[§4 Advanced tuning](#4-advanced-tuning).

## 2. Inference service

The variables in this section are consulted only when the client selects `wav2lip`,
`musetalk`, `flashtalk`, or `flashhead`. The `mock` backend ignores all entries here.
For weight downloads and model-specific startup commands, see
[Models](../model-deployment/index.md).

OpenTalking selects the inference entry point per model through `backend`; it is not
tied to one inference platform. Recommended defaults:

```yaml
models:
  wav2lip:
    backend: omnirt      # can switch to local / direct_ws
  musetalk:
    backend: omnirt      # can switch to local / direct_ws
  flashtalk:
    backend: omnirt
  flashhead:
    backend: direct_ws
  quicktalk:
    backend: local
  mock:
    backend: mock
```

| backend | Best for |
|---------|----------|
| `mock` | Local self-test, no inference service |
| `local` | Lightweight models or local adapters such as QuickTalk |
| `direct_ws` | A single-model WebSocket service such as FlashHead |
| `omnirt` | Heavyweight, multi-card, GPU/NPU remote inference |

### OmniRT (recommended)

A single OmniRT endpoint serves all models configured with `backend: omnirt`. Routes are derived from the
URL template `ws://<host>:9000/v1/audio2video/{model}`.

| Variable | Default | Description |
|----------|---------|-------------|
| `OMNIRT_ENDPOINT` | _empty_ | Base URL of the OmniRT instance, e.g. `http://127.0.0.1:9000`. Only affects models with `backend: omnirt`. |
| `OMNIRT_API_KEY` | _empty_ | Optional bearer token forwarded to OmniRT. |
| `OPENTALKING_OMNIRT_AUDIO2VIDEO_PATH_TEMPLATE` | `/v1/audio2video/{model}` | Override only when OmniRT is deployed at a non-default path. |

Start an OmniRT instance locally:

```bash title="terminal"
bash scripts/run_omnirt.sh
# Individual model entry points:
bash scripts/quickstart/start_omnirt_wav2lip.sh --device cuda
bash scripts/quickstart/start_omnirt_flashtalk.sh --device cuda
```

### Direct single-model connection (legacy)

Used for point-to-point integration with a single-model WebSocket service. FlashTalk keeps
a legacy fallback: when `OMNIRT_ENDPOINT` is unset, `OPENTALKING_FLASHTALK_WS_URL` can
connect directly to a FlashTalk single-process server.

| Variable | Description |
|----------|-------------|
| `OPENTALKING_FLASHTALK_WS_URL` | `ws://<host>:8765` of a SoulX FlashTalk single-process server. |

### FlashHead (independent path)

FlashHead implements its own WebSocket protocol and does not route through OmniRT.

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENTALKING_FLASHHEAD_WS_URL` | _empty_ | `ws://<host>:8766/v1/avatar/realtime` |
| `OPENTALKING_FLASHHEAD_BASE_URL` | _empty_ | `http://<host>:8766`, REST control plane. |
| `OPENTALKING_FLASHHEAD_MODEL` | `soulx-flashhead-1.3b` | Model identifier. |

## 3. Production deployment

The variables in this section are required only for the API/Worker split deployment
mode. The single-process unified mode (`opentalking-unified`) ignores all entries.

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENTALKING_REDIS_URL` | `redis://localhost:6379/0` | Message bus between API and Worker. |
| `OPENTALKING_REDIS_MODE` | `redis` | Set to `memory` to use the in-process bus (single-process mode only). |
| `OPENTALKING_API_HOST` | `0.0.0.0` | API bind address. |
| `OPENTALKING_API_PORT` | `8000` | API bind port. |
| `OPENTALKING_WORKER_HOST` | `0.0.0.0` | Worker bind address. |
| `OPENTALKING_WORKER_PORT` | `9001` | Worker bind port. |
| `OPENTALKING_WORKER_URL` | `http://127.0.0.1:9001` | URL through which the API reaches the Worker. |
| `OPENTALKING_TORCH_DEVICE` | `cpu` | Device used for orchestration-side audio and frame post-processing. |
| `OPENTALKING_AVATARS_DIR` | `./examples/avatars` | Avatar bundle root directory. |
| `OPENTALKING_VOICES_DIR` | `./var/voices` | Storage for cloned voices. |
| `OPENTALKING_SQLITE_PATH` | `./data/opentalking.sqlite3` | Local metadata database file. |
| `OPENTALKING_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated list of permitted frontend origins. |

## 4. Advanced tuning

The variables in this section are intended for fine-grained control over specific
backends. Consult `.env.example` for the complete list. Representative entries are
documented below.

### DashScope Qwen realtime TTS

```env
OPENTALKING_TTS_PROVIDER=dashscope
OPENTALKING_QWEN_TTS_MODEL=qwen3-tts-flash-realtime
OPENTALKING_QWEN_TTS_REUSE_WS=1
```

### ElevenLabs TTS

```env
OPENTALKING_TTS_PROVIDER=elevenlabs
OPENTALKING_TTS_ELEVENLABS_API_KEY=sk_...
OPENTALKING_TTS_ELEVENLABS_VOICE_ID=...
OPENTALKING_TTS_ELEVENLABS_MODEL_ID=eleven_flash_v2_5
```

### FlashTalk rendering parameters

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENTALKING_FLASHTALK_FRAME_NUM` | `25` | Frames generated per inference chunk. |
| `OPENTALKING_FLASHTALK_SAMPLE_STEPS` | `2` | Diffusion sample steps. Higher values increase quality and inference time. |
| `OPENTALKING_FLASHTALK_HEIGHT` | `704` | Output video height. |
| `OPENTALKING_FLASHTALK_WIDTH` | `416` | Output video width. |
| `OPENTALKING_FLASHTALK_JPEG_QUALITY` | `55` | JPEG quality of the WebRTC stream. |
| `OPENTALKING_FLASHTALK_IDLE_ENABLE` | `1` | Generates idle frames during pauses in speech. |
| `OPENTALKING_FLASHTALK_TTS_BOUNDARY_FADE_MS` | `18` | Audio fade duration applied at TTS chunk boundaries. |

### QuickTalk (local real-time)

| Variable | Description |
|----------|-------------|
| `OPENTALKING_QUICKTALK_ASSET_ROOT` | Path to the QuickTalk asset bundle. |
| `OPENTALKING_QUICKTALK_TEMPLATE_VIDEO` | Path to the QuickTalk template video file. |
| `OPENTALKING_QUICKTALK_WORKER_CACHE` | When set to `1`, reuses workers across sessions to reduce cold-start latency. |
| `OPENTALKING_PREWARM_AVATARS` | Comma-separated avatar identifiers to warm at server startup. |

## YAML configuration

The YAML configuration layer provides structural defaults. The runtime loads
`configs/default.yaml` and overlays the file referenced by `OPENTALKING_CONFIG_FILE`.

### `configs/default.yaml` top-level keys

```yaml title="configs/default.yaml (excerpt)"
api:
  host: 0.0.0.0
  port: 8000
  cors_origins: [http://localhost:5173, http://127.0.0.1:5173]
infrastructure:
  redis_url: redis://localhost:6379/0
  avatars_dir: ./examples/avatars
  models_dir: ./models
  worker_url: http://127.0.0.1:9001
flashtalk:
  mode: off
  ckpt_dir: ./models/SoulX-FlashTalk-14B
  port: 8765
flashhead:
  ws_url: ""
  model: soulx-flashhead-1.3b
  fps: 25
  sample_rate: 16000
llm:
  model: qwen-flash
tts:
  voice: zh-CN-XiaoxiaoNeural
  sample_rate: 16000
model:
  torch_device: cpu
  default_model: wav2lip
models:
  wav2lip: { stream_batch_size: 8, pads: [0, 10, 0, 0] }
  musetalk: { context_ms: 320.0, silence_gate: 0.04 }
  flashtalk: { frame_num: 33, sample_steps: 2 }
```

### Hardware profiles

The directory `configs/profiles/` ships with four predefined profiles:

- `cpu-demo.yaml` — orchestration-only, mock synthesis.
- `cuda-3090.yaml` — wav2lip and musetalk on a single GPU.
- `cuda-4090.yaml` — flashtalk-14B on a single GPU.
- `ascend-910b.yaml` — NPU deployment.

To apply a profile:

```bash title="terminal"
export OPENTALKING_CONFIG_FILE=./configs/profiles/cuda-3090.yaml
opentalking-unified
```

### Synthesis-specific tuning

Files under `configs/synthesis/` override the `models.<name>` subtree without
duplicating the complete default configuration.

## Precedence summary

The effective configuration is resolved with the following precedence, from highest to
lowest:

1. Shell environment variables.
2. Variables defined in the `.env` file.
3. YAML file referenced by `OPENTALKING_CONFIG_FILE`.
4. `configs/default.yaml`.

!!! note "Restart required for changes"
    Configuration values are read at process startup. Configuration changes require a
    restart of the relevant processes to take effect.
