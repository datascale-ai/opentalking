from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

from opentalking.core.types.frames import AudioChunk

logger = logging.getLogger(__name__)


@dataclass
class DrivingFeatures:
    """Features + frame budget for one audio chunk (adapter-internal contract)."""

    vector: np.ndarray
    frame_count: int


def extract_mel_placeholder(chunk: AudioChunk, fps: int) -> DrivingFeatures:
    """Simple RMS feature as stand-in when Whisper is not available."""
    from opentalking.models.common.frame_avatar import audio_chunk_to_frame_count

    x = chunk.data.astype(np.float32)
    if x.size == 0:
        vec = np.zeros((1,), dtype=np.float32)
    else:
        rms = float(np.sqrt(np.mean(np.square(x))))
        vec = np.array([rms], dtype=np.float32)
    fc = audio_chunk_to_frame_count(chunk, fps)
    return DrivingFeatures(vector=vec, frame_count=fc)


def extract_whisper_features(
    chunk: AudioChunk,
    whisper_model: Any,
    fps: int,
    device: str = "cuda",
) -> DrivingFeatures:
    """Extract audio features using Whisper-tiny encoder.

    Converts PCM audio chunk to mel spectrogram, runs through Whisper encoder,
    returns the encoded feature tensor as a numpy array.
    """
    import torch
    import whisper

    from opentalking.models.common.frame_avatar import audio_chunk_to_frame_count

    fc = audio_chunk_to_frame_count(chunk, fps)

    # Convert PCM int16 to float32 [-1, 1]
    audio_f32 = chunk.data.astype(np.float32) / 32768.0

    # Pad or trim to 30s (Whisper expects fixed-length mel)
    # For short chunks we pad with zeros
    audio_f32 = whisper.pad_or_trim(audio_f32)

    # Compute mel spectrogram
    mel = whisper.log_mel_spectrogram(audio_f32).to(device)

    # Run through Whisper encoder
    with torch.no_grad():
        # mel shape: (80, 3000) -> add batch dim -> (1, 80, 3000)
        if mel.ndim == 2:
            mel = mel.unsqueeze(0)
        audio_feature = whisper_model.encoder(mel)
        # audio_feature shape: (1, 1500, dim)

    # Extract the portion corresponding to our chunk duration
    # Whisper has 50 tokens/sec (1500 tokens for 30s)
    tokens_per_sec = 50
    chunk_tokens = max(1, int(chunk.duration_ms / 1000.0 * tokens_per_sec))
    feature_slice = audio_feature[0, :chunk_tokens, :].cpu().numpy()

    return DrivingFeatures(vector=feature_slice, frame_count=fc)
