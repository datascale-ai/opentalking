"""OpenAI-compatible chat completion provider (works with Qwen, vLLM, etc.)."""

from opentalking.core.registry import register
from opentalking.providers.llm.openai_compatible.adapter import OpenAICompatibleLLMClient

register("llm", "openai_compatible")(OpenAICompatibleLLMClient)

__all__ = ["OpenAICompatibleLLMClient"]
