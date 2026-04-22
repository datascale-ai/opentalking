from opentalking.tts.cosyvoice.adapter import CosyVoiceAdapter
from opentalking.tts.coqui.adapter import CoquiXTTSAdapter
from opentalking.tts.factory import build_tts_adapter
from opentalking.tts.edge.adapter import EdgeTTSAdapter
from opentalking.tts.elevenlabs.adapter import ElevenLabsTTSAdapter

__all__ = ["build_tts_adapter", "CosyVoiceAdapter", "CoquiXTTSAdapter", "EdgeTTSAdapter", "ElevenLabsTTSAdapter"]
