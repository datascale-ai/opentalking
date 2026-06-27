# Sessions

A session represents one conversational connection between a client and the
OpenTalking server. The session encapsulates the chosen avatar, the chosen synthesis
model, the WebRTC track, and the lifecycle state of the underlying pipeline.

The session endpoints fall into four categories:

- **Lifecycle** — create, query, start, terminate.
- **Conversational interaction** — `speak`, `transcribe`, `interrupt`, customization.
- **Direct audio input** — `speak_audio`, `speak_flashtalk_audio`, plus the WebSocket variant documented in [Events and Streaming](events.md).
- **WebRTC signaling and FlashTalk recording** — SDP exchange, on-line recording, deferred rendering.

## Lifecycle

### `POST /sessions`

Creates a new session.

**Request body — `application/json`**

`CreateSessionRequest`:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `avatar_id` | string | Yes | Avatar identifier from `GET /avatars`. |
| `model` | string | Yes | Synthesis model. Must appear in `GET /models` with `connected=true`. |
| `tts_provider` | string \| null | No | Overrides `OPENTALKING_TTS_DEFAULT_PROVIDER` for this session. Common values: `edge`, `dashscope`, `local_cosyvoice`, `indextts`, `cosyvoice`, `elevenlabs`, `openai_compatible`, `xiaomi_mimo`. |
| `tts_voice` | string \| null | No | Overrides the default voice. Format depends on provider. |
| `llm_system_prompt` | string \| null | No | Overrides `OPENTALKING_LLM_SYSTEM_PROMPT` for this session. |
| `wav2lip_postprocess_mode` | string \| null | No | wav2lip-specific post-processing flag. Forwarded to the selected Wav2Lip backend when supported. |

**Response — `200 OK`**

`CreateSessionResponse`:

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | string | UUID4 of the newly created session. |
| `status` | string | Always `"created"` on success. |

```bash title="curl"
curl -s -X POST http://localhost:8000/sessions \
  -H 'content-type: application/json' \
  -d '{
        "avatar_id": "demo-avatar",
        "model": "mock"
      }'
```

```json title="response"
{
  "session_id": "1f4a8c98-3e5e-4b6c-a3f1-9b8e2c4d7e91",
  "status": "created"
}
```

**Error responses**

| Code | Condition |
|------|-----------|
| `400` | `avatar_id` does not exist; or `model` is not connected; or `tts_provider` is unknown. |
| `502` | An upstream service (DashScope, OmniRT, or a direct WebSocket backend) returned an error during initialization. |

### `GET /sessions/{session_id}`

Returns the current state of a session.

**Path parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | string | UUID4 returned by `POST /sessions`. |

**Response — `200 OK`**

The body includes the session metadata (avatar, model, voice) and the high-level
state (`created`, `running`, `paused`, `terminated`).

**Error responses**

| Code | Condition |
|------|-----------|
| `404` | Session not found. |

### `POST /sessions/{session_id}/start`

Marks the session as active so that subsequent `speak` requests are honored. May be invoked once per session.

**Response — `200 OK`**

```json
{"status": "running"}
```

**Error responses**

| Code | Condition |
|------|-----------|
| `404` | Session not found. |
| `409` | Session is already running or terminated. |

### `DELETE /sessions/{session_id}`

Terminates the session. Closes the WebRTC track, releases the associated worker, and
removes session state from Redis.

**Response — `200 OK`**

```json
{"status": "terminated"}
```

**Error responses**

| Code | Condition |
|------|-----------|
| `404` | Session not found. |

## Text and Audio Interaction

### `POST /sessions/{session_id}/speak`

Synthesizes a fixed string. Bypasses the language model; useful for scripted greetings,
demonstrations, or playback of pre-computed text.

**Request body — `application/json`**

`SpeakRequest`:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `text` | string | Yes | Text to synthesize. |
| `voice` | string \| null | No | Voice override. For Edge, a `zh-CN-*Neural` short name. For DashScope, a voice name from the console. For ElevenLabs, a `voice_id`. |
| `tts_provider` | string \| null | No | One of `edge`, `dashscope`, `local_cosyvoice`, `indextts`, `cosyvoice`, `elevenlabs`, `openai_compatible`, `xiaomi_mimo`, `qwen_tts`, `sambert`. |
| `tts_model` | string \| null | No | Provider-specific model. Examples: `qwen3-tts-flash-realtime`, `cosyvoice-v3-flash`, `eleven_flash_v2_5`. |

**Response — `200 OK`** — empty body. Pipeline output is delivered through SSE and
WebRTC.

```bash title="curl"
curl -s -X POST "http://localhost:8000/sessions/$SID/speak" \
  -H 'content-type: application/json' \
  -d '{"text": "Welcome to OpenTalking."}'
```

### `POST /sessions/{session_id}/transcribe`

Submits a PCM audio buffer for speech recognition. Returns the recognized text. The
recognized text may optionally be forwarded to the language model and trigger a
speech response, depending on the request flags.

**Request body — `multipart/form-data`**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `audio` | file | Yes | PCM audio, 16-bit signed, mono, at the sample rate configured for the session (default 16000 Hz). |
| `trigger_chat` | boolean | No | When `true`, the recognized text is forwarded to the language model. |

**Response — `200 OK`**

```json
{"transcript": "Recognized text."}
```

### `POST /sessions/{session_id}/interrupt`

Cancels any in-flight `speak`, `speak_audio`, or `transcribe` request. The
pipeline halts at the next frame boundary, drains in-flight frames, and returns to
the idle state.

**Response — `200 OK`**

```json
{"interrupted": true}
```

The pipeline typically settles to the idle state within 200 ms.

### `POST /sessions/{session_id}/customize` and variants

Endpoints for runtime persona customization:

- `POST /sessions/{session_id}/customize` — replaces multiple persona attributes in a
  single call.
- `POST /sessions/{session_id}/customize/prompt` — replaces the session's system
  prompt.
- `POST /sessions/{session_id}/customize/reference` — sets a reference audio for
  voice continuity.

The schemas are defined in `apps/api/routes/sessions.py`. Refer to the source for the
current request bodies and validation rules.

## Direct audio input

### `POST /sessions/{session_id}/speak_audio`

Submits pre-generated audio bytes for synthesis, bypassing the text-to-speech stage.
Used when audio is generated by an external system (a custom TTS, a recorded clip,
or a separate audio pipeline).

**Request body — `multipart/form-data`**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `audio` | file | Yes | PCM or MP3 audio. Format detected automatically. |
| `sample_rate` | integer | No | Required if the audio is raw PCM. Default 16000. |

**Response — `200 OK`** — empty body. Synthesized frames are delivered through SSE
and WebRTC.

### `POST /sessions/{session_id}/speak_flashtalk_audio`

FlashTalk-optimized variant of `speak_audio`. Performs additional audio segmentation
and smoothing tailored to FlashTalk's chunk size and idle-frame model. Recommended
when the configured synthesis model is `flashtalk`.

The request body matches `speak_audio`.

### WebSocket variant

`WebSocket /sessions/{session_id}/speak_audio_stream` — streams audio in real time
for synthesis. See [Events and Streaming → Audio input WebSocket](events.md#audio-input-websocket).

## WebRTC signaling

### `POST /sessions/{session_id}/webrtc/offer`

Exchanges Session Description Protocol messages to establish the WebRTC connection.
The client sends an SDP offer; the server returns an SDP answer containing the
configured audio and video tracks.

**Request body — `application/json`**

`WebRTCOfferRequest`:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `sdp` | string | Yes | The SDP offer string generated by the client's RTCPeerConnection. |
| `type` | string | Yes | Always `"offer"`. |

**Response — `200 OK`**

```json
{
  "sdp": "v=0\r\no=- ...",
  "type": "answer"
}
```

**Error responses**

| Code | Condition |
|------|-----------|
| `400` | The SDP is malformed. |
| `404` | Session not found. |
| `409` | Session is already terminated. |

## FlashTalk recording

These endpoints capture an in-flight FlashTalk session for deferred review.

| Endpoint | Purpose |
|----------|---------|
| `POST /sessions/{session_id}/flashtalk-recording/start` | Begins recording the session's audio and frames. |
| `POST /sessions/{session_id}/flashtalk-recording/stop` | Ends the recording. The artifact is finalized to disk. |
| `GET /sessions/{session_id}/flashtalk-recording` | Returns the current recording state and, when complete, a downloadable artifact identifier. |

The response from `GET /sessions/{session_id}/flashtalk-recording` includes:

```json
{
  "state": "idle | recording | complete",
  "artifact_url": "<download URL when state=complete>",
  "duration_ms": 12500
}
```

## FlashTalk offline bundle

Endpoints for batch rendering of a full session for one-time playback. The offline
bundle is rendered after the session is complete and produces an MP4 file.

### `POST /sessions/{session_id}/flashtalk-offline-bundle`

Submits a bundle rendering job.

**Response — `200 OK`**

```json
{
  "job_id": "<uuid4>",
  "status": "pending"
}
```

### `GET /sessions/{session_id}/flashtalk-offline-bundle/{job_id}`

Returns job status.

**Response — `200 OK`**

```json
{
  "job_id": "<uuid4>",
  "status": "pending | running | complete | failed",
  "progress": 0.62,
  "error": null
}
```

### `GET /sessions/{session_id}/flashtalk-offline-bundle/{job_id}/download`

Downloads the rendered MP4 once `status=complete`. Response Content-Type is
`video/mp4`.

**Error responses**

| Code | Condition |
|------|-----------|
| `404` | Job identifier not found. |
| `409` | Job is not yet complete. |

## Source files

- `apps/api/routes/sessions.py` — endpoint implementations.
- `apps/api/schemas/session.py` — `CreateSessionRequest`, `CreateSessionResponse`, `SpeakRequest`, `ChatRequest`, `WebRTCOfferRequest`.
- `opentalking/runtime/` — the pipeline driver that handles `speak`, `transcribe`, and `interrupt`.
- `opentalking/rtc/` — WebRTC track management invoked by `/webrtc/offer`.
