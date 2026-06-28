# F5-TTS Local Deployment

F5-TTS is integrated through OpenTalking's `local_f5_tts` provider. Use it for local voice cloning, short realtime replies, and offline video dubbing. The integration runs as a same-machine HTTP sidecar so the OpenTalking main process stays isolated from F5-TTS runtime and CUDA dependencies.

## Use Cases

- Local voice cloning without a hosted TTS API.
- A 3-15 second reference clip and matching transcript are available.
- F5-TTS dependencies should stay outside the main OpenTalking venv.

## Weight Preparation

Use a single local audio model root, for example `$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT`:

```bash title="Terminal"
cd "$OPENTALKING_HOME"
export OPENTALKING_LOCAL_AUDIO_MODEL_ROOT="${OPENTALKING_LOCAL_AUDIO_MODEL_ROOT:-$OPENTALKING_HOME/models/local-audio}"

python scripts/download_local_audio_models.py \
  --root "$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT" \
  --model f5-tts-v1-base
```

The downloader maps `SWivid/F5-TTS` `F5TTS_v1_Base/model_1250000.safetensors` to:

```text
$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT/SWivid__F5-TTS__F5TTS_v1_Base/model_1250000.safetensors
```

Prepare the runtime and sidecar venv:

```bash title="Terminal"
mkdir -p "$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT/runtime"
cd "$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT/runtime"

if [ ! -d F5-TTS/.git ]; then
  git clone https://github.com/SWivid/F5-TTS.git F5-TTS
fi

python3 -m venv --system-site-packages "$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT/runtime/.venv-f5-tts-system"
. "$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT/runtime/.venv-f5-tts-system/bin/activate"
pip install -U pip wheel setuptools
pip install --no-deps -e "$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT/runtime/F5-TTS"
pip install fastapi "uvicorn[standard]" soundfile cached_path hydra-core ema_pytorch vocos x_transformers transformers_stream_generator rjieba pypinyin tomli bitsandbytes pydub torchcodec torchdiffeq unidecode wandb
```

## Configuration

```env title=".env"
OPENTALKING_TTS_DEFAULT_PROVIDER=local_f5_tts
OPENTALKING_TTS_LOCAL_F5_TTS_SERVICE_URL=http://127.0.0.1:19095/synthesize
OPENTALKING_LOCAL_AUDIO_MODEL_ROOT=./models/local-audio
OPENTALKING_TTS_LOCAL_F5_TTS_RUNTIME_DIR=./models/local-audio/runtime/F5-TTS
OPENTALKING_TTS_LOCAL_F5_TTS_DEVICE=cuda
```

## Voice Cloning

`local_f5_tts` requires reference audio. Upload a clone voice through the API, or prepare the directory manually:

```text
$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT/voices/clones/my-f5-voice/
  prompt.wav
  prompt.txt
  meta.json
```

Example `meta.json`:

```json
{"provider":"local_f5_tts"}
```

After upload, `/api/voices?provider=local_f5_tts` returns the voice id. TTS preview, realtime dialogue, and video generation can all use that voice.

## Start Command

Start the F5-TTS sidecar first, then OpenTalking:

```bash title="Terminal"
cd "$OPENTALKING_HOME"
export OPENTALKING_LOCAL_AUDIO_MODEL_ROOT="${OPENTALKING_LOCAL_AUDIO_MODEL_ROOT:-$OPENTALKING_HOME/models/local-audio}"
export OPENTALKING_F5_TTS_VENV_DIR="$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT/runtime/.venv-f5-tts-system"
bash scripts/quickstart/start_local_f5_tts.sh --port 19095

export OPENTALKING_TTS_DEFAULT_PROVIDER=local_f5_tts
export OPENTALKING_TTS_LOCAL_F5_TTS_SERVICE_URL=http://127.0.0.1:19095/synthesize
python -m apps.api.main
```

## Verification

```bash title="Terminal"
curl -fsS http://127.0.0.1:19095/health
curl -fsS http://127.0.0.1:8000/health
```

TTS preview should use provider `local_f5_tts` and a clone voice with `prompt.wav`. Save the result as WAV and verify the spoken text and voice by ASR or listening.

## Benchmark Log

| Item | Command / API | Target | Measured |
|------|---------------|--------|----------|
| TTS preview | `/tts/preview` + SenseVoiceSmall ASR | Playable WAV, correct text | Passed: preview returned a 16 kHz mono WAV; SenseVoiceSmall ASR matched the target text. |
| Realtime dialogue | local mode dialogue / warm TTS | RTF < 1.0 | Passed: warm RTF 0.278 for 3.31s audio in 0.918s; prior warm checks were 0.386 and 0.518, all below 1 |
| Offline video | video generation API / CLI | Generation succeeds, audio drives avatar | Passed: QuickTalk + F5 clone voice generated an MP4; ffprobe showed H.264 video and 16 kHz mono AAC audio. |

## Common Errors

| Symptom | Action |
|---------|--------|
| `Missing F5-TTS checkpoint` | Confirm `model_1250000.safetensors` is under `SWivid__F5-TTS__F5TTS_v1_Base`. |
| `requires prompt_audio` | Select a clone voice or set `OPENTALKING_TTS_LOCAL_F5_TTS_PROMPT_AUDIO`. |
| Dependency conflicts | Do not run the sidecar from OpenTalking's main `.venv`; use a separate venv such as `$OPENTALKING_LOCAL_AUDIO_MODEL_ROOT/runtime/.venv-f5-tts-system` and reuse the host PyTorch/CUDA environment when appropriate. |
| Slow first request | Set `OPENTALKING_TTS_LOCAL_F5_TTS_PRELOAD=1` and run a short warm-up request after startup. |
| QuickTalk v3 reshape error | Keep `OPENTALKING_QUICKTALK_RESOLUTION=256` for the current TorchScript export when generating video; 160/128 resolution makes internal feature shapes mismatch. |
