"""ElevenLabs TTS adapter."""

from opentalking.core.registry import register
from opentalking.providers.tts.elevenlabs.adapter import ElevenLabsTTSAdapter, list_elevenlabs_voices

register("tts", "elevenlabs")(ElevenLabsTTSAdapter)

__all__ = ["ElevenLabsTTSAdapter", "list_elevenlabs_voices"]
