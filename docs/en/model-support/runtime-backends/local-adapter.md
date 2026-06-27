# Local Adapter

## Suitable Scenarios

Local Adapter means the talking-head model is loaded inside the OpenTalking
process. It is suitable for development, single-machine demos, low-concurrency
validation, and model adapter work.

The main local paths are Wav2Lip, QuickTalk, and MuseTalk. MuseTalk local mode
requires CUDA plus its official preprocessing dependencies.

## Benefits and Limits

Benefits:

- Short startup chain and easier debugging.
- No separate inference service is required.
- The adapter can read local avatar and model files directly.

Limits:

- The API process owns GPU, CPU, and memory usage.
- Model dependencies can affect the OpenTalking environment.
- Isolation is weaker when multiple models or concurrent sessions share the same process.

## Configuration

Through the startup script:

```bash
bash scripts/start_unified.sh --backend local --model musetalk
```

Through environment variables:

```bash
export OPENTALKING_MUSETALK_BACKEND=local
export OPENTALKING_QUICKTALK_BACKEND=local
export OPENTALKING_WAV2LIP_BACKEND=local
```

Through configuration:

```yaml
models:
  musetalk:
    backend: local
  quicktalk:
    backend: local
  wav2lip:
    backend: local
```

## Model Compatibility

| Model | Local support guidance |
| --- | --- |
| Wav2Lip | Recommended for lightweight local validation |
| QuickTalk | Recommended for local GPU validation |
| MuseTalk | Supported for local CUDA validation; requires weights, official MuseTalk source, and full OpenMMLab preprocessing dependencies |
| FlashTalk | Prefer OmniRT |
| FlashHead | Prefer standalone HTTP / direct_ws |

## Verify

```bash
bash scripts/start_unified.sh --backend local --model musetalk --api-port 18000
curl -s http://127.0.0.1:18000/models | jq '.statuses[] | select(.id=="musetalk")'
```

WebUI should choose a matching avatar and model. For MuseTalk, session creation
runs official avatar preprocessing first if the avatar does not already contain
MuseTalk `prepared/` assets.

## Common Issues

### Local model loading fails

Check model weight paths, installed extras, CUDA / PyTorch / ONNX Runtime
versions, and `OPENTALKING_TORCH_DEVICE`.

### MuseTalk preprocessing fails

Check that `OPENTALKING_MUSETALK_REPO` points to the official MuseTalk source and
that `OPENTALKING_MUSETALK_PREPROCESS_PYTHON` contains full OpenMMLab
dependencies, especially `mmcv` with `mmcv._ext`.

### API startup or first session is slow

Local mode loads model dependencies in-process. MuseTalk also preprocesses the
selected avatar before the first session when no valid `prepared/` cache exists.
