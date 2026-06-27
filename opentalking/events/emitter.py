from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Optional

from opentalking.events.schemas import event_sse_payload

EventHandler = Callable[[str, dict[str, Any]], Optional[Awaitable[None]]]


class EventEmitter:
    """Fan-out session events to SSE subscribers and optional hooks."""

    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue[tuple[str, str]]]] = {}
        self._handlers: list[EventHandler] = []

    def subscribe(self, session_id: str) -> asyncio.Queue[tuple[str, str]]:
        q: asyncio.Queue[tuple[str, str]] = asyncio.Queue(maxsize=256)
        self._queues.setdefault(session_id, []).append(q)
        return q

    def unsubscribe(self, session_id: str, q: asyncio.Queue[tuple[str, str]]) -> None:
        subs = self._queues.get(session_id)
        if not subs:
            return
        if q in subs:
            subs.remove(q)
        if not subs:
            self._queues.pop(session_id, None)

    def add_handler(self, handler: EventHandler) -> None:
        self._handlers.append(handler)

    async def emit(self, session_id: str, event: Any) -> None:
        name, data = event_sse_payload(event)
        payload = {"event": name, "data": data}
        for h in self._handlers:
            r = h(session_id, payload)
            if asyncio.iscoroutine(r):
                await r
        for q in list(self._queues.get(session_id, [])):
            try:
                q.put_nowait((name, data))
            except asyncio.QueueFull:
                pass
