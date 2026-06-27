"""DashScope (百炼) Qwen TTS Realtime over WebSocket."""

from opentalking.core.registry import register
from opentalking.providers.tts.dashscope_qwen.adapter import DashScopeQwenTTSAdapter

register("tts", "dashscope_qwen")(DashScopeQwenTTSAdapter)

__all__ = ["DashScopeQwenTTSAdapter"]
