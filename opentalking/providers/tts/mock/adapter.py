from __future__ import annotations

import math
from collections.abc import AsyncIterator

import numpy as np

from opentalking.core.types.frames import AudioChunk


def _tone_frequency(text: str) -> float:
    checksum = sum(ord(ch) for ch in text)
    return 180.0 + float(checksum % 220)


def _sine_wave(text: str, sample_rate: int, chunk_ms: float) -> np.ndarray:
    duration_sec = max(0.4, min(2.0, len(text) * 0.06))
    sample_count = max(1, int(sample_rate * duration_sec))
    t = np.arange(sample_count, dtype=np.float32) / sample_rate
    freq = _tone_frequency(text)
    carrier = np.sin(2.0 * math.pi * freq * t)
    envelope = np.linspace(0.15, 0.95, sample_count, dtype=np.float32)
    audio = carrier * envelope * 0.22
    return np.clip(audio * 32767.0, -32768, 32767).astype(np.int16)


class MockTTSAdapter:
    def __init__(
        self,
        default_voice: str = "mock",
        sample_rate: int = 16000,
        chunk_ms: float = 40.0,
    ) -> None:
        self.default_voice = default_voice
        self.sample_rate = sample_rate
        self.chunk_ms = chunk_ms

    async def synthesize_stream(self, text: str, voice: str | None = None) -> AsyncIterator[AudioChunk]:
        del voice
        pcm = _sine_wave(text, self.sample_rate, self.chunk_ms)
        chunk_samples = max(1, int(self.sample_rate * (self.chunk_ms / 1000.0)))
        for start in range(0, len(pcm), chunk_samples):
            part = pcm[start : start + chunk_samples]
            if part.size == 0:
                continue
            yield AudioChunk(
                data=part.copy(),
                sample_rate=self.sample_rate,
                duration_ms=1000.0 * float(part.size) / float(self.sample_rate),
            )
