"""LiteLLM AI gateway provider — unified access to 100+ LLM providers."""

from opentalking.core.registry import register
from opentalking.providers.llm.litellm_chat.adapter import LiteLLMChatClient

register("llm", "litellm")(LiteLLMChatClient)

__all__ = ["LiteLLMChatClient"]
