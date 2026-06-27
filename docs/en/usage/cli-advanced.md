# Advanced CLI Arguments

Advanced arguments control backend selection, ports, host binding, and environment files. Most users only need `scripts/start_unified.sh`; use these options when you connect remote inference, run multiple instances, or expose WebUI on a server.

## When to Use Advanced Arguments

Use advanced arguments when:

- Default ports are already occupied.
- WebUI needs to be reachable from another machine on the LAN.
- A model should use Mock, local, OmniRT, or direct WebSocket backend.
- Model paths, provider keys, mirrors, and endpoints should be managed in an env file.

## Backend Selection Arguments

### `--mock`

The lightest startup mode:

```bash
bash scripts/start_unified.sh --mock
```

It uses the built-in Mock backend and does not load model weights or require GPU.

### `--backend`

Select the backend type for a model:

```bash
bash scripts/start_unified.sh --backend local --model quicktalk
```

Accepted values:

- `mock`: no real model, useful for flow validation.
- `local`: load the model inside OpenTalking.
- `omnirt`: call an independent OmniRT inference service.
- `direct_ws`: connect through a direct WebSocket backend.

### `--model`

Specify which model receives the backend override:

```bash
bash scripts/start_unified.sh --backend local --model quicktalk
```

The script sets the default model and an environment variable such as `OPENTALKING_QUICKTALK_BACKEND=local`.

## Service Port Arguments

### `--api-port`

Set the OpenTalking API / unified backend port:

```bash
bash scripts/start_unified.sh --mock --api-port 8001
```

### `--web-port`

Set the WebUI dev server port:

```bash
bash scripts/start_unified.sh --mock --web-port 5174
```

When you change both API and WebUI ports, pass both arguments together.

### `--host`

Set the WebUI bind host:

```bash
bash scripts/start_unified.sh --mock --host 0.0.0.0
```

Use `0.0.0.0` only when WebUI should be reachable from outside the local machine, and check firewall or security group rules.

## Remote Inference Arguments

### `--omnirt`

Set the OmniRT service URL when using `--backend omnirt`:

```bash
bash scripts/start_unified.sh \
  --backend omnirt \
  --model flashtalk \
  --omnirt http://127.0.0.1:9000
```

If `--omnirt` is omitted, set `OMNIRT_ENDPOINT` first.

### `--env`

Load a quickstart environment file:

```bash
cp scripts/quickstart/env.example .env.quickstart
bash scripts/start_unified.sh --env .env.quickstart --backend local --model quicktalk
```

Use env files for model paths, TTS provider keys, mirrors, default ports, and endpoints. Do not commit files that contain secrets.

## Common Combinations

### Mock Local Validation

```bash
bash scripts/start_unified.sh --mock
```

Best for first-time installation, WebUI checks, and basic interaction flow.

### QuickTalk Local Model

```bash
bash scripts/start_unified.sh --backend local --model quicktalk
```

Use this on a local GPU machine after model weights and dependencies are ready.

### OmniRT Remote Model

```bash
bash scripts/start_unified.sh \
  --backend omnirt \
  --model quicktalk \
  --omnirt http://127.0.0.1:9000
```

Use this when inference runs outside OpenTalking and OpenTalking handles WebUI, sessions, and orchestration.

### Custom Ports

```bash
bash scripts/start_unified.sh \
  --mock \
  --api-port 8001 \
  --web-port 5174
```

Useful when debugging multiple branches or configurations on one machine.

## Common Issues

### `--backend omnirt` Requires an Endpoint

Pass `--omnirt`, or set:

```bash
export OMNIRT_ENDPOINT=http://127.0.0.1:9000
```

### WebUI Opens but Session Creation Fails

Check API logs and model backend health. For OmniRT, verify that the endpoint is reachable and that the selected model is supported by the remote backend.

### WebUI Cannot Be Reached from LAN

Start with `--host 0.0.0.0`, then check firewall, security group, and WebUI port access.
