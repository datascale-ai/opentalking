# Gesture Pose Preprocess Pack

This folder contains a reusable preprocessing pass for the six gesture poses extracted from the two source collage images.

## Outputs

- `raw_split/`: collage panels split into individual source poses
- `aligned/`: portrait-aligned outputs with matched eye and shoulder anchors
- `annotated/`: MediaPipe Holistic debug overlays
- `landmarks/`: per-pose face, pose, and hand landmark json
- `manifests/panel_manifest.json`: panel index and file map
- `manifests/state_machine.json`: starter motion state machine
- `manifests/transition_manifest.json`: transition recommendations
- `transitions/`: sample crossfade plus offset-compensation transition previews

## Pose Labels

- `confidence`: raised-hand lecture cue
- `explain`: double-hand open gesture
- `emphasis`: pointing gesture
- `idle`: neutral ready pose
- `hands_down`: natural hand-down pose
- `subtle_hands`: light hand motion pose

## Rerun

```bash
source /data1/cw/miniconda3/etc/profile.d/conda.sh
conda activate /data1/cw/miniconda3/envs/xx_talk
python /data1/xuxin/opentalking/preprocess/gesture_avatar_20260418/build_pose_pack.py \
  --image "/data1/xuxin/opentalking/ChatGPT Image 2026年4月18日 19_37_52.png" \
  --image "/data1/xuxin/opentalking/ChatGPT Image 2026年4月18日 19_41_00.png"
```

## Transition Preview

```bash
source /data1/cw/miniconda3/etc/profile.d/conda.sh
conda activate /data1/cw/miniconda3/envs/xx_talk
python /data1/xuxin/opentalking/preprocess/gesture_avatar_20260418/build_transition_preview.py \
  --src idle \
  --dst explain
```
