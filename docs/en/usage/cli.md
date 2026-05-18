# Command Line Tools

Command line tools are used to start services, prepare assets, switch model backends, and run performance checks. They are most useful during development and integration, especially when you need reproducible startup commands or automation.

## When to Use Command Line Tools

Use the CLI when you need to:

- Validate that the environment is installed correctly.
- Start Mock mode, a local QuickTalk model, or an OmniRT backend.
- Change API or WebUI ports.
- Prepare Wav2Lip image or video avatar assets.
- Benchmark QuickTalk first-frame time, render FPS, and initialization time.

If you only want to try the interactive flow, start from [Quick Start](../quick-start/index.md) and open WebUI.

## Service Commands

### `opentalking-unified`

`opentalking-unified` is the recommended local development entry point. It runs the API, session orchestration, and in-memory queue in one process.

```bash
uv run opentalking-unified
```

Common environment variables:

```bash
export OPENTALKING_AVATARS_DIR=./examples/avatars
export OPENTALKING_DEFAULT_MODEL=quicktalk
```

In practice, `scripts/start_unified.sh` is usually more convenient because it also starts WebUI and handles ports, backend selection, and env files.

### `opentalking-api`

`opentalking-api` starts only the API service.

```bash
uv run opentalking-api
```

Use it when you intentionally want to run API, worker, and frontend separately.

### `opentalking-worker`

`opentalking-worker` consumes tasks and runs model inference as a separate worker.

```bash
uv run opentalking-worker
```

Use this mode for multi-worker validation, queue behavior, GPU binding, or production-like topology checks.

## Quick Start Scripts

### `scripts/start_unified.sh`

This is the most useful startup script. It starts the OpenTalking backend and WebUI.

Mock mode:

```bash
bash scripts/start_unified.sh --mock
```

Local QuickTalk:

```bash
bash scripts/start_unified.sh --backend local --model quicktalk
```

Remote OmniRT:

```bash
bash scripts/start_unified.sh \
  --backend omnirt \
  --model flashtalk \
  --omnirt http://127.0.0.1:9000
```

The script prints the WebUI URL after startup. The default is `http://127.0.0.1:5173`.

### `scripts/quickstart/start_mock.sh`

`start_mock.sh` is a focused Mock-mode entry point.

```bash
bash scripts/quickstart/start_mock.sh
```

Mock mode does not load real models or require model weights. It is useful for checking WebUI, session state, frontend assets, and basic APIs.

### `scripts/quickstart/status.sh`

Check whether API, WebUI, and OmniRT services are online:

```bash
bash scripts/quickstart/status.sh
```

With custom ports:

```bash
bash scripts/quickstart/status.sh --api-port 8001 --web-port 5174
```

### `scripts/quickstart/stop_all.sh`

Stop services started by quickstart scripts:

```bash
bash scripts/quickstart/stop_all.sh
```

If several OpenTalking instances are running, check `status.sh` first.

## Avatar Processing Scripts

### `prepare_wav2lip_image_asset.py`

Prepare one image as a Wav2Lip avatar asset:

```bash
uv run python scripts/prepare_wav2lip_image_asset.py \
  --source-image ./assets/my-avatar.png \
  --out ./examples/avatars/my-avatar \
  --avatar-id my-avatar \
  --name "My Avatar"
```

The script writes `manifest.json`, `reference.png`, `preview.png`, frame assets, and mouth metadata.

### `prepare_wav2lip_video_asset.py`

Prepare one video as a Wav2Lip avatar asset:

```bash
uv run python scripts/prepare_wav2lip_video_asset.py \
  --source-video ./assets/my-avatar.mp4 \
  --out ./examples/avatars/my-video-avatar \
  --avatar-id my-video-avatar \
  --name "My Video Avatar" \
  --max-frames 125
```

Video assets preserve more natural motion, but they take longer to prepare and depend more heavily on source quality.

## Benchmark / Debug Scripts

### `opentalking-quicktalk-bench`

Use `opentalking-quicktalk-bench` to measure QuickTalk initialization time, first-frame latency, render FPS, and output generation.

```bash
uv run opentalking-quicktalk-bench \
  --asset-root ./examples/avatars/quicktalk-daytime \
  --template-video ./examples/avatars/quicktalk-daytime/quicktalk/template_900.mp4 \
  --audio ./assets/test.wav \
  --output ./outputs/quicktalk-bench.mp4 \
  --device cuda:0
```

The command prints JSON metrics that can be compared across GPUs, assets, and model versions.

## Common Issues

### Port Already in Use

Use custom ports:

```bash
bash scripts/start_unified.sh --mock --api-port 8001 --web-port 5174
```

### WebUI Cannot Reach API

Run:

```bash
bash scripts/quickstart/status.sh
```

If you changed the API port, make sure WebUI was started with the same port.

### Model Does Not Take Effect

Check that both `--backend` and `--model` were specified:

```bash
bash scripts/start_unified.sh --backend local --model quicktalk
```

### Custom Avatar Does Not Appear

Confirm the avatar directory is under `OPENTALKING_AVATARS_DIR` and contains a valid `manifest.json` and `preview.png`.
