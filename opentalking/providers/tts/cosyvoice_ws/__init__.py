"""DashScope CosyVoice WebSocket TTS adapter."""

from opentalking.core.registry import register
from opentalking.providers.tts.cosyvoice_ws.adapter import DashScopeCosyVoiceWsAdapter

register("tts", "cosyvoice_ws")(DashScopeCosyVoiceWsAdapter)

__all__ = ["DashScopeCosyVoiceWsAdapter"]
