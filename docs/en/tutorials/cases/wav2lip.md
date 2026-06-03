# Wav2Lip Integration Case

## Goal

Switch an OpenTalking session from `mock` to `wav2lip`. The currently runnable
compatibility path is `backend: omnirt`; once the local adapter is complete, the same model
can move to `local`.

## Prerequisites

- [Mock E2E](mock-e2e.md) has passed.
- `wav2lip384.pth` and `s3fd.pth` are downloaded as described in
  [Talking-head Models → Wav2Lip](../../model-deployment/wav2lip/local.md).
- An OmniRT checkout exists next to `opentalking/`.

## Steps

Start the Wav2Lip OmniRT service:

```bash title="Terminal"
cd opentalking
bash scripts/quickstart/start_omnirt_wav2lip.sh --device cuda
```

Point OpenTalking at OmniRT:

```env title=".env"
OMNIRT_ENDPOINT=http://127.0.0.1:9000
```

Start OpenTalking:

```bash title="Terminal"
bash scripts/quickstart/start_all.sh --omnirt http://127.0.0.1:9000
```

## Verification

```bash title="Terminal"
curl -fsS http://127.0.0.1:8000/models | jq '.statuses[] | select(.id=="wav2lip")'
```

The status should report `backend: omnirt` and `connected: true`. In the browser, choose a
Wav2Lip-compatible avatar before starting the session.

## Troubleshooting

| Symptom | Action |
|---------|--------|
| `/models` reports `not_configured` | Check `OMNIRT_ENDPOINT` in the active `.env` and restart OpenTalking. |
| OmniRT exits during startup | Inspect the script log path and verify the Wav2Lip/S3FD weight filenames. |
| Avatar mismatch | Use an avatar with `model_type: wav2lip` or regenerate assets with `scripts/prepare_wav2lip_*_asset.py`. |
