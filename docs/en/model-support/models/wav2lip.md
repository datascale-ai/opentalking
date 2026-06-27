# Wav2Lip

## When to Use Wav2Lip

Wav2Lip is a good fit for quick lip-sync validation, image avatars, short-video avatars, and lightweight local demos. It has a relatively low deployment cost and a clear asset path, which makes it a strong first real model for OpenTalking.

## Requirements

- Python dependencies must include the Wav2Lip extra.
- The model weights must include `wav2lip384.pth` or a compatible checkpoint.
- `s3fd.pth` is required for face detection.
- NVIDIA GPU is recommended; CPU is only for functional checks.
- Avatars use OpenTalking's shared avatar flow; Wav2Lip consumes a reference image,
  preprocessed frames, or a detectable face region when it runs.

## Prepare Weights

Default model directory:

```text
./avatar_models/wav2lip
```

Configurable paths:

```bash
export OPENTALKING_WAV2LIP_MODEL_ROOT=./avatar_models/wav2lip
export OPENTALKING_WAV2LIP_CHECKPOINT=./avatar_models/wav2lip/wav2lip384.pth
```

`s3fd.pth` can live at:

```text
./avatar_models/wav2lip/s3fd.pth
```

Full download commands are in [Wav2Lip Local](../../avatar_models/deployment/wav2lip-local.md).

## Prepare Avatar Derivatives

To pre-generate image-frame assets for Wav2Lip:

```bash
uv run python scripts/prepare_wav2lip_image_asset.py \
  --source-image ./assets/avatar.png \
  --out ./examples/avatars/my-wav2lip \
  --avatar-id my-wav2lip \
  --name "My Wav2Lip Avatar"
```

To pre-generate video-frame assets for Wav2Lip:

```bash
uv run python scripts/prepare_wav2lip_video_asset.py \
  --source-video ./assets/avatar.mp4 \
  --out ./examples/avatars/my-wav2lip-video \
  --avatar-id my-wav2lip-video \
  --name "My Wav2Lip Video Avatar"
```

## Configure Backend

### local

```bash
bash scripts/start_unified.sh --backend local --model wav2lip
```

### omnirt

```bash
bash scripts/start_unified.sh \
  --backend omnirt \
  --model wav2lip \
  --omnirt http://127.0.0.1:9000
```

## Start Service

```bash
bash scripts/start_unified.sh --backend local --model wav2lip
```

## Verify

1. Open the WebUI.
2. Select an available avatar.
3. Select the `wav2lip` model.
4. Send a short sentence and confirm first frame, audio, and lip output.

## Troubleshooting

### Missing checkpoint

Check `OPENTALKING_WAV2LIP_MODEL_ROOT` and `OPENTALKING_WAV2LIP_CHECKPOINT`.

### Missing `s3fd.pth`

Put `s3fd.pth` under `models/wav2lip/`.

### Mouth region looks unnatural

Adjust `OPENTALKING_WAV2LIP_PADS`, the postprocess mode, and the avatar reference image.
