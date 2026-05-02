from __future__ import annotations

import logging
import math
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
    frame_energy: np.ndarray | None = None


def _compute_per_frame_energy(pcm_f32: np.ndarray, frame_count: int) -> np.ndarray:
    if frame_count <= 0:
        return np.zeros((0,), dtype=np.float32)
    x = np.asarray(pcm_f32, dtype=np.float32).reshape(-1)
    if x.size == 0:
        return np.zeros((frame_count,), dtype=np.float32)

    boundaries = np.linspace(0, x.shape[0], num=frame_count + 1, dtype=np.int32)
    energies = np.zeros((frame_count,), dtype=np.float32)
    for i in range(frame_count):
        start = int(boundaries[i])
        end = int(boundaries[i + 1])
        if end <= start:
            end = min(x.shape[0], start + 1)
        window = x[start:end]
        if window.size == 0:
            continue
        rms = float(np.sqrt(np.mean(np.square(window), dtype=np.float32)))
        zcr = float(np.mean(np.abs(np.diff(np.signbit(window)))) if window.size > 1 else 0.0)
        energies[i] = rms * (1.0 + 0.25 * zcr)

    peak = float(np.max(energies)) if energies.size else 0.0
    if peak > 1e-6:
        floor = max(0.01, min(0.06, peak * 0.18))
        energies = np.clip((energies - floor) / max(1e-6, peak - floor), 0.0, 1.0)
        energies = energies * energies * (3.0 - 2.0 * energies)
    else:
        energies.fill(0.0)
    return energies.astype(np.float32, copy=False)


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
    return DrivingFeatures(
        vector=vec,
        frame_count=fc,
        frame_energy=_compute_per_frame_energy(x / 32768.0 if x.size else x, fc),
    )


def _extract_whisper_hidden_states(
    mel: Any,
    whisper_model: Any,
    device: str,
) -> Any:
    """Extract multi-layer hidden states from openai/whisper encoder."""
    import torch

    with torch.no_grad():
        encoder = whisper_model.encoder
        x = encoder.conv1(mel)
        x = torch.nn.functional.gelu(x)
        x = encoder.conv2(x)
        x = torch.nn.functional.gelu(x)
        x = x.permute(0, 2, 1)
        x = x + encoder.positional_embedding[: x.shape[1]]

        hidden_states = []
        for block in encoder.blocks:
            x = block(x)
            hidden_states.append(x)
        x = encoder.ln_post(x)
        hidden_states.append(x)
        stacked = torch.stack(hidden_states, dim=2)

    return stacked


def _encode_whisper_tokens(
    audio_f32: np.ndarray,
    whisper_model: Any,
    device: str,
) -> Any:
    import whisper

    audio_f32_padded = whisper.pad_or_trim(audio_f32)
    mel = whisper.log_mel_spectrogram(audio_f32_padded).to(device)
    if mel.ndim == 2:
        mel = mel.unsqueeze(0)

    whisper_feature = _extract_whisper_hidden_states(mel, whisper_model, device)
    audio_duration_sec = len(audio_f32) / 16000.0
    actual_length = max(1, int(audio_duration_sec * 50))
    whisper_feature = whisper_feature[:, :actual_length, ...]
    return whisper_feature


def _frame_features_from_token_timeline(
    whisper_feature: Any,
    frame_token_positions: np.ndarray,
    *,
    fps: int,
    audio_padding_length_left: int,
    audio_padding_length_right: int,
) -> np.ndarray:
    import torch

    whisper_idx_multiplier = 50.0 / fps
    audio_feature_length_per_frame = 2 * (audio_padding_length_left + audio_padding_length_right + 1)
    padding_nums = math.ceil(whisper_idx_multiplier)
    whisper_feature = torch.cat(
        [
            torch.zeros_like(whisper_feature[:, : padding_nums * audio_padding_length_left]),
            whisper_feature,
            torch.zeros_like(whisper_feature[:, : padding_nums * 3 * audio_padding_length_right]),
        ],
        dim=1,
    )

    audio_prompts = []
    for token_pos in frame_token_positions.tolist():
        audio_index = int(token_pos)
        audio_clip = whisper_feature[:, audio_index : audio_index + audio_feature_length_per_frame]
        if audio_clip.shape[1] < audio_feature_length_per_frame:
            pad = torch.zeros(
                1,
                audio_feature_length_per_frame - audio_clip.shape[1],
                audio_clip.shape[2],
                audio_clip.shape[3],
                device=audio_clip.device,
                dtype=audio_clip.dtype,
            )
            audio_clip = torch.cat([audio_clip, pad], dim=1)
        audio_prompts.append(audio_clip)

    if not audio_prompts:
        return np.zeros((0, 50, 384), dtype=np.float32)

    audio_prompts = torch.cat(audio_prompts, dim=0)
    bsz, channels, hidden_layers, dim = audio_prompts.shape
    audio_prompts = audio_prompts.reshape(bsz, channels * hidden_layers, dim)
    return audio_prompts.cpu().numpy().astype(np.float32, copy=False)


def extract_whisper_features(
    chunk: AudioChunk,
    whisper_model: Any,
    fps: int,
    device: str = "cuda",
    audio_padding_length_left: int = 2,
    audio_padding_length_right: int = 2,
) -> DrivingFeatures:
    """Extract audio features using Whisper encoder, matching MuseTalk convention."""
    from opentalking.models.common.frame_avatar import audio_chunk_to_frame_count

    fc = audio_chunk_to_frame_count(chunk, fps)
    audio_f32 = chunk.data.astype(np.float32) / 32768.0

    whisper_feature = _encode_whisper_tokens(audio_f32, whisper_model, device)
    frame_token_positions = np.arange(fc, dtype=np.float32) * (50.0 / fps)
    feature_np = _frame_features_from_token_timeline(
        whisper_feature,
        frame_token_positions,
        fps=fps,
        audio_padding_length_left=audio_padding_length_left,
        audio_padding_length_right=audio_padding_length_right,
    )

    return DrivingFeatures(
        vector=feature_np,
        frame_count=fc,
        frame_energy=_compute_per_frame_energy(audio_f32, fc),
    )


def extract_whisper_features_with_left_context(
    chunk: AudioChunk,
    left_context_pcm: np.ndarray,
    whisper_model: Any,
    fps: int,
    *,
    device: str = "cuda",
    context_keep_ms: float = 1600.0,
    frame_index_start: int = 0,
    samples_before_chunk: int = 0,
    audio_padding_length_left: int = 2,
    audio_padding_length_right: int = 2,
) -> tuple[DrivingFeatures, np.ndarray, int]:
    """Extract per-frame features for the current chunk using left audio context."""
    left_context_pcm = np.asarray(left_context_pcm, dtype=np.int16).reshape(-1)
    current_pcm = np.asarray(chunk.data, dtype=np.int16).reshape(-1)
    sample_rate = max(1, int(chunk.sample_rate))

    samples_after_chunk = samples_before_chunk + current_pcm.size
    exact_frame_end = samples_after_chunk * float(fps) / sample_rate
    target_frame_end = max(frame_index_start + 1, int(math.floor(exact_frame_end + 1e-6)))
    current_fc = max(1, target_frame_end - frame_index_start)

    combined_pcm = np.concatenate([left_context_pcm, current_pcm]).astype(np.int16, copy=False)
    combined_audio_f32 = combined_pcm.astype(np.float32) / 32768.0
    whisper_feature = _encode_whisper_tokens(combined_audio_f32, whisper_model, device)

    combined_start_sample = samples_before_chunk - left_context_pcm.size
    combined_start_sec = combined_start_sample / float(sample_rate)
    frame_times_sec = (frame_index_start + np.arange(current_fc, dtype=np.float32) + 0.5) / float(fps)
    rel_times_sec = frame_times_sec - combined_start_sec
    frame_token_positions = rel_times_sec * 50.0
    feature_np = _frame_features_from_token_timeline(
        whisper_feature,
        frame_token_positions,
        fps=fps,
        audio_padding_length_left=audio_padding_length_left,
        audio_padding_length_right=audio_padding_length_right,
    )
    features = DrivingFeatures(
        vector=feature_np.astype(np.float32, copy=False),
        frame_count=current_fc,
        frame_energy=_compute_per_frame_energy(current_pcm.astype(np.float32) / 32768.0, current_fc),
    )

    keep_samples = max(1, int(round(chunk.sample_rate * (context_keep_ms / 1000.0))))
    new_context = np.concatenate([left_context_pcm, current_pcm]).astype(np.int16, copy=False)
    if new_context.size > keep_samples:
        new_context = new_context[-keep_samples:]
    return features, new_context, samples_after_chunk
