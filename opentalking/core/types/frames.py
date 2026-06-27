from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class AudioChunk:
    """PCM audio segment."""

    data: np.ndarray
    sample_rate: int
    duration_ms: float


@dataclass
class VideoFrameData:
    """Single video frame (BGR or RGB uint8)."""

    data: np.ndarray
    width: int
    height: int
    timestamp_ms: float
