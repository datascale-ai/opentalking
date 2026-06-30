from __future__ import annotations

from collections.abc import AsyncIterator


class LiteLLMChatClient:
    """Async streaming chat client powered by LiteLLM.

    Supports 100+ LLM providers (OpenAI, Anthropic, Google, Bedrock, Azure,
    Ollama, etc.) through a single interface.  Model routing is handled by
    the ``model`` identifier, e.g. ``anthropic/claude-3-sonnet``,
    ``gemini/gemini-pro``, ``bedrock/anthropic.claude-3-sonnet``.

    See https://docs.litellm.ai/docs/providers for the full list.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str = "gpt-4o",
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.api_key = api_key
        self.model = model

    async def chat_stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        try:
            import litellm
        except ImportError:
            raise ImportError(
                "LiteLLM is not installed. "
                "Install it with: pip install 'opentalking[litellm]'"
            )

        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "drop_params": True,
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.base_url:
            kwargs["api_base"] = self.base_url

        response = await litellm.acompletion(**kwargs)
        async for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content
