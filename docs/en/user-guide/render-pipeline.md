# Render Pipeline

The render pipeline transforms a user prompt or a fixed text input into a stream of
audio and video frames delivered over WebRTC. This page documents each stage of the
pipeline, the interruption mechanism, and the latency budget.

## Pipeline overview

```mermaid
flowchart LR
    User([User microphone]) -->|PCM via WebSocket| STT
    STT[Speech recognition<br/>Paraformer realtime] -->|transcript event| LLM
    LLM[Language model<br/>OpenAI-compatible streaming] -->|token deltas| Splitter
    Splitter[Sentence splitter] -->|per-sentence text| TTS
    TTS[Text-to-speech<br/>Edge / DashScope / ElevenLabs] -->|MP3 or PCM stream| Decode
    Decode[ffmpeg PCM decode] -->|16-bit PCM chunks| Adapter
    Adapter[Synthesis adapter<br/>wav2lip / flashtalk / quicktalk] -->|video frames| AV
    AV[AV packing] -->|encoded media| WebRTC
    WebRTC([WebRTC track]) --> Browser([Browser])
```

## Stage-by-stage description

### 1. Speech recognition

Audio is delivered to the server through the WebSocket endpoint
`speak_audio_stream` or the HTTP endpoint `/transcribe`. The DashScope
`paraformer-realtime-v2` model produces partial transcripts, which are emitted as
`transcript` events. Source: `opentalking/stt/`.

### 2. Language model generation

Final transcripts are forwarded to an OpenAI-compatible chat completion endpoint.
Tokens are streamed back and re-emitted as `llm` events for client-side display.
Source: `opentalking/llm/`.

### 3. Sentence splitting

Language model tokens are concatenated until a sentence boundary is detected (`。`,
`！`, `？`, `.`, `!`, `?`, or a newline). Each completed sentence triggers an
immediate text-to-speech synthesis call, allowing playback to begin before the full
response is generated.

### 4. Text-to-speech synthesis

The text-to-speech adapter streams audio in the format supported by the provider:

- **Edge** — MP3 chunks.
- **DashScope Qwen realtime** — PCM frames over WebSocket.
- **ElevenLabs** — MP3 or PCM, depending on the configured `output_format`.
- **CosyVoice** — MP3 or WAV via the DashScope cloud service.

Source: `opentalking/tts/`.

### 5. Audio decoding

When the provider returns MP3 audio, a long-lived
`ffmpeg -f mp3 -i - -f s16le -ar 16000 -ac 1 -` subprocess decodes the bytes into
16-bit PCM. The PCM stream is sliced into `AudioChunk` instances (default duration:
20 ms). Smoothing at chunk boundaries is controlled by
`OPENTALKING_FLASHTALK_TTS_BOUNDARY_FADE_MS`. Source: `opentalking/tts/adapters/`.

### 6. Synthesis adapter

Each `AudioChunk` is passed to the registered `ModelAdapter`. The adapter's
`extract_features`, `infer`, and `compose_frame` methods are invoked in sequence. The
adapter emits video frames at the rate specified by the avatar's `fps` field (typically
25). See [Model Adapter](../developer-guide/model-adapter.md).

For remote synthesis backends (`flashtalk`, OmniRT-backed `wav2lip` and `musetalk`),
the adapter is a thin WebSocket client; inference is performed on the model service.

### 7. AV packing and WebRTC delivery

`opentalking/rtc/` packages PCM audio and synthesized frames into `RTCAudioFrame` and
`RTCVideoFrame` primitives, then writes them to the configured WebRTC track. The
browser renders the audio and video through the `<video>` element in `apps/web`.

## Interruption (barge-in)

The endpoint `POST /sessions/{id}/interrupt` sets a cancellation flag on the session.
The pipeline checks the flag between stages:

1. Language model stream — token reading is halted and the connection is closed.
2. Sentence splitter — the in-flight sentence is discarded.
3. Text-to-speech — the upstream WebSocket is aborted and the ffmpeg subprocess is
   terminated.
4. Synthesis adapter — frames for the current chunk are drained, after which the
   adapter returns to idle.
5. WebRTC — the track remains open; idle frames take over.

The pipeline settles to the idle state within approximately 200 ms of an interruption.

## Latency budget

The following measurements correspond to a single NVIDIA 4090 running Edge TTS and
FlashTalk-14B.

| Stage | Latency contribution |
|-------|---------------------|
| Speech recognition partial to final | 300–600 ms (depends on end-of-speech detection) |
| First language model token | 200–500 ms |
| Language model tokens to sentence boundary | One sentence of text |
| First text-to-speech audio | 150–400 ms |
| Audio chunk to first synthesized frame | 80–180 ms |
| Frame queue to WebRTC playback | < 50 ms (browser-side jitter) |

End-to-end latency from end-of-speech to first avatar frame is typically 700–1500 ms.
The dominant factor is the language model: `qwen-flash` is faster than `qwen-plus`,
and a local Ollama deployment with a preloaded model may achieve sub-100 ms time-to-
first-token.

## Source files

| File | Stage |
|------|-------|
| `opentalking/stt/` | Speech recognition adapters. |
| `opentalking/llm/` | Language model streaming clients. |
| `opentalking/worker/` | Pipeline orchestration, including sentence splitting and fan-out. |
| `opentalking/tts/adapters/` | Text-to-speech provider implementations. |
| `opentalking/models/quicktalk/` and related | Synthesis adapters. |
| `opentalking/rtc/` | WebRTC track and frame queue management. |
| `apps/api/routes/sessions.py` | Endpoints that drive and control the pipeline. |
