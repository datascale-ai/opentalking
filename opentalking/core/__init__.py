"""Shared foundation for OpenTalking."""

from opentalking.core.config import Settings, get_settings
from opentalking.core.interfaces.avatar_asset import AvatarManifest
from opentalking.core.interfaces.llm_adapter import LLMAdapter
from opentalking.core.interfaces.model_adapter import ModelAdapter
from opentalking.core.interfaces.render_session import RenderSession, SessionState
from opentalking.core.interfaces.tts_adapter import TTSAdapter
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
    "AvatarManifest",
    "ErrorEvent",
    "LLMAdapter",
    "ModelAdapter",
    "RenderSession",
    "SessionState",
    "SessionStateChangedEvent",
    "Settings",
    "SpeechEndedEvent",
    "SpeechStartedEvent",
    "SubtitleChunkEvent",
    "TTSAdapter",
    "VideoFrameData",
    "get_settings",
]
