# IndexTTS Local Deployment

IndexTTS is integrated through OpenTalking's `indextts` provider. Use it for controllable dubbing, emotion control, and cloned voices. This page covers the same-machine HTTP sidecar shape.

## Use Cases

- More voice control than the default Edge TTS path.
- IndexTTS runtime should be isolated from the main OpenTalking process.
- TTS must run locally instead of through a hosted API.

## Weight Preparation

```bash title="Terminal"
cd "$OPENTALKING_HOME"
mkdir -p ./avatar_models/local-audio

export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
uv sync --extra dev --extra models --extra local-audio --python 3.11

python scripts/download_local_audio_models.py \
  --root ./avatar_models/local-audio \
  --model indextts2 \
  --model indextts2-w2v-bert \
  --model indextts2-maskgct \
  --model indextts2-campplus \
  --model indextts2-bigvgan
```

Prepare the runtime:

```bash title="Terminal"
mkdir -p ./avatar_models/local-audio/runtime
GIT_LFS_SKIP_SMUDGE=1 git clone https://github.com/index-tts/index-tts.git ./avatar_models/local-audio/runtime/index-tts
cd ./avatar_models/local-audio/runtime/index-tts
uv sync --python 3.11
uv pip install fastapi "uvicorn[standard]" soundfile
```

## Configuration

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=indextts
OPENTALKING_TTS_INDEXTTS_BACKEND=local
OPENTALKING_TTS_INDEXTTS_SERVICE_URL=http://127.0.0.1:19190/synthesize
```

When OmniRT hosts the IndexTTS runtime, OpenTalking still exposes
`provider=indextts`; `backend=omnirt` switches it to the remote resident service.
OmniRT owns model loading, segmented streaming, and token-window streaming:

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=indextts
OPENTALKING_TTS_INDEXTTS_BACKEND=omnirt
OPENTALKING_TTS_OMNIRT_INDEXTTS_SERVICE_URL=http://127.0.0.1:9012/v1/text2audio/indextts
OPENTALKING_TTS_OMNIRT_INDEXTTS_STREAMING_MODE=token_window
OPENTALKING_TTS_OMNIRT_INDEXTTS_TOKEN_WINDOW_SIZE=40
```

## Start Command

Start the IndexTTS sidecar first, then start OpenTalking. The exact sidecar command depends on the IndexTTS runtime version; make sure it exposes an HTTP endpoint matching `OPENTALKING_TTS_INDEXTTS_SERVICE_URL`.

```bash title="Terminal"
cd "$OPENTALKING_HOME"
cd ./models/local-audio/runtime/index-tts
cd "$OPENTALKING_HOME"
./models/local-audio/runtime/index-tts/.venv/bin/python scripts/local_indextts_service.py --host 127.0.0.1 --port 19092
```

Then start OpenTalking:

```bash title="Terminal"
cd "$OPENTALKING_HOME"
bash scripts/start_unified.sh --backend local --model quicktalk --api-port 8000 --web-port 5173
```

## Verification

```bash title="Terminal"
curl -fsS http://127.0.0.1:8000/health
curl -fsS --max-time 300 http://127.0.0.1:8000/runtime/status | jq '.tts_providers.indextts.backend, .tts_providers.indextts.resolved_provider'
```

After creating a `mock` session, call `/speak` to verify that the TTS provider returns audio.

## Common Errors

| Symptom | Action |
|---------|--------|
| Sidecar API path mismatch | Check that the IndexTTS runtime path matches `SERVICE_URL`. |
| Missing downloaded files | Re-run the download script and confirm all five `indextts2*` model directories exist. |
| Dependency conflicts | Keep the IndexTTS runtime in its own venv. |
| Slow first startup | The downloader resumes partial downloads; confirm the model directories are complete, then restart the sidecar. |
