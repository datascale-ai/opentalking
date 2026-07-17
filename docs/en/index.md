---
title: OpenTalking
---

# OpenTalking

<p align="center">
  <img src="/opentalking/assets/images/logo_white.png" alt="OpenTalking logo" width="200">
</p>

<p align="center">
  <a href="https://github.com/datascale-ai/opentalking/stargazers"><img src="https://img.shields.io/github/stars/datascale-ai/opentalking?style=flat&label=stars" alt="GitHub stars"></a>
  <a href="https://github.com/datascale-ai/opentalking/forks"><img src="https://img.shields.io/github/forks/datascale-ai/opentalking?style=flat&label=forks" alt="GitHub forks"></a>
  <a href="https://github.com/datascale-ai/opentalking/issues"><img src="https://img.shields.io/github/issues/datascale-ai/opentalking?style=flat&label=open%20issues" alt="Open issues"></a>
  <a href="https://github.com/datascale-ai/opentalking/issues?q=is%3Aissue+is%3Aclosed"><img src="https://img.shields.io/github/issues-closed/datascale-ai/opentalking?style=flat&label=issue%20resolution" alt="Issue resolution"></a>
  <img src="https://img.shields.io/badge/PyPI-planned-lightgrey?style=flat" alt="PyPI planned">
  <img src="https://img.shields.io/badge/python-%3E%3D3.10-blue?style=flat" alt="Python >= 3.10">
  <a href="https://github.com/datascale-ai/opentalking/releases"><img src="https://img.shields.io/github/downloads/datascale-ai/opentalking/total?style=flat&label=downloads" alt="GitHub downloads"></a>
  <img src="https://img.shields.io/badge/downloads-source-lightgrey?style=flat" alt="Source downloads">
  <a href="https://modelscope.cn/models?name=OpenTalking"><img src="https://img.shields.io/badge/ModelScope-models-624aff?style=flat" alt="ModelScope"></a>
  <a href="https://huggingface.co/models?search=OpenTalking"><img src="https://img.shields.io/badge/HuggingFace-models-ffcc4d?style=flat" alt="Hugging Face"></a>
</p>

## Project Introduction

OpenTalking is an open-source orchestration framework for real-time digital-human
applications. It connects frontend interaction, session state, LLM responses, TTS and
voice settings, subtitle events, WebRTC audio/video playback, and local or remote
digital-human synthesis backends.

OpenTalking is not a single talking-head model. It sits between product experiences and
model services, organizing LLM, speech recognition, speech synthesis, avatar rendering,
event streaming, and browser playback into a unified runtime. Developers can start with
Mock validation and then move to real models and inference backends such as Wav2Lip,
QuickTalk, FasterLivePortrait, MuseTalk, FlashTalk, or OmniRT.

It is designed for scenarios such as AI customer support, product demos, course presenters,
news anchors, companion characters, and private digital-human deployments. If you are new to
the project, start with [Quick Start](quick-start/index.md) and run the Mock path first. If
you are already evaluating models, runtime backends, GPU/NPU resources, or OmniRT, continue
with [Model Support](model-support/index.md).

### Demo Video

<video src="https://github.com/user-attachments/assets/a3abce76-12c0-4b8b-844f-bbc5c3227dc7" controls width="100%"></video>


## Get Started Fast

- [Quick Start](quick-start/index.md) — first run and mock validation.
- [Model Support](model-support/index.md) — choose models, backends, and deployment paths.
- [Deployment](deployment/index.md) — model deployment and TTS weight prep.
- [Avatar Models](avatar_models/index.md) — Wav2Lip, QuickTalk, MuseTalk, FlashTalk, and more.
- [Speech Generation Models](speech_models/index.md) — LLM, STT, and TTS deployment.
- [Deployment Recipes](recipes/index.md) — combined setup such as local audio + QuickTalk.

## Key Features

- **Real-time conversation pipeline**: coordinates speech input, LLM response, TTS synthesis, subtitle events, avatar rendering, and WebRTC playback.
- **Pluggable model backends**: supports backend modes such as `mock`, `local`, `direct_ws`, and `omnirt`, from local validation to remote inference services.
- **Multiple model paths**: provides an evolving integration plan for Wav2Lip, QuickTalk, FasterLivePortrait, MuseTalk, FlashTalk, FlashHead, and related talking-head models.
- **Video Clone workflow**: use camera frames or uploaded video as driving input in WebUI to drive a source digital-human avatar.
- **Open LLM/TTS configuration**: supports OpenAI-compatible LLM endpoints, including DashScope, DeepSeek, Ollama, vLLM, or internal model services.
- **WebUI and command-line tools**: use WebUI for session validation, avatar selection, voice configuration, and model status; use CLI entrypoints for service startup and debugging.
- **Production-oriented runtime modes**: supports local development, Mock validation, Docker, API / Worker split, and external inference-service integration.

## User Guide

- [Usage](usage/index.md): command-line startup, WebUI usage, Video Clone, avatar configuration, and voice/TTS settings.
- [Examples](examples/index.md): customer support, product demos, course presenters, and similar scenarios.
- [Model Support](model-support/index.md): model and backend selection, plus production topology.
- [Reference Materials](reference/index.md): benchmark metrics and changelog entries.
- [FAQ](faq.md): installation, configuration, WebRTC, model backend, and runtime issues.

## License Information

OpenTalking is released under the Apache License 2.0. Talking-head models, model weights,
TTS services, LLM services, and external inference backends may have their own licenses or
terms of use. Check the corresponding project or service before deployment or commercial use.
