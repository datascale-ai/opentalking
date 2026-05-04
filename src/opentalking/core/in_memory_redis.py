"""
In-process async Redis-like client for single-process (no external Redis) mode.

Implements only the subset of redis.asyncio used by OpenTalking API + Worker.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from time import monotonic
from typing import TYPE_CHECKING, Any

from opentalking.core.redis_keys import TASK_QUEUE

if TYPE_CHECKING:
    pass


class InMemoryRedis:
    """Hash + task queue + pub/sub for unified single-process mode."""

    def __init__(self) -> None:
        self._hash: dict[str, dict[str, str]] = {}
        self._kv: dict[str, bytes] = {}
        self._task_queue: asyncio.Queue[str] | None = None
        self._listeners: dict[str, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(list)
        self._expiry: dict[str, float] = {}

    @property
    def task_queue(self) -> asyncio.Queue[str]:
        if self._task_queue is None:
            self._task_queue = asyncio.Queue()
        return self._task_queue

    def _purge_if_expired(self, name: str) -> None:
        deadline = self._expiry.get(name)
        if deadline is None:
            return
        if monotonic() < deadline:
            return
        self._expiry.pop(name, None)
        self._hash.pop(name, None)
        self._kv.pop(name, None)

    def _register_listener(self, channel: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        if q not in self._listeners[channel]:
            self._listeners[channel].append(q)

    def _unregister_listener(self, channel: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        lst = self._listeners.get(channel)
        if not lst:
            return
        if q in lst:
            lst.remove(q)
        if not lst:
            self._listeners.pop(channel, None)

    async def hset(
        self,
        name: str,
        key: str | None = None,
        value: str | None = None,
        mapping: dict[str, Any] | None = None,
    ) -> int:
        self._purge_if_expired(name)
        h = self._hash.setdefault(name, {})
        if mapping is not None:
            for k, v in mapping.items():
                h[str(k)] = str(v)
            return len(mapping)
        if key is not None and value is not None:
            h[str(key)] = str(value)
            return 1
        return 0

    async def hgetall(self, name: str) -> dict[str, str]:
        self._purge_if_expired(name)
        return dict(self._hash.get(name, {}))

    async def delete(self, *names: str) -> int:
        n = 0
        for name in names:
            self._purge_if_expired(name)
            removed = False
            if name in self._hash:
                del self._hash[name]
                removed = True
            if name in self._kv:
                del self._kv[name]
                removed = True
            if removed:
                self._expiry.pop(name, None)
                n += 1
        return n

    async def exists(self, name: str) -> int:
        self._purge_if_expired(name)
        return 1 if name in self._hash or name in self._kv else 0

    async def expire(self, name: str, seconds: int) -> int:
        self._purge_if_expired(name)
        if name not in self._hash and name not in self._kv:
            return 0
        self._expiry[name] = monotonic() + max(0, seconds)
        return 1

    async def persist(self, name: str) -> int:
        self._purge_if_expired(name)
        return 1 if self._expiry.pop(name, None) is not None else 0

    async def set(self, name: str, value: bytes | str, ex: int | None = None) -> bool:
        self._purge_if_expired(name)
        self._kv[name] = value.encode("utf-8") if isinstance(value, str) else bytes(value)
        if ex is not None:
            self._expiry[name] = monotonic() + max(0, int(ex))
        else:
            self._expiry.pop(name, None)
        return True

    async def get(self, name: str) -> bytes | None:
        self._purge_if_expired(name)
        return self._kv.get(name)

    async def rpush(self, name: str, *values: str) -> int:
        _ = name  # only TASK_QUEUE used
        for v in values:
            await self.task_queue.put(str(v))
        return len(values)

    async def brpop(self, keys: str | list[str], timeout: int = 0) -> tuple[str, str] | None:
        if isinstance(keys, str):
            key_list = [keys]
        else:
            key_list = list(keys)
        if TASK_QUEUE not in key_list:
            return None
        t = float(timeout) if timeout else None
        try:
            if t is not None and t > 0:
                item = await asyncio.wait_for(self.task_queue.get(), timeout=t)
            else:
                item = await self.task_queue.get()
            return (TASK_QUEUE, item)
        except asyncio.TimeoutError:
            return None

    async def publish(self, channel: str, message: str) -> int:
        msg: dict[str, Any] = {
            "type": "message",
            "channel": channel,
            "data": message,
        }
        n = 0
        for q in list(self._listeners.get(channel, [])):
            try:
                q.put_nowait(msg)
                n += 1
            except asyncio.QueueFull:
                pass
        return n

    def pubsub(self) -> MemoryPubSub:
        return MemoryPubSub(self)

    async def aclose(self) -> None:
        return


class MemoryPubSub:
    """Minimal pubsub compatible with the SSE event route usage."""

    def __init__(self, broker: InMemoryRedis) -> None:
        self._broker = broker
        self._incoming: asyncio.Queue[dict[str, Any]] | None = None
        self._channels: set[str] = set()

    @property
    def incoming(self) -> asyncio.Queue[dict[str, Any]]:
        if self._incoming is None:
            self._incoming = asyncio.Queue(maxsize=256)
        return self._incoming

    async def subscribe(self, *channels: str) -> None:
        for ch in channels:
            self._channels.add(ch)
            self._broker._register_listener(ch, self.incoming)

    async def unsubscribe(self, *channels: str) -> None:
        for ch in channels:
            self._channels.discard(ch)
            if self._incoming is not None:
                self._broker._unregister_listener(ch, self._incoming)

    async def get_message(
        self,
        *,
        ignore_subscribe_messages: bool = True,
        timeout: float | None = 30.0,
    ) -> dict[str, Any] | None:
        _ = ignore_subscribe_messages
        try:
            if timeout is None:
                return await self.incoming.get()
            return await asyncio.wait_for(self.incoming.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def aclose(self) -> None:
        for ch in list(self._channels):
            await self.unsubscribe(ch)
