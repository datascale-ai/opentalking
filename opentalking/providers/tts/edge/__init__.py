"""Edge TTS adapter."""

from opentalking.core.registry import register
from opentalking.providers.tts.edge.adapter import EdgeTTSAdapter

register("tts", "edge")(EdgeTTSAdapter)

__all__ = ["EdgeTTSAdapter"]
