# Usage Overview

This section explains the everyday ways to use OpenTalking: start and debug services from the command line, then use WebUI to select avatars, choose models, configure voices, and validate a session.

If you have not started the project yet, begin with [Quick Start](../quick-start/index.md). If WebUI already opens, this section is the next place to look.

## Who This Section Is For

This section is for developers and integrators who have completed the basic setup and want to use OpenTalking more effectively. It covers:

- Starting OpenTalking services, the frontend, and helper scripts.
- Using WebUI for avatar, model, voice, and session configuration.
- Preparing custom avatars and previewing or cloning voices.
- Common parameters, ports, backends, and environment files.

It keeps model support, scenario tutorials, and API schemas out of the main usage flow so the page stays focused on how to use the current version.

## Main Usage Modes

### Command Line Tools

Command line tools are best for development, integration, deployment validation, and automation. Use them to start unified mode, select inference backends, set ports, prepare avatar assets, and run QuickTalk benchmarks.

Start with [Command Line Tools](./cli.md), then use [Advanced CLI Arguments](./cli-advanced.md) when you need backend, port, host, or remote inference options.

### WebUI

WebUI is best for interactive validation. It provides avatar selection, model selection, TTS provider and voice configuration, text or voice conversation, video creation, video clone, and status feedback.

Start with [WebUI Basic Usage](./webui/basic.md), then continue to [Custom Avatar](./webui/custom-avatar.md), [Voice and TTS](./webui/voice-and-tts.md), [Video Creation](./webui/video-creation.md), or [Video Clone](./webui/video-clone.md) when needed.

## Recommended Paths

### I Want to Try the UI

1. Start Mock mode from [Quick Start](../quick-start/index.md).
2. Open WebUI.
3. Follow [WebUI Basic Usage](./webui/basic.md) to select avatar, model, voice, and create a session.

Mock mode does not require model weights, so it is the fastest way to verify the UI and backend flow.

### I Want to Customize Avatar

1. Validate one built-in avatar first.
2. Read [Custom Avatar](./webui/custom-avatar.md) to understand image, video, and model requirements.
3. Upload an image in WebUI, or prepare Wav2Lip assets with scripts.
4. Select the new avatar in WebUI and test it with a short message.

### I Want to Configure Voice / TTS

1. Read [Voice and TTS](./webui/voice-and-tts.md) and choose the TTS provider.
2. Select or preview a default voice in WebUI.
3. If voice cloning is needed, prepare provider credentials, sample audio, and public access settings.

### I Want to Create a Digital-Human Video

1. Confirm WebUI opens and at least one avatar is available.
2. Read [Video Creation](./webui/video-creation.md), then choose `quicktalk` or `wav2lip` as the offline generation model.
3. Choose an audio source: upload audio, synthesize text, or clone a voice first.
4. Preview the result on the right or open the asset library to download the generated video.

Video Creation is an offline or near-realtime generation workflow. It does not require a realtime conversation session or WebRTC session.

### I Want to Drive an Avatar with Camera Expressions

1. Start the FasterLivePortrait OmniRT runtime according to the deployment guide.
2. Read [Video Clone](./webui/video-clone.md), then choose the source avatar.
3. Use a camera or uploaded driving video for expression and head-motion input.
4. Tune pasteback, driving crop, animation region, and mouth controls as needed.

### I Want to Start Services from CLI

1. Read [Command Line Tools](./cli.md) for the main commands and scripts.
2. Use `scripts/start_unified.sh` for Mock, local model, or OmniRT modes.
3. Use [Advanced CLI Arguments](./cli-advanced.md) when you need custom ports, host binding, or environment files.

## What This Section Does Not Cover

### Business Examples

Customer-service avatars, live commerce, course narration, and private assistants belong in [Tutorials](../tutorials/index.md). Usage pages focus on shared operations.

### Model and Runtime Backend Selection

Model capabilities, runtime backends, and production topology belong in [Model Support](../model-support/index.md). Usage pages only explain how to pass these choices into the current tools.

### API Schema

The recommended getting-started path currently focuses on WebUI and CLI. Detailed API fields, events, and asset formats will be organized in reference materials.

## Next Steps

- Start and debug services with scripts: [Command Line Tools](./cli.md).
- Learn the UI workflow: [WebUI Basic Usage](./webui/basic.md).
- Add your own avatar: [Custom Avatar](./webui/custom-avatar.md).
- Configure speech: [Voice and TTS](./webui/voice-and-tts.md).
- Generate offline videos: [Video Creation](./webui/video-creation.md).
- Drive an avatar with camera or uploaded video: [Video Clone](./webui/video-clone.md).
