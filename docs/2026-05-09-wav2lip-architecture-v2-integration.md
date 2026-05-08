# Wav2Lip Architecture V2 Integration Changes

Date: 2026-05-09

This document records the OpenTalking-side changes made while migrating Wav2Lip
support onto the architecture-v2 asset/runtime split. OmniRT owns inference;
OpenTalking owns avatar assets, session configuration, WebRTC playback, and the
client-facing API.

## Asset model

- Extended avatar manifests with explicit asset metadata for built-in avatars.
- Added Wav2Lip mouth metadata under avatar metadata so an asset can carry a
  precomputed mouth polygon, normalized mouth center/radius, source image hash,
  and face box.
- Added `opentalking/avatar/mouth_metadata.py` to compute and update mouth
  metadata from a reference image using MediaPipe when it is available.
- Custom avatar upload now writes the uploaded image as a new avatar asset and
  stores the generated thumbnail/reference frame in the avatar directory.
- Large custom uploads are resized only when they exceed the realtime maximum
  box. Smaller images are not upscaled.

## Session and runtime integration

- Wav2Lip sessions pass `enable_enhanced_postprocessing`, `mouth_metadata`, and
  optional video size config to the FlashTalk-compatible OmniRT websocket client.
- The Wav2Lip client init payload now includes width, height, fps, enhanced
  postprocessing state, and mouth metadata when supplied.
- OpenTalking preserves avatar/model decoupling: the selected avatar supplies
  image and metadata; the selected driver model determines the runtime.
- Reference frame resizing now matches the target video dimensions directly so
  the initial WebRTC frame and generated frames have the same shape.

## Tests

- Added coverage for FlashTalk websocket init payloads used by Wav2Lip.
- Added coverage for reference frame resizing.
- Expanded custom avatar tests to cover asset creation, thumbnail/reference
  output, image-size limiting, and mouth metadata behavior.
