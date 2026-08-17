"""LLM client factory — resolves the configured provider."""
from __future__ import annotations

from typing import Any


def create_llm_client(
    *,
    provider: str = "openai_compatible",
    base_url: str = "",
    api_key: str = "",
    model: str = "qwen-turbo",
) -> Any:
    if provider == "litellm":
        from opentalking.providers.llm.litellm_chat.adapter import LiteLLMChatClient

        return LiteLLMChatClient(base_url=base_url, api_key=api_key, model=model)

    from opentalking.providers.llm.openai_compatible.adapter import OpenAICompatibleLLMClient

    return OpenAICompatibleLLMClient(base_url=base_url, api_key=api_key, model=model)
