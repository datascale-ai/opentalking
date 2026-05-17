from __future__ import annotations

import numpy as np


NUM_MELS = 80
N_FFT = 800
HOP_SIZE = 200
WIN_SIZE = 800
SAMPLE_RATE = 16000
PREEMPHASIS = 0.97
PREEMPHASIZE = True
MIN_LEVEL_DB = -100
REF_LEVEL_DB = 20
FMIN = 55
FMAX = 7600
ALLOW_CLIPPING_IN_NORMALIZATION = True
SYMMETRIC_MELS = True
MAX_ABS_VALUE = 4.0

_mel_basis: np.ndarray | None = None


def preemphasis(wav: np.ndarray, k: float, preemphasize: bool = True) -> np.ndarray:
    if preemphasize:
        try:
            from scipy import signal
        except ImportError as exc:
            raise RuntimeError("scipy is required for Wav2Lip audio preprocessing") from exc
        return signal.lfilter([1, -k], [1], wav)
    return wav


def melspectrogram(wav: np.ndarray) -> np.ndarray:
    try:
        import librosa
    except ImportError as exc:
        raise RuntimeError("librosa is required for Wav2Lip mel spectrogram generation") from exc
    stft = librosa.stft(
        y=preemphasis(wav, PREEMPHASIS, PREEMPHASIZE),
        n_fft=N_FFT,
        hop_length=HOP_SIZE,
        win_length=WIN_SIZE,
    )
    mel = _amp_to_db(_linear_to_mel(np.abs(stft))) - REF_LEVEL_DB
    return _normalize(mel)


def _linear_to_mel(spectrogram: np.ndarray) -> np.ndarray:
    global _mel_basis
    if _mel_basis is None:
        try:
            import librosa.filters
        except ImportError as exc:
            raise RuntimeError("librosa is required for Wav2Lip mel filter generation") from exc
        _mel_basis = librosa.filters.mel(
            sr=SAMPLE_RATE,
            n_fft=N_FFT,
            n_mels=NUM_MELS,
            fmin=FMIN,
            fmax=FMAX,
        )
    return np.dot(_mel_basis, spectrogram)


def _amp_to_db(x: np.ndarray) -> np.ndarray:
    min_level = np.exp(MIN_LEVEL_DB / 20 * np.log(10))
    return 20 * np.log10(np.maximum(min_level, x))


def _normalize(spec: np.ndarray) -> np.ndarray:
    if not ALLOW_CLIPPING_IN_NORMALIZATION:
        return (2 * MAX_ABS_VALUE) * ((spec - MIN_LEVEL_DB) / (-MIN_LEVEL_DB)) - MAX_ABS_VALUE
    if SYMMETRIC_MELS:
        return np.clip(
            (2 * MAX_ABS_VALUE) * ((spec - MIN_LEVEL_DB) / (-MIN_LEVEL_DB)) - MAX_ABS_VALUE,
            -MAX_ABS_VALUE,
            MAX_ABS_VALUE,
        )
    return np.clip(MAX_ABS_VALUE * ((spec - MIN_LEVEL_DB) / (-MIN_LEVEL_DB)), 0, MAX_ABS_VALUE)
