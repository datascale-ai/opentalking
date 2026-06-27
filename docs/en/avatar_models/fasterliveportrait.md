# FasterLivePortrait / JoyVASA
## Support Status

| Item | Value |
|------|-------|
| Model ID | `fasterliveportrait` |
| Backend | `omnirt` |
| Evidence level | Documented; realtime path exposed through the OmniRT runtime |
| Best for | Single-GPU realtime audio-driven portrait avatars, original-image pasteback, frontend amplitude hot updates |

## Common Errors

| Symptom | Action |
|---------|--------|
| `/models` shows `runtime_not_enabled` | Ensure OmniRT was started with `OMNIRT_FASTLIVEPORTRAIT_RUNTIME=1`, then check checkpoint paths and `logs/omnirt`. |
| Audio driving has no lip motion | Check `JoyVASA/motion_generator`, `JoyVASA/motion_template`, and `chinese-hubert-base/pytorch_model.bin`. |
| Generation reports an ONNXRuntime `GridSample` error | Re-run `uv sync --extra server --extra fasterliveportrait --python 3.11`, confirm `import tensorrt` works, and start with `OMNIRT_FASTLIVEPORTRAIT_CFG=configs/trt_infer.yaml`. |
| Browser sees the model but session creation fails | Select an avatar whose `model_type` matches `fasterliveportrait`, or prepare a matching avatar bundle. |


FasterLivePortrait also runs through the OmniRT `audio2video` compatibility path. OpenTalking owns sessions, TTS/audio streaming, WebRTC playback, and frontend parameter updates. OmniRT keeps FasterLivePortrait and JoyVASA resident and exposes `/v1/audio2video/fasterliveportrait`.

This path is intended for single-GPU realtime avatars. The default live profile uses 25fps, one-second audio chunks, a 448px width, and pasteback into the original avatar image. Full-body uploads are still driven through the detected face region; body motion is not synthesized by this runtime.

## 1. Prepare code and weights

You need a FasterLivePortrait source checkout and a real checkpoint directory. If you do not want symlinks, copy or download the files directly into the model root.

```bash title="terminal"
if [ ! -d "$FASTERLIVEPORTRAIT_HOME/.git" ]; then
  git clone https://github.com/KlingAIResearch/LivePortrait.git "$FASTERLIVEPORTRAIT_HOME"
fi

mkdir -p "$OMNIRT_MODEL_ROOT/FasterLivePortrait/checkpoints"
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
  liveportrait/ or appearance_feature_extractor.onnx and the other FasterLivePortrait ONNX/TRT files
```

If the model files already exist elsewhere, copy real files with `rsync`:

```bash title="terminal"
rsync -a /path/to/FasterLivePortrait/checkpoints/ \
  "$OMNIRT_MODEL_ROOT/FasterLivePortrait/checkpoints/"
```

Preflight check:

```bash title="terminal"
test -f "$OMNIRT_MODEL_ROOT/FasterLivePortrait/checkpoints/JoyVASA/motion_generator/motion_generator_hubert_chinese.pt"
test -f "$OMNIRT_MODEL_ROOT/FasterLivePortrait/checkpoints/JoyVASA/motion_template/motion_template.pkl"
test -f "$OMNIRT_MODEL_ROOT/FasterLivePortrait/checkpoints/chinese-hubert-base/pytorch_model.bin"
```

## 2. Prepare the OmniRT environment

```bash title="terminal"
cd "$OMNIRT_HOME"
export UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$DIGITAL_HUMAN_HOME/.uv-cache}"
uv sync --extra server --extra fasterliveportrait --python 3.11
```

The realtime FasterLivePortrait path uses TensorRT by default. The `fasterliveportrait` extra installs `onnxruntime-gpu`, `tensorrt-cu12`, `tensorrt-cu12-bindings`, and `tensorrt-cu12-libs`. The TensorRT libs wheel is about 4GB, so keep `UV_CACHE_DIR` on a data disk with enough space; do not let it fall back to a small `/root/.cache/uv`.

Before deployment, verify that `uv run python -c "import tensorrt as trt; print(trt.__version__)"` prints a version.

## 3. Start the OmniRT FasterLivePortrait runtime

```bash title="terminal"
cd "$OMNIRT_HOME"
OMNIRT_FASTLIVEPORTRAIT_RUNTIME=1 \
OMNIRT_FASTLIVEPORTRAIT_LOAD_MODELS=1 \
OMNIRT_FASTLIVEPORTRAIT_ROOT="$FASTERLIVEPORTRAIT_HOME" \
OMNIRT_FASTLIVEPORTRAIT_CHECKPOINTS_DIR="$OMNIRT_MODEL_ROOT/FasterLivePortrait/checkpoints" \
OMNIRT_FASTLIVEPORTRAIT_CFG=configs/trt_infer.yaml \
OMNIRT_FASTLIVEPORTRAIT_DEVICE=cuda:0 \
OMNIRT_FASTLIVEPORTRAIT_JPEG_QUALITY=85 \
uv run omnirt serve-avatar-ws --host 0.0.0.0 --port 9000 --backend cuda
```

Verify OmniRT reports the model:

```bash title="terminal"
curl -s http://127.0.0.1:9000/v1/audio2video/models | jq '.statuses[] | select(.id=="fasterliveportrait")'
```

Expected status:

```json
{"id":"fasterliveportrait","connected":true,"reason":"fasterliveportrait_runtime"}
```

## 4. Configure and start OpenTalking

OpenTalking configures `fasterliveportrait` as `backend: omnirt` by default. The realtime profile lives in `configs/synthesis/fasterliveportrait.yaml`; common defaults are:

```yaml title="configs/synthesis/fasterliveportrait.yaml"
width: 448
fps: 25
chunk_samples: 16000
emit_frames_per_chunk: 25
head_motion_multiplier: 0.3
pose_motion_multiplier: 0.35
yaw_multiplier: 0.85
pitch_multiplier: 1.0
roll_multiplier: 0.85
animation_region: lip
expression_multiplier: 1.0
mouth_open_multiplier: 1.25
mouth_corner_multiplier: 0.85
cheek_jaw_multiplier: 0.9
driving_multiplier: 1.0
cfg_scale: 4.0
flag_relative_motion: true
flag_stitching: true
head_only_pasteback: false
```

Start OpenTalking against OmniRT:

```bash title="terminal"
cd "$OPENTALKING_HOME"
OMNIRT_ENDPOINT=http://127.0.0.1:9000 \
OPENTALKING_OMNIRT_ENDPOINT=http://127.0.0.1:9000 \
uv run opentalking-unified --host 0.0.0.0 --port 8000
```

Frontend:

```bash title="terminal"
cd "$OPENTALKING_HOME/apps/web"
npm ci
VITE_BACKEND_PORT=8000 npm run dev -- --host 0.0.0.0 --port 5173
```

Verify OpenTalking sees the model:

```bash title="terminal"
curl -s http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="fasterliveportrait")'
```

Expected status:

```json
{"id":"fasterliveportrait","backend":"omnirt","connected":true,"reason":"omnirt"}
```

## 5. Frontend controls and hot updates

After selecting `FasterLivePortrait`, the frontend shows a parameter panel. Before a session starts, clicking Apply stores values for the next session. During a session, clicking Apply sends a hot update and takes effect on the next audio chunk without restarting the conversation.

| Parameter | Effect | Suggested range |
|-----------|--------|-----------------|
| `head_motion_multiplier` | Overall head motion amplitude | default 0.3, common 0.2-0.8 |
| `pose_motion_multiplier` | pitch/yaw/roll amplitude; lower this first when the head sways too much | 0.2-0.5 |
| `yaw_multiplier` | Left/right head turn amplitude | default 0.85, common 0.6-1.0 |
| `pitch_multiplier` | Up/down nod amplitude | default 1.0, common 0.7-1.1 |
| `roll_multiplier` | Side tilt amplitude | default 0.85, common 0.6-1.0 |
| `animation_region` | FLP animation region; realtime defaults to mouth-only to reduce wide eyes and exaggerated full-face motion | default `lip`; use `all` for full expression |
| `expression_multiplier` | Overall expression and lip amplitude | default 1.0, common 0.9-1.2 |
| `mouth_open_multiplier` | Mouth opening amplitude | default 1.25, common 1.0-1.4 |
| `mouth_corner_multiplier` | Mouth-corner movement | default 0.85, common 0.7-1.0 |
| `cheek_jaw_multiplier` | Cheek and jaw movement | default 0.9, common 0.7-1.1 |
| `driving_multiplier` | Overall keypoint driving amplitude | 0.8-1.2 |
| `cfg_scale` | JoyVASA audio-following strength | default 4.0, common 3.5-4.5 |

Start with `head_motion_multiplier=0.3`, `pose_motion_multiplier=0.35`, `yaw_multiplier=0.85`, `roll_multiplier=0.85`, `animation_region=lip`, `expression_multiplier=1.0`, `mouth_open_multiplier=1.25`, `mouth_corner_multiplier=0.85`, `cheek_jaw_multiplier=0.9`, `cfg_scale=4.0`, and keep `flag_relative_motion=true`. If the head sways left/right, lower `yaw_multiplier` to `0.7`. If the mouth looks pursed or the smile is too strong, lower `mouth_corner_multiplier` to `0.75`. Switch the region from `lip` to `all` only when you need richer facial expression. Do not improve speed by dropping mouth-open frames.

## 6. Performance check

```bash title="terminal"
cd "$OMNIRT_HOME"
uv run python scripts/bench_fasterliveportrait_ws.py \
  --url ws://127.0.0.1:9000/v1/audio2video/fasterliveportrait \
  --duration 30 \
  --chunk-samples 16000
```

For single-GPU realtime use, watch first packet latency, per-chunk render time, output fps, and whether the browser queue keeps growing. If 448px width cannot stay above 25fps, drop to 416px. Use 480px or 540px only for quality-first runs, not as the realtime default.
