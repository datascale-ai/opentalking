# Quickstart

This guide walks through a complete end-to-end conversation with a digital human using
the mock synthesis path. The mock path requires no GPU and no pre-downloaded model
weights, making it suitable for first-time installation and CI environments.

The resulting environment exposes a web interface at `http://localhost:5173` where audio
input is streamed through speech recognition, a language model, and text-to-speech, with
synthesized video frames delivered over WebRTC.

## Prerequisites

| Component | Minimum version | Purpose |
|-----------|-----------------|---------|
| Python | 3.9 (3.11 recommended) | Server runtime |
| Node.js | 18 | React frontend toolchain |
| ffmpeg | Recent stable release | Audio decoding for the TTS pipeline |
| DashScope API key | — | Required for the default language model (`qwen-flash`) and speech recognition (`paraformer-realtime-v2`). Apply at [bailian.console.aliyun.com](https://bailian.console.aliyun.com). |

GPU and NPU resources are not required for the quickstart. CUDA or Ascend hardware is
only necessary when switching to a real talking-head model in [Step 5](#5-enable-a-talking-head-model).

## 1. Install from source

```bash title="terminal"
git clone https://github.com/datascale-ai/opentalking.git
cd opentalking

python3 -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"
cp .env.example .env
```

## 2. Configure required credentials

Configure the following two variables in `.env`. All remaining settings have working
defaults and may be left unchanged.

```env title=".env"
OPENTALKING_LLM_API_KEY=<dashscope-api-key>
DASHSCOPE_API_KEY=<dashscope-api-key>
```

Both variables must be set to the same DashScope API key. `OPENTALKING_LLM_API_KEY` is
consumed by the language model client; `DASHSCOPE_API_KEY` is read directly by the
DashScope SDK used for speech recognition.

!!! note "Alternative language model providers"
    Any OpenAI-compatible endpoint may be used in place of DashScope. When switching
    providers, also update `OPENTALKING_LLM_BASE_URL` and `OPENTALKING_LLM_MODEL`. See
    [Configuration](configuration.md#1-language-model-speech-recognition-and-text-to-speech).

## 3. Start the services

```bash title="terminal"
bash scripts/quickstart/start_all.sh --mock
```

The script starts two processes:

1. **OpenTalking unified server** at `http://127.0.0.1:8000`, providing the FastAPI
   endpoints for sessions, avatars, server-sent events, and WebRTC signaling.
2. **Frontend development server** at `http://localhost:5173`, serving the Vite-built
   React client.

The mock synthesis backend runs in-process and does not require OmniRT or any external
inference service.

## 4. Initiate a conversation

Open <http://localhost:5173> in a Chromium-based browser. WebRTC support is required.

1. Select `demo-avatar` from the avatar list.
2. Select `mock` from the model selector.
3. Click the microphone icon and begin speaking. The user interface streams transcripts,
   model output, synthesized audio, and rendered video frames in real time.

The mock backend returns a placeholder image for each audio chunk, allowing end-to-end
validation of the pipeline before a real model is integrated.

## 5. Enable a talking-head model

Once the mock path has been verified, the system may be reconfigured to use a real
talking-head model. The complete per-model weight download and startup procedures are
documented in [Models](../model-deployment/index.md). The shortest paths are:

=== "wav2lip"

    Lightweight lip-synchronization model suitable for a single NVIDIA 3090-class GPU.
    The preferred deployment direction is local or direct single-model backend; the
    current quickstart uses OmniRT as the runnable compatibility path until the local
    Wav2Lip adapter is bundled.

    ```bash title="terminal"
    # Run from a separate terminal. OmniRT must be checked out next to opentalking/.
    bash scripts/quickstart/start_omnirt_wav2lip.sh --device cuda
    ```

    Add the following entry to `.env`:

    ```env
    OMNIRT_ENDPOINT=http://127.0.0.1:9000
    ```

    Restart `start_all.sh` and select `wav2lip` in the model selector. For
    China-friendly download alternatives, see
    [Models → Wav2Lip](../model-deployment/talking-head.md#wav2lip).

=== "FlashTalk"

    SoulX FlashTalk-14B end-to-end talking-head model, requiring an NVIDIA 4090 or
    A100-class GPU.

    ```bash title="terminal"
    bash scripts/quickstart/start_omnirt_flashtalk.sh --device cuda
    ```

    Set the OmniRT endpoint:

    ```env
    OMNIRT_ENDPOINT=http://127.0.0.1:9000
    ```

    Select `flashtalk` in the model selector. For FlashTalk weight directories,
    CUDA/Ascend startup, and domestic mirror links, see
    [Models → FlashTalk](../model-deployment/talking-head.md#flashtalk).

=== "Ascend 910B"

    NPU evaluation is best done from source on the host CANN environment. See
    [From source → Ascend 910B](install-from-source.md#ascend-910b).

## 6. Verify and shut down

Verify the running services:

```bash title="terminal"
bash scripts/quickstart/status.sh
```

The output reports the state of the unified server, frontend, and OmniRT. To stop all
processes started by the quickstart:

```bash title="terminal"
bash scripts/quickstart/stop_all.sh
```

## Troubleshooting

The following table lists common installation issues and their resolutions.

| Symptom | Resolution |
|---------|------------|
| `ffmpeg: not found` during TTS decoding | Install ffmpeg. On macOS: `brew install ffmpeg`. On Debian/Ubuntu: `apt install ffmpeg`. |
| Language model returns HTTP 401 | Ensure `OPENTALKING_LLM_API_KEY` and `DASHSCOPE_API_KEY` are both set to the same DashScope key. |
| Browser reports WebRTC is unavailable | Use a Chromium-based browser. Safari requires `OPENTALKING_API_HOST=127.0.0.1` and a matching CORS origin. |
| Port 8000 is already in use | Override the bound ports: `bash scripts/quickstart/start_all.sh --mock --api-port 8010 --web-port 5180`. |
| OmniRT exits during startup | Inspect the log file referenced in the OmniRT script output (typically `~/logs/omnirt-wav2lip.log`). |

## Next steps

- [Configuration](configuration.md) — reference for all environment variables and YAML fields.
- [Models](../model-deployment/index.md) — end-to-end setup for each supported model backend.
- [Deployment](deployment.md) — multi-process deployment, Docker Compose, and production guidance.
- [Architecture](../developer-guide/architecture.md) — system internals and event bus schema.
- [API Reference](../api-reference/index.md) — complete HTTP and WebSocket endpoint documentation.
