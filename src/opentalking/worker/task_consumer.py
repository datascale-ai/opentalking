from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from opentalking.core.config import get_settings
from opentalking.core.redis_keys import TASK_QUEUE
from opentalking.core.session_store import set_session_state
from opentalking.worker.session_runner import SessionRunner

log = logging.getLogger(__name__)

# Type alias: both SessionRunner and FlashTalkRunner share the same duck-typed interface
AnyRunner = Any


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
            tts_provider=str(task.get("tts_provider", "") or settings.normalized_tts_provider),
            tts_voice=str(task.get("tts_voice", "") or default_tts_voice),
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
        log.warning("unknown session %s for cmd %s", sid, cmd)
        return
    if cmd == "speak":
        text = str(task.get("text", ""))
        runner.create_speak_task(text)
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
