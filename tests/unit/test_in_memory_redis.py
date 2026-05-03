from __future__ import annotations

import asyncio

import pytest

from opentalking.core.in_memory_redis import InMemoryRedis
from opentalking.core.redis_keys import TASK_QUEUE
from opentalking.core.session_store import (
    FLASHTALK_DISK_RECORDING_FIELD,
    FLASHTALK_RECORDING_EPOCH_FIELD,
    apply_flashtalk_recording_start,
    apply_flashtalk_recording_stop,
    session_key,
)


@pytest.mark.asyncio
async def test_in_memory_task_queue() -> None:
    r = InMemoryRedis()
    await r.rpush(TASK_QUEUE, '{"cmd":"noop"}')
    out = await r.brpop(TASK_QUEUE, timeout=1)
    assert out is not None
    assert out[0] == TASK_QUEUE
    assert out[1] == '{"cmd":"noop"}'


@pytest.mark.asyncio
async def test_in_memory_pubsub() -> None:
    r = InMemoryRedis()
    ps = r.pubsub()
    await ps.subscribe("ch1")
    await r.publish("ch1", "hello")
    msg = await ps.get_message(timeout=1.0)
    assert msg is not None
    assert msg["data"] == "hello"
    await ps.aclose()


@pytest.mark.asyncio
async def test_in_memory_expire_and_persist() -> None:
    r = InMemoryRedis()
    key = session_key("sess_123")
    await r.hset(key, mapping={"state": "created"})
    assert await r.expire(key, 0) == 1
    await asyncio.sleep(0)
    assert await r.exists(key) == 0

    await r.hset(key, mapping={"state": "created"})
    assert await r.expire(key, 60) == 1
    assert await r.persist(key) == 1
    assert await r.exists(key) == 1


@pytest.mark.asyncio
async def test_in_memory_hash_get_supports_recording_state() -> None:
    r = InMemoryRedis()
    sid = "sess_recording"
    key = session_key(sid)
    await r.hset(key, mapping={"session_id": sid, "model": "flashtalk"})

    assert await r.hget(key, FLASHTALK_RECORDING_EPOCH_FIELD) is None

    await apply_flashtalk_recording_start(r, sid)
    assert await r.hget(key, FLASHTALK_DISK_RECORDING_FIELD) == "1"
    assert await r.hget(key, FLASHTALK_RECORDING_EPOCH_FIELD) == "1"

    await apply_flashtalk_recording_start(r, sid)
    assert await r.hget(key, FLASHTALK_RECORDING_EPOCH_FIELD) == "2"

    await apply_flashtalk_recording_stop(r, sid)
    assert await r.hget(key, FLASHTALK_DISK_RECORDING_FIELD) == "0"
