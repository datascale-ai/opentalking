# Video Clone

Video Clone is a WebUI workflow next to Realtime Conversation. It keeps an OpenTalking avatar-library asset as the source, then uses browser camera frames or an uploaded video as the driving video so the avatar follows the user's expression, mouth, and head motion.

![Video Clone workspace](../../../assets/images/usage/video-clone-workspace.png)

## When to Use It

- Validate FasterLivePortrait video-driven output.
- Use a camera to test realtime expression and head-motion following.
- Upload a selfie video to inspect driving-video mouth shape, crop, and pasteback behavior.

Video Clone does not start an LLM conversation and does not call TTS or STT. It is separate from the audio-driven Realtime Conversation workflow.

## Prerequisites

1. OmniRT is running the FasterLivePortrait runtime.
2. OpenTalking API can reach OmniRT.
3. WebUI model status reports `fasterliveportrait` as connected.
4. The browser can access the camera. Use `localhost`, `127.0.0.1`, or HTTPS.

If services are not running yet, first follow the [FasterLivePortrait model page](../../../avatar_models/fasterliveportrait.md) and complete both Start OmniRT and Start OpenTalking WebUI.

## Page Layout

### Source Avatar

The source panel lists digital-human assets from the avatar library. Click an asset to make it the output character. Camera or uploaded video frames do not become the source; they only provide motion.

If the output appears as an over-zoomed head, make sure `Pasteback` is enabled. It pastes the animated face back into the original source image so the body, background, and aspect ratio are preserved.

### Clone Output

The center panel shows the selected source and the cloned output. The status strip shows sent frames, received frames, dropped frames, and latency.

After stopping, click the change-avatar control to return to source selection and choose another asset.

### Driving Input

The right panel selects camera, FPS, resolution, and local preview. After Start, the browser samples camera frames through a canvas timer and sends them to the backend.

Uploaded driving video is a secondary testing path for comparing the same selfie video under different parameters.

## Live Camera Driving

1. Open WebUI and switch to Video Clone.
2. Select a digital-human source on the left.
3. Select camera, FPS, and resolution on the right.
4. Click Start and allow browser camera permission.
5. Watch the center output and status strip.
6. Click Stop or leave the page only after the camera preview closes.

Start with `12fps` and `448px`. Increase FPS or resolution only after output is stable.

## Uploaded Driving Video

Uploaded video is for validating driving-video expression, mouth, and crop behavior. Use a clear frontal or half-body selfie video. Avoid a tiny face, heavy occlusion, extreme head turns, or very narrow aspect ratios.

If uploaded-video output looks worse than camera output:

- Disable `Crop driving face` so the driving face is not cropped too tightly.
- Enable `Pasteback` so output is not a cropped head-only view.
- Enable `Lip retargeting` and disable `Relative motion`.
- Change the driving region from `Mouth` to `Expression` or `All` and check whether mouth corners and cheeks recover.

## Parameter Suggestions

| Parameter | Effect | Suggestion |
| --- | --- | --- |
| Motion amplitude | Overall driving strength | Start from `1.0` |
| Expression amplitude | Expression and mouth strength | Start from `1.0` |
| Head amplitude | Overall head motion | Start from `0.3` |
| Mouth opening | Mouth open/close amplitude | `0.8-1.3` |
| Yaw / pitch / roll | Pose components | Lower the component that looks too strong |
| Pasteback | Preserve source composition | Keep enabled |
| Stitching | Stabilize face boundary | Keep enabled |
| Relative motion | Preserve source base pose | Usually disable when lip retargeting is enabled |
| Lip normalize | Reduce initial mouth-shape offset | Keep enabled |
| Lip retargeting | Improve mouth following | Try when the mouth is puffy or does not open enough |
| Crop driving face | Crop input-video face | Disable when uploaded-video aspect ratio looks wrong |

## Common Issues

### Cannot Start Camera or Video Clone Service

Check browser permissions, page origin (`localhost` / `127.0.0.1` / HTTPS), and whether FasterLivePortrait is connected in `/models`.

### Uploaded Video Mouth Looks Puffy or Too Closed

This is usually related to driving-video crop, face position, scaling, or lip parameters. Disable `Crop driving face` first, then try `Lip retargeting + Relative motion off`.

### Lip Retargeting Turns into Mostly Vertical Mouth Opening

Lip retargeting strengthens mouth open/close. If relative motion stays enabled, mouth corners and cheek movement can become weak. Disable `Relative motion` and switch the driving region to `Expression` or `All`.

### Avatar Aspect Ratio Looks Wrong After Selection

Enable `Pasteback` and choose a source with the desired original composition. Video Clone should use the source image for output composition; the driving video only provides motion.
