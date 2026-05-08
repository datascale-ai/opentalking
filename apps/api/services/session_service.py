from __future__ import annotations

import base64
import inspect
import json
import time
import uuid
from collections.abc import Awaitable
from typing import Any

import redis.asyncio as redis

from opentalking.core.redis_keys import TASK_QUEUE, uploaded_pcm_key
from opentalking.core.session_store import get_session_record, session_key, set_session_state


async def _await_result(value: Awaitable[Any] | Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _push_task(r: redis.Redis, task: dict[str, Any]) -> None:
    await _await_result(r.rpush(TASK_QUEUE, json.dumps(task, ensure_ascii=False)))

async def create_session(
    r: redis.Redis,
    *,
    avatar_id: str,
    model: str,
    tts_provider: str | None = None,
    tts_voice: str | None = None,
    llm_system_prompt: str | None = None,
    custom_ref_image_path: str | None = None,
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
    if llm_system_prompt:
        data["llm_system_prompt"] = llm_system_prompt
    if custom_ref_image_path:
        data["custom_ref_image_path"] = custom_ref_image_path
    await _await_result(r.hset(session_key(sid), mapping=data))
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
    if llm_system_prompt:
        init_task["llm_system_prompt"] = llm_system_prompt
    if custom_ref_image_path:
        init_task["custom_ref_image_path"] = custom_ref_image_path
    await _push_task(
        r,
        init_task,
    )
    return sid


async def get_session(r: redis.Redis, sid: str) -> dict[str, str] | None:
    return await get_session_record(r, sid)


async def update_session_state(r: redis.Redis, sid: str, state: str) -> None:
    await set_session_state(r, sid, state)


async def enqueue_flashtalk_offline_bundle(
    r: redis.Redis,
    sid: str,
    *,
    pcm_path: str,
    job_id: str,
) -> None:
    """离线：上传 PCM 路径 → Worker 跑完整 FlashTalk 推理并落盘音视频（不经 WebRTC）。"""
    await _push_task(
        r,
        {
            "cmd": "flashtalk_offline_bundle",
            "session_id": sid,
            "pcm_path": pcm_path,
            "job_id": job_id,
        },
    )


async def speak_flashtalk_uploaded_pcm(
    r: redis.Redis,
    sid: str,
    pcm_bytes: bytes,
) -> None:
    """将上传音频解码后的 PCM 送入 Worker，仅走 FlashTalk（不经 LLM/TTS）。

    PCM 存在共享 Redis 临时键中，任务里只传 key，避免 API/Worker 分离部署时依赖共享文件系统。
    """
    await interrupt(r, sid)
    upload_id = uuid.uuid4().hex
    key = uploaded_pcm_key(sid, upload_id)
    await r.set(key, base64.b64encode(bytes(pcm_bytes)).decode("ascii"), ex=10 * 60)
    await _push_task(
        r,
        {
            "cmd": "speak_flashtalk_audio",
            "session_id": sid,
            "pcm_key": key,
            "enqueue_unix": time.time(),
        },
    )


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
        task["tts_voice"] = voice
    if tts_provider:
        task["tts_provider"] = tts_provider.strip().lower()
    if tts_model:
        task["tts_model"] = tts_model.strip()
    await _push_task(r, task)


async def chat(
    r: redis.Redis,
    sid: str,
    prompt: str,
    *,
    voice: str | None = None,
    tts_provider: str | None = None,
    tts_model: str | None = None,
) -> None:
    """LLM 流式 → 句级 TTS → 数字人渲染（仅 quicktalk 已对接）。"""
    await interrupt(r, sid)
    task: dict[str, Any] = {
        "cmd": "chat",
        "session_id": sid,
        "prompt": prompt,
        "enqueue_unix": time.time(),
    }
    if voice:
        task["voice"] = voice
        task["tts_voice"] = voice
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
