from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from opentalking.core.config import get_settings
from opentalking.core.queue_status import set_flashtalk_queue_status
from opentalking.core.redis_keys import (
    TASK_QUEUE,
    command_receipt_key,
    knowledge_index_job_key,
    knowledge_prepare_job_key,
)
from opentalking.core.session_store import get_session_record, set_session_state
from opentalking.agent.context_builder import AgentSessionConfig
from opentalking.runtime.bus import publish_event
from opentalking.pipeline.session.runner import SessionRunner
from opentalking.pipeline.speak.synthesis_runner import FlashTalkRunner
from opentalking.models.registry import get_adapter
from opentalking.providers.synthesis.audio2video_client import (
    LocalAudio2VideoClient,
    OmniRTAudio2VideoClient,
)
from opentalking.providers.synthesis.backends import resolve_model_backend
from opentalking.providers.synthesis.flashtalk.ws_client import FlashTalkWSClient
from opentalking.providers.memory.runtime import normalize_memory_scope

log = logging.getLogger(__name__)


async def _finish_speak_receipt(r: Any, sid: str, command_id: str, task: asyncio.Task[Any]) -> None:
    """Move a dispatched speak receipt to a terminal, redacted state."""
    key = command_receipt_key(sid, command_id)
    try:
        raw = await r.get(key)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        try:
            receipt = json.loads(str(raw or "{}"))
        except json.JSONDecodeError:
            receipt = {}
        receipt["status"] = "completed" if not task.cancelled() and task.exception() is None else "failed"
        if receipt["status"] == "failed":
            receipt["error"] = "speech_task_failed"
        await r.set(key, json.dumps(receipt, separators=(",", ":")), ex=24 * 60 * 60)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.debug("failed to finalize speak receipt: session=%s", sid, exc_info=True)

# Type alias: both SessionRunner and FlashTalkRunner share the same duck-typed interface
AnyRunner = Any

# ---------------------------------------------------------------------------
# FlashTalk single-slot scheduler
# One asyncio.Lock guards the single FlashTalk inference slot.
# _slot_queue_size tracks how many sessions are waiting (not yet holding the lock).
# _queued_tasks tracks background tasks for sessions still waiting in queue,
# so they can be cancelled when the session is deleted before getting the slot.
# ---------------------------------------------------------------------------
_flashtalk_slot_lock: asyncio.Lock | None = None
_slot_queue_size: int = 0
_queued_tasks: dict[str, asyncio.Task] = {}  # sid -> queued background task
_knowledge_index_locks: dict[str, asyncio.Lock] = {}
_knowledge_index_tasks: set[asyncio.Task[Any]] = set()
_knowledge_index_semaphore: asyncio.Semaphore | None = None


def _knowledge_index_limit() -> int:
    try:
        return max(1, int(os.environ.get("OPENTALKING_KNOWLEDGE_INDEX_WORKERS", "2")))
    except ValueError:
        return 2


def _knowledge_index_max_attempts() -> int:
    try:
        return max(1, int(os.environ.get("OPENTALKING_KNOWLEDGE_INDEX_MAX_ATTEMPTS", "3")))
    except ValueError:
        return 3


def _get_knowledge_index_semaphore() -> asyncio.Semaphore:
    global _knowledge_index_semaphore
    if _knowledge_index_semaphore is None:
        _knowledge_index_semaphore = asyncio.Semaphore(_knowledge_index_limit())
    return _knowledge_index_semaphore


def _get_slot_lock() -> asyncio.Lock:
    global _flashtalk_slot_lock
    if _flashtalk_slot_lock is None:
        _flashtalk_slot_lock = asyncio.Lock()
    return _flashtalk_slot_lock


def slot_queue_size() -> int:
    """Return number of sessions currently waiting for the FlashTalk slot."""
    return _slot_queue_size


def slot_is_occupied() -> bool:
    """Return True if a session currently holds the FlashTalk slot."""
    lock = _flashtalk_slot_lock
    return lock is not None and lock.locked()


async def _sync_slot_status(r: Any) -> None:
    try:
        await set_flashtalk_queue_status(
            r,
            slot_occupied=slot_is_occupied(),
            queue_size=slot_queue_size(),
        )
    except Exception:
        log.warning("failed to sync FlashTalk slot status to Redis", exc_info=True)


def _log_task_exception(task: asyncio.Task, sid: str) -> None:
    """Surface background init errors that were previously silent."""
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        log.info("FlashTalk init task cancelled: session=%s", sid)
        return
    except Exception:
        log.exception("FlashTalk init task state check failed: session=%s", sid)
        return
    if exc is not None:
        log.exception("FlashTalk init task failed: session=%s", sid, exc_info=exc)


def _local_runner_device(model: str, settings: Any, default_device: str) -> str:
    model = model.strip().lower()
    if model == "quicktalk":
        from opentalking.models.quicktalk.adapter import _configured_quicktalk_device

        return _configured_quicktalk_device(
            getattr(settings, "quicktalk_device", ""),
            os.environ.get("OPENTALKING_DEVICE"),
            os.environ.get("DEVICE"),
            getattr(settings, "torch_device", ""),
            getattr(settings, "device", ""),
            default_device,
        )
    if model == "wav2lip":
        return str(
            os.environ.get("OPENTALKING_WAV2LIP_DEVICE")
            or getattr(settings, "wav2lip_device", "")
            or os.environ.get("OPENTALKING_TORCH_DEVICE")
            or getattr(settings, "torch_device", "")
            or os.environ.get("OPENTALKING_DEVICE")
            or getattr(settings, "device", "")
            or os.environ.get("DEVICE")
            or default_device
        )
    if model == "musetalk":
        return str(
            os.environ.get("OPENTALKING_MUSETALK_DEVICE")
            or os.environ.get("OPENTALKING_TORCH_DEVICE")
            or getattr(settings, "torch_device", "")
            or os.environ.get("OPENTALKING_DEVICE")
            or getattr(settings, "device", "")
            or os.environ.get("DEVICE")
            or default_device
        )
    return default_device


def _task_bool(task: dict[str, Any], key: str) -> bool:
    value = task.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _task_knowledge_base_ids(task: dict[str, Any]) -> list[str]:
    raw = task.get("knowledge_base_ids")
    if isinstance(raw, str):
        text = raw.strip()
        if text:
            try:
                raw = json.loads(text)
            except json.JSONDecodeError:
                raw = [text]
    if not isinstance(raw, list):
        raw = [task.get("knowledge_base_id")]

    selected: list[str] = []
    seen: set[str] = set()
    for item in raw:
        kb_id = str(item or "").strip()
        if not kb_id or kb_id in seen:
            continue
        selected.append(kb_id)
        seen.add(kb_id)
    return selected


def _update_runner_agent_knowledge_bases(runner: Any, knowledge_base_ids: list[str]) -> None:
    current = getattr(runner, "agent_config", None)
    if current is None:
        return
    knowledge_enabled = bool(knowledge_base_ids)
    runner.agent_config = AgentSessionConfig(
        user_id=getattr(current, "user_id", None),
        agent_enabled=bool(getattr(current, "agent_enabled", False) or knowledge_enabled),
        memory_enabled=bool(getattr(current, "memory_enabled", False)),
        knowledge_enabled=knowledge_enabled,
        knowledge_base_id=knowledge_base_ids[0] if knowledge_base_ids else None,
        knowledge_base_ids=knowledge_base_ids,
    )


async def _task_with_latest_agent_knowledge(task: dict[str, Any], r: Any, sid: str) -> dict[str, Any]:
    try:
        record = await get_session_record(r, sid)
    except Exception:
        log.warning("failed to read latest session agent knowledge config: session=%s", sid, exc_info=True)
        return task
    if not record:
        return task
    merged = dict(task)
    for key in (
        "agent_enabled",
        "memory_enabled",
        "knowledge_enabled",
        "knowledge_base_id",
        "knowledge_base_ids",
        "user_id",
    ):
        if key in record:
            merged[key] = record[key]
    return merged


def _create_runner(
    task: dict[str, Any],
    r: Any,
    avatars_root: Path,
    device: str,
) -> AnyRunner:
    """Factory: pick the realtime runner backend for the requested model."""
    model = str(task.get("model", ""))
    sid = str(task["session_id"])
    avatar_id = str(task["avatar_id"])
    persona_id = str(task.get("persona_id", "") or "").strip() or None
    settings = get_settings()
    backend = resolve_model_backend(model, settings)
    knowledge_base_ids = _task_knowledge_base_ids(task)
    agent_kwargs = {
        "agent_user_id": str(task.get("user_id", "") or "").strip() or None,
        "persona_id": persona_id,
        "agent_enabled": _task_bool(task, "agent_enabled"),
        "memory_enabled": _task_bool(task, "memory_enabled"),
        "knowledge_enabled": _task_bool(task, "knowledge_enabled"),
        "knowledge_base_id": knowledge_base_ids[0] if knowledge_base_ids else None,
        "knowledge_base_ids": knowledge_base_ids,
    }
    memory_scope = normalize_memory_scope(
        settings=settings,
        memory_enabled=task.get("memory_enabled"),
        profile_id=str(task.get("memory_profile_id") or ""),
        character_id=str(task.get("character_id") or ""),
        avatar_id=avatar_id,
        library_id=str(task.get("memory_library_id") or ""),
    )
    if not memory_scope.enabled:
        memory_scope = None

    # Mock mode: pick the in-process mock client (echoes reference image).
    # Selected explicitly when the user picks model=mock in the UI.
    mock_mode = backend.backend == "mock"

    local_audio2video_models = {"musetalk", "quicktalk", "wav2lip"}
    if mock_mode or backend.backend in {"omnirt", "direct_ws"} or (
        backend.backend == "local" and model in local_audio2video_models
    ):
        audio2video_client = None
        flashtalk_ws_url: str | None = None

        if mock_mode:
            from opentalking.providers.synthesis.mock_client import MockFlashTalkClient

            audio2video_client = OmniRTAudio2VideoClient(MockFlashTalkClient())
            effective_model = "mock"
        elif model == "flashhead":
            from opentalking.providers.synthesis.flashhead import FlashHeadWSClient

            audio2video_client = OmniRTAudio2VideoClient(
                FlashHeadWSClient(
                    ws_url=backend.ws_url or settings.flashhead_ws_url,
                    model=settings.flashhead_model,
                    config={
                        "fps": int(settings.flashhead_fps),
                        "sample_rate": int(settings.flashhead_sample_rate),
                        "width": int(settings.flashhead_width),
                        "height": int(settings.flashhead_height),
                        "frame_num": int(settings.flashhead_frame_num),
                        "chunk_samples": int(settings.flashhead_chunk_samples),
                    },
                )
            )
            effective_model = "flashhead"
        elif backend.backend in {"omnirt", "direct_ws"}:
            from opentalking.providers.synthesis.omnirt import auth_headers as omnirt_auth_headers

            if backend.backend == "direct_ws":
                flashtalk_ws_url = backend.ws_url
            else:
                # Resolve WS URL via OmniRT endpoint (path-based per model) with
                # the legacy FlashTalk URL fallback when OMNIRT_ENDPOINT is unset.
                from opentalking.providers.synthesis.omnirt import resolve_synthesis_ws_url

                flashtalk_ws_url = resolve_synthesis_ws_url(model, settings)
            headers = omnirt_auth_headers(settings)
            audio2video_client = OmniRTAudio2VideoClient(
                FlashTalkWSClient(flashtalk_ws_url, extra_headers=headers or None)
            )
            # Preserve the user's chosen model name (flashtalk / musetalk / wav2lip / fasterliveportrait).
            # FlashTalkRunner only branches on model_type for model-specific
            # features; musetalk / wav2lip / fasterliveportrait just skip
            # those features without breaking the speak pipeline.
            effective_model = model
        else:
            local_device = _local_runner_device(model, settings, device)
            audio2video_client = LocalAudio2VideoClient(
                get_adapter(model),
                device=local_device,
            )
            effective_model = model

        return FlashTalkRunner(
            session_id=sid,
            avatar_id=avatar_id,
            avatars_root=avatars_root,
            redis=r,
            flashtalk_ws_url=flashtalk_ws_url,
            audio2video_client=audio2video_client,
            custom_ref_image_path=str(task.get("custom_ref_image_path", "") or ""),
            llm_base_url=settings.llm_base_url,
            llm_api_key=settings.llm_api_key,
            llm_model=settings.llm_model,
            system_prompt=str(task.get("llm_system_prompt", "") or settings.llm_system_prompt)
            or "你是一个友好的数字人助手，请用简洁的语言回答问题。不要使用表情符号或emoji。",
            model_type=effective_model,
            wav2lip_postprocess_mode=str(task.get("wav2lip_postprocess_mode", "") or ""),
            fasterliveportrait_config=task.get("fasterliveportrait_config")
            if isinstance(task.get("fasterliveportrait_config"), dict)
            else None,
            memory_scope=memory_scope,
            **agent_kwargs,
        )

    local_device = _local_runner_device(model, settings, device)
    return SessionRunner(
        session_id=sid,
        avatar_id=avatar_id,
        model_type=model,
        avatars_root=avatars_root,
        redis=r,
        device=local_device,
        llm_base_url=settings.llm_base_url,
        llm_api_key=settings.llm_api_key,
        llm_model=settings.llm_model,
        llm_system_prompt=str(task.get("llm_system_prompt", "") or settings.llm_system_prompt)
        or "你是一个友好的数字人助手，请用简洁的语言回答问题。不要使用表情符号或emoji。",
        wav2lip_postprocess_mode=str(task.get("wav2lip_postprocess_mode", "") or ""),
        memory_scope=memory_scope,
        **agent_kwargs,
    )


async def _do_init(
    task: dict[str, Any],
    r: Any,
    avatars_root: Path,
    device: str,
    runners: dict[str, AnyRunner],
    sid: str,
) -> None:
    """Create runner and call prepare(); caller holds the slot lock if needed."""
    task = await _task_with_latest_agent_knowledge(task, r, sid)
    runner = _create_runner(task, r, avatars_root, device)
    runners[sid] = runner
    try:
        await runner.prepare()
        await set_session_state(r, sid, "worker_ready")
        await publish_event(r, sid, "session.queued", {
            "session_id": sid,
            "position": 0,
            "message": "worker_ready",
        })
    except Exception:
        runners.pop(sid, None)
        await set_session_state(r, sid, "error")
        raise


async def _init_flashtalk_with_queue(
    task: dict[str, Any],
    r: Any,
    avatars_root: Path,
    device: str,
    runners: dict[str, AnyRunner],
    sid: str,
) -> None:
    """Serialise FlashTalk sessions through a single slot lock with bounded queue.

    The lock is held for the entire session lifetime (until runner is closed/removed),
    not just during init — so only one FlashTalk session is active at a time.
    Uses a manual cancellation flag instead of asyncio.wait_for to avoid
    forcibly cancelling the lock and corrupting queue state.
    """
    global _slot_queue_size, _queued_tasks
    settings = get_settings()
    max_queue = settings.flashtalk_max_queue_size
    timeout_sec = settings.flashtalk_slot_timeout_sec or None
    lock = _get_slot_lock()

    # Reject immediately when queue is full
    if lock.locked() and max_queue > 0 and _slot_queue_size >= max_queue:
        log.warning("FlashTalk slot queue full (%d), rejecting session %s", max_queue, sid)
        await set_session_state(r, sid, "error")
        await publish_event(r, sid, "session.queued", {
            "session_id": sid, "position": -1, "message": "queue_full",
        })
        return

    _slot_queue_size += 1
    position = _slot_queue_size
    await _sync_slot_status(r)
    cancelled = False  # set to True when session is deleted while waiting
    deadline = (asyncio.get_event_loop().time() + timeout_sec) if timeout_sec else None

    log.info("FlashTalk slot: session %s queued at position %d", sid, position)
    await publish_event(r, sid, "session.queued", {
        "session_id": sid, "position": position, "message": "waiting",
    })

    async def _run_with_lock() -> None:
        nonlocal cancelled
        global _slot_queue_size
        acquired = False
        try:
            async with lock:
                acquired = True
                _slot_queue_size -= 1
                _queued_tasks.pop(sid, None)
                await _sync_slot_status(r)

                if cancelled:
                    log.info("FlashTalk slot: session %s was cancelled while waiting, skipping", sid)
                    return

                log.info("FlashTalk slot acquired by session %s", sid)
                await _do_init(task, r, avatars_root, device, runners, sid)
                # Notify after init so the SSE connection is already established
                await publish_event(r, sid, "session.queued", {
                    "session_id": sid, "position": 0, "message": "slot_acquired",
                })

                # Hold the lock for the entire session lifetime.
                max_session_sec = settings.flashtalk_max_session_sec
                session_deadline = (
                    asyncio.get_event_loop().time() + max_session_sec
                ) if max_session_sec else None
                warning_sent = False
                while sid in runners:
                    runner = runners.get(sid)
                    # WebRTC auto-close: runner.close() sets _closed=True
                    if runner is not None and getattr(runner, "_closed", False):
                        log.info("Session %s self-closed (WebRTC disconnect), releasing slot", sid)
                        runners.pop(sid, None)
                        break
                    # Max session duration: warn at 60s remaining, then force close
                    if session_deadline:
                        remaining = session_deadline - asyncio.get_event_loop().time()
                        if not warning_sent and remaining <= 60:
                            warning_sent = True
                            log.info("Session %s expiring in %.0fs, notifying client", sid, remaining)
                            await publish_event(r, sid, "session.expiring", {
                                "session_id": sid,
                                "remaining_sec": int(remaining),
                            })
                        if remaining <= 0:
                            log.warning("Session %s exceeded max duration (%ss), force closing", sid, max_session_sec)
                            await publish_event(r, sid, "session.expired", {
                                "session_id": sid,
                                "message": "session_expired",
                            })
                            if runner is not None:
                                await runner.close()
                            runners.pop(sid, None)
                            break
                    await asyncio.sleep(0.5)
                log.info("FlashTalk slot released by session %s", sid)
        finally:
            if acquired:
                await _sync_slot_status(r)

    # Wait for lock with manual timeout check (avoids asyncio.wait_for cancelling the lock)
    async def _wait_with_timeout() -> None:
        nonlocal cancelled
        task_obj = asyncio.current_task()
        if task_obj and sid:
            _queued_tasks[sid] = task_obj

        try:
            while True:
                # Check cancellation (session deleted while waiting)
                if cancelled:
                    _slot_queue_size_dec()
                    await _sync_slot_status(r)
                    return
                # Check timeout
                if deadline and asyncio.get_event_loop().time() > deadline:
                    _slot_queue_size_dec()
                    await _sync_slot_status(r)
                    log.warning("FlashTalk slot wait timed out (%ss) for session %s", timeout_sec, sid)
                    await set_session_state(r, sid, "error")
                    await publish_event(r, sid, "session.queued", {
                        "session_id": sid, "position": -1, "message": "timeout",
                    })
                    return
                # Try to acquire lock without blocking (poll every 0.5s)
                if not lock.locked():
                    await _run_with_lock()
                    return
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            # Session was deleted while waiting in queue
            _slot_queue_size_dec()
            _queued_tasks.pop(sid, None)
            await _sync_slot_status(r)
            log.info("FlashTalk queued session %s cancelled (session deleted)", sid)

    await _wait_with_timeout()


def _slot_queue_size_dec() -> None:
    global _slot_queue_size
    if _slot_queue_size > 0:
        _slot_queue_size -= 1


async def handle_worker_task(
    task: dict[str, Any],
    r: Any,
    avatars_root: Path,
    device: str,
    runners: dict[str, SessionRunner],
) -> None:
    cmd = task.get("cmd")
    sid = task.get("session_id")
    if cmd == "knowledge_index":
        kb_id = str(task.get("kb_id") or "").strip()
        doc_id = str(task.get("doc_id") or "").strip()
        attempt = max(0, int(task.get("attempt") or 0))
        generation_raw = task.get("generation")
        generation = int(generation_raw) if generation_raw is not None else None
        if not kb_id or not doc_id:
            log.warning("knowledge_index task missing kb_id/doc_id")
            return

        async def _run_knowledge_index() -> None:
            lock = _knowledge_index_locks.setdefault(kb_id, asyncio.Lock())
            async with _get_knowledge_index_semaphore(), lock:
                retry_queued = False
                try:
                    from opentalking.agent.context_builder import default_knowledge_store

                    store = default_knowledge_store()
                    if generation is None:
                        document = await store.index_document(kb_id=kb_id, doc_id=doc_id)
                    else:
                        document = await store.index_document_for_generation(
                            kb_id=kb_id,
                            doc_id=doc_id,
                            generation=generation,
                        )
                    log.info(
                        "knowledge index completed: kb=%s doc=%s status=%s chunks=%s",
                        kb_id,
                        doc_id,
                        document.status,
                        document.chunk_count,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    if getattr(exc, "discard_job", False):
                        log.info(
                            "discarding stale knowledge index job: kb=%s doc=%s generation=%s",
                            kb_id,
                            doc_id,
                            generation,
                        )
                        return
                    # A worker-level exception (for example a missing file or a
                    # database failure) must be visible in the document state.
                    # The store handles index/extraction errors it can classify;
                    # this catches failures before it can return a document.
                    document_exists = False
                    try:
                        from opentalking.agent.context_builder import default_knowledge_store

                        store = default_knowledge_store()
                        # Enrichment failures happen after local chunks have
                        # been committed. Preserve that fast index so the
                        # document remains queryable while retries continue.
                        if getattr(exc, "preserve_fast_index", False):
                            marked = await store.mark_index_enrichment_error(
                                kb_id=kb_id,
                                doc_id=doc_id,
                                error=f"worker failed: {exc}",
                                retry_count=attempt + 1,
                            )
                        else:
                            marked = await store.mark_index_error(
                                kb_id=kb_id,
                                doc_id=doc_id,
                                error=f"worker failed: {exc}",
                                retry_count=attempt + 1,
                            )
                        document_exists = marked is not None
                    except Exception:  # noqa: BLE001
                        log.exception(
                            "failed to persist knowledge worker error: kb=%s doc=%s",
                            kb_id,
                            doc_id,
                        )
                    if document_exists and attempt + 1 < _knowledge_index_max_attempts():
                        retry_task = {
                            "cmd": "knowledge_index",
                            "kb_id": kb_id,
                            "doc_id": doc_id,
                            "attempt": attempt + 1,
                        }
                        if generation is not None:
                            retry_task["generation"] = generation
                        if task.get("content_hash"):
                            retry_task["content_hash"] = task["content_hash"]
                        try:
                            await r.rpush(
                                TASK_QUEUE,
                                json.dumps(retry_task, ensure_ascii=False),
                            )
                            retry_queued = True
                            log.warning(
                                "knowledge index retry queued: kb=%s doc=%s attempt=%s",
                                kb_id,
                                doc_id,
                                attempt + 1,
                            )
                        except Exception:  # noqa: BLE001
                            log.exception(
                                "failed to queue knowledge index retry: kb=%s doc=%s",
                                kb_id,
                                doc_id,
                            )
                    else:
                        log.exception(
                            "knowledge index worker failed permanently: kb=%s doc=%s attempts=%s",
                            kb_id,
                            doc_id,
                            attempt + 1,
                        )
                finally:
                    if not retry_queued and hasattr(r, "delete"):
                        await r.delete(knowledge_index_job_key(kb_id, doc_id))

        index_task = asyncio.create_task(_run_knowledge_index())
        _knowledge_index_tasks.add(index_task)
        index_task.add_done_callback(_knowledge_index_tasks.discard)
        return
    if cmd == "knowledge_index_batch":
        kb_id = str(task.get("kb_id") or "").strip()
        raw_doc_ids = task.get("doc_ids")
        doc_ids = [str(value).strip() for value in raw_doc_ids if str(value).strip()] if isinstance(raw_doc_ids, list) else []
        attempt = max(0, int(task.get("attempt") or 0))
        raw_generations = task.get("generations")
        generations: dict[str, int] = {
            str(doc_id): int(raw_generations[str(doc_id)])
            for doc_id in doc_ids
            if isinstance(raw_generations, dict) and str(doc_id) in raw_generations
        }
        if raw_generations is not None and not generations:
            log.warning("knowledge_index_batch task has no valid generations: kb=%s", kb_id)
        if not kb_id or not doc_ids:
            log.warning("knowledge_index_batch task missing kb_id/doc_ids")
            return

        async def _run_knowledge_index_batch() -> None:
            lock = _knowledge_index_locks.setdefault(kb_id, asyncio.Lock())
            async with _get_knowledge_index_semaphore(), lock:
                retry_queued = False
                try:
                    from opentalking.agent.context_builder import default_knowledge_store

                    store = default_knowledge_store()
                    if generations:
                        documents = await store.index_documents(
                            kb_id=kb_id,
                            doc_ids=doc_ids,
                            expected_generations=generations,
                        )
                    else:
                        documents = await store.index_documents(kb_id=kb_id, doc_ids=doc_ids)
                    log.info(
                        "knowledge index batch completed: kb=%s docs=%s statuses=%s",
                        kb_id,
                        len(documents),
                        [document.status for document in documents],
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    if getattr(exc, "discard_job", False):
                        log.info("discarding stale knowledge index batch: kb=%s docs=%s", kb_id, doc_ids)
                        return
                    existing_doc_ids: list[str] = []
                    try:
                        from opentalking.agent.context_builder import default_knowledge_store

                        store = default_knowledge_store()
                        for doc_id in doc_ids:
                            if getattr(exc, "preserve_fast_index", False):
                                marked = await store.mark_index_enrichment_error(
                                    kb_id=kb_id,
                                    doc_id=doc_id,
                                    error=f"batch worker failed: {exc}",
                                    retry_count=attempt + 1,
                                )
                            else:
                                marked = await store.mark_index_error(
                                    kb_id=kb_id,
                                    doc_id=doc_id,
                                    error=f"batch worker failed: {exc}",
                                    retry_count=attempt + 1,
                                )
                            if marked is not None:
                                existing_doc_ids.append(doc_id)
                    except Exception:  # noqa: BLE001
                        log.exception(
                            "failed to persist batch knowledge worker error: kb=%s",
                            kb_id,
                        )
                    if existing_doc_ids and attempt + 1 < _knowledge_index_max_attempts():
                        try:
                            retry_generations = {
                                doc_id: generations[doc_id]
                                for doc_id in existing_doc_ids
                                if doc_id in generations
                            }
                            await r.rpush(
                                TASK_QUEUE,
                                json.dumps(
                                    {
                                        "cmd": "knowledge_index_batch",
                                        "kb_id": kb_id,
                                        "doc_ids": existing_doc_ids,
                                        "attempt": attempt + 1,
                                        **({"generations": retry_generations} if retry_generations else {}),
                                    },
                                    ensure_ascii=False,
                                ),
                            )
                            retry_queued = True
                            log.warning(
                                "knowledge index batch retry queued: kb=%s docs=%s attempt=%s",
                                kb_id,
                                len(doc_ids),
                                attempt + 1,
                            )
                        except Exception:  # noqa: BLE001
                            log.exception(
                                "failed to queue knowledge index batch retry: kb=%s",
                                kb_id,
                            )
                    log.exception(
                        "knowledge index batch worker failed: kb=%s docs=%s attempt=%s",
                        kb_id,
                        len(doc_ids),
                        attempt + 1,
                    )
                finally:
                    if not retry_queued and hasattr(r, "delete"):
                        for doc_id in doc_ids:
                            await r.delete(knowledge_index_job_key(kb_id, doc_id))

        batch_task = asyncio.create_task(_run_knowledge_index_batch())
        _knowledge_index_tasks.add(batch_task)
        batch_task.add_done_callback(_knowledge_index_tasks.discard)
        return
    if cmd == "knowledge_prepare_file":
        file_id = str(task.get("file_id") or "").strip()
        attempt = max(0, int(task.get("attempt") or 0))
        if not file_id:
            log.warning("knowledge_prepare_file task missing file_id")
            return
        retry_queued = False
        try:
            from opentalking.agent.context_builder import default_knowledge_store

            document = await default_knowledge_store().prepare_file(file_id)
            log.info(
                "knowledge file prepared: file=%s status=%s chunks=%s",
                file_id,
                document.status,
                document.chunk_count,
            )
        except Exception as exc:  # noqa: BLE001
            try:
                marked = await default_knowledge_store().mark_file_error(
                    file_id=file_id,
                    error=f"worker failed: {exc}",
                )
                if marked is not None and attempt + 1 < _knowledge_index_max_attempts():
                    await r.rpush(
                        TASK_QUEUE,
                        json.dumps(
                            {
                                "cmd": "knowledge_prepare_file",
                                "file_id": file_id,
                                "attempt": attempt + 1,
                            },
                            ensure_ascii=False,
                        ),
                    )
                    retry_queued = True
                    log.warning(
                        "knowledge file preparation retry queued: file=%s attempt=%s",
                        file_id,
                        attempt + 1,
                    )
            except Exception:  # noqa: BLE001
                log.exception("failed to persist knowledge file worker error: file=%s", file_id)
            log.exception("knowledge file preparation failed: file=%s", file_id)
        finally:
            if not retry_queued and hasattr(r, "delete"):
                await r.delete(knowledge_prepare_job_key(file_id))
        return
    if not sid or not cmd:
        return
    if cmd == "init":
        if sid in runners:
            return
        model = str(task.get("model", ""))
        if model in {"flashtalk", "flashhead"}:
            t = asyncio.create_task(
                _init_flashtalk_with_queue(task, r, avatars_root, device, runners, sid)
            )

            def _done(_t: asyncio.Task[None], _sid: str = str(sid)) -> None:
                _log_task_exception(_t, _sid)

            t.add_done_callback(_done)
        elif model == "quicktalk":
            t = asyncio.create_task(
                _do_init(task, r, avatars_root, device, runners, sid)
            )

            def _done(_t: asyncio.Task[None], _sid: str = str(sid)) -> None:
                _log_task_exception(_t, _sid)

            t.add_done_callback(_done)
        else:
            await _do_init(task, r, avatars_root, device, runners, sid)
        return
    runner = runners.get(sid)
    if not runner:
        # Session may still be waiting in the FlashTalk queue — cancel it
        queued_task = _queued_tasks.pop(sid, None)
        if queued_task and cmd == "close":
            # Mark cancelled so _wait_with_timeout exits cleanly on next poll
            # We can't set `cancelled` directly (closure), so cancel the task
            queued_task.cancel()
            log.info("Cancelled queued FlashTalk task for session %s", sid)
        else:
            log.warning("unknown session %s for cmd %s", sid, cmd)
        return
    if cmd == "speak":
        text = str(task.get("text", ""))
        raw_voice = task.get("tts_voice") or task.get("voice")
        tts_voice = str(raw_voice).strip() if raw_voice else None
        tp = task.get("tts_provider")
        tts_provider = str(tp).strip().lower() if tp else None
        tm = task.get("tts_model")
        tts_model = str(tm).strip() if tm else None
        command_id = str(task.get("command_id") or "").strip() or None
        if command_id:
            # Event publishers read this ephemeral value; it is deliberately
            # not persisted on the runner or written to media payloads.
            setattr(runner, "_active_command_id", command_id)
        enqueue_unix = task.get("enqueue_unix")
        if isinstance(enqueue_unix, (int, float)):
            log.info(
                "speak task dequeue from API enqueue: %.0f ms session=%s",
                (time.time() - float(enqueue_unix)) * 1000.0,
                sid,
            )
        enqueue_value = (
            float(enqueue_unix) if isinstance(enqueue_unix, (int, float)) else None
        )
        create_chat_task = getattr(runner, "create_chat_task", None)
        if callable(create_chat_task):
            speech_task = create_chat_task(
                text,
                tts_voice=tts_voice or None,
                tts_provider=tts_provider or None,
                tts_model=tts_model or None,
                enqueue_unix=enqueue_value,
            )
        else:
            speech_task = runner.create_speak_task(
                text,
                tts_voice=tts_voice or None,
                tts_provider=tts_provider or None,
                tts_model=tts_model or None,
                enqueue_unix=enqueue_value,
            )
        if command_id and isinstance(speech_task, asyncio.Task):
            speech_task.add_done_callback(
                lambda done, _sid=str(sid), _command_id=command_id: asyncio.create_task(
                    _finish_speak_receipt(r, _sid, _command_id, done)
                )
            )
    elif cmd == "update_agent_knowledge_bases":
        _update_runner_agent_knowledge_bases(runner, _task_knowledge_base_ids(task))
    elif cmd == "speak_flashtalk_audio":
        pcm_path = task.get("pcm_path")
        pcm_key = task.get("pcm_key")
        fn = getattr(runner, "create_speak_uploaded_pcm_task", None)
        if fn is None:
            log.warning("speak_flashtalk_audio unsupported runner session=%s", sid)
            return
        if isinstance(pcm_key, str) and pcm_key.strip():
            raw = await r.get(pcm_key.strip())
            await r.delete(pcm_key.strip())
            if not raw:
                log.warning("speak_flashtalk_audio missing pcm data key=%s session=%s", pcm_key, sid)
                return
            raw_bytes = raw.encode("ascii") if isinstance(raw, str) else bytes(raw)
            try:
                pcm_bytes = base64.b64decode(raw_bytes, validate=True)
            except Exception:
                log.warning("speak_flashtalk_audio invalid pcm payload key=%s session=%s", pcm_key, sid)
                return
            base = Path(tempfile.gettempdir()) / "opentalking_worker_pcm"
            base.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                suffix=".pcm",
                prefix=f"{sid}_",
                dir=base,
                delete=False,
            ) as tmp:
                tmp.write(pcm_bytes)
                pcm_path = tmp.name
        elif not pcm_path or not isinstance(pcm_path, str):
            log.warning("speak_flashtalk_audio missing pcm_key/pcm_path session=%s", sid)
            return
        eu = task.get("enqueue_unix")
        fn(
            pcm_path.strip(),
            enqueue_unix=float(eu) if isinstance(eu, (int, float)) else None,
        )
    elif cmd == "flashtalk_offline_bundle":
        job_id = task.get("job_id")
        pcm_path = task.get("pcm_path")
        if not job_id or not pcm_path:
            log.warning("flashtalk_offline_bundle missing job_id or pcm_path")
            return

        import numpy as np

        from opentalking.core.redis_keys import offline_bundle_job_key
        from opentalking.pipeline.recording.offline_export import run_flashtalk_offline_av_bundle
        from opentalking.pipeline.speak.synthesis_runner import FlashTalkRunner

        k = offline_bundle_job_key(str(job_id))
        if not isinstance(runner, FlashTalkRunner):
            await r.hset(k, mapping={"status": "error", "message": "not a FlashTalk session"})
            log.warning("flashtalk_offline_bundle: not FlashTalkRunner session=%s", sid)
            return
        try:
            await r.hset(k, mapping={"status": "processing"})
            path = Path(str(pcm_path))
            raw = path.read_bytes()
            path.unlink(missing_ok=True)
            pcm = np.frombuffer(raw, dtype=np.int16).copy()
            paths = await run_flashtalk_offline_av_bundle(
                runner,
                pcm,
                session_id=str(sid),
                job_id=str(job_id),
            )
            await r.hset(
                k,
                mapping={
                    "status": "done",
                    "bundle_mp4": paths["bundle_mp4"],
                    "aligned_audio_wav": paths["aligned_audio_wav"],
                    "video_only_mp4": paths["video_only_mp4"],
                    "zip": paths["zip"],
                    "work_dir": paths["work_dir"],
                },
            )
            log.info(
                "flashtalk_offline_bundle done session=%s job=%s bundle=%s",
                sid,
                job_id,
                paths["bundle_mp4"],
            )
        except Exception as e:  # noqa: BLE001
            log.exception("flashtalk_offline_bundle failed session=%s job=%s", sid, job_id)
            await r.hset(
                k,
                mapping={"status": "error", "message": str(e)[:2000]},
            )
    elif cmd == "interrupt":
        await runner.interrupt()
    elif cmd == "update_fasterliveportrait_config":
        update_fn = getattr(runner, "update_fasterliveportrait_runtime_config", None)
        if not callable(update_fn):
            log.warning("update_fasterliveportrait_config unsupported runner session=%s", sid)
            return
        raw_config = task.get("fasterliveportrait_config")
        if not isinstance(raw_config, dict):
            log.warning("update_fasterliveportrait_config missing config session=%s", sid)
            return
        await update_fn(raw_config)
    elif cmd == "close":
        await runner.close()
        runners.pop(sid, None)


async def consume_task_queue(
    r: Any,
    avatars_root: Path,
    device: str,
    runners: dict[str, SessionRunner],
) -> None:
    # Recover jobs left in ``uploaded``/``indexing`` state after a worker
    # restart. The document/chunks are durable; only extraction/index side
    # effects are retried.
    try:
        from opentalking.agent.context_builder import default_knowledge_store

        store = default_knowledge_store()
        pending_documents = await store.list_indexing_documents()
        # ``uploaded`` records are also recoverable: they have durable files
        # but extraction/chunking has not yet started.
        seen: set[tuple[str, str]] = set()
        for document in pending_documents:
            if document.status not in {"uploaded", "indexing"}:
                continue
            marker = (document.kb_id, document.id)
            if marker in seen:
                continue
            seen.add(marker)
            key = knowledge_index_job_key(document.kb_id, document.id)
            if hasattr(r, "set") and not await r.set(key, "queued", nx=True, ex=24 * 60 * 60):
                continue
            await r.rpush(
                TASK_QUEUE,
                json.dumps(
                    {
                        "cmd": "knowledge_index",
                        "kb_id": document.kb_id,
                        "doc_id": document.id,
                        "generation": document.generation,
                        "content_hash": document.sha256,
                    },
                    ensure_ascii=False,
                ),
            )
        for document in await store.list_pending_files():
            key = knowledge_prepare_job_key(document.id)
            if hasattr(r, "set") and not await r.set(key, "queued", nx=True, ex=24 * 60 * 60):
                continue
            await r.rpush(
                TASK_QUEUE,
                json.dumps(
                    {"cmd": "knowledge_prepare_file", "file_id": document.id},
                    ensure_ascii=False,
                ),
            )
    except Exception:  # noqa: BLE001
        log.warning("failed to recover knowledge indexing jobs", exc_info=True)

    while True:
        try:
            res = await r.brpop(TASK_QUEUE, timeout=5)
            if not res:
                continue
            _, raw = res
            task = json.loads(raw)
            await handle_worker_task(task, r, avatars_root, device, runners)
        except asyncio.CancelledError:
            break
        except Exception:  # noqa: BLE001
            log.exception("task consumer error")
