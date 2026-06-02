from __future__ import annotations

import asyncio
import inspect
import uuid
from collections.abc import Sequence
from typing import Any

from opentalking.providers.memory.base import MemoryProvider
from opentalking.providers.memory.schemas import MemoryItem, MemoryLibrary, utc_now_iso


class Mem0UnavailableError(RuntimeError):
    pass


def _import_memory_class() -> Any:
    try:
        from mem0 import Memory  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise Mem0UnavailableError("mem0 package is not installed") from exc
    return Memory


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class Mem0MemoryProvider(MemoryProvider):
    def __init__(
        self,
        *,
        config: dict[str, Any] | None = None,
        client: Any | None = None,
    ) -> None:
        if client is not None:
            self._client = client
        else:
            memory_cls = _import_memory_class()
            cfg = config or {}
            try:
                self._client = memory_cls.from_config(cfg) if cfg else memory_cls()
            except AttributeError:
                self._client = memory_cls(config=cfg) if cfg else memory_cls()

    async def list_libraries(
        self,
        *,
        profile_id: str,
        character_id: str,
    ) -> list[MemoryLibrary]:
        items = await self._all_scoped_items(profile_id=profile_id, character_id=character_id)
        libraries: dict[str, MemoryLibrary] = {}
        counts: dict[str, int] = {}
        for item in items:
            meta = item.metadata
            library_id = str(meta.get("library_id") or "default")
            if not meta.get("opentalking_library_marker"):
                counts[library_id] = counts.get(library_id, 0) + 1
            if library_id not in libraries:
                created_at = str(meta.get("library_created_at") or item.created_at)
                updated_at = str(meta.get("library_updated_at") or item.created_at)
                libraries[library_id] = MemoryLibrary(
                    id=library_id,
                    name=str(meta.get("library_name") or "Default memory"),
                    profile_id=profile_id,
                    character_id=character_id,
                    created_at=created_at,
                    updated_at=updated_at,
                )
        return [
            MemoryLibrary(
                id=library.id,
                name=library.name,
                profile_id=library.profile_id,
                character_id=library.character_id,
                memory_count=counts.get(library.id, 0),
                created_at=library.created_at,
                updated_at=library.updated_at,
            )
            for library in sorted(libraries.values(), key=lambda row: row.updated_at, reverse=True)
        ]

    async def create_library(
        self,
        *,
        library_id: str | None,
        name: str | None,
        profile_id: str,
        character_id: str,
    ) -> MemoryLibrary:
        now = utc_now_iso()
        library = MemoryLibrary(
            id=library_id or "default",
            name=name or "Default memory",
            profile_id=profile_id,
            character_id=character_id,
            created_at=now,
            updated_at=now,
        )
        marker = MemoryItem(
            id=f"lib_{uuid.uuid4().hex}",
            text=f"Memory library: {library.name}",
            type="note",
            metadata={
                "library_id": library.id,
                "library_name": library.name,
                "library_created_at": now,
                "library_updated_at": now,
                "opentalking_library_marker": True,
            },
            created_at=now,
        )
        await self.add_items(
            library_id=library.id,
            profile_id=profile_id,
            character_id=character_id,
            items=[marker],
        )
        return library

    async def get_library(
        self,
        *,
        library_id: str,
        profile_id: str,
        character_id: str,
    ) -> MemoryLibrary | None:
        for library in await self.list_libraries(profile_id=profile_id, character_id=character_id):
            if library.id == library_id:
                return library
        return None

    async def list_items(
        self,
        *,
        library_id: str,
        profile_id: str,
        character_id: str,
    ) -> list[MemoryItem]:
        items = await self._all_scoped_items(profile_id=profile_id, character_id=character_id)
        return [
            item
            for item in items
            if item.metadata.get("library_id") == library_id
            and not item.metadata.get("opentalking_library_marker")
        ]

    async def add_items(
        self,
        *,
        library_id: str,
        profile_id: str,
        character_id: str,
        items: Sequence[MemoryItem],
    ) -> int:
        imported = 0
        for item in items:
            text = item.text.strip()
            if not text:
                continue
            metadata = dict(item.metadata or {})
            metadata.update(
                {
                    "library_id": library_id,
                    "profile_id": profile_id,
                    "character_id": character_id,
                    "type": item.type,
                    "opentalking_memory_id": item.id or uuid.uuid4().hex,
                    "created_at": item.created_at or utc_now_iso(),
                }
            )
            await self._add(text, profile_id=profile_id, character_id=character_id, metadata=metadata)
            imported += 1
        return imported

    async def delete_item(
        self,
        *,
        library_id: str,
        item_id: str,
        profile_id: str,
        character_id: str,
    ) -> bool:
        item = await self._find_item(
            library_id=library_id,
            item_id=item_id,
            profile_id=profile_id,
            character_id=character_id,
        )
        if item is None:
            return False
        delete = getattr(self._client, "delete", None)
        if not callable(delete):
            return False
        raw_id = item.metadata.get("_mem0_id") or item.id
        await _maybe_await(delete(raw_id))
        return True

    async def close(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):
            await _maybe_await(close())

    async def _add(
        self,
        text: str,
        *,
        profile_id: str,
        character_id: str,
        metadata: dict[str, Any],
    ) -> None:
        add = getattr(self._client, "add", None)
        if not callable(add):
            raise RuntimeError("mem0 client does not expose add()")

        kwargs = {
            "user_id": profile_id,
            "agent_id": character_id,
            "metadata": metadata,
            "infer": False,
        }
        try:
            await _maybe_await(add(text, **kwargs))
        except TypeError:
            messages = [{"role": "user", "content": text}]
            await _maybe_await(add(messages, **kwargs))

    async def _all_scoped_items(self, *, profile_id: str, character_id: str) -> list[MemoryItem]:
        get_all = getattr(self._client, "get_all", None)
        if not callable(get_all):
            return []
        try:
            raw = await _maybe_await(get_all(user_id=profile_id, agent_id=character_id))
        except TypeError:
            raw = await _maybe_await(get_all(user_id=profile_id))
        return [
            item
            for item in self._normalize_raw_items(raw)
            if item.metadata.get("profile_id", profile_id) == profile_id
            and item.metadata.get("character_id", character_id) == character_id
        ]

    async def _find_item(
        self,
        *,
        library_id: str,
        item_id: str,
        profile_id: str,
        character_id: str,
    ) -> MemoryItem | None:
        for item in await self.list_items(
            library_id=library_id,
            profile_id=profile_id,
            character_id=character_id,
        ):
            if item.id == item_id or item.metadata.get("_mem0_id") == item_id:
                return item
        return None

    def _normalize_raw_items(self, raw: Any) -> list[MemoryItem]:
        if isinstance(raw, dict):
            source = raw.get("results") or raw.get("memories") or raw.get("items") or []
        else:
            source = raw or []
        out: list[MemoryItem] = []
        for entry in source:
            if not isinstance(entry, dict):
                continue
            metadata = dict(entry.get("metadata") or {})
            text = str(entry.get("memory") or entry.get("text") or entry.get("content") or "").strip()
            if not text:
                continue
            raw_id = str(entry.get("id") or metadata.get("opentalking_memory_id") or uuid.uuid4().hex)
            item_id = str(metadata.get("opentalking_memory_id") or raw_id)
            metadata["_mem0_id"] = raw_id
            out.append(
                MemoryItem(
                    id=item_id,
                    text=text,
                    type=str(metadata.get("type") or "note"),  # type: ignore[arg-type]
                    metadata=metadata,
                    created_at=str(
                        metadata.get("created_at") or entry.get("created_at") or utc_now_iso()
                    ),
                )
            )
        return out


class InMemoryMemoryProvider(MemoryProvider):
    """Small test/local provider with the same OpenTalking API semantics."""

    def __init__(self) -> None:
        self._libraries: dict[tuple[str, str, str], MemoryLibrary] = {}
        self._items: dict[tuple[str, str, str], list[MemoryItem]] = {}
        self._lock = asyncio.Lock()

    async def list_libraries(
        self,
        *,
        profile_id: str,
        character_id: str,
    ) -> list[MemoryLibrary]:
        async with self._lock:
            libraries = [
                library
                for (p, c, _), library in self._libraries.items()
                if p == profile_id and c == character_id
            ]
            return [self._with_count(library) for library in libraries]

    async def create_library(
        self,
        *,
        library_id: str | None,
        name: str | None,
        profile_id: str,
        character_id: str,
    ) -> MemoryLibrary:
        async with self._lock:
            now = utc_now_iso()
            library = MemoryLibrary(
                id=library_id or "default",
                name=name or "Default memory",
                profile_id=profile_id,
                character_id=character_id,
                created_at=now,
                updated_at=now,
            )
            self._libraries[(profile_id, character_id, library.id)] = library
            self._items.setdefault((profile_id, character_id, library.id), [])
            return library

    async def get_library(
        self,
        *,
        library_id: str,
        profile_id: str,
        character_id: str,
    ) -> MemoryLibrary | None:
        async with self._lock:
            library = self._libraries.get((profile_id, character_id, library_id))
            return self._with_count(library) if library is not None else None

    async def list_items(
        self,
        *,
        library_id: str,
        profile_id: str,
        character_id: str,
    ) -> list[MemoryItem]:
        async with self._lock:
            return list(self._items.get((profile_id, character_id, library_id), []))

    async def add_items(
        self,
        *,
        library_id: str,
        profile_id: str,
        character_id: str,
        items: Sequence[MemoryItem],
    ) -> int:
        async with self._lock:
            key = (profile_id, character_id, library_id)
            if key not in self._libraries:
                now = utc_now_iso()
                self._libraries[key] = MemoryLibrary(
                    id=library_id,
                    name="Default memory",
                    profile_id=profile_id,
                    character_id=character_id,
                    created_at=now,
                    updated_at=now,
                )
            bucket = self._items.setdefault(key, [])
            for item in items:
                if not item.text.strip():
                    continue
                bucket.append(
                    MemoryItem(
                        id=item.id or uuid.uuid4().hex,
                        text=item.text,
                        type=item.type,
                        metadata=dict(item.metadata),
                        created_at=item.created_at,
                    )
                )
            library = self._libraries[key]
            self._libraries[key] = MemoryLibrary(
                id=library.id,
                name=library.name,
                profile_id=library.profile_id,
                character_id=library.character_id,
                memory_count=len(bucket),
                created_at=library.created_at,
                updated_at=utc_now_iso(),
            )
            return len(items)

    async def delete_item(
        self,
        *,
        library_id: str,
        item_id: str,
        profile_id: str,
        character_id: str,
    ) -> bool:
        async with self._lock:
            key = (profile_id, character_id, library_id)
            before = self._items.get(key, [])
            after = [item for item in before if item.id != item_id]
            self._items[key] = after
            return len(after) != len(before)

    async def close(self) -> None:
        return

    def _with_count(self, library: MemoryLibrary) -> MemoryLibrary:
        count = len(self._items.get((library.profile_id, library.character_id, library.id), []))
        return MemoryLibrary(
            id=library.id,
            name=library.name,
            profile_id=library.profile_id,
            character_id=library.character_id,
            memory_count=count,
            created_at=library.created_at,
            updated_at=library.updated_at,
        )
