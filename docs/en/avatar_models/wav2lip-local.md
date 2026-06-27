# Wav2Lip Local Single-Machine Deployment

Use this path when you want to validate a lighter lip-sync effect on a single consumer GPU and do not want to introduce a standalone inference service at the beginning. OpenTalking includes the `wav2lip` local adapter and runtime, so you only need local model dependencies and Wav2Lip weights.

#### 1. Install Local Model Dependencies

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
uv sync --extra dev --extra models --python 3.11
source .venv/bin/activate
```

#### 2. Prepare Wav2Lip Weights

Place the weights under repository-root `models/wav2lip/`:

```bash
cd "$DIGITAL_HUMAN_HOME/opentalking"
mkdir -p models/wav2lip

# Install the Hugging Face CLI if it is not already installed.
uv pip install -U "huggingface_hub[cli]"

# Wav2Lip 384 main checkpoint.
hf download Pypa/wav2lip384 \
  wav2lip384.pth \
  --local-dir models/wav2lip

# S3FD face detector checkpoint.
hf download rippertnt/wav2lip \
  s3fd.pth \
  --local-dir models/wav2lip
```

The final layout should look like this:

```text
models/
  wav2lip/
    wav2lip384.pth
    s3fd.pth
```

Check key files:

```bash
stat models/wav2lip/wav2lip384.pth
stat models/wav2lip/s3fd.pth
```

If the server cannot access Hugging Face directly, download the files on a machine with network access first, then sync the same files into `models/wav2lip/` with `rsync` or an offline package.

#### 3. Start OpenTalking With Wav2Lip

```bash
export OPENTALKING_WAV2LIP_MODEL_ROOT="$DIGITAL_HUMAN_HOME/opentalking/models/wav2lip"
export OPENTALKING_WAV2LIP_DEVICE=cuda
export OPENTALKING_WAV2LIP_BATCH_SIZE=16
export OPENTALKING_WAV2LIP_MAX_LONG_EDGE=832
export OPENTALKING_WAV2LIP_FACE_DET_DEVICE=cpu

cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/start_unified.sh --backend local --model wav2lip --api-port 8210 --web-port 5280
```

Open `http://localhost:5280`, select an available avatar, select the `wav2lip` model,
and start a conversation. If you omit `--web-port`, the default frontend URL is
`http://localhost:5173`. The first load initializes the Wav2Lip checkpoint, S3FD face
detector, and avatar cache, which may take tens of seconds.

Local Wav2Lip defaults to `easy_improved` post-processing. The frontend exposes `auto`, `basic`, `opentalking_improved`, and `easy_improved`. The backend also accepts `easy_enhanced` for API/env driven tests, but that mode requires GFPGAN to be installed and `OPENTALKING_WAV2LIP_GFPGAN_CHECKPOINT` to point to a checkpoint.

#### 4. Wav2Lip Single-Machine Tuning

If GPU memory is tight or first-frame latency is high, tune these parameters first:

| Parameter | Recommended default | Purpose |
| --- | --- | --- |
| `OPENTALKING_WAV2LIP_DEVICE` | `cuda` | Select the Wav2Lip runtime device; use `cpu` for debugging. |
| `OPENTALKING_WAV2LIP_BATCH_SIZE` | `16` | Matches the OmniRT CUDA quickstart default; lower it if GPU memory is tight. |
| `OPENTALKING_WAV2LIP_MAX_LONG_EDGE` | `832` | Matches the OmniRT CUDA quickstart default and keeps render latency closer to realtime; set `0` only when prioritizing full source resolution over latency. |
| `OPENTALKING_WAV2LIP_JPEG_QUALITY` | `85` | Output-frame JPEG quality; higher values improve visuals but increase bandwidth. |
| `OPENTALKING_PREWARM_AVATARS` | `singer` | Prewarm commonly used avatars when the service starts. |
