# Tutorials

Tutorials are organized by task path. Use them to run OpenTalking from scratch, connect a
real model, prepare custom avatars, or enter the development workflow.

## First Run

1. [Installation](installation.md) — check Python, Node.js, ffmpeg, DashScope keys, and hardware requirements.
2. [Quickstart](quickstart.md) — run the `mock` synthesis path through browser, API, LLM, STT, TTS, and WebRTC.
3. [Configuration](configuration.md) — understand `.env`, YAML configuration, providers, and backend precedence.
4. [Mock E2E case](cases/mock-e2e.md) — validate the local environment with the smallest full path.

## Connect a Real Model

Verify orchestration with `mock` first, then connect a real talking-head backend:

| Scenario | Tutorial |
|----------|----------|
| First real lip-sync model | [Wav2Lip integration](cases/wav2lip.md) |
| High-quality FlashTalk/OmniRT path | [FlashTalk integration](cases/flashtalk.md) |
| Model, weight, and deployment selection | [Model deployment](../deployment/index.md) |

These pages focus on low-level integration steps. If you want to start from business
scenarios, see [Use Cases](../cases/index.md).

## Custom Avatar

Start with [Custom Avatar](cases/custom-avatar.md) to learn how images, videos, and
`manifest.json` form an avatar bundle that OpenTalking can discover. Field details are in
[Avatar Format](../docs/avatar-format.md).

## Development and Debugging

| Goal | Entry |
|------|-------|
| Modify API, session, or Worker behavior | [Developing](../docs/developing.md) |
| Understand components and data flow | [Architecture](../docs/architecture.md) |
| Add a new talking-head backend | [Model Adapter](../docs/model-adapter.md) |
| Investigate performance and first-frame latency | [Benchmark](../benchmark/index.md) |
