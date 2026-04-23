from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from opentalking.core.config import get_settings
from opentalking.core.redis_keys import TASK_QUEUE
from opentalking.core.session_store import set_session_state
from opentalking.worker.bus import publish_event
from opentalking.worker.session_runner import SessionRunner

log = logging.getLogger(__name__)

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


def _create_runner(
    task: dict[str, Any],
    r: Any,
    avatars_root: Path,
    device: str,
) -> AnyRunner:
    """Factory: pick FlashTalkRunner or regular SessionRunner."""
    model = str(task.get("model", ""))
    sid = str(task["session_id"])
    avatar_id = str(task["avatar_id"])
    settings = get_settings()

    if model == "flashtalk":
        from opentalking.worker.flashtalk_runner import FlashTalkRunner

        flashtalk_mode = settings.normalized_flashtalk_mode
        flashtalk_client = None
        flashtalk_ws_url: str | None = None
        default_tts_voice = (
            settings.tts_elevenlabs_voice_id
            if settings.normalized_tts_provider == "elevenlabs"
            else settings.tts_voice
        )

        if flashtalk_mode == "remote":
            flashtalk_ws_url = settings.flashtalk_ws_url
        elif flashtalk_mode == "local":
            from opentalking.models.flashtalk import FlashTalkLocalClient

            flashtalk_client = FlashTalkLocalClient(
                ckpt_dir=settings.flashtalk_ckpt_dir,
                wav2vec_dir=settings.flashtalk_wav2vec_dir,
                device=settings.flashtalk_device,
                world_size=1,
                frame_num=settings.flashtalk_frame_num,
                motion_frames_num=settings.flashtalk_motion_frames_num,
                fps=settings.flashtalk_tgt_fps,
                height=settings.flashtalk_height,
                width=settings.flashtalk_width,
                sample_rate=settings.flashtalk_sample_rate,
            )
        else:
            raise RuntimeError(
                "FlashTalk is disabled (OPENTALKING_FLASHTALK_MODE=off). "
                "Use demo-avatar/wav2lip for the open-source demo path, or switch "
                "FlashTalk mode to remote/local."
            )

        return FlashTalkRunner(
            session_id=sid,
            avatar_id=avatar_id,
            avatars_root=avatars_root,
            redis=r,
            flashtalk_ws_url=flashtalk_ws_url,
            flashtalk_client=flashtalk_client,
            llm_base_url=settings.llm_base_url,
            llm_api_key=settings.llm_api_key,
            llm_model=settings.llm_model,
            system_prompt=settings.llm_system_prompt
            or "你是一个友好的数字人助手，请用简洁的语言回答问题。不要使用表情符号或emoji。",
        )

    return SessionRunner(
        session_id=sid,
        avatar_id=avatar_id,
        model_type=model,
        avatars_root=avatars_root,
        redis=r,
        device=device,
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
    runner = _create_runner(task, r, avatars_root, device)
    runners[sid] = runner
    try:
        await runner.prepare()
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
    cancelled = False  # set to True when session is deleted while waiting
    deadline = (asyncio.get_event_loop().time() + timeout_sec) if timeout_sec else None

    log.info("FlashTalk slot: session %s queued at position %d", sid, position)
    await publish_event(r, sid, "session.queued", {
        "session_id": sid, "position": position, "message": "waiting",
    })

    async def _run_with_lock() -> None:
        nonlocal cancelled
        global _slot_queue_size
        async with lock:
            _slot_queue_size -= 1
            _queued_tasks.pop(sid, None)

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
            session_deadline = (asyncio.get_event_loop().time() + max_session_sec) if max_session_sec else None
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
                    return
                # Check timeout
                if deadline and asyncio.get_event_loop().time() > deadline:
                    _slot_queue_size_dec()
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
    if not sid or not cmd:
        return
    if cmd == "init":
        if sid in runners:
            return
        model = str(task.get("model", ""))
        if model == "flashtalk":
            t = asyncio.create_task(
                _init_flashtalk_with_queue(task, r, avatars_root, device, runners, sid)
            )
            t.add_done_callback(lambda _t, _sid=sid: _log_task_exception(_t, _sid))
        else:
            runner = _create_runner(task, r, avatars_root, device)
            runners[sid] = runner
            try:
                await runner.prepare()
            except Exception:
                runners.pop(sid, None)
                await set_session_state(r, sid, "error")
                raise
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
        raw_voice = task.get("voice")
        tts_voice = str(raw_voice).strip() if raw_voice else None
        tp = task.get("tts_provider")
        tts_provider = str(tp).strip().lower() if tp else None
        tm = task.get("tts_model")
        tts_model = str(tm).strip() if tm else None
        enqueue_unix = task.get("enqueue_unix")
        if isinstance(enqueue_unix, (int, float)):
            log.info(
                "speak task dequeue from API enqueue: %.0f ms session=%s",
                (time.time() - float(enqueue_unix)) * 1000.0,
                sid,
            )
        runner.create_speak_task(
            text,
            tts_voice=tts_voice or None,
            tts_provider=tts_provider or None,
            tts_model=tts_model or None,
            enqueue_unix=float(enqueue_unix)
            if isinstance(enqueue_unix, (int, float))
            else None,
        )
    elif cmd == "interrupt":
        await runner.interrupt()
    elif cmd == "close":
        await runner.close()
        runners.pop(sid, None)


async def consume_task_queue(
    r: Any,
    avatars_root: Path,
    device: str,
    runners: dict[str, SessionRunner],
) -> None:
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
