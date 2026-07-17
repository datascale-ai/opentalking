from __future__ import annotations

import base64
import inspect
import json
import time
import uuid
from collections.abc import Awaitable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, TypeAlias

import redis.asyncio as redis

from opentalking.core.redis_keys import TASK_QUEUE, uploaded_pcm_key
from opentalking.core.session_store import get_session_record, session_key, set_session_state

if TYPE_CHECKING:
    RedisHashValue: TypeAlias = bytes | bytearray | memoryview[int] | str | int | float
else:
    RedisHashValue: TypeAlias = bytes | bytearray | memoryview | str | int | float


async def _await_result(value: Awaitable[Any] | Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _push_task(r: redis.Redis, task: dict[str, Any]) -> None:
    await _await_result(r.rpush(TASK_QUEUE, json.dumps(task, ensure_ascii=False)))


def _bool_hash(value: bool) -> str:
    return "1" if value else "0"


def _normalize_knowledge_base_ids(
    *,
    knowledge_base_id: str | None,
    knowledge_base_ids: list[str] | None,
) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    candidates: Sequence[str | None] = knowledge_base_ids or [knowledge_base_id]
    for candidate in candidates:
        kb_id = str(candidate or "").strip()
        if not kb_id or kb_id in seen:
            continue
        selected.append(kb_id)
        seen.add(kb_id)
    return selected


async def create_session(
    r: redis.Redis,
    *,
    persona_id: str | None = None,
    avatar_id: str,
    model: str,
    tts_provider: str | None = None,
    stt_provider: str | None = None,
    tts_voice: str | None = None,
    tts_model: str | None = None,
    llm_system_prompt: str | None = None,
    custom_ref_image_path: str | None = None,
    wav2lip_postprocess_mode: str | None = None,
    fasterliveportrait_config: Mapping[str, object] | None = None,
    user_id: str | None = None,
    agent_enabled: bool = False,
    memory_enabled: bool = False,
    memory_profile_id: str | None = None,
    character_id: str | None = None,
    memory_library_id: str | None = None,
    knowledge_enabled: bool = False,
    knowledge_base_id: str | None = None,
    knowledge_base_ids: list[str] | None = None,
) -> str:
    sid = f"sess_{uuid.uuid4().hex[:12]}"
    selected_knowledge_base_ids = _normalize_knowledge_base_ids(
        knowledge_base_id=knowledge_base_id,
        knowledge_base_ids=knowledge_base_ids,
    )
    legacy_knowledge_base_id = selected_knowledge_base_ids[0] if selected_knowledge_base_ids else None
    data: dict[RedisHashValue, RedisHashValue] = {
        "session_id": sid,
        "avatar_id": avatar_id,
        "model": model,
        "state": "created",
    }
    if persona_id:
        data["persona_id"] = persona_id
    if tts_provider:
        data["tts_provider"] = tts_provider
    if stt_provider:
        data["stt_provider"] = stt_provider
    if tts_voice:
        data["tts_voice"] = tts_voice
    if tts_model:
        data["tts_model"] = tts_model
    if llm_system_prompt:
        data["llm_system_prompt"] = llm_system_prompt
    if custom_ref_image_path:
        data["custom_ref_image_path"] = custom_ref_image_path
    if wav2lip_postprocess_mode:
        data["wav2lip_postprocess_mode"] = wav2lip_postprocess_mode
    if fasterliveportrait_config:
        data["fasterliveportrait_config"] = json.dumps(fasterliveportrait_config, ensure_ascii=False)
    if user_id:
        data["user_id"] = user_id
    if agent_enabled or memory_enabled or knowledge_enabled:
        data["agent_enabled"] = _bool_hash(agent_enabled)
        data["memory_enabled"] = _bool_hash(memory_enabled)
        data["knowledge_enabled"] = _bool_hash(knowledge_enabled)
        if memory_profile_id:
            data["memory_profile_id"] = memory_profile_id
        if character_id:
            data["character_id"] = character_id
        if memory_library_id:
            data["memory_library_id"] = memory_library_id
        if legacy_knowledge_base_id:
            data["knowledge_base_id"] = legacy_knowledge_base_id
        data["knowledge_base_ids"] = json.dumps(selected_knowledge_base_ids, ensure_ascii=False)
    await _await_result(r.hset(session_key(sid), mapping=data))
    init_task: dict[str, Any] = {
        "cmd": "init",
        "session_id": sid,
        "avatar_id": avatar_id,
        "model": model,
    }
    if persona_id:
        init_task["persona_id"] = persona_id
    if tts_provider:
        init_task["tts_provider"] = tts_provider
    if stt_provider:
        init_task["stt_provider"] = stt_provider
    if tts_voice:
        init_task["tts_voice"] = tts_voice
    if tts_model:
        init_task["tts_model"] = tts_model
    if llm_system_prompt:
        init_task["llm_system_prompt"] = llm_system_prompt
    if custom_ref_image_path:
        init_task["custom_ref_image_path"] = custom_ref_image_path
    if wav2lip_postprocess_mode:
        init_task["wav2lip_postprocess_mode"] = wav2lip_postprocess_mode
    if fasterliveportrait_config:
        init_task["fasterliveportrait_config"] = dict(fasterliveportrait_config)
    if user_id:
        init_task["user_id"] = user_id
    if agent_enabled or memory_enabled or knowledge_enabled:
        init_task["agent_enabled"] = bool(agent_enabled)
        init_task["memory_enabled"] = bool(memory_enabled)
        init_task["knowledge_enabled"] = bool(knowledge_enabled)
        if memory_profile_id:
            init_task["memory_profile_id"] = memory_profile_id
        if character_id:
            init_task["character_id"] = character_id
        if memory_library_id:
            init_task["memory_library_id"] = memory_library_id
        if legacy_knowledge_base_id:
            init_task["knowledge_base_id"] = legacy_knowledge_base_id
        init_task["knowledge_base_ids"] = selected_knowledge_base_ids
    await _push_task(
        r,
        init_task,
    )
    return sid


async def get_session(r: redis.Redis, sid: str) -> dict[str, str] | None:
    return await get_session_record(r, sid)


async def update_session_state(r: redis.Redis, sid: str, state: str) -> None:
    await set_session_state(r, sid, state)


async def update_agent_knowledge_bases(
    r: redis.Redis,
    sid: str,
    *,
    knowledge_base_ids: list[str] | None = None,
    knowledge_base_id: str | None = None,
) -> list[str]:
    selected_knowledge_base_ids = _normalize_knowledge_base_ids(
        knowledge_base_id=knowledge_base_id,
        knowledge_base_ids=knowledge_base_ids,
    )
    legacy_knowledge_base_id = selected_knowledge_base_ids[0] if selected_knowledge_base_ids else ""
    await _await_result(
        r.hset(
            session_key(sid),
            mapping={
                "agent_enabled": "1",
                "knowledge_enabled": _bool_hash(bool(selected_knowledge_base_ids)),
                "knowledge_base_id": legacy_knowledge_base_id,
                "knowledge_base_ids": json.dumps(selected_knowledge_base_ids, ensure_ascii=False),
            },
        )
    )
    await _push_task(
        r,
        {
            "cmd": "update_agent_knowledge_bases",
            "session_id": sid,
            "knowledge_base_ids": selected_knowledge_base_ids,
        },
    )
    return selected_knowledge_base_ids


async def update_fasterliveportrait_config(
    r: redis.Redis,
    sid: str,
    config: Mapping[str, object],
) -> None:
    await _push_task(
        r,
        {
            "cmd": "update_fasterliveportrait_config",
            "session_id": sid,
            "fasterliveportrait_config": dict(config),
        },
    )


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


async def interrupt(r: redis.Redis, sid: str) -> None:
    await _push_task(r, {"cmd": "interrupt", "session_id": sid})


async def close_session(r: redis.Redis, sid: str) -> None:
    await set_session_state(r, sid, "closing")
    await _push_task(r, {"cmd": "close", "session_id": sid})
