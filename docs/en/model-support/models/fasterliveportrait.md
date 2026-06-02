# FasterLivePortrait

## Model Introduction

FasterLivePortrait is integrated through OmniRT. OpenTalking currently supports two paths:

- Realtime conversation: OpenTalking generates speech and OmniRT drives the avatar through `/v1/audio2video/fasterliveportrait`.
- Video clone: OpenTalking keeps a digital-human asset as the `source`, while browser camera frames or an uploaded video act as the `driving` input. Frames are streamed through an independent video-clone WebSocket.

Video clone does not enter the LLM, STT, or TTS conversation pipeline. It is a visual driving workflow for testing camera-driven facial expression and head motion.

## Suitable Scenarios

- Realtime preview of expression, head motion, and mouth motion.
- Use a clear frontal or half-body image as `source`, then drive it with a camera or selfie video.
- Use “Realtime Conversation” and “Video Clone” side by side in the same WebUI.

## Recommended Runtime Backend

Use `omnirt`. OpenTalking owns assets, WebUI, parameters, and browser frame streaming. OmniRT keeps FasterLivePortrait loaded and provides inference WebSockets.

| OpenTalking entry | OmniRT entry | Purpose |
| --- | --- | --- |
| `/sessions` with a FasterLivePortrait session | `/v1/audio2video/fasterliveportrait` | Audio-driven realtime conversation |
| `/video-clone/fasterliveportrait/ws` | `/v1/avatar/video-clone/fasterliveportrait` | Video-clone frame stream |

## Weights and Startup

First follow [FasterLivePortrait deployment](../../model-deployment/fasterliveportrait.md) to prepare the FasterLivePortrait source checkout, JoyVASA weights, TensorRT/ONNXRuntime dependencies, OmniRT, and OpenTalking.

Check whether OpenTalking sees the video-clone service:

```bash
curl -s http://127.0.0.1:8000/video-clone/status | jq
```

`connected` should be `true`. If it is `false`, check whether OmniRT started the FasterLivePortrait runtime and whether `OMNIRT_ENDPOINT` points to that service.

## Avatar Requirements

`source` is the digital-human image in the OpenTalking avatar library. Recommended assets:

- Clear frontal or half-body image.
- Unblocked face and stable lighting.
- Full head-and-shoulder composition. With pasteback enabled, output is pasted back into the original source image instead of showing only a cropped head.

The Video Clone page can upload a new `source` image directly. OpenTalking reuses the existing `/avatars/custom` asset API, adds the image to the avatar library, and selects it as the current source.

## Driving Input

`driving` controls expression and head motion. It is not the source identity:

- Live camera frames are the primary path.
- Uploaded driving video is useful for offline or near-realtime testing.
- Driving video is not cropped by default. If the face is too small or detection is unstable, try enabling “crop driving face”.

## Frontend Controls

The Video Clone page exposes driving controls:

| Control | Effect |
| --- | --- |
| Motion / expression / head-motion amplitude | Overall motion and expression strength |
| Mouth opening | First knob to raise when uploaded videos do not open the mouth enough |
| Animation region | Full face, expression, pose, mouth, or eyes |
| Pasteback | Preserve the original source composition instead of showing only a cropped head |
| Relative motion | Preserve relative motion differences between source and driving |
| Lip normalization / lip retargeting | Can improve mouth shape, but aggressive retargeting may reduce motion to simple vertical opening |

If the mouth looks puffy or misaligned, first check whether the driving video is being cropped. Then try disabling crop, keeping pasteback enabled, and balancing mouth opening with lip retargeting.

## WebUI Flow

1. Start the OmniRT FasterLivePortrait runtime.
2. Start OpenTalking API and WebUI.
3. Open WebUI and select “Video Clone” in the top navigation.
4. Select or upload the source avatar on the left.
5. Select a camera, or upload a driving video on the right.
6. Click Start and inspect the cloned output in the center.

When stopped or when the page is switched, WebUI releases the camera track, WebSocket, and current video-clone session.
