from __future__ import annotations

import numpy as np

from opentalking.models.musetalk.feature_extractor import DrivingFeatures, extract_mel_placeholder
from opentalking.core.types.frames import AudioChunk


def extract_mel_for_wav2lip(chunk: AudioChunk, fps: int) -> DrivingFeatures:
    """Reuse placeholder features; real Wav2Lip uses mel spectrogram."""
    return extract_mel_placeholder(chunk, fps)
