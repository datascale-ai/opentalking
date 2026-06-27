# FasterLivePortrait

## When to Use FasterLivePortrait

FasterLivePortrait is a good fit for realtime portrait driving on a single CUDA GPU. In OpenTalking it is integrated through OmniRT and currently supports two workflows:

- **Realtime conversation**: the selected digital-human avatar is the source; TTS/audio is converted into motion by JoyVASA, then FasterLivePortrait pastes the animated face back into the original avatar image.
- **Video Clone**: the selected avatar remains the source; browser camera frames or an uploaded selfie video act as the driving video for expression, mouth, and head motion.

Realtime conversation still uses the normal OpenTalking LLM / STT / TTS / WebRTC session path. Video Clone is video-driven only and does not enter the LLM, TTS, or STT conversation chain.

![FasterLivePortrait Video Clone workspace](../../../assets/images/model-support/fasterliveportrait-video-clone.png)

## Concept Boundaries

| Concept | Meaning |
| --- | --- |
| `source` | A digital-human image or video asset from the OpenTalking avatar library. This is the character shown in the output. |
| `driving` | Browser camera frames or an uploaded selfie video. This only provides expression, mouth, and head motion. |
| Pasteback | Paste the animated face region back into the original source composition to preserve body, background, and aspect ratio. |
| Crop driving | Crop the driving video's face region before driving. In Video Clone it can be disabled when full-frame detection or preview is preferable. |

Video Clone does not use the camera user as the source. The camera or uploaded video is only the driving input.

## Recommended Runtime Backend

Use `omnirt` for FasterLivePortrait. OpenTalking owns WebUI, avatar selection, session or Video Clone bridge, playback, and parameter updates. OmniRT owns FasterLivePortrait, JoyVASA, TensorRT/ONNXRuntime components, and model weights.

| Capability | OpenTalking entry | OmniRT entry |
| --- | --- | --- |
| Realtime audio-driven conversation | Normal session creation and `/sessions/{id}/speak` | `/v1/audio2video/fasterliveportrait` |
| Video-driven Video Clone | WebUI Video Clone workspace | `/v1/video2video/fasterliveportrait` |
| Model status | `/models` or WebUI status | `/v1/audio2video/models` |

## Weights and Source Requirements

OmniRT needs a FasterLivePortrait source checkout and a checkpoint directory. Public docs should describe paths with environment variables instead of placing model files inside the OpenTalking repository:

```bash title="terminal"
export DIGITAL_HUMAN_HOME=/opt/digital_human
export OPENTALKING_HOME="$DIGITAL_HUMAN_HOME/opentalking"
export OMNIRT_HOME="$DIGITAL_HUMAN_HOME/omnirt"
export FASTERLIVEPORTRAIT_HOME="$DIGITAL_HUMAN_HOME/FasterLivePortrait"
export OMNIRT_MODEL_ROOT="$DIGITAL_HUMAN_HOME/models"
```

The checkpoint directory must include at least:

```text
$OMNIRT_MODEL_ROOT/FasterLivePortrait/checkpoints/
  JoyVASA/
    motion_generator/motion_generator_hubert_chinese.pt
    motion_template/motion_template.pkl
  chinese-hubert-base/
    config.json
    preprocessor_config.json
    pytorch_model.bin
  liveportrait/ or appearance_feature_extractor.onnx and other FasterLivePortrait ONNX/TRT files
```

Preflight check:

```bash title="terminal"
test -f "$OMNIRT_MODEL_ROOT/FasterLivePortrait/checkpoints/JoyVASA/motion_generator/motion_generator_hubert_chinese.pt"
test -f "$OMNIRT_MODEL_ROOT/FasterLivePortrait/checkpoints/JoyVASA/motion_template/motion_template.pkl"
test -f "$OMNIRT_MODEL_ROOT/FasterLivePortrait/checkpoints/chinese-hubert-base/pytorch_model.bin"
```

## Start OmniRT

```bash title="terminal"
cd "$OMNIRT_HOME"
uv sync --extra server --extra fasterliveportrait --python 3.11

OMNIRT_FASTLIVEPORTRAIT_RUNTIME=1 \
OMNIRT_FASTLIVEPORTRAIT_LOAD_MODELS=1 \
OMNIRT_FASTLIVEPORTRAIT_ROOT="$FASTERLIVEPORTRAIT_HOME" \
OMNIRT_FASTLIVEPORTRAIT_CHECKPOINTS_DIR="$OMNIRT_MODEL_ROOT/FasterLivePortrait/checkpoints" \
OMNIRT_FASTLIVEPORTRAIT_CFG=configs/trt_infer.yaml \
OMNIRT_FASTLIVEPORTRAIT_DEVICE=cuda:0 \
OMNIRT_FASTLIVEPORTRAIT_JPEG_QUALITY=85 \
uv run omnirt serve-avatar-ws --host 0.0.0.0 --port 9000 --backend cuda
```

Verify OmniRT model status:

```bash title="terminal"
curl -s http://127.0.0.1:9000/v1/audio2video/models | jq '.statuses[] | select(.id=="fasterliveportrait")'
```

The expected result has `connected=true`.

!!! tip "Next step"
    After OmniRT returns `connected=true`, continue with [Start OpenTalking WebUI](#start-opentalking-webui). That section starts OpenTalking API and the frontend page. For general startup script details, see [Command Line Tools](../../usage/cli.md). For ports, host binding, and OmniRT endpoint parameters, see [Advanced CLI Arguments](../../usage/cli-advanced.md).

## Start OpenTalking WebUI

OpenTalking uses FasterLivePortrait through OmniRT. The command below starts the OpenTalking API / unified backend, and `start_unified.sh` also starts WebUI:

```bash title="terminal"
cd "$OPENTALKING_HOME"
export OPENTALKING_OMNIRT_ENDPOINT=http://127.0.0.1:9000
export OMNIRT_ENDPOINT=http://127.0.0.1:9000
bash scripts/start_unified.sh --backend omnirt --model fasterliveportrait
```

After startup, the terminal prints the WebUI URL. The default is `http://127.0.0.1:5173`. After opening the page:

- For audio-driven realtime conversation: open Realtime Conversation, select FasterLivePortrait, and select a compatible avatar.
- For camera or uploaded-video driving: open Video Clone and follow the [Video Clone guide](../../usage/webui/video-clone.md).

For Video Clone validation, OpenTalking API still needs to reach OmniRT and `/models` should report `fasterliveportrait` as connected.

## Realtime Conversation Parameters

Realtime conversation defaults live in `configs/synthesis/fasterliveportrait.yaml`. Common fields:

| Parameter | Effect | Common setting |
| --- | --- | --- |
| `width` / `height` | Output shape | Start from `448` width for realtime |
| `fps` | Output frame rate | Default `25` |
| `animation_region` | Driven region | Conversation default is `lip` to reduce exaggerated full-face motion |
| `head_motion_multiplier` | Overall head motion | `0.2-0.8` |
| `pose_motion_multiplier` | Pose motion | `0.2-0.5` |
| `mouth_open_multiplier` | Mouth opening | `1.0-1.4` |
| `mouth_corner_multiplier` | Mouth-corner movement | `0.7-1.0` |
| `driving_multiplier` | Overall keypoint amplitude | `0.8-1.2` |
| `cfg_scale` | JoyVASA audio-following strength | `3.5-4.5` |
| `flag_stitching` | Stabilize face boundary | Keep enabled |
| `flag_normalize_lip` | Reduce initial mouth-shape offset | Keep enabled |
| `flag_relative_motion` | Preserve source base pose | Enabled by default for conversation |
| `flag_lip_retargeting` | Improve mouth following | Enable by effect |

After selecting FasterLivePortrait in the frontend, these amplitude controls can be updated live. During a running session, updates usually take effect on the next audio chunk.

## Video Clone Parameters

The Video Clone workspace provides source selection, driving input, and realtime controls. The first path is live camera driving; uploaded driving video is useful for validation and near-realtime testing.

| Control | Effect | Suggestion |
| --- | --- | --- |
| Camera | Select browser input device | Allow browser camera permission on first use |
| FPS | Camera sampling rate | Start with `12` or `15` |
| Resolution | Driving frame sampling size | Start with `448px` |
| Mirror preview | Local preview only | Usually enabled for selfie camera |
| Driving region | `all` / `exp` / `pose` / `lip` / `eye` | Use `lip` or `exp` for mouth tests; `all` for richer expression |
| Pasteback | Paste output into source image | Keep enabled to avoid an over-zoomed head-only result |
| Crop driving face | Crop driving input | Disable when uploaded-video aspect ratio or face position looks wrong |
| Lip retargeting | Improve mouth following | Try when the mouth looks puffy or does not open enough |
| Relative motion | Preserve source pose offset | Usually disable this when lip retargeting is enabled |

If uploaded video driving makes the mouth look puffy or too closed, debug in this order:

1. Disable `Crop driving face` to make sure the driving video is not cropped too tightly.
2. Enable `Pasteback` so the output keeps the original source composition.
3. Enable `Lip retargeting` and disable `Relative motion`.
4. Change `animation_region` from `lip` to `exp` or `all` and check whether mouth corners and cheeks recover.
5. Tune `mouth_open_multiplier` around `0.8-1.3` and `mouth_corner_multiplier` around `1.0-1.3`.

Lip retargeting can improve mouth following, but combined with relative motion it may reduce the mouth to mostly vertical open/close. Treat those two switches as a pair during Video Clone tuning.

## Avatar Requirements

- Use a clear frontal or half-body source when possible.
- Enable `Pasteback` when you want to preserve a half-body composition.
- If aspect ratio or crop is wrong, inspect the avatar preview and source image before changing only driving parameters.
- Video Clone can reuse existing avatar-library assets. You do not need to upload the camera user as an avatar.

## Verify

1. Start OmniRT and confirm `fasterliveportrait` is connected.
2. Start OpenTalking WebUI.
3. Open Realtime Conversation, select FasterLivePortrait, send a short text message, and confirm the audio-driven path still works.
4. Open Video Clone, select a digital-human source, allow camera permission, click Start, and confirm the source avatar follows camera expression.
5. Stop or leave the page and confirm camera tracks, WebSocket session, and OmniRT session are released.

## Troubleshooting

### `/models` shows `runtime_not_enabled`

Start OmniRT with `OMNIRT_FASTLIVEPORTRAIT_RUNTIME=1` and check checkpoint paths.

### Audio driving has no lip motion

Check JoyVASA motion generator, motion template, and `chinese-hubert-base/pytorch_model.bin`.

### Video Clone cannot start the camera

Open the page from `localhost` / `127.0.0.1` or HTTPS, allow browser camera permission, and confirm OpenTalking API can connect to OmniRT.

### Uploaded-video driving differs from camera driving

Uploaded videos are sensitive to resolution, face position, crop, and scaling. Disable driving crop first, then tune lip retargeting, relative motion, and mouth multipliers.
