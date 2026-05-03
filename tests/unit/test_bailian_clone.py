from __future__ import annotations

import math
import wave
from io import BytesIO

import numpy as np

from opentalking.voices.bailian_clone import convert_audio_to_wav_24k_mono


def _wav_bytes(sample_rate: int, seconds: float) -> bytes:
    n = int(sample_rate * seconds)
    t = np.arange(n, dtype=np.float32) / float(sample_rate)
    pcm = (0.2 * np.sin(2.0 * math.pi * 220.0 * t) * 32767.0).astype(np.int16)
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def test_convert_audio_to_wav_24k_mono_trims_long_clone_sample() -> None:
    src = _wav_bytes(16000, 8.0)
    out = convert_audio_to_wav_24k_mono(src, ".wav", max_seconds=5.0)

    with wave.open(BytesIO(out), "rb") as wf:
        assert wf.getframerate() == 24000
        assert wf.getnchannels() == 1
        duration = wf.getnframes() / float(wf.getframerate())

    assert 4.5 <= duration <= 5.1
