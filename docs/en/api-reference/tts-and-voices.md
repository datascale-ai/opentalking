# TTS and Voices

Endpoints for one-off text-to-speech synthesis (without creating a session) and for
management of cloned voices.

## TTS preview

### `POST /tts/preview`

Synthesizes a short audio clip without creating a session. Used by the frontend for
voice auditioning before a session is started.

**Request body — `application/json`**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `text` | string | Yes | Text to synthesize. Recommended maximum length: 200 characters. |
| `voice` | string | No | Voice identifier. Format depends on `provider`. |
| `provider` | string | No | One of `edge`, `dashscope`, `cosyvoice`, `elevenlabs`. Defaults to `OPENTALKING_TTS_PROVIDER`. |
| `model` | string | No | Provider-specific model identifier. |

**Response — `200 OK`**

Content-Type: `audio/wav`. Body is a 16-bit PCM WAV file at the session sample rate
(default 16000 Hz).

```bash title="curl"
curl -s -X POST http://localhost:8000/tts/preview \
  -H 'content-type: application/json' \
  -d '{"text": "Hello, this is a voice preview.", "provider": "edge", "voice": "en-US-AriaNeural"}' \
  -o preview.wav
```

**Error responses**

| Code | Condition |
|------|-----------|
| `400` | `text` is empty or exceeds the configured length limit. |
| `502` | The upstream TTS provider returned an error. |

## Voices

The voice catalog persists cloned voices in a local SQLite database. Cloned voices
remain available until explicitly deleted; they survive process restarts.

### `GET /voices`

Lists cloned voices.

**Query parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `provider` | string \| null | Filter by provider (`cosyvoice` or `dashscope`). |

**Response — `200 OK`**

```json
{
  "items": [
    {
      "id": 1,
      "user_id": null,
      "provider": "dashscope",
      "voice_id": "u3e7c12ab",
      "display_label": "Alice's Voice",
      "target_model": "qwen3-tts-flash-realtime",
      "source": "clone"
    }
  ]
}
```

Field descriptions:

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Catalog primary key. Used in `DELETE /voices/{entry_id}`. |
| `user_id` | string \| null | Reserved for future multi-tenant deployments. |
| `provider` | string | `cosyvoice` or `dashscope`. |
| `voice_id` | string | Provider-side voice identifier. Pass this value as the session's `tts_voice` when using the cloned voice. |
| `display_label` | string | Human-readable label. |
| `target_model` | string | TTS model identifier this clone was created for. |
| `source` | string | Always `"clone"` for entries created by this endpoint. |

```bash title="curl"
curl -s 'http://localhost:8000/voices?provider=dashscope' | jq
```

### `POST /voices/clone`

Clones a voice from an audio sample. Two providers are supported, each with its own
requirements.

**Request body — `multipart/form-data`**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `provider` | string | Yes | `cosyvoice` or `dashscope`. |
| `target_model` | string | Yes | TTS model identifier the clone will be used with. For DashScope: a voice-cloning-compatible model such as a Qwen VC model. For CosyVoice: a CosyVoice model identifier. |
| `display_label` | string | Yes | Human-readable label. The endpoint deduplicates labels by appending a timestamp suffix when a conflict exists. |
| `audio` | file | Yes | Audio sample. Minimum 256 bytes, maximum 12 MB. |
| `prefix` | string | No | CosyVoice only. Optional voice identifier prefix; random characters are generated when omitted. |
| `preferred_name` | string | No | DashScope only. Preferred voice name; a random identifier is generated when omitted. |

**Provider-specific requirements**

- **CosyVoice** uploads the audio sample and provides its public URL to DashScope; the
  OpenTalking server must be reachable from DashScope. Configure
  `OPENTALKING_PUBLIC_BASE_URL` to specify the public URL. The sample is removed from
  disk approximately 300 seconds after upload.
- **DashScope** uses base64-encoded inline audio and does not require public
  reachability.

**Response — `200 OK`**

```json
{
  "ok": true,
  "entry_id": 12,
  "voice_id": "u3e7c12ab",
  "display_label": "Alice's Voice",
  "provider": "dashscope",
  "target_model": "qwen3-tts-flash-realtime",
  "message": "..."
}
```

| Field | Type | Description |
|-------|------|-------------|
| `entry_id` | integer | Catalog primary key, for later deletion. |
| `voice_id` | string | Provider-side voice identifier. Use this value when invoking `speak` or `chat` with the cloned voice. |
| `display_label` | string | Resolved label (may include a deduplication suffix). |
| `message` | string | Human-readable status message. |

```bash title="curl: DashScope clone"
curl -s -X POST http://localhost:8000/voices/clone \
  -F provider=dashscope \
  -F target_model=qwen3-tts-flash-realtime \
  -F display_label="Alice's Voice" \
  -F audio=@sample.wav
```

**Error responses**

| Code | Condition |
|------|-----------|
| `400` | `provider` is not `cosyvoice` or `dashscope`; audio is too short, missing, or exceeds 12 MB; audio format cannot be converted to 24 kHz mono WAV. |
| `502` | The upstream provider returned an error (DashScope rejection, CosyVoice cloning failure). |

### `DELETE /voices/{entry_id}`

Removes a cloned voice from the catalog.

**Path parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `entry_id` | integer | Catalog primary key from `GET /voices`. |

**Response — `200 OK`**

```json
{"deleted": true}
```

**Error responses**

| Code | Condition |
|------|-----------|
| `404` | The entry identifier was not found. |

### `GET /voice-uploads/{token}`

Internal endpoint that serves an uploaded audio sample for CosyVoice. The endpoint
exists so that DashScope's CosyVoice service can retrieve the sample over HTTP.

**Path parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `token` | string | 32-character hex token generated by `POST /voices/clone`. |

**Response — `200 OK`**

Content-Type: `audio/wav`. Body is the uploaded sample.

**Error responses**

| Code | Condition |
|------|-----------|
| `404` | The token is malformed or the sample has expired. |

!!! warning "Public exposure"
    This endpoint serves user-uploaded audio. Production deployments should rate-limit
    the path at the reverse proxy and ensure that `OPENTALKING_PUBLIC_BASE_URL` points
    to an internet-reachable address only when CosyVoice cloning is in use.

## Provider matrix

| Provider | Cloning | Voice format | Notes |
|----------|---------|--------------|-------|
| `edge` | Not supported | `<lang>-<region>-<name>Neural` (e.g. `en-US-AriaNeural`) | Built-in, no API key required. |
| `dashscope` | Supported | Console-defined name (e.g. `xiaoxiao`) or `voice_id` from clone | Requires `DASHSCOPE_API_KEY`. |
| `cosyvoice` | Supported | `voice_id` returned by clone, prefixed | Requires the OpenTalking server to be reachable from DashScope. |
| `elevenlabs` | External to OpenTalking | ElevenLabs `voice_id` | Requires `OPENTALKING_TTS_ELEVENLABS_API_KEY`. |

## Source files

- `apps/api/routes/tts_preview.py` — `/tts/preview`.
- `apps/api/routes/voices.py` — `/voices/*`, `/voice-uploads/{token}`.
- `opentalking/providers/tts/dashscope_qwen/clone.py` — DashScope and CosyVoice cloning implementations.
- `opentalking/voice/store.py` — voice catalog (SQLite).
- `opentalking/tts/adapters/` — provider-specific TTS adapters used by `/tts/preview` and session synthesis.
