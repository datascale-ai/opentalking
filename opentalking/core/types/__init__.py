"""Shared type definitions for OpenTalking core."""

from opentalking.core.types.events import (
    ErrorEvent,
    SessionStateChangedEvent,
    SpeechEndedEvent,
    SpeechStartedEvent,
    SubtitleChunkEvent,
)
from opentalking.core.types.frames import AudioChunk, VideoFrameData

__all__ = [
    "AudioChunk",
    "ErrorEvent",
    "SessionStateChangedEvent",
    "SpeechEndedEvent",
    "SpeechStartedEvent",
    "SubtitleChunkEvent",
    "VideoFrameData",
]
