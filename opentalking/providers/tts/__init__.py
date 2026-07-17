"""TTS providers — importing this package auto-registers every adapter."""

from opentalking.providers.tts import (  # noqa: F401  side-effect imports
    cosyvoice_ws,
    dashscope_qwen,
    dashscope_sambert,
    edge,
    elevenlabs,
    mock,
)
from opentalking.providers.tts.edge.adapter import EdgeTTSAdapter
from opentalking.providers.tts.factory import build_tts_adapter, create_tts_adapter

__all__ = ["build_tts_adapter", "create_tts_adapter", "EdgeTTSAdapter"]
