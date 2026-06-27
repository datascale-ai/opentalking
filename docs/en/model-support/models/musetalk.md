# MuseTalk

## Support Status

| Item | Value |
|------|-------|
| Model ID | `musetalk` |
| Backend | `omnirt`, `direct_ws`, or `local` |
| Evidence level | Local adapter is wired; local mode runs official MuseTalk preprocessing before session initialization |
| Best for | Teams that need MuseTalk quality while keeping startup orchestration in OpenTalking |

## Recommended Hardware

Single GPU or remote model service. `local` mode should use a CUDA GPU; the first
session for an avatar also loads DWPose, face parsing, and the VAE for official
preprocessing.

## Weights

Upstream sources:

- [TMElyralab/MuseTalk](https://github.com/TMElyralab/MuseTalk)
- [MuseTalk on Hugging Face](https://huggingface.co/TMElyralab/MuseTalk)
- [ModelScope search for MuseTalk](https://modelscope.cn/models?name=MuseTalk)
- [Modelers search for MuseTalk](https://modelers.cn/models?name=MuseTalk)

For `local` mode, place these weights under `DIGITAL_HUMAN_HOME/models`, or point
`OPENTALKING_MUSETALK_MODEL_ROOT` at an equivalent directory:

```text
models/
  musetalk/
    musetalk.json
    pytorch_model.bin
  sd-vae-ft-mse/
    config.json
    diffusion_pytorch_model.bin
    diffusion_pytorch_model.safetensors
  whisper/
    tiny.pt
  dwpose/
    dw-ll_ucoco_384.pth
  face-parse-bisenet/
    79999_iter.pth
```

## Directory Layout

`omnirt` and `direct_ws` modes let the external service own the MuseTalk runtime.
In `local` mode, OpenTalking loads the weights directly and needs the official
MuseTalk source checkout for avatar preprocessing:

```text
DIGITAL_HUMAN_HOME/
  models/
  model-repos/
    MuseTalk/
      musetalk/utils/preprocessing.py
      musetalk/utils/blending.py
  runtimes/
    musetalk-preprocess/
      venv/bin/python
```

`runtimes/musetalk-preprocess/venv` must contain the full OpenMMLab stack,
especially `mmcv` with `mmcv._ext`; `mmcv-lite` is not enough for official
preprocessing. The main OpenTalking `.venv` may still use `mmcv-lite` for local
MuseTalk realtime inference. Official preprocessing is executed through
`OPENTALKING_MUSETALK_PREPROCESS_PYTHON` or the default Python path shown above.

## Configuration

OmniRT path:

```yaml title="configs/default.yaml"
models:
  musetalk:
    backend: omnirt
```

Local path:

```yaml title="configs/default.yaml"
models:
  musetalk:
    backend: local
```

## Start

Point OpenTalking at an OmniRT service that exposes MuseTalk:

```bash title="Terminal"
bash scripts/quickstart/start_all.sh --omnirt http://127.0.0.1:9000
```

Local mode:

```bash title="Terminal"
bash scripts/start_unified.sh --backend local --model musetalk --api-port 18000 --web-port 18173 --host 0.0.0.0
```

The command checks local MuseTalk inference dependencies. When a user enters a
conversation and creates a session, OpenTalking checks the selected avatar. If
`prepared/prepared_info.json` is missing, or it was not produced by
`source_preprocess=musetalk_official`, OpenTalking runs official MuseTalk
preprocessing first, writes the assets to the avatar's `prepared/` directory, and
then loads the session.

## `/models` Verification

```bash title="Terminal"
curl -s http://127.0.0.1:18000/models | jq '.statuses[] | select(.id=="musetalk")'
```

When OmniRT or the local runtime provides the model, it should report
`connected=true`. For local mode:

```json
{"id":"musetalk","backend":"local","connected":true,"reason":"local_runtime"}
```

## Common Errors

| Symptom | Action |
|---------|--------|
| `reason=omnirt_unavailable` | Check that OmniRT reports `/v1/audio2video/musetalk`. |
| `No module named 'mmcv._ext'` | The preprocessing Python lacks full OpenMMLab dependencies; use an `OPENTALKING_MUSETALK_PREPROCESS_PYTHON` environment with full `mmcv`. |
| Session fails during preprocessing | Check that `OPENTALKING_MUSETALK_REPO` points to the official MuseTalk source and that `dwpose` and `face-parse-bisenet` weights exist. |
| Avatar asset unavailable | Check that the avatar is uploaded, readable, and the session configuration is complete. |
