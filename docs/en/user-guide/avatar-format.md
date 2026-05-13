# Avatar Format

An avatar bundle defines the visual identity of a digital human together with the
metadata required to align mouth motion with audio. OpenTalking reads avatar bundles
when a session is created, pairs them with the configured synthesis model (`wav2lip`,
`musetalk`, `flashtalk`, `flashhead`, or `quicktalk`), and drives video generation
from streaming audio input.

This page documents the directory layout, the `manifest.json` schema, the scripts that
generate avatar bundles, and the validation endpoints.

## Directory layout

Each avatar bundle is a single subdirectory containing a `manifest.json` file:

```text
examples/avatars/
├── demo-avatar/
│   ├── manifest.json
│   └── preview.png
├── singer-wav2lip/
│   ├── manifest.json
│   ├── preview.png
│   └── frames/
│       ├── frame_00000.png
│       ├── frame_00001.png
│       └── ...
└── singer-musetalk/
    ├── manifest.json
    ├── preview.png
    └── full_frames/
        └── ...
```

Per-model conventions:

| `model_type` | Required subdirectory | Contents |
|--------------|----------------------|----------|
| `wav2lip` | `frames/` | Ordered image sequence (PNG or JPG), sorted by filename. |
| `musetalk` | `full_frames/` | Ordered image sequence. Future extensions may include `mask/` and `latent/`. |
| `quicktalk` | _none_ | External assets referenced via `metadata.asset_root` and `metadata.template_video`. |
| `flashtalk` | _none_ | Reference identity managed by the model service. |
| `flashhead` | _none_ | Reference identity managed by the model service. |

A `preview.png` file is recommended; the frontend uses it to populate the avatar picker.

## `manifest.json` schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | Yes | Globally unique identifier referenced by the client. |
| `name` | string | No | Display name. Defaults to `id`. |
| `model_type` | enum | Yes | One of `wav2lip`, `musetalk`, `quicktalk`, `flashtalk`, `flashhead`. |
| `fps` | number | Yes | Target output frame rate. Typical value: 25. |
| `sample_rate` | number | Yes | Audio sample rate aligned with the TTS output. Typical value: 16000. |
| `width` | number | Yes | Output video width in pixels. |
| `height` | number | Yes | Output video height in pixels. |
| `version` | string | No | Asset version string. |
| `metadata` | object | No | Arbitrary additional fields, including per-model conventions documented below. |

## Wav2Lip `metadata`

Wav2lip avatars should populate the `metadata` field with mouth localization data:

```json
{
  "source_image_hash": "<sha256>",
  "animation": {
    "mouth_center": [0.5, 0.56],
    "mouth_rx": 0.06,
    "mouth_ry": 0.02,
    "outer_lip": [[0.45, 0.55], [0.5, 0.53], [0.55, 0.55]],
    "inner_mouth": [[0.47, 0.55], [0.53, 0.55], [0.5, 0.57]]
  }
}
```

Coordinates are normalized to the image dimensions. When a single-image wav2lip avatar
is uploaded through `/avatars/custom`, OpenTalking attempts mouth detection using
MediaPipe locally. If detection fails, the upload succeeds without an `animation`
field; in this case, OmniRT's wav2lip backend falls back to its built-in alignment.
The `wav2lip_postprocess_mode` flag controls whether server-side post-processing is
applied; the default is disabled.

## QuickTalk manifest example

```json
{
  "id": "quicktalk-daytime",
  "name": "QuickTalk Daytime",
  "model_type": "quicktalk",
  "fps": 25,
  "sample_rate": 16000,
  "width": 512,
  "height": 512,
  "version": "1.0",
  "metadata": {
    "asset_root": "/path/to/quicktalk/assets",
    "template_video": "/path/to/template.mp4"
  }
}
```

## Avatar bundle preparation

### From a video file

```bash title="terminal"
python scripts/prepare_wav2lip_video_asset.py \
    --source /path/to/source.mp4 \
    --output-dir examples/avatars/my-avatar \
    --avatar-id my-avatar \
    --name "My Avatar" \
    --fps 25
```

The script performs the following steps:

1. Extracts frames using ffmpeg and writes them to `examples/avatars/my-avatar/frames/`.
2. Runs MediaPipe mouth detection and records the results in `metadata.animation`.
3. Generates `manifest.json` and `preview.png`.

### From a single image

```bash title="terminal"
python scripts/prepare_wav2lip_image_asset.py \
    --source /path/to/face.jpg \
    --output-dir examples/avatars/my-avatar-static \
    --avatar-id my-avatar-static
```

This produces a single frame at `frames/frame_00000.png` along with a complete manifest.

### Interactive preparation

```bash title="terminal"
bash scripts/prepare-avatar.sh
```

The script prompts for the source file, model type, and avatar identifier.

## Validation

### REST endpoint

```bash title="terminal"
curl -s http://127.0.0.1:8000/avatars | jq
# [
#   {"id":"demo-avatar","name":"Demo","model_type":"mock","width":512,...},
#   ...
# ]
```

### Programmatic validation

```python
from opentalking.avatar.validator import list_avatar_dirs
from opentalking.avatar.loader import load_avatar_bundle

for path in list_avatar_dirs("./examples/avatars"):
    bundle = load_avatar_bundle(path, strict=True)
    print(bundle.manifest.id, bundle.manifest.model_type)
```

The `strict=True` parameter raises an exception when required fields or subdirectories
are missing; this mode is appropriate for continuous integration.

## Custom upload

The frontend's avatar creation flow invokes `POST /avatars/custom` with a multipart
request body:

| Field | Description |
|-------|-------------|
| `name` | Display name. |
| `base_avatar_id` | Identifier of the avatar whose manifest serves as the template. |
| `image` | Portrait image uploaded by the user. |

The server copies the base avatar's manifest, overrides `id` and `name`, sets
`metadata.custom_avatar=true`, writes the uploaded image to `frames/frame_00000.png`,
and runs mouth detection.

Only avatars marked `custom_avatar=true` may be removed through
`DELETE /avatars/{avatar_id}`.

## Source files

| File | Responsibility |
|------|---------------|
| `opentalking/avatar/loader.py` | Manifest parsing and bundle loading. |
| `opentalking/avatar/validator.py` | Directory traversal and strict validation. |
| `opentalking/avatar/mouth_metadata.py` | MediaPipe mouth detection. |
| `apps/api/routes/avatars.py` | REST endpoint implementations. |
