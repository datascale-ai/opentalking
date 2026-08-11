from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass(frozen=True)
class ProgramVideo:
    """A video frame on the monotonic program timeline."""

    data: np.ndarray
    width: int
    height: int
    timestamp_ms: float
    source: str = "unknown"
    utterance_id: str | None = None


@dataclass(frozen=True)
class ProgramAudio:
    """A mono int16 audio tick on the program timeline."""

    data: np.ndarray
    sample_rate: int
    timestamp_ms: float
    source: str = "unknown"
    utterance_id: str | None = None

    @property
    def duration_ms(self) -> float:
        return len(self.data) * 1000.0 / max(1, self.sample_rate)


@dataclass
class OutputBranchStats:
    """Operational counters intentionally safe to expose in status responses."""

    offered_video: int = 0
    offered_audio: int = 0
    dropped_video: int = 0
    dropped_audio: int = 0
    delivered_video: int = 0
    delivered_audio: int = 0
    callback_errors: int = 0
    last_error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

