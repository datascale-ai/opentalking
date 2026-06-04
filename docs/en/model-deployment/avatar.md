# Avatar Assets

Avatar assets bind a visual identity to the selected talking-head backend. A model may
be connected, but session creation still fails or looks wrong if the avatar bundle does
not match that model.

## Minimal rule

The avatar `manifest.json` must declare a `model_type` compatible with the selected
session model:

| Model | Typical avatar requirement |
|-------|----------------------------|
| `mock` | Preview/reference image only. |
| `wav2lip` | Reference frames or prepared Wav2Lip frame assets. |
| `quicktalk` | `metadata.asset_root` and `metadata.template_video`. |
| `flashhead` | Reference image for the FlashHead session. |
| `flashtalk` | Portrait/reference image compatible with the backend service. |

## Example manifest

```json title="examples/avatars/quicktalk-demo/manifest.json"
{
  "id": "quicktalk-demo",
  "name": "QuickTalk Demo",
  "model_type": "quicktalk",
  "fps": 25,
  "sample_rate": 16000,
  "width": 512,
  "height": 512,
  "metadata": {
    "asset_root": "/absolute/path/to/models/quicktalk/hdModule",
    "template_video": "/absolute/path/to/template.mp4"
  }
}
```

## Prepare and validate

Use the existing avatar guide for the complete schema and preparation scripts:

- [Avatar Format](../docs/avatar-format.md)
- [Models → Talking-Head Models](talking-head/index.md)

Verify the server sees the avatar:

```bash title="terminal"
curl -s http://127.0.0.1:8000/avatars | python3 -m json.tool
```

When troubleshooting, check three values together: session `model`, avatar
`model_type`, and `/models` `backend`.

## Frontend Entry

After the model or backend service is running, use the OpenTalking WebUI:

```bash title="Terminal"
cd "$OPENTALKING_HOME"
bash scripts/quickstart/start_frontend.sh --api-port 8000 --web-port 5173 --host 0.0.0.0
```

For a remote server, forward your local browser port to the server `5173`, then open `http://127.0.0.1:5173`.
