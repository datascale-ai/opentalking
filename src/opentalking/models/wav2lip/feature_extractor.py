from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from opentalking.core.types.frames import AudioChunk
from opentalking.models.common.frame_avatar import audio_chunk_to_frame_count


WAV2LIP_SAMPLE_RATE = 16000
MEL_STEP_SIZE = 16


@dataclass
class Wav2LipTestFeatures:
    per_frame_energy: np.ndarray
    frame_count: int
    chunk_rms: float
    peak_energy: float


@dataclass
class Wav2LipStreamFeatures:
    mel_chunks: np.ndarray
    frame_count: int
    start_frame_index: int
    stop_frame_index: int
    total_frame_count: int


def _smoothstep01(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def _resample_pcm(pcm: np.ndarray, sample_rate: int, target_rate: int) -> np.ndarray:
    if sample_rate == target_rate or pcm.size == 0:
        return pcm.astype(np.float32, copy=False)
    try:
        from scipy import signal
    except ImportError as exc:
        raise RuntimeError("scipy is required for Wav2Lip audio resampling") from exc
    up = target_rate // math.gcd(sample_rate, target_rate)
    down = sample_rate // math.gcd(sample_rate, target_rate)
    return signal.resample_poly(pcm, up, down).astype(np.float32, copy=False)


def pcm_to_wav2lip_mel(pcm: np.ndarray, sample_rate: int) -> np.ndarray:
    wav = np.asarray(pcm, dtype=np.float32).reshape(-1)
    if wav.size == 0:
        return np.zeros((80, 0), dtype=np.float32)
    wav = wav / 32768.0
    if sample_rate != WAV2LIP_SAMPLE_RATE:
        wav = _resample_pcm(wav, sample_rate, WAV2LIP_SAMPLE_RATE)
    from opentalking.models.wav2lip import audio as wav2lip_audio

    mel = wav2lip_audio.melspectrogram(wav)
    mel = np.nan_to_num(mel, nan=0.0, posinf=0.0, neginf=0.0)
    return np.asarray(mel, dtype=np.float32)


def extract_stream_mel_chunks(
    pcm: np.ndarray,
    sample_rate: int,
    fps: int,
    *,
    start_frame_index: int,
    stop_frame_index: int | None = None,
    min_context_frames: int = 8,
    allow_padding: bool = False,
) -> Wav2LipStreamFeatures:
    total_pcm = np.asarray(pcm, dtype=np.int16).reshape(-1)
    total_frame_count = max(0, int((total_pcm.shape[0] / max(1, sample_rate)) * fps))
    emit_stop_frame_index = total_frame_count if stop_frame_index is None else min(
        max(start_frame_index, int(stop_frame_index)),
        total_frame_count,
    )
    if total_pcm.size == 0 or total_frame_count <= start_frame_index:
        return Wav2LipStreamFeatures(
            mel_chunks=np.zeros((0, 80, MEL_STEP_SIZE), dtype=np.float32),
            frame_count=0,
            start_frame_index=start_frame_index,
            stop_frame_index=emit_stop_frame_index,
            total_frame_count=total_frame_count,
        )

    mel = pcm_to_wav2lip_mel(total_pcm, sample_rate)
    mel_frames = int(mel.shape[1]) if mel.ndim == 2 else 0
    if mel_frames < max(MEL_STEP_SIZE, min_context_frames):
        return Wav2LipStreamFeatures(
            mel_chunks=np.zeros((0, 80, MEL_STEP_SIZE), dtype=np.float32),
            frame_count=0,
            start_frame_index=start_frame_index,
            stop_frame_index=emit_stop_frame_index,
            total_frame_count=total_frame_count,
        )

    mel_idx_multiplier = 80.0 / max(1, fps)
    chunks: list[np.ndarray] = []
    for frame_idx in range(start_frame_index, emit_stop_frame_index):
        start_idx = int(frame_idx * mel_idx_multiplier)
        end_idx = start_idx + MEL_STEP_SIZE
        if start_idx >= mel_frames:
            break
        if end_idx > mel_frames and not allow_padding:
            break
        chunk = mel[:, start_idx:min(end_idx, mel_frames)]
        if chunk.shape[1] < MEL_STEP_SIZE:
            if chunk.shape[1] == 0:
                if not allow_padding:
                    break
                chunk = np.zeros((mel.shape[0], MEL_STEP_SIZE), dtype=np.float32)
            else:
                if not allow_padding:
                    break
                pad = np.repeat(chunk[:, -1:], MEL_STEP_SIZE - chunk.shape[1], axis=1)
                chunk = np.concatenate((chunk, pad), axis=1)
        chunks.append(np.asarray(chunk, dtype=np.float32))

    if not chunks:
        mel_chunks = np.zeros((0, 80, MEL_STEP_SIZE), dtype=np.float32)
    else:
        mel_chunks = np.stack(chunks, axis=0).astype(np.float32, copy=False)

    return Wav2LipStreamFeatures(
        mel_chunks=mel_chunks,
        frame_count=int(mel_chunks.shape[0]),
        start_frame_index=start_frame_index,
        stop_frame_index=emit_stop_frame_index,
        total_frame_count=total_frame_count,
    )


def extract_mel_for_wav2lip(chunk: AudioChunk, fps: int) -> Wav2LipTestFeatures:
    """Extract a stable per-frame speech-energy envelope for debug lip sync."""
    frame_count = audio_chunk_to_frame_count(chunk, fps)
    pcm = np.asarray(chunk.data, dtype=np.float32).reshape(-1)
    if pcm.size == 0:
        zeros = np.zeros((frame_count,), dtype=np.float32)
        return Wav2LipTestFeatures(
            per_frame_energy=zeros,
            frame_count=frame_count,
            chunk_rms=0.0,
            peak_energy=0.0,
        )

    x = pcm / 32768.0
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
        energies[i] = rms * (1.0 + 0.35 * zcr)

    peak = float(np.max(energies)) if energies.size else 0.0
    chunk_rms = float(np.sqrt(np.mean(np.square(x), dtype=np.float32)))
    if peak > 1e-6:
        floor = max(0.01, min(0.08, peak * 0.22))
        energies = _smoothstep01((energies - floor) / max(1e-6, peak - floor))
    else:
        energies.fill(0.0)

    return Wav2LipTestFeatures(
        per_frame_energy=energies.astype(np.float32, copy=False),
        frame_count=frame_count,
        chunk_rms=chunk_rms,
        peak_energy=peak,
    )
