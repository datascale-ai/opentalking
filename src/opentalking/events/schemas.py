from __future__ import annotations

import json
from typing import Any

from opentalking.core.types.events import (
    ErrorEvent,
    SessionQueuedEvent,
    SessionStateChangedEvent,
    SpeechEndedEvent,
    SpeechStartedEvent,
    SubtitleChunkEvent,
    event_to_dict,
)

EVENT_TYPE_MAP: dict[type, str] = {
    SpeechStartedEvent: "speech.started",
    SubtitleChunkEvent: "subtitle.chunk",
    SpeechEndedEvent: "speech.ended",
    SessionStateChangedEvent: "session.state_changed",
    SessionQueuedEvent: "session.queued",
    ErrorEvent: "error",
}


def event_type_for(obj: Any) -> str:
    t = type(obj)
    if t not in EVENT_TYPE_MAP:
        raise TypeError(f"Unknown event type: {t}")
    return EVENT_TYPE_MAP[t]


def event_sse_payload(obj: Any) -> tuple[str, str]:
    """Return (event_name, json_data) for SSE."""
    name = event_type_for(obj)
    data = json.dumps(event_to_dict(obj), ensure_ascii=False)
    return name, data
