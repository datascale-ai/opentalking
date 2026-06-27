from __future__ import annotations

import numpy as np
import pytest

from opentalking.core.types.frames import AudioChunk
from opentalking.providers.tts.edge import adapter


@pytest.mark.asyncio
async def test_synthesize_stream_prefers_streaming_decode(monkeypatch: pytest.MonkeyPatch) -> None:
    streamed = [
        AudioChunk(data=np.array([1, 2, 3], dtype=np.int16), sample_rate=16000, duration_ms=0.1875),
        AudioChunk(data=np.array([4, 5], dtype=np.int16), sample_rate=16000, duration_ms=0.125),
    ]

    async def fake_stream_decode(*_args, **_kwargs):
        for chunk in streamed:
            yield chunk

    monkeypatch.setattr(adapter, "_env_bool", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(adapter, "_edge_audio_stream", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(adapter, "_stream_decode_mp3_to_pcm_chunks", fake_stream_decode)

    out = []
    async for chunk in adapter.EdgeTTSAdapter().synthesize_stream("hello"):
        out.append(chunk)

    assert out == streamed


@pytest.mark.asyncio
async def test_synthesize_stream_missing_ffmpeg_errors_when_streaming_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_stream_decode(*_args, **_kwargs):
        raise FileNotFoundError("ffmpeg")
        yield

    monkeypatch.setattr(adapter, "_env_bool", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(adapter, "_stream_decode_mp3_to_pcm_chunks", fake_stream_decode)

    tts = adapter.EdgeTTSAdapter()
    with pytest.raises(RuntimeError, match="ffmpeg is required for streaming Edge TTS decode"):
        async for _ in tts.synthesize_stream("hello"):
            pass
