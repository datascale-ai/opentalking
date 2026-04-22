from __future__ import annotations

import json
import uuid
from typing import Any

import redis.asyncio as redis

from opentalking.core.session_store import get_session_record, session_key, set_session_state
from opentalking.core.redis_keys import TASK_QUEUE


async def _push_task(r: redis.Redis, task: dict[str, Any]) -> None:
    await r.rpush(TASK_QUEUE, json.dumps(task, ensure_ascii=False))

async def create_session(
    r: redis.Redis,
    *,
    avatar_id: str,
    model: str,
    tts_provider: str | None = None,
    tts_voice: str | None = None,
) -> str:
    sid = f"sess_{uuid.uuid4().hex[:12]}"
    data = {
        "session_id": sid,
        "avatar_id": avatar_id,
        "model": model,
        "state": "created",
    }
    if tts_provider:
        data["tts_provider"] = tts_provider
    if tts_voice:
        data["tts_voice"] = tts_voice
    await r.hset(session_key(sid), mapping=data)
    init_task: dict[str, Any] = {
        "cmd": "init",
        "session_id": sid,
        "avatar_id": avatar_id,
        "model": model,
    }
    if tts_provider:
        init_task["tts_provider"] = tts_provider
    if tts_voice:
        init_task["tts_voice"] = tts_voice
    await _push_task(
        r,
        init_task,
    )
    return sid


async def get_session(r: redis.Redis, sid: str) -> dict[str, str] | None:
    return await get_session_record(r, sid)


async def update_session_state(r: redis.Redis, sid: str, state: str) -> None:
    await set_session_state(r, sid, state)


async def speak(r: redis.Redis, sid: str, text: str) -> None:
    await _push_task(r, {"cmd": "speak", "session_id": sid, "text": text})


async def interrupt(r: redis.Redis, sid: str) -> None:
    await _push_task(r, {"cmd": "interrupt", "session_id": sid})


async def close_session(r: redis.Redis, sid: str) -> None:
    await set_session_state(r, sid, "closing")
    await _push_task(r, {"cmd": "close", "session_id": sid})
