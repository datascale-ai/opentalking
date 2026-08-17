"""Unit tests for the LiteLLM LLM provider."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_factory_returns_litellm_client():
    from opentalking.providers.llm.factory import create_llm_client
    from opentalking.providers.llm.litellm_chat.adapter import LiteLLMChatClient

    client = create_llm_client(
        provider="litellm",
        base_url="http://localhost:4000",
        api_key="sk-test",
        model="anthropic/claude-3-sonnet",
    )
    assert isinstance(client, LiteLLMChatClient)
    assert client.model == "anthropic/claude-3-sonnet"
    assert client.api_key == "sk-test"
    assert client.base_url == "http://localhost:4000"


def test_factory_returns_openai_compatible_by_default():
    from opentalking.providers.llm.factory import create_llm_client
    from opentalking.providers.llm.openai_compatible.adapter import OpenAICompatibleLLMClient

    client = create_llm_client(
        base_url="http://localhost:8080/v1",
        api_key="sk-test",
        model="qwen-turbo",
    )
    assert isinstance(client, OpenAICompatibleLLMClient)


def test_litellm_client_empty_base_url():
    from opentalking.providers.llm.litellm_chat.adapter import LiteLLMChatClient

    client = LiteLLMChatClient(base_url="", api_key="sk-test", model="gpt-4o")
    assert client.base_url == ""


def test_litellm_client_strips_trailing_slash():
    from opentalking.providers.llm.litellm_chat.adapter import LiteLLMChatClient

    client = LiteLLMChatClient(
        base_url="http://localhost:4000/",
        api_key="sk-test",
        model="gpt-4o",
    )
    assert client.base_url == "http://localhost:4000"


@pytest.mark.asyncio
async def test_litellm_chat_stream():
    from opentalking.providers.llm.litellm_chat.adapter import LiteLLMChatClient

    chunk1 = MagicMock()
    chunk1.choices = [MagicMock(delta=MagicMock(content="Hello"))]

    chunk2 = MagicMock()
    chunk2.choices = [MagicMock(delta=MagicMock(content=" world"))]

    chunk_done = MagicMock()
    chunk_done.choices = [MagicMock(delta=MagicMock(content=None))]

    async def fake_chunks():
        for c in [chunk1, chunk2, chunk_done]:
            yield c

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
        mock_acompletion.return_value = fake_chunks()

        client = LiteLLMChatClient(
            base_url="",
            api_key="sk-test",
            model="gpt-4o",
        )
        messages = [{"role": "user", "content": "Hi"}]
        result = []
        async for delta in client.chat_stream(messages):
            result.append(delta)

        assert result == ["Hello", " world"]
        mock_acompletion.assert_called_once_with(
            model="gpt-4o",
            messages=messages,
            stream=True,
            drop_params=True,
            api_key="sk-test",
        )


def test_registry_registration():
    from opentalking.core.registry import list_keys, resolve
    from opentalking.providers.llm.litellm_chat.adapter import LiteLLMChatClient

    import opentalking.providers.llm.litellm_chat  # noqa: F401

    assert "litellm" in list_keys("llm")
    cls = resolve("llm", "litellm")
    assert cls is LiteLLMChatClient
