# Events and Streaming

OpenTalking exposes two streaming interfaces over a session: a Server-Sent Events
channel for out-of-band events from the pipeline, and a WebSocket endpoint for
real-time audio input.

## Session event stream

### `GET /sessions/{session_id}/events`

Server-Sent Events stream that delivers the session's lifetime events: transcripts,
language model token deltas, text-to-speech lifecycle markers, video frame timing,
and errors. The stream remains open for the lifetime of the session.

**Path parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | string | Session UUID4. |

**Response — `200 OK`**

Content-Type: `text/event-stream`. Each message follows the SSE wire format:

```text
event: <type>
data: <json payload>

```

The `event` field is one of the types described below; the `data` field is a JSON
object whose schema depends on `event`.

**Reverse proxy configuration**

The SSE stream requires proxy buffering to be disabled. For nginx:

```nginx
location ~ ^/sessions/[^/]+/events$ {
    proxy_pass http://opentalking;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_cache off;
    proxy_set_header Connection '';
    chunked_transfer_encoding off;
}
```

### Event types

| Event | Payload schema | Emitted when |
|-------|---------------|--------------|
| `transcript` | `{ "text": string, "is_final": boolean }` | Speech recognition produces a partial or final transcript. |
| `llm` | `{ "delta": string }` | The language model emits a token delta. The full response is the concatenation of all `llm.delta` strings until the next `status` boundary. |
| `tts` | `{ "stage": string, "ms_elapsed": integer, "sentence_index": integer? }` | A text-to-speech lifecycle marker is reached. `stage` values: `start`, `first_audio`, `complete`. |
| `frame` | `{ "frame_idx": integer, "pts_ms": integer }` | A synthesized video frame is queued for delivery. `pts_ms` is the presentation timestamp relative to the start of the speak/chat turn. |
| `status` | `{ "stage": string, "message": string? }` | A high-level pipeline state change. `stage` values: `listening`, `thinking`, `speaking`, `idle`, `interrupted`, `error`. |
| `error` | `{ "code": string, "message": string }` | A recoverable or unrecoverable error. Recoverable errors emit a subsequent `status: idle` event; unrecoverable errors are followed by `session.terminated`. |
| `session.terminated` | `{}` | The session has been terminated and the stream is about to close. |

### Example stream

The following sequence corresponds to one user utterance, followed by one chat
response:

```text
event: transcript
data: {"text":"What is the","is_final":false}

event: transcript
data: {"text":"What is the weather today","is_final":true}

event: status
data: {"stage":"thinking","message":""}

event: llm
data: {"delta":"Today's"}

event: llm
data: {"delta":" weather is"}

event: tts
data: {"stage":"start","ms_elapsed":340,"sentence_index":0}

event: tts
data: {"stage":"first_audio","ms_elapsed":520,"sentence_index":0}

event: frame
data: {"frame_idx":0,"pts_ms":600}

event: frame
data: {"frame_idx":1,"pts_ms":640}

event: status
data: {"stage":"idle","message":""}
```

### Client implementation example

```javascript title="EventSource"
const events = new EventSource(`/sessions/${sessionId}/events`);

events.addEventListener('transcript', (e) => {
  const { text, is_final } = JSON.parse(e.data);
  console.log(is_final ? 'final' : 'partial', text);
});

events.addEventListener('llm', (e) => {
  const { delta } = JSON.parse(e.data);
  appendToResponse(delta);
});

events.addEventListener('error', (e) => {
  const { code, message } = JSON.parse(e.data);
  console.error('pipeline error', code, message);
});

events.addEventListener('session.terminated', () => {
  events.close();
});
```

```python title="httpx async stream"
import httpx, json

async with httpx.AsyncClient(timeout=None) as client:
    async with client.stream(
        "GET", f"http://localhost:8000/sessions/{session_id}/events"
    ) as response:
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                event_name = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                payload = json.loads(line.removeprefix("data:").strip())
                handle_event(event_name, payload)
```

## Audio input WebSocket

### `WebSocket /sessions/{session_id}/speak_audio_stream`

Streams raw PCM audio from the client to the server for real-time synthesis. The
client opens the connection, sends framed audio messages, and signals end-of-stream.
The server delivers synthesized output through the SSE channel and WebRTC track.

**Path parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | string | Session UUID4 of an already-started session. |

**Subprotocol** — none. The endpoint uses raw WebSocket framing.

### Message format

Messages may be binary frames (audio data) or text frames (control commands).

**Binary frames**

Raw 16-bit signed PCM, little-endian, mono, at the session's configured sample rate
(default 16000 Hz). Each binary frame may contain any number of complete PCM samples;
20 ms (640 bytes at 16 kHz) is the recommended frame size for low-latency streaming.

**Text frames (control)**

JSON-encoded control messages.

| Message | Schema | Purpose |
|---------|--------|---------|
| `{ "type": "config", "sample_rate": integer? }` | Optional first message. Overrides the audio sample rate for this stream. | |
| `{ "type": "eos" }` | Signals the end of the audio stream. The server flushes any pending audio through the synthesis pipeline. | |
| `{ "type": "interrupt" }` | Equivalent to `POST /sessions/{id}/interrupt`. Cancels the current synthesis. | |

### Server-to-client messages

The server may emit text frames with status updates:

| Message | Schema | Purpose |
|---------|--------|---------|
| `{ "type": "ack" }` | Sent after the configuration message is accepted. |
| `{ "type": "error", "code": string, "message": string }` | Sent before closing on unrecoverable errors. |

Synthesized audio and video are delivered through the WebRTC track, not through this
WebSocket. Status updates and frame timing remain on the SSE event stream.

### Close behavior

The connection is closed by the server when:

- The client sends an `eos` message and the pipeline has flushed.
- An unrecoverable error occurs (an `error` message is sent first).
- The session is terminated.

The client should treat any close as terminal and not reconnect to the same
`session_id`.

### Client implementation example

```javascript title="browser WebSocket"
const ws = new WebSocket(`ws://localhost:8000/sessions/${sessionId}/speak_audio_stream`);
ws.binaryType = 'arraybuffer';

ws.onopen = () => {
  ws.send(JSON.stringify({ type: 'config', sample_rate: 16000 }));
  startMicrophoneCapture((pcmFrame /* Int16Array */) => {
    ws.send(pcmFrame.buffer);
  });
};

ws.onmessage = (e) => {
  if (typeof e.data === 'string') {
    const msg = JSON.parse(e.data);
    if (msg.type === 'error') console.error(msg);
  }
};

function stopRecording() {
  ws.send(JSON.stringify({ type: 'eos' }));
}
```

```python title="websockets client"
import asyncio, json, websockets

async def stream_audio(session_id: str, pcm_chunks):
    uri = f"ws://localhost:8000/sessions/{session_id}/speak_audio_stream"
    async with websockets.connect(uri, max_size=2**22) as ws:
        await ws.send(json.dumps({"type": "config", "sample_rate": 16000}))
        for chunk in pcm_chunks:           # iterable of 16-bit PCM bytes
            await ws.send(chunk)
        await ws.send(json.dumps({"type": "eos"}))
        async for message in ws:           # drain server status messages
            if isinstance(message, str):
                print(json.loads(message))
```

## Event ordering and back-pressure

- Within a single speak or chat turn, events are emitted in causal order: `transcript` → `status:thinking` → `llm.delta`* → `tts:start` → `tts:first_audio` → `frame`* → `status:idle`.
- `frame` events are emitted in monotonically increasing `frame_idx`. Frame delivery on the WebRTC track is not gated on the corresponding SSE event being consumed.
- The server applies no back-pressure on slow SSE consumers. A consumer that falls more than ~5 seconds behind may be disconnected.
- The WebSocket audio input does apply back-pressure: clients that send faster than the synthesis pipeline can absorb receive flow-control signals from the underlying transport.

## Source files

- `apps/api/routes/events.py` — SSE endpoint.
- `apps/api/routes/sessions.py` — `speak_audio_stream` WebSocket endpoint.
- `opentalking/core/events.py` — event schemas.
- `opentalking/core/bus.py` — pub/sub bus.
