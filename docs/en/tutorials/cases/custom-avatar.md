# Custom Avatar Case

## Goal

Prepare a custom avatar that OpenTalking can discover and use in a browser session.
The avatar itself is a shared visual asset; this case uses the Wav2Lip preparation
scripts to generate the smallest runnable reference-frame derivatives.

## Prerequisites

- [Mock E2E](mock-e2e.md) has passed.
- [Avatar Format](../../docs/avatar-format.md) has been reviewed.
- A frontal image or template video is available.

## Steps

Create reference-frame derivatives from an image:

```bash title="Terminal"
python scripts/prepare_wav2lip_image_asset.py \
  --image /path/to/avatar.png \
  --output examples/avatars/my-avatar \
  --id my-avatar \
  --name "My Avatar" \
  --fps 25
```

Create reference-frame derivatives from a video:

```bash title="Terminal"
python scripts/prepare_wav2lip_video_asset.py \
  --video /path/to/template.mp4 \
  --output examples/avatars/my-video-avatar \
  --id my-video-avatar \
  --name "My Video Avatar"
```

After the service starts, the Web UI reads avatars from `OPENTALKING_AVATARS_DIR`.

## Verification

```bash title="Terminal"
curl -fsS http://127.0.0.1:8000/avatars | jq '.[] | select(.id=="my-avatar")'
curl -fsS http://127.0.0.1:8000/avatars/my-avatar
```

Make sure `model_type` matches the model selected in the session.

## Troubleshooting

| Symptom | Action |
|---------|--------|
| Avatar does not appear | Check that `manifest.json` exists and `OPENTALKING_AVATARS_DIR` points at the parent directory. |
| Session creation fails | Confirm `model_type` matches the selected model. |
| Preview is unavailable | Keep preview images or frame files inside the avatar directory. |
