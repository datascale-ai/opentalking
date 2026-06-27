from __future__ import annotations

from typing import Any

from opentalking.core.redis_keys import FLASHTALK_QUEUE_STATUS


def _as_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return str(value)


def _as_bool(value: Any) -> bool:
    return _as_text(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: Any) -> int:
    try:
        return max(0, int(_as_text(value).strip()))
    except (TypeError, ValueError):
        return 0


def _hash_get(data: dict[Any, Any], key: str, default: str) -> Any:
    return data.get(key, data.get(key.encode("utf-8"), default))


async def set_flashtalk_queue_status(
    redis: Any,
    *,
    slot_occupied: bool,
    queue_size: int,
) -> None:
    await redis.hset(
        FLASHTALK_QUEUE_STATUS,
        mapping={
            "slot_occupied": "1" if slot_occupied else "0",
            "queue_size": str(max(0, int(queue_size))),
        },
    )


async def get_flashtalk_queue_status(redis: Any) -> dict[str, bool | int]:
    data = await redis.hgetall(FLASHTALK_QUEUE_STATUS)
    if not data:
        return {"slot_occupied": False, "queue_size": 0}
    return {
        "slot_occupied": _as_bool(_hash_get(data, "slot_occupied", "0")),
        "queue_size": _as_int(_hash_get(data, "queue_size", "0")),
    }
