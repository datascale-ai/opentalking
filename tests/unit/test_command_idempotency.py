from __future__ import annotations

import pytest

from apps.api.services import session_service
from opentalking.core.in_memory_redis import InMemoryRedis


@pytest.mark.asyncio
async def test_speak_command_is_idempotent_and_conflicts_on_payload_change() -> None:
    redis = InMemoryRedis()
    first = await session_service.speak(
        redis,
        "sess_test",
        "hello",
        tts_provider="mock",
        command_id="cmd-1",
    )
    duplicate = await session_service.speak(
        redis,
        "sess_test",
        "hello",
        tts_provider="mock",
        command_id="cmd-1",
    )
    assert first == {"command_id": "cmd-1", "status": "queued"}
    assert duplicate == {"command_id": "cmd-1", "status": "duplicate"}
    assert redis.task_queue.qsize() == 2  # interrupt + speak from the first call

    with pytest.raises(ValueError, match="different payload"):
        await session_service.speak(
            redis,
            "sess_test",
            "different",
            tts_provider="mock",
            command_id="cmd-1",
        )
    assert redis.task_queue.qsize() == 2

