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
export OPENTALKING_WAV2LIP_BATCH_SIZE=4
export OPENTALKING_WAV2LIP_MAX_LONG_EDGE=768

cd "$DIGITAL_HUMAN_HOME/opentalking"
bash scripts/start_unified.sh --backend local --model wav2lip --api-port 8210 --web-port 5280
```

Open `http://localhost:5173`, select a built-in Wav2Lip avatar such as `singer`, `office-woman`, or `ancient-beauty`, select the `wav2lip` model, and start a conversation. The first load initializes the Wav2Lip checkpoint, S3FD face detector, and avatar cache, which may take tens of seconds.

#### 4. Wav2Lip Single-Machine Tuning

If GPU memory is tight or first-frame latency is high, tune these parameters first:

| Parameter | Recommended default | Purpose |
| --- | --- | --- |
| `OPENTALKING_WAV2LIP_DEVICE` | `cuda` | Select the Wav2Lip runtime device; use `cpu` for debugging. |
| `OPENTALKING_WAV2LIP_BATCH_SIZE` | `4` or `8` | Lower values reduce peak memory; higher values improve throughput. |
| `OPENTALKING_WAV2LIP_MAX_LONG_EDGE` | `768` | Limit the long edge of input avatars to reduce memory and preprocessing cost. |
| `OPENTALKING_WAV2LIP_JPEG_QUALITY` | `85` | Output-frame JPEG quality; higher values improve visuals but increase bandwidth. |
| `OPENTALKING_PREWARM_AVATARS` | `singer` | Prewarm Wav2Lip avatars when the service starts. |
