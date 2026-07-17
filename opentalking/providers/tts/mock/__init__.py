from opentalking.core.registry import register
from opentalking.providers.tts.mock.adapter import MockTTSAdapter

register("tts", "mock")(MockTTSAdapter)

__all__ = ["MockTTSAdapter"]
