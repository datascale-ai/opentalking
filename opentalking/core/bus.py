from __future__ import annotations

import json
from typing import Any

from opentalking.core.redis_keys import TASK_QUEUE, events_channel


async def publish_event(redis_client: Any, session_id: str, name: str, data: dict[str, Any]) -> None:
    payload = json.dumps({"event": name, "data": data}, ensure_ascii=False)
    await redis_client.publish(events_channel(session_id), payload)


async def push_task(redis_client: Any, task: dict[str, Any]) -> None:
    await redis_client.rpush(TASK_QUEUE, json.dumps(task, ensure_ascii=False))
