# Concepts and API

This section is for developers and integrators. It explains OpenTalking concepts, API
boundaries, and extension points. If the goal is to run the project first, start with
[Tutorials](../tutorials/index.md). If the goal is to understand business scenarios, start
with [Use Cases](../cases/index.md). If the goal is model serving, start with
[Model Deployment](../model-deployment/index.md).

## Understand Concepts

- [Architecture](architecture.md) — components, deployment topologies, session lifecycle, event bus, and backend boundaries.
- [Render Pipeline](render-pipeline.md) — how LLM, TTS, synthesis backends, and WebRTC fit together.
- [Avatar Format](avatar-format.md) — avatar bundles, manifest fields, and model matching rules.

## Query the API

- [API Interfaces](api/index.md) — Base URL, error conventions, endpoint table, and common request sequence.
- [Health and Models](api/health.md) — `/health`, `/models`, and queue status.
- [Sessions](api/sessions.md) — sessions, chat, WebRTC, recording, and offline bundles.
- [Events and Streaming](api/events.md) — SSE and audio WebSocket protocols.

## Extend Implementation

- [Model Adapter](model-adapter.md) — integration contract for new talking-head backends.
- [Developing](developing.md) — local execution, tests, debugging, and repository layout.

## Debug and Contribute

Before contributing, run `python -m mkdocs build --strict --clean` and update the API docs,
model deployment docs, or Benchmark records according to the change. See
[Community](../community/index.md) for contribution paths.
