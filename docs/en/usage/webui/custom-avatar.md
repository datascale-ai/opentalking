# Custom Avatar

Custom avatars let you bring your own image or video assets into OpenTalking. The recommended first step is an image avatar: it is easier to prepare and faster to validate in WebUI.

## What You Will Build

This page explains:

- What makes a good avatar source asset.
- The difference between image and video avatars.
- How to upload a custom image avatar in WebUI.
- How to prepare Wav2Lip image or video assets with scripts.
- How to troubleshoot missing or low-quality avatars.

## Avatar and Model Compatibility

OpenTalking is gradually decoupling avatars from models so one avatar can be reused where possible, but models still have different asset requirements.

General guidance:

- Image avatars are best for quick validation.
- Video avatars preserve more natural motion but require more preparation.
- QuickTalk can generate a template video from an uploaded image for quick validation.
- Wav2Lip depends more on preprocessed frames, mouth metadata, and manifest files.

If unsure, start with image upload in WebUI.

## Prepare Source Assets

### Image

Recommended image qualities:

- Frontal or near-frontal face.
- Clear face, no occlusion.
- Even lighting, no heavy shadows or overexposure.
- Reasonable resolution; oversized images are resized for realtime use.
- Simple background when possible.

WebUI custom image upload currently has a 10MB limit.

### Video

Video assets are useful when natural posture and background motion matter. Recommended qualities:

- Face stays visible and sharp.
- Head movement is not too large.
- Stable frame rate.
- Short clips for initial validation.

Video assets are currently best prepared with scripts and placed under the avatar directory.

## Create Avatar from Image

### Upload in WebUI

1. Open WebUI.
2. Go to the avatar library.
3. Click the local upload entry.
4. Choose a base avatar.
5. Enter a new avatar name and upload an image.
6. Select the new avatar after processing completes.

![Custom avatar upload entry in WebUI.](../../../assets/images/usage/webui/custom-avatar-upload.png)

*Custom avatar upload entry in WebUI. Click it to choose a local image and create a new avatar.*

If the result is not good, try a clearer image with a more frontal face.

### Prepare a Wav2Lip Image Asset

To create a built-in Wav2Lip avatar from one image:

```bash
uv run python scripts/prepare_wav2lip_image_asset.py \
  --source-image ./assets/my-avatar.png \
  --out ./examples/avatars/my-avatar \
  --avatar-id my-avatar \
  --name "My Avatar"
```

Restart services after generation so WebUI reloads the avatar directory.

## Create Avatar from Video

Prepare a Wav2Lip video avatar:

```bash
uv run python scripts/prepare_wav2lip_video_asset.py \
  --source-video ./assets/my-avatar.mp4 \
  --out ./examples/avatars/my-video-avatar \
  --avatar-id my-video-avatar \
  --name "My Video Avatar" \
  --max-frames 125
```

The script extracts frames, creates preview images, writes `manifest.json`, and stores mouth metadata.

## Select Avatar in WebUI

After creating the asset:

1. Refresh WebUI or restart services.
2. Find the new avatar in the library.
3. Select model and voice.
4. Create a session and test with a short message.

Suggested test:

```text
Hello, please introduce yourself in one sentence.
```

## Common Issues

### Upload Fails

Check image format, file size, and backend logs. Oversized files, unsupported formats, or face detection failures can all cause errors.

### Upload Succeeds but Quality Is Poor

Try better source material. Avatar quality depends heavily on image clarity, face angle, lighting, and model compatibility.

### New Avatar Is Missing in WebUI

Confirm the avatar directory is under `OPENTALKING_AVATARS_DIR` and contains `manifest.json` and `preview.png`. Script-generated assets usually require a service restart or page refresh.

### Deleted Avatar Still Appears

Refresh the page and confirm the backend removed the avatar directory. Only avatars created through WebUI are deletable from the interface.

## Reference: Avatar Format

A typical avatar directory contains:

- `manifest.json`: metadata, model type, and asset references.
- `preview.png`: preview image for WebUI.
- `reference.png`: reference image used by models.
- `frames/`: video or preprocessed frame assets.
- `source/`: original source assets.

A fuller Avatar Format reference will be added later.
