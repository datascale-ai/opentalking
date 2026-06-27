# Qwen3-TTS Local Deployment

Qwen3-TTS is integrated through OpenTalking's `local_qwen3_tts` provider. It runs as a local HTTP sidecar and is useful for private deployments that need Qwen3-TTS Base voice-cloning behavior.

## Use Cases

- Local Qwen3-TTS Base generation or voice cloning is required.
- The TTS runtime should be isolated from the main OpenTalking process.
- Reference audio and reference text are available for the Base model's voice-clone input.

## Weight Preparation

```bash title="Terminal"
cd "$OPENTALKING_HOME"
mkdir -p ./avatar_models/local-audio

uv pip install -U "huggingface_hub[cli]"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

hf download Qwen/Qwen3-TTS-12Hz-0.6B-Base \
  --local-dir ./avatar_models/local-audio/Qwen__Qwen3-TTS-12Hz-0.6B-Base
```

## Sidecar Environment

Use a separate venv for Qwen3-TTS to avoid dependency conflicts with the main OpenTalking environment:

```bash title="Terminal"
cd "$OPENTALKING_HOME"
uv venv .venv-qwen3-tts --python 3.11
source .venv-qwen3-tts/bin/activate
uv pip install -e ".[local-qwen3-tts-service]"
```

## Configuration

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=local_qwen3_tts
OPENTALKING_LOCAL_QWEN3_TTS_SERVICE_URL=http://127.0.0.1:19091/synthesize
OPENTALKING_LOCAL_QWEN3_TTS_MODEL_DIR=./avatar_models/local-audio/Qwen__Qwen3-TTS-12Hz-0.6B-Base
OPENTALKING_LOCAL_QWEN3_TTS_DEVICE=cuda:0
OPENTALKING_LOCAL_QWEN3_TTS_DTYPE=bfloat16
OPENTALKING_LOCAL_QWEN3_TTS_REF_AUDIO=/path/to/reference.wav
OPENTALKING_LOCAL_QWEN3_TTS_REF_TEXT=Transcript matching the reference audio
```

## Start Command

Start the Qwen3-TTS sidecar first:

```bash title="Terminal"
cd "$OPENTALKING_HOME"
source .venv-qwen3-tts/bin/activate
python scripts/local_qwen3_tts_service.py --host 127.0.0.1 --port 19091
```

Start OpenTalking from another terminal:

```bash title="Terminal"
cd "$OPENTALKING_HOME"
bash scripts/start_unified.sh --backend mock --model mock --api-port 8000 --web-port 5173
```

## Verification

```bash title="Terminal"
curl -fsS http://127.0.0.1:19091/health
curl -s -X POST http://127.0.0.1:19091/synthesize \
  -H 'content-type: application/json' \
  -d '{"text":"Hello, this is a local Qwen3-TTS test."}' \
  --output /tmp/qwen3-tts-test.wav
```

## Common Errors

| Symptom | Action |
|---------|--------|
| `reference audio and reference text` error | The Base model requires reference audio and text; configure `REF_AUDIO` and `REF_TEXT`. |
| Model directory not found | Check that `OPENTALKING_LOCAL_QWEN3_TTS_MODEL_DIR` points to the downloaded directory. |
| Dependency conflicts | Use the separate `.venv-qwen3-tts`; do not install sidecar dependencies into the main `.venv`. |
