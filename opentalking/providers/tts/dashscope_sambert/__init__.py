"""DashScope Sambert TTS adapter."""

from opentalking.core.registry import register
from opentalking.providers.tts.dashscope_sambert.adapter import DashScopeSambertTTSAdapter

register("tts", "dashscope_sambert")(DashScopeSambertTTSAdapter)

__all__ = ["DashScopeSambertTTSAdapter"]
