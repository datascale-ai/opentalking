from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from opentalking.providers.memory.schemas import MemoryItem, MemoryLibrary


class MemoryProvider(ABC):
    @abstractmethod
    async def list_libraries(
        self,
        *,
        profile_id: str,
        character_id: str,
    ) -> list[MemoryLibrary]:
        raise NotImplementedError

    @abstractmethod
    async def create_library(
        self,
        *,
        library_id: str | None,
        name: str | None,
        profile_id: str,
        character_id: str,
    ) -> MemoryLibrary:
        raise NotImplementedError

    @abstractmethod
    async def get_library(
        self,
        *,
        library_id: str,
        profile_id: str,
        character_id: str,
    ) -> MemoryLibrary | None:
        raise NotImplementedError

    @abstractmethod
    async def list_items(
        self,
        *,
        library_id: str,
        profile_id: str,
        character_id: str,
    ) -> list[MemoryItem]:
        raise NotImplementedError

    @abstractmethod
    async def add_items(
        self,
        *,
        library_id: str,
        profile_id: str,
        character_id: str,
        items: Sequence[MemoryItem],
    ) -> int:
        raise NotImplementedError

    @abstractmethod
    async def delete_item(
        self,
        *,
        library_id: str,
        item_id: str,
        profile_id: str,
        character_id: str,
    ) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError
