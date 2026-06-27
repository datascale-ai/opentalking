from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SessionState(str, Enum):
    CREATED = "created"
    LOADING = "loading"
    READY = "ready"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"
    ERROR = "error"
    CLOSED = "closed"


@dataclass
class RenderSession:
    """Runtime session metadata (API/worker coordination)."""

    session_id: str
    avatar_id: str
    model_type: str
    state: SessionState = SessionState.CREATED
    current_text: str | None = None
    worker_id: str | None = None
    extra: dict = field(default_factory=dict)
