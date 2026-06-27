"""PCM audio helpers (fades, trim) for the speak pipeline.

Extracted from synthesis_runner.py to keep that file focused on orchestration.
"""
from __future__ import annotations

import numpy as np


def fade_edges_i16(pcm: np.ndarray, sample_rate: int, fade_ms: float) -> np.ndarray:
    """Apply a tiny sentence-boundary fade to reduce TTS splice clicks."""
    arr = np.asarray(pcm, dtype=np.int16)
    fade_samples = int(sample_rate * max(0.0, fade_ms) / 1000.0)
    if arr.size == 0 or fade_samples <= 1:
        return arr
    fade_samples = min(fade_samples, arr.size // 2)
    if fade_samples <= 1:
        return arr
    out = arr.astype(np.float32, copy=True)
    out[:fade_samples] *= np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
    out[-fade_samples:] *= np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
    return np.clip(out, -32768, 32767).astype(np.int16)


def fade_head_i16(pcm: np.ndarray, sample_rate: int, fade_ms: float) -> np.ndarray:
    """Fade the first samples of a streamed sentence."""
    arr = np.asarray(pcm, dtype=np.int16)
    fade_samples = int(sample_rate * max(0.0, fade_ms) / 1000.0)
    if arr.size == 0 or fade_samples <= 1:
        return arr
    fade_samples = min(fade_samples, arr.size)
    out = arr.astype(np.float32, copy=True)
    out[:fade_samples] *= np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
    return np.clip(out, -32768, 32767).astype(np.int16)


def fade_tail_i16(pcm: np.ndarray, sample_rate: int, fade_ms: float) -> np.ndarray:
    """Fade the remaining tail before padding with silence."""
    arr = np.asarray(pcm, dtype=np.int16)
    fade_samples = int(sample_rate * max(0.0, fade_ms) / 1000.0)
    if arr.size == 0 or fade_samples <= 1:
        return arr
    fade_samples = min(fade_samples, arr.size)
    out = arr.astype(np.float32, copy=True)
    out[-fade_samples:] *= np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
    return np.clip(out, -32768, 32767).astype(np.int16)


def trim_trailing_silence_i16(
    pcm: np.ndarray,
    sample_rate: int,
    *,
    threshold: int = 300,
    min_tail_ms: float = 60.0,
) -> np.ndarray:
    """Remove trailing near-silence from PCM, keeping at least *min_tail_ms* ms."""
    if pcm.size == 0:
        return pcm
    min_keep = max(1, int(sample_rate * min_tail_ms / 1000.0))
    abs_pcm = np.abs(pcm)
    indices = np.nonzero(abs_pcm > threshold)[0]
    if indices.size == 0:
        return pcm[:min_keep]
    last_loud = int(indices[-1])
    end = max(last_loud + 1 + min_keep, min_keep)
    return pcm[: min(end, pcm.size)]
