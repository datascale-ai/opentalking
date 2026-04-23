from __future__ import annotations

import json
import time
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


async def speak(
    r: redis.Redis,
    sid: str,
    text: str,
    *,
    voice: str | None = None,
    tts_provider: str | None = None,
    tts_model: str | None = None,
) -> None:
    # 新用户输入前先打断，避免上一条仍在推理/播报时排队等到结束才生效
    await interrupt(r, sid)
    task: dict[str, Any] = {
        "cmd": "speak",
        "session_id": sid,
        "text": text,
        # Worker 用于测量「API 入队 speak → 首帧进 WebRTC」墙钟（与 Worker 同机时钟）
        "enqueue_unix": time.time(),
    }
    if voice:
        task["voice"] = voice
    if tts_provider:
        task["tts_provider"] = tts_provider.strip().lower()
    if tts_model:
        task["tts_model"] = tts_model.strip()
    await _push_task(r, task)


async def interrupt(r: redis.Redis, sid: str) -> None:
    await _push_task(r, {"cmd": "interrupt", "session_id": sid})


async def close_session(r: redis.Redis, sid: str) -> None:
    await set_session_state(r, sid, "closing")
    await _push_task(r, {"cmd": "close", "session_id": sid})
