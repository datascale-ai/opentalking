from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable


@runtime_checkable
class LLMAdapter(Protocol):
    """Streaming chat-completion interface."""

    async def chat_stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        """Yield text deltas from the configured LLM backend."""
        ...
