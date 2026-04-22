# OpenTalking Unified Architecture Design Spec

> Archived design draft.
> Some module paths, package splits, and rollout assumptions in this file no longer match the current repository layout.
> For the current implementation, prefer `docs/architecture.md`, `docs/configuration.md`, `docs/local-dev.md`, and `docs/deployment.md`.

**Date**: 2026-04-15
**Status**: Draft
**License**: Apache 2.0

## Context

OpenTalking is a real-time digital human system composed of two independent codebases:

1. **SoulX-FlashTalk** (`liveact/SoulX-FlashTalk/`) — 14B diffusion-based talking head video generation engine. Runs on 8×GPU/NPU via `torchrun`, generates synchronized video frames from audio at real-time speed (~1.03s per 33 frames at 25fps). ~7,800 LOC.

2. **OpenTalking** (`opentalking/`) — Modular orchestration framework. Routes user text through LLM → TTS → model inference → WebRTC to the browser. Supports multiple model adapters (wav2lip, musetalk, flashtalk). React frontend. Docker deployment. ~14,500 LOC.

**Problem**: These two projects are currently separate, with FlashTalk running as a remote WebSocket service that OpenTalking connects to. For open-source release, they need to be a unified, well-organized, self-contained project that users can clone and run.

**Goal**: Create a single, from-scratch architecture that consolidates both codebases into one open-source repository called **OpenTalking**, licensed under Apache 2.0.

**Scope**: FlashTalk + OpenTalking only (no DigitalMan desktop app).

---

## Architecture Overview

```
Browser (React + Vite + Tailwind)
  │  WebRTC video/audio + SSE events + REST API
  ▼
apps/api (FastAPI)  ──Redis queue──  opentalking.worker (TaskConsumer + Runner)
  │                                       │
  │                           ┌───────────┼───────────┐
  │                           ▼           ▼           ▼
  │                    opentalking.llm  opentalking.tts  opentalking.models
  │                    (OpenAI-compat)  (Edge TTS)      (adapter registry)
  │                                                          │
  │                                                  ┌───────┴───────┐
  │                                                  ▼               ▼
  │                                           remote mode      local mode
  │                                        (FlashTalkWSClient) (LocalAdapter)
  │                                                  │               │
  │                                                  ▼               ▼
  │                                        opentalking.server  opentalking.engine
  │                                        (WS, torchrun)      (direct call)
  │                                                  │
  │                                                  ▼
  │                                        opentalking.engine
  │                                        (14B pipeline, multi-GPU)
  ▼
apps/unified  (single-process, no Redis, API + Worker in one process)
```

---

## Directory Structure

```
opentalking/
├── LICENSE                              # Apache 2.0
├── README.md                            # Project overview, quickstart, badges
├── CONTRIBUTING.md                      # Contribution guide
├── CHANGELOG.md
├── pyproject.toml                       # Unified monorepo (PEP 621)
├── Makefile                             # Convenience targets
├── .env.example                         # All configurable vars, safe defaults
├── .gitignore
├── .pre-commit-config.yaml
│
├── configs/
│   ├── default.yaml                     # Single source of truth for all defaults
│   ├── flashtalk.yaml                   # FlashTalk inference params
│   └── examples/
│       ├── distributed.yaml             # Multi-node deployment
│       ├── single-gpu.yaml              # Single GPU
│       └── cpu-only.yaml                # CPU fallback
│
├── src/opentalking/
│   ├── __init__.py
│   ├── version.py                       # Single version source
│   │
│   ├── core/                            # Shared foundation (zero inference deps)
│   │   ├── __init__.py
│   │   ├── config.py                    # Unified Settings (pydantic-settings)
│   │   ├── interfaces/
│   │   │   ├── __init__.py
│   │   │   ├── model_adapter.py         # ModelAdapter protocol
│   │   │   ├── tts_adapter.py           # TTSAdapter protocol
│   │   │   ├── llm_adapter.py           # LLMAdapter protocol (NEW)
│   │   │   └── render_session.py        # RenderSession dataclass
│   │   ├── types/
│   │   │   ├── __init__.py
│   │   │   ├── events.py                # SpeechStartedEvent, SubtitleChunkEvent, etc.
│   │   │   └── frames.py               # AudioChunk, VideoFrameData
│   │   ├── bus.py                       # Unified message bus (Redis or InMemory)
│   │   ├── redis_keys.py               # Redis key constants
│   │   └── in_memory_redis.py           # InMemoryRedis for unified mode
│   │
│   ├── engine/                          # FlashTalk 14B inference (self-contained)
│   │   ├── __init__.py                  # Public API: get_pipeline, run_pipeline, etc.
│   │   ├── inference.py                 # Core facade (4 public functions)
│   │   ├── accelerator.py              # Device abstraction (CUDA/NPU/CPU)
│   │   ├── pipeline/
│   │   │   ├── __init__.py
│   │   │   └── flash_talk_pipeline.py   # FlashTalkPipeline class
│   │   ├── distributed/
│   │   │   ├── __init__.py
│   │   │   ├── usp_device.py            # USP parallel degree
│   │   │   └── xdit_context_parallel.py
│   │   ├── audio/
│   │   │   ├── __init__.py
│   │   │   ├── wav2vec2.py              # Speech feature extraction
│   │   │   ├── torch_utils.py
│   │   │   └── loudness.py              # loudness_norm
│   │   ├── modules/
│   │   │   ├── __init__.py
│   │   │   ├── multitalk_attention.py
│   │   │   └── multitalk_model.py
│   │   ├── wan/                         # Alibaba Wan foundation model components
│   │   │   └── modules/
│   │   │       ├── __init__.py
│   │   │       ├── attention.py
│   │   │       ├── clip.py
│   │   │       ├── model.py
│   │   │       ├── t5.py
│   │   │       ├── tokenizers.py
│   │   │       ├── vace_model.py
│   │   │       ├── vae.py
│   │   │       └── xlm_roberta.py
│   │   └── configs/
│   │       ├── __init__.py
│   │       └── wan_multitalk_14B.py
│   │
│   ├── server/                          # FlashTalk WebSocket server (torchrun)
│   │   ├── __init__.py
│   │   ├── ws_server.py                 # WebSocket message loop + session state
│   │   ├── worker_loop.py               # Non-rank-0 process command dispatch
│   │   ├── broadcast.py                 # Distributed broadcast helpers
│   │   ├── idle_cache.py                # Idle cache generation, disk persist, masks
│   │   ├── video_codec.py              # JPEG encode/decode, VIDX wire format
│   │   └── __main__.py                  # Entry: torchrun -m opentalking.server
│   │
│   ├── models/                          # Model adapter registry
│   │   ├── __init__.py
│   │   ├── registry.py                  # @register_model, get_adapter, list_models
│   │   ├── flashtalk/
│   │   │   ├── __init__.py
│   │   │   ├── ws_client.py             # FlashTalkWSClient (remote server mode)
│   │   │   └── local_adapter.py         # FlashTalkLocalAdapter (co-located, NEW)
│   │   ├── musetalk/
│   │   │   ├── __init__.py
│   │   │   ├── adapter.py              # @register_model("musetalk")
│   │   │   ├── composer.py
│   │   │   ├── face_utils.py
│   │   │   ├── feature_extractor.py
│   │   │   ├── inference.py
│   │   │   └── loader.py
│   │   └── wav2lip/
│   │       ├── __init__.py
│   │       ├── adapter.py              # @register_model("wav2lip")
│   │       ├── feature_extractor.py
│   │       └── loader.py
│   │
│   ├── tts/                             # Text-to-speech adapters
│   │   ├── __init__.py
│   │   └── edge/
│   │       ├── __init__.py
│   │       └── adapter.py              # EdgeTTSAdapter (streaming MP3 -> PCM)
│   │
│   ├── llm/                             # LLM integration
│   │   ├── __init__.py
│   │   ├── openai_compatible.py         # OpenAI-compatible client (replaces dashscope_client)
│   │   ├── conversation.py              # Multi-turn context management
│   │   └── sentence_splitter.py         # Sentence segmentation for streaming TTS
│   │
│   ├── rtc/                             # WebRTC transport
│   │   ├── __init__.py
│   │   └── aiortc_adapter.py            # WebRTCSession (aiortc)
│   │
│   ├── avatars/                         # Avatar asset management
│   │   ├── __init__.py
│   │   ├── loader.py                    # Load AvatarBundle from manifest
│   │   ├── manifest.py                  # Parse manifest.json
│   │   └── validator.py                 # Validate avatar directories
│   │
│   ├── events/                          # Event system
│   │   ├── __init__.py
│   │   ├── emitter.py                   # EventEmitter + pub/sub
│   │   └── schemas.py                   # SSE payload formatting
│   │
│   └── worker/                          # Session orchestration
│       ├── __init__.py
│       ├── session_runner.py            # Generic ModelAdapter runner
│       ├── flashtalk_runner.py          # FlashTalk pipeline (LLM -> TTS -> FlashTalk -> WebRTC)
│       ├── task_consumer.py             # Redis/in-memory task queue consumer
│       ├── pipeline/
│       │   ├── __init__.py
│       │   ├── audio_pipeline.py        # TTS chunk processing
│       │   └── render_pipeline.py       # Feature extraction + inference
│       └── text_sanitize.py             # Emoji stripping, text cleanup
│
├── apps/
│   ├── api/                             # FastAPI REST server
│   │   ├── __init__.py
│   │   ├── main.py                      # create_app(), lifespan, entrypoint
│   │   ├── config.py                    # API-specific Settings overlay
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── health.py               # GET /health
│   │   │   ├── avatars.py              # GET /avatars
│   │   │   ├── models.py               # GET /models
│   │   │   ├── sessions.py             # POST/DELETE /sessions, /speak, /interrupt, /webrtc
│   │   │   └── events.py               # GET /sessions/{id}/events (SSE)
│   │   └── services/
│   │       ├── __init__.py
│   │       ├── session_service.py
│   │       └── worker_service.py        # Forward WebRTC offer to worker
│   │
│   ├── unified/                         # Single-process mode (no Redis)
│   │   ├── __init__.py
│   │   └── main.py
│   │
│   ├── web/                             # React frontend
│   │   ├── package.json
│   │   ├── tsconfig.json
│   │   ├── vite.config.ts
│   │   ├── tailwind.config.js
│   │   └── src/
│   │       ├── App.tsx                  # Main component + state management
│   │       ├── main.tsx
│   │       ├── types.ts
│   │       ├── lib/
│   │       │   ├── api.ts              # HTTP client
│   │       │   ├── sse.ts              # Server-sent events
│   │       │   └── webrtc.ts           # RTCPeerConnection setup
│   │       └── components/
│   │           ├── VideoBackground.tsx
│   │           ├── ChatMessages.tsx
│   │           ├── ChatInput.tsx
│   │           ├── SubtitleOverlay.tsx
│   │           ├── TopBar.tsx
│   │           ├── SettingsPanel.tsx
│   │           └── StartOverlay.tsx
│   │
│   └── cli/                             # CLI tools
│       ├── __init__.py
│       ├── generate_video.py            # Batch video generation
│       ├── gradio_app.py               # Gradio demo UI
│       └── download_models.py           # Interactive model download (HF + ModelScope)
│
├── scripts/
│   ├── download_models.sh               # Shell-based model download
│   ├── deploy_ascend_910b.sh            # Ascend deployment (parameterized)
│   ├── start_server.sh                  # FlashTalk server launcher
│   └── start_unified.sh                 # Unified mode launcher
│
├── docker/
│   ├── docker-compose.yml               # Full distributed: Redis + API + Worker + FlashTalk + Web
│   ├── docker-compose.unified.yml       # Single-process mode
│   ├── docker-compose.flashtalk.yml     # FlashTalk server only
│   ├── Dockerfile.api
│   ├── Dockerfile.worker
│   ├── Dockerfile.web
│   ├── Dockerfile.flashtalk             # FlashTalk server (CUDA)
│   ├── Dockerfile.flashtalk.ascend      # FlashTalk server (Ascend 910B)
│   └── nginx-web.conf                   # Nginx reverse proxy for SPA
│
├── examples/
│   ├── avatars/
│   │   ├── demo-wav2lip/                # wav2lip fallback frames
│   │   │   └── manifest.json
│   │   ├── demo-musetalk/               # musetalk full_frames
│   │   │   └── manifest.json
│   │   └── flashtalk-demo/              # flashtalk reference image
│   │       └── manifest.json
│   └── audio/                           # Sample audio files
│       └── sample_16k.wav
│
├── tests/
│   ├── conftest.py
│   ├── unit/
│   │   ├── test_config.py
│   │   ├── test_sentence_splitter.py
│   │   ├── test_registry.py
│   │   ├── test_text_sanitize.py
│   │   └── test_video_codec.py
│   ├── integration/
│   │   ├── test_api_smoke.py
│   │   ├── test_edge_tts.py
│   │   └── test_idle_cache.py
│   └── e2e/
│       └── test_unified_flow.py
│
├── docs/
│   ├── architecture.md                  # System architecture & data flow
│   ├── quickstart.md                    # 5-minute getting started
│   ├── deployment.md                    # All 4 deployment modes
│   ├── model-download.md               # Model acquisition guide
│   ├── configuration.md                # Unified config reference
│   ├── api-reference.md                # REST + WebSocket + SSE API
│   ├── avatar-format.md                # Avatar manifest schema
│   ├── model-adapter.md                # How to add new model adapters
│   ├── hardware.md                      # CUDA, Ascend 910B, CPU modes
│   └── developing.md                   # Developer setup guide
│
└── .github/
    ├── workflows/
    │   ├── ci.yml                       # Lint, type check, unit test, frontend build
    │   └── docker.yml                   # Docker image builds
    ├── ISSUE_TEMPLATE/
    │   ├── bug_report.md
    │   └── feature_request.md
    └── PULL_REQUEST_TEMPLATE.md
```

---

## Module Specifications

### 1. `opentalking.core` — Shared Foundation

**Responsibility**: Types, interfaces, configuration, message bus. Zero inference dependencies.

**Key Components**:

- **`config.py`**: Single `Settings` class via `pydantic-settings`:
  ```python
  class Settings(BaseSettings):
      model_config = SettingsConfigDict(
          env_prefix="OPENTALKING_",
          env_file=".env",
      )
      # General
      log_level: str = "INFO"
      # API
      api_host: str = "0.0.0.0"
      api_port: int = 8000
      cors_origins: str = "*"
      # Infrastructure
      redis_url: str = "redis://localhost:6379/0"
      avatars_dir: str = "./examples/avatars"
      worker_url: str = "http://127.0.0.1:9001"
      # FlashTalk Engine
      flashtalk_mode: str = "remote"          # "remote" | "local" | "off"
      flashtalk_ws_url: str = "ws://localhost:8765"
      flashtalk_ckpt_dir: str = "./models/SoulX-FlashTalk-14B"
      flashtalk_wav2vec_dir: str = "./models/chinese-wav2vec2-base"
      flashtalk_port: int = 8765
      flashtalk_device: str = "auto"          # "auto" | "cuda" | "npu" | "cpu"
      flashtalk_gpu_count: int = 8
      # FlashTalk Inference
      flashtalk_frame_num: int = 33
      flashtalk_motion_frames_num: int = 5
      flashtalk_sample_steps: int = 4
      flashtalk_height: int = 768
      flashtalk_width: int = 448
      flashtalk_sample_rate: int = 16000
      flashtalk_tgt_fps: int = 25
      flashtalk_jpeg_quality: int = 40
      # FlashTalk Idle Cache
      flashtalk_idle_cache_chunks: int = 4
      flashtalk_idle_mouth_lock: float = 0.97
      flashtalk_idle_eye_lock: float = 0.65
      # LLM
      llm_base_url: str = ""
      llm_api_key: str = ""
      llm_model: str = "qwen-turbo"
      llm_system_prompt: str = "You are a friendly digital human assistant."
      # TTS
      tts_voice: str = "zh-CN-XiaoxiaoNeural"
      tts_sample_rate: int = 16000
      tts_streaming_decode: bool = True
      # Model
      torch_device: str = "cpu"
      default_model: str = "flashtalk"
  ```

- **Configuration priority** (highest wins):
  1. Environment variables (`OPENTALKING_FLASHTALK_WS_URL=...`)
  2. `.env` file
  3. YAML config file (via `--config` flag)
  4. Built-in defaults

- **Backward compatibility**: Existing `FLASHTALK_*` env vars (without `OPENTALKING_` prefix) supported via aliases.

- **Interfaces**:
  - `ModelAdapter` protocol: `load_model()`, `load_avatar()`, `extract_features()`, `infer()`, `compose_frame()`, `idle_frame()`
  - `TTSAdapter` protocol: `synthesize_stream(text, voice) -> AsyncIterator[AudioChunk]`
  - `LLMAdapter` protocol (NEW): `chat_stream(messages) -> AsyncIterator[str]`

- **Types**: `AudioChunk`, `VideoFrameData`, `SpeechStartedEvent`, `SubtitleChunkEvent`, `SpeechEndedEvent`, `ErrorEvent`, `SessionState` enum

- **Bus**: `publish_event()`, `push_task()` — routes to Redis or InMemoryRedis based on runtime mode

### 2. `opentalking.engine` — FlashTalk 14B Inference Engine

**Responsibility**: Self-contained diffusion inference. No knowledge of REST, WebRTC, TTS, or orchestration.

**Public API** (thin facade in `engine/__init__.py`):
```python
def get_pipeline(world_size, ckpt_dir, wav2vec_dir, cpu_offload=False) -> FlashTalkPipeline
def get_base_data(pipeline, input_prompt, cond_image, base_seed) -> None
def get_audio_embedding(pipeline, audio_array, start=-1, end=-1) -> Tensor
def run_pipeline(pipeline, audio_embedding) -> Tensor
def run_pipeline_deferred(pipeline, audio_embedding) -> tuple[Tensor, Tensor]
def run_pipeline_stream(pipeline, audio_embedding) -> Generator[Tensor]
```

**Internal structure**: FlashTalkPipeline, Wan model (T5, CLIP, VAE, WanModel), wav2vec2 audio encoder, USP distributed parallelism, device abstraction (CUDA/NPU/CPU), attention ops, model configs.

**Key refactoring from current code**:
- Replace file-relative YAML loading (`open("flash_talk/configs/infer_params.yaml")`) with `importlib.resources` so module works regardless of CWD
- Defer `patch_cuda_api_for_npu()` call from import-time to `get_pipeline()` initialization
- All `flash_talk.*` imports become `opentalking.engine.*`

### 3. `opentalking.server` — FlashTalk WebSocket Server

**Responsibility**: Wraps `opentalking.engine` as a WebSocket service for distributed multi-GPU inference.

**Decomposition of current `flashtalk_server.py` (1515 LOC)**:

| New module | LOC (approx) | Responsibility |
|------------|-------------|----------------|
| `ws_server.py` | ~400 | WebSocket message loop, session state machine, init/generate/close handlers |
| `worker_loop.py` | ~150 | Non-rank-0 process: poll for commands, execute, loop |
| `broadcast.py` | ~150 | `broadcast_cmd()`, `broadcast_string()`, `broadcast_audio_embedding()` |
| `idle_cache.py` | ~400 | Idle cache generation, disk persist, mouth/eye masks, crossfade, eye-region constraints |
| `video_codec.py` | ~200 | JPEG encode (ThreadPoolExecutor), decode, VIDX binary wire format, progressive send |
| `__main__.py` | ~50 | CLI arg parsing + rank dispatch |

**Protocol** (unchanged):
- Init: `{"type": "init", "ref_image": base64, "prompt": "...", "seed": 9999}` → `{"type": "init_ok", ...}`
- Generate: `MAGIC_AUDIO + PCM bytes` → `MAGIC_VIDEO + frame_count + [len + JPEG]×N`
- Close: `{"type": "close"}` → `{"type": "close_ok"}`

**Entry point**: `torchrun --nproc_per_node=8 -m opentalking.server --ckpt_dir ... --port 8765`

### 4. `opentalking.models` — Model Adapter Registry

**Responsibility**: Registry of lip-sync model adapters via `@register_model` decorator.

**Adapters**:
- `flashtalk/ws_client.py`: `FlashTalkWSClient` — async WebSocket client for remote FlashTalk server
- `flashtalk/local_adapter.py`: `FlashTalkLocalAdapter` (NEW) — wraps `opentalking.engine` directly, no WS overhead, for single-GPU dev/test
- `musetalk/adapter.py`: MuseTalk inference adapter
- `wav2lip/adapter.py`: Wav2Lip inference adapter

**Key change**: `FlashTalkLocalAdapter` enables co-located mode. Controlled by `OPENTALKING_FLASHTALK_MODE=local|remote`.

### 5. `opentalking.llm` — LLM Integration

**Key change**: Replace `DashScopeLLMClient` with `OpenAICompatibleLLMClient`.

```python
class OpenAICompatibleLLMClient:
    """Works with any /v1/chat/completions endpoint:
    OpenAI, DashScope, Ollama, vLLM, DeepSeek, etc."""

    def __init__(self, base_url: str, api_key: str, model: str):
        ...

    async def chat_stream(self, messages: list[dict]) -> AsyncIterator[str]:
        """Stream LLM response chunks."""
        ...
```

Configured via `OPENTALKING_LLM_BASE_URL`, `OPENTALKING_LLM_API_KEY`, `OPENTALKING_LLM_MODEL`.

### 6. `opentalking.tts`, `opentalking.rtc`, `opentalking.avatars`, `opentalking.events`

These retain the existing OpenTalking design with import path changes (`opentalking_tts.*` → `opentalking.tts.*`, etc.).

### 7. `opentalking.worker` — Session Orchestration

**Key classes**:
- `SessionRunner`: Generic runner for ModelAdapter-based models (wav2lip, musetalk)
- `FlashTalkRunner`: Specialized runner for FlashTalk (LLM streaming, sentence splitting, TTS, FlashTalk generate, idle cache, WebRTC push, interrupt handling)
- `TaskConsumer`: Drains Redis/in-memory task queue, routes to appropriate runner

---

## Data Flow: Full Pipeline

```
User types "Hello" in browser
    │
    ▼
[React App] ──POST /sessions/{id}/speak──▶ [FastAPI (apps/api)]
                                                 │
                                         push_task(redis, {cmd: "speak", text: "Hello"})
                                                 │
                                                 ▼
                                         [TaskConsumer (worker)]
                                                 │
                                                 ▼
                                         [FlashTalkRunner.speak()]
                                                 │
                   ┌─────────────────────────────┼──────────────────┐
                   ▼                             ▼                  ▼
            [LLM Feeder]                  [TTS Worker]        [Consumer]
            OpenAI-compat API             EdgeTTSAdapter        │
            stream response               MP3 → PCM            │
                   │                             │              │
            sentences ──▶ sentence_q      audio chunks ──▶ audio_q
                                                                │
                                                                ▼
                                               [FlashTalkWSClient.generate()]
                                                    or
                                               [FlashTalkLocalAdapter.generate()]
                                                                │
                                                                ▼
                                               AUDI ──▶ [FlashTalk Server 8×GPU]
                                                                │
                                               VIDX ◀── JPEG frames
                                                                │
                                                                ▼
                                               [WebRTCSession: video + audio tracks]
                                                                │
                                                                ▼
                                               [Browser <video> element]

Events (SSE):
  FlashTalkRunner ──publish──▶ Redis/InMemory ──SSE──▶ Browser
  Events: speech.started, subtitle.chunk, speech.ended
```

---

## Deployment Modes

### Mode 1: CLI Tools (No Server)

```bash
# Batch video generation (directly uses engine, no server infra)
python -m opentalking.cli.generate_video \
    --ckpt_dir ./models/SoulX-FlashTalk-14B \
    --wav2vec_dir ./models/chinese-wav2vec2-base \
    --cond_image examples/avatars/flashtalk-demo/ref.jpg \
    --audio_path examples/audio/sample_16k.wav

# Gradio demo
python -m opentalking.cli.gradio_app

# Download models interactively
python -m opentalking.cli.download_models
```

### Mode 2: Unified (Single Process, No Redis)

```bash
opentalking-unified --port 8000
# or: python -m opentalking.apps.unified
```

API + Worker in one process, InMemoryRedis. For FlashTalk: connects to remote server or uses local adapter on single GPU.

### Mode 3: Distributed (Multi-Process)

```bash
# Terminal 1: FlashTalk server on GPU machine
torchrun --nproc_per_node=8 -m opentalking.server \
    --ckpt_dir ./models/SoulX-FlashTalk-14B --port 8765

# Terminal 2: API
opentalking-api

# Terminal 3: Worker
opentalking-worker

# Terminal 4: Frontend
cd apps/web && npm run dev
```

### Mode 4: Docker Compose

```bash
# Full stack (GPU host for flashtalk)
docker compose -f docker/docker-compose.yml up

# Unified mode
docker compose -f docker/docker-compose.unified.yml up

# FlashTalk server only
docker compose -f docker/docker-compose.flashtalk.yml up
```

Docker Compose adds `flashtalk` service alongside existing Redis + API + Worker + Web.

---

## Sensitivity Cleanup

| Issue | Current location | Fix |
|-------|-----------------|-----|
| Hardcoded IP `<internal-ip>` | `ws_client.py`, `task_consumer.py` | Default → `ws://localhost:8765` |
| Password `<redacted>` | `SESSION_SUMMARY.md`, `machine.md` | Remove from repo entirely |
| Absolute paths `<user-home>` | `deploy_ascend_910b.sh`, `test_idle_e2e.py` | Parameterize `${PROJECT_DIR}`, use relative paths |
| DashScope-specific client | `dashscope_client.py` | Generalize to `OpenAICompatibleLLMClient` |
| Internal server IPs | `START_REALTIME.md` | Sanitize to `<your-server-ip>` |

---

## Migration Mapping

### From SoulX-FlashTalk → opentalking

| Source | Destination |
|--------|------------|
| `flash_talk/inference.py` | `src/opentalking/engine/inference.py` |
| `flash_talk/src/accelerator.py` | `src/opentalking/engine/accelerator.py` |
| `flash_talk/src/pipeline/flash_talk_pipeline.py` | `src/opentalking/engine/pipeline/flash_talk_pipeline.py` |
| `flash_talk/src/distributed/` | `src/opentalking/engine/distributed/` |
| `flash_talk/infinite_talk/audio_analysis/` | `src/opentalking/engine/audio/` |
| `flash_talk/infinite_talk/modules/` | `src/opentalking/engine/modules/` |
| `flash_talk/infinite_talk/utils/multitalk_utils.py` | `src/opentalking/engine/audio/loudness.py` |
| `flash_talk/infinite_talk/configs/` | `src/opentalking/engine/configs/` |
| `flash_talk/infinite_talk/distributed/` | `src/opentalking/engine/distributed/` (merge) |
| `flash_talk/wan/` | `src/opentalking/engine/wan/` |
| `flash_talk/configs/infer_params.yaml` | `configs/flashtalk.yaml` |
| `flashtalk_server.py` (1515 LOC) | `src/opentalking/server/` (5 modules) |
| `generate_video.py` | `apps/cli/generate_video.py` |
| `gradio_app.py` | `apps/cli/gradio_app.py` |
| `requirements.txt` | `pyproject.toml [project.optional-dependencies.engine]` |
| `deploy_ascend_910b.sh` | `scripts/deploy_ascend_910b.sh` (parameterized) |

### From OpenTalking → opentalking

| Source | Destination |
|--------|------------|
| `packages/core/src/opentalking_core/` | `src/opentalking/core/` |
| `packages/events/src/opentalking_events/` | `src/opentalking/events/` |
| `packages/avatars/src/opentalking_avatars/` | `src/opentalking/avatars/` |
| `packages/models/src/opentalking_models/` | `src/opentalking/models/` |
| `packages/tts/src/opentalking_tts/` | `src/opentalking/tts/` |
| `packages/llm/src/opentalking_llm/` | `src/opentalking/llm/` |
| `packages/rtc/src/opentalking_rtc/` | `src/opentalking/rtc/` |
| `apps/api/src/opentalking_api/` | `apps/api/` (flatten src/) |
| `apps/worker/src/opentalking_worker/` | `src/opentalking/worker/` |
| `apps/unified/src/opentalking_unified/` | `apps/unified/` |
| `apps/web/` | `apps/web/` |
| `docker-compose.yml` | `docker/docker-compose.yml` (add flashtalk service) |
| `pyproject.toml` | `pyproject.toml` (merge, unified structure) |
| `examples/avatars/` | `examples/avatars/` |

---

## pyproject.toml Design

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "opentalking"
version = "0.1.0"
description = "Real-time digital human framework with FlashTalk 14B inference"
readme = "README.md"
requires-python = ">=3.10"
license = { text = "Apache-2.0" }
dependencies = [
  "fastapi>=0.109",
  "uvicorn[standard]>=0.27",
  "pydantic>=2",
  "pydantic-settings>=2",
  "redis>=5",
  "numpy>=1.24",
  "httpx>=0.26",
  "edge-tts>=6.1",
  "aiortc>=1.6",
  "av>=14",
  "python-multipart>=0.0.9",
  "pillow>=10",
  "websockets>=13",
  "loguru>=0.7",
  "PyYAML>=6",
]

[project.optional-dependencies]
engine = [
  "torch>=2.0",
  "torchaudio>=2.0",
  "diffusers>=0.34",
  "transformers>=4.46",
  "accelerate>=1.0",
  "opencv-python>=4.8",
  "xfuser>=0.4",
  "librosa>=0.10",
  "pyloudnorm",
  "easydict",
  "imageio",
  "imageio-ffmpeg",
  "xformers>=0.0.28",
]
ascend = ["torch-npu>=2.1"]
models = [
  "torch>=2.0",
  "torchaudio>=2.0",
  "opencv-python>=4.8",
  "onnxruntime>=1.16",
]
demo = ["gradio>=5.0"]
dev = [
  "pytest>=7.4",
  "pytest-asyncio>=0.23",
  "ruff>=0.4",
  "mypy>=1.8",
  "pre-commit>=3",
]

[project.scripts]
opentalking-api = "apps.api.main:main"
opentalking-worker = "opentalking.worker.main:main"
opentalking-unified = "apps.unified.main:main"
opentalking-download = "apps.cli.download_models:main"

[tool.setuptools.packages.find]
where = ["src", "apps"]

[tool.ruff]
line-length = 100
target-version = "py310"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

---

## Open-Source Readiness Additions

### Files to Create

- `LICENSE` — Apache 2.0 full text
- `CONTRIBUTING.md` — Coding standards, PR process, testing
- `CODE_OF_CONDUCT.md` — Contributor Covenant
- `.github/workflows/ci.yml` — Lint (ruff), unit tests, frontend build
- `.github/workflows/docker.yml` — Docker image builds
- `.github/ISSUE_TEMPLATE/bug_report.md`
- `.github/ISSUE_TEMPLATE/feature_request.md`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.pre-commit-config.yaml` — ruff + trailing whitespace

### Model Download Experience

`python -m opentalking.cli.download_models` provides:
1. Download SoulX-FlashTalk-14B from HuggingFace (~37GB)
2. Download from ModelScope (China mirror)
3. Download chinese-wav2vec2-base (~400MB)
4. Verify model checksums
5. Download all

Also: `scripts/download_models.sh` for shell-based download.

### CI/CD Pipeline

```yaml
# .github/workflows/ci.yml
jobs:
  lint:
    - ruff check src/ apps/ tests/
  test-unit:
    - pip install -e ".[dev]"
    - pytest tests/unit -v
  test-integration:
    - services: redis:7-alpine
    - pytest tests/integration -v
  frontend:
    - cd apps/web && npm ci && npm run build
```

---

## Known Challenges

1. **Engine import side effects**: `inference.py` calls `patch_cuda_api_for_npu()` at import time and loads YAML via relative path. Must defer NPU patch to `get_pipeline()` and use `importlib.resources` for YAML.

2. **Server decomposition**: The 1515-LOC `flashtalk_server.py` uses extensive `nonlocal` state. Extract into `ServerSession` dataclass to hold audio_buffer, idle_cache, etc.

3. **Dual idle cache implementations**: Both `flashtalk_server.py` and `flashtalk_session_runner.py` have independent idle cache code. Canonical implementation goes in `opentalking.server.idle_cache`, runner uses thin async wrapper.

4. **FlashTalk worker protocol**: The non-rank-0 workers use file-based command dispatch (`/tmp/.flashtalk_cmd_{rank}`). This is functional but fragile; preserve as-is for v0.1.0 but document as known limitation.

---

## Verification Plan

After implementation, verify via:

1. **Unit tests**: `pytest tests/unit -v` — config loading, sentence splitter, registry, text sanitize
2. **Lint**: `ruff check src/ apps/` — no errors
3. **Frontend build**: `cd apps/web && npm ci && npm run build` — builds successfully
4. **CLI smoke test**: `python -m opentalking.cli.generate_video --help` — prints usage without import errors
5. **Server smoke test**: `python -c "from opentalking.engine import get_pipeline; print('OK')"` (with `[engine]` extras)
6. **API smoke test**: `opentalking-unified --port 8000` + `curl http://localhost:8000/health` returns OK
7. **Docker build**: `docker compose -f docker/docker-compose.yml build` — all images build
8. **No secrets scan**: `grep -rn "<redacted>\\|<internal-ip>" . --include="*.py" --include="*.md" --include="*.sh"` — zero hits
9. **Integration test**: Start unified mode, open browser to web UI, create session, send text, verify SSE events flow
