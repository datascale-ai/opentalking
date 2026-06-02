from __future__ import annotations

from collections.abc import Sequence

from opentalking.providers.memory.base import MemoryProvider
from opentalking.providers.memory.schemas import MemoryItem, MemoryLibrary


class NoopMemoryProvider(MemoryProvider):
    async def list_libraries(
        self,
        *,
        profile_id: str,
        character_id: str,
    ) -> list[MemoryLibrary]:
        return []

    async def create_library(
        self,
        *,
        library_id: str | None,
        name: str | None,
        profile_id: str,
        character_id: str,
    ) -> MemoryLibrary:
        library = MemoryLibrary(
            id=library_id or "default",
            name=name or "Default memory",
            profile_id=profile_id,
            character_id=character_id,
        )
        return library

    async def get_library(
        self,
        *,
        library_id: str,
        profile_id: str,
        character_id: str,
    ) -> MemoryLibrary | None:
        return None

    async def list_items(
        self,
        *,
        library_id: str,
        profile_id: str,
        character_id: str,
    ) -> list[MemoryItem]:
        return []

    async def add_items(
        self,
        *,
        library_id: str,
        profile_id: str,
        character_id: str,
        items: Sequence[MemoryItem],
    ) -> int:
        return 0

    async def delete_item(
        self,
        *,
        library_id: str,
        item_id: str,
        profile_id: str,
        character_id: str,
    ) -> bool:
        return False

    async def close(self) -> None:
        return
