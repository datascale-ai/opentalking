from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ProgramClock:
    """Continuous CFR/constant-audio-clock for a live program.

    Source renderers are allowed to reset their own timestamps between speech
    turns.  This clock is owned by the output layer and therefore never resets
    when an utterance is interrupted.  Video advances in fixed frame periods;
    audio advances in fixed sample ticks (normally 20 ms at 48 kHz).
    """

    fps: float = 25.0
    sample_rate: int = 48_000
    audio_tick_ms: int = 20
    _video_index: int = 0
    _audio_samples: int = 0

    def __post_init__(self) -> None:
        if self.fps <= 0:
            raise ValueError("fps must be positive")
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if self.audio_tick_ms <= 0:
            raise ValueError("audio_tick_ms must be positive")

    @property
    def video_period_ms(self) -> float:
        return 1000.0 / float(self.fps)

    @property
    def audio_tick_samples(self) -> int:
        # Round once and keep every tick the same length.  The configured
        # defaults (48 kHz/20 ms) produce exactly 960 samples.
        return max(1, int(round(self.sample_rate * self.audio_tick_ms / 1000.0)))

    @property
    def video_timestamp_ms(self) -> float:
        return self._video_index * self.video_period_ms

    @property
    def audio_timestamp_ms(self) -> float:
        return self._audio_samples * 1000.0 / self.sample_rate

    @property
    def video_index(self) -> int:
        return self._video_index

    @property
    def audio_samples(self) -> int:
        return self._audio_samples

    def next_video(self) -> float:
        timestamp = self.video_timestamp_ms
        self._video_index += 1
        return timestamp

    def next_audio_tick(self) -> tuple[float, int]:
        timestamp = self.audio_timestamp_ms
        samples = self.audio_tick_samples
        self._audio_samples += samples
        return timestamp, samples

    def reset(self) -> None:
        """Reset only for a newly-created Program, never for an utterance."""
        self._video_index = 0
        self._audio_samples = 0

