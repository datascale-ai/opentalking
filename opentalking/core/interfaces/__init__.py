"""Protocols and interface types for OpenTalking core."""

from opentalking.core.interfaces.avatar_asset import AvatarManifest
from opentalking.core.interfaces.llm_adapter import LLMAdapter
from opentalking.core.interfaces.model_adapter import ModelAdapter
from opentalking.core.interfaces.render_session import RenderSession, SessionState
from opentalking.core.interfaces.stt_adapter import STTAdapter
from opentalking.core.interfaces.synthesis_adapter import SynthesisAdapter
from opentalking.core.interfaces.tts_adapter import TTSAdapter

__all__ = [
    "AvatarManifest",
    "LLMAdapter",
    "ModelAdapter",
    "RenderSession",
    "SessionState",
    "STTAdapter",
    "SynthesisAdapter",
    "TTSAdapter",
]
