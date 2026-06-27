from __future__ import annotations

from typing import Any

SESSION_TTL_SECONDS = 600
TERMINAL_STATES = {"closed", "error"}


def session_key(session_id: str) -> str:
    return f"opentalking:session:{session_id}"


# FlashTalk 磁盘录制：任意 API worker 可写开关；持有 Runner 的进程通过 Redis 读取。
FLASHTALK_DISK_RECORDING_FIELD = "flashtalk_disk_recording"
FLASHTALK_RECORDING_EPOCH_FIELD = "flashtalk_recording_epoch"


async def apply_flashtalk_recording_start(r: Any, session_id: str) -> None:
    """清空本会话录制文件、打开录制开关并递增 epoch。"""
    from opentalking.pipeline.recording.recording import clear_flashtalk_recording_files

    clear_flashtalk_recording_files(session_id)
    key = session_key(session_id)
    cur = await r.hget(key, FLASHTALK_RECORDING_EPOCH_FIELD)
    n = int(cur or 0) + 1
    await r.hset(
        key,
        mapping={
            FLASHTALK_DISK_RECORDING_FIELD: "1",
            FLASHTALK_RECORDING_EPOCH_FIELD: str(n),
        },
    )


async def apply_flashtalk_recording_stop(r: Any, session_id: str) -> None:
    await r.hset(session_key(session_id), FLASHTALK_DISK_RECORDING_FIELD, "0")


async def get_session_record(r: Any, session_id: str) -> dict[str, str] | None:
    raw = await r.hgetall(session_key(session_id))
    if not raw:
        return None
    return dict(raw)


async def set_session_state(
    r: Any,
    session_id: str,
    state: str,
    *,
    extra: dict[str, Any] | None = None,
) -> None:
    mapping: dict[str, Any] = {"state": state}
    if extra:
        mapping.update(extra)
    await r.hset(session_key(session_id), mapping=mapping)
    if state in TERMINAL_STATES:
        await r.expire(session_key(session_id), SESSION_TTL_SECONDS)
    else:
        persist = getattr(r, "persist", None)
        if callable(persist):
            await persist(session_key(session_id))
