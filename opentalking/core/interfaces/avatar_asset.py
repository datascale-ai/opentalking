from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AvatarManifest:
    """Avatar asset manifest loaded from manifest.json."""

    id: str
    model_type: str  # e.g. "musetalk" | "wav2lip"
    fps: int
    sample_rate: int
    width: int
    height: int
    version: str
    name: str | None = None
    metadata: dict[str, Any] | None = field(default_factory=dict)
