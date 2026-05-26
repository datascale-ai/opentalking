# Local STT/TTS + QuickTalk

This page describes a single-machine path for private validation:

- STT: local `SenseVoiceSmall`, CPU by default.
- TTS: local `Fun-CosyVoice3-0.5B-2512`, served through the `local_cosyvoice` service.
- Video: local `QuickTalk`, CUDA by default.
- LLM: still configured through an OpenAI-compatible endpoint. If you already operate a local LLM server, point `OPENTALKING_LLM_BASE_URL` to that service.

This path keeps the existing OpenTalking `/sessions/*`, `/tts/preview`, and session runner protocols unchanged. The frontend only chooses the local or API provider before a session starts. If an API provider is selected and its key is missing, startup fails before entering the digital-human session; OpenTalking does not silently fall back to local or cloud providers.

## Hardware Guidance

| Component | Default placement | Guidance |
|-----------|-------------------|----------|
| SenseVoiceSmall | CPU | Usually enough for short utterances and saves VRAM. |
| Fun-CosyVoice3-0.5B-2512 | `cuda:0` | 12GB VRAM is recommended; use API TTS first on 8GB machines. |
| QuickTalk | `cuda:0` | Watch peak VRAM and first-turn warmup when sharing the GPU with local TTS. |

## Install Dependencies

```bash title="terminal"
cd "$DIGITAL_HUMAN_HOME/opentalking"
uv sync --extra dev --extra models --extra local-audio --extra local-cosyvoice-service --python 3.11
source .venv/bin/activate
```

## Download Local Audio Models

Do not commit model weights. The download helper uses ModelScope for these models by default; configure a Hugging Face mirror only for HF-backed models.

```bash title="terminal"
python scripts/download_local_audio_models.py \
  --root ./models/local-audio \
  --model sensevoice-small \
  --model fun-cosyvoice3-0.5b-2512
```

Expected layout:

```text
models/local-audio/
  iic__SenseVoiceSmall/
  FunAudioLLM__Fun-CosyVoice3-0.5B-2512/
```

## Prepare QuickTalk Weights

Place QuickTalk weights, HuBERT files, and InsightFace dependencies as described in [QuickTalk](quicktalk.md):

```text
models/quicktalk/checkpoints/
```

The key setting is `OPENTALKING_QUICKTALK_ASSET_ROOT`, which must point to the directory containing `checkpoints/`.

## Prepare the CosyVoice Runtime

The recommended `local_cosyvoice` shape is a standalone Python service. Runtime source should stay outside git-tracked files; placing it under the model directory is fine:

```bash title="terminal"
mkdir -p ./models/local-audio/runtime
git clone https://github.com/FunAudioLLM/CosyVoice.git ./models/local-audio/runtime/CosyVoice
cd ./models/local-audio/runtime/CosyVoice
git submodule update --init --recursive
```

## `.env` Example

```env title=".env"
# LLM: separate module. Use DashScope, OpenAI, vLLM, Ollama, or a local OpenAI-compatible service.
OPENTALKING_LLM_PROVIDER=openai_compatible
OPENTALKING_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENTALKING_LLM_API_KEY=<llm-key>
OPENTALKING_LLM_MODEL=qwen-flash

# STT: local SenseVoiceSmall
OPENTALKING_STT_DEFAULT_PROVIDER=sensevoice
OPENTALKING_STT_ENABLED_PROVIDERS=sensevoice,dashscope
OPENTALKING_STT_SENSEVOICE_MODEL=iic/SenseVoiceSmall
OPENTALKING_STT_SENSEVOICE_MODEL_DIR=./models/local-audio/iic__SenseVoiceSmall
OPENTALKING_STT_SENSEVOICE_DEVICE=cpu

# TTS: local CosyVoice3
OPENTALKING_TTS_DEFAULT_PROVIDER=local_cosyvoice
OPENTALKING_TTS_ENABLED_PROVIDERS=local_cosyvoice,dashscope,edge
OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL=FunAudioLLM/Fun-CosyVoice3-0.5B-2512
OPENTALKING_TTS_LOCAL_COSYVOICE_MODEL_DIR=./models/local-audio/FunAudioLLM__Fun-CosyVoice3-0.5B-2512
OPENTALKING_TTS_LOCAL_COSYVOICE_RUNTIME_DIR=./models/local-audio/runtime/CosyVoice
OPENTALKING_TTS_LOCAL_COSYVOICE_SERVICE_URL=http://127.0.0.1:19090/synthesize
OPENTALKING_TTS_LOCAL_COSYVOICE_DEVICE=cuda:0

# Video: QuickTalk local
OPENTALKING_DEFAULT_MODEL=quicktalk
OPENTALKING_QUICKTALK_BACKEND=local
OPENTALKING_QUICKTALK_ASSET_ROOT=./models/quicktalk
OPENTALKING_QUICKTALK_WORKER_CACHE=1
OPENTALKING_TORCH_DEVICE=cuda:0
```

If users can switch the frontend to API STT/TTS, configure the provider-specific keys explicitly:

```env title=".env"
OPENTALKING_STT_DASHSCOPE_API_KEY=<dashscope-stt-key>
OPENTALKING_TTS_DASHSCOPE_API_KEY=<dashscope-tts-key>
```

## Startup Order

Start the local TTS service first:

```bash title="terminal"
OPENTALKING_TTS_LOCAL_COSYVOICE_PRELOAD=1 \
python scripts/local_cosyvoice_service.py --host 127.0.0.1 --port 19090
```

Start OpenTalking:

```bash title="terminal"
bash scripts/start_unified.sh --backend local --model quicktalk
```

To set ports explicitly:

```bash title="terminal"
bash scripts/start_unified.sh --backend local --model quicktalk --api-port 8210 --web-port 5280
```

## Verification

```bash title="terminal"
curl -fsS http://127.0.0.1:19090/health
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/api/runtime/status
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="quicktalk")'
```

Expected state:

- `stt_provider` is `sensevoice`.
- `tts_provider` is `local_cosyvoice`.
- `quicktalk_backend` is `local`.
- `/models` reports `quicktalk.connected=true` and `reason=local_runtime`.

In the frontend, select `Local SenseVoiceSmall`, `Local CosyVoice3-0.5B-2512`, and a QuickTalk avatar, then test:

1. Text input: `LLM -> local_cosyvoice -> QuickTalk -> WebRTC`.
2. Microphone input: `SenseVoiceSmall -> LLM -> local_cosyvoice -> QuickTalk -> WebRTC`.
3. `/tts/preview`: confirm that local system voices and cloned voices play.

## Notes

- `*_DEFAULT_PROVIDER` only controls the default selection. It is not a failure fallback chain.
- LLM, STT, and TTS keys are independent. `DASHSCOPE_API_KEY` does not automatically configure any module.
- The CosyVoice3 service returns audio as a stream, but first-chunk latency still depends on model inference and warmup.
- On 8GB VRAM machines, keep `SenseVoiceSmall CPU + QuickTalk local` and use DashScope or Edge TTS first if local TTS is slow or OOMs.
- Weights, runtime checkouts, avatar caches, and logs are deployment artifacts and should not be committed.
