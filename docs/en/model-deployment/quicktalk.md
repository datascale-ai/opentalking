# QuickTalk

QuickTalk supports both `local` and `omnirt` modes in the current repository. The commit history includes QuickTalk routed through OmniRT audio2video, and the current scripts include `scripts/quickstart/start_omnirt_quicktalk.sh`; it is not a local-only model.

| Item | Value |
|------|-------|
| Model ID | `quicktalk` |
| Backends | `local`, `omnirt` |
| Repo default | `omnirt` |
| Recommended start | Use `local` for single-machine validation; use `omnirt` for service isolation. |

## Asset Layouts

Both modes need QuickTalk weights, HuBERT files, and InsightFace assets, but they read different roots. The OmniRT quickstart script reads top-level files under `$OMNIRT_MODEL_ROOT/quicktalk`:

```text
$OMNIRT_MODEL_ROOT/quicktalk/
  quicktalk.pth
  repair.npy
  chinese-hubert-large/
    config.json
    preprocessor_config.json
    pytorch_model.bin
  auxiliary/models/buffalo_l/
    det_10g.onnx
```

The local adapter reads an asset root that contains `checkpoints/`:

```text
$OPENTALKING_QUICKTALK_ASSET_ROOT/
  checkpoints/
    quicktalk.pth or 256.onnx
    repair.npy
    chinese-hubert-large/
      pytorch_model.bin
    auxiliary/models/buffalo_l/ or auxiliary_min/
      det_10g.onnx
```

## Guides

- [QuickTalk Local](quicktalk/local.md)
- [QuickTalk with OmniRT](quicktalk/omnirt.md)
- [Local Audio + QuickTalk](recipes/local-quicktalk-audio.md)
- [Support Matrix](support-matrix.md)
