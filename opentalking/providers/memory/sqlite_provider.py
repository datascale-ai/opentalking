from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from collections.abc import Sequence
from pathlib import Path

from opentalking.providers.memory.base import MemoryProvider
from opentalking.providers.memory.schemas import MemoryItem, MemoryLibrary, utc_now_iso


class SQLiteMemoryProvider(MemoryProvider):
    """Raw local memory store used before LLM/embedding recall is enabled."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self._lock = asyncio.Lock()

    async def list_libraries(
        self,
        *,
        profile_id: str,
        character_id: str,
    ) -> list[MemoryLibrary]:
        rows = await self._execute_fetchall(
            """
            SELECT l.id, l.name, l.profile_id, l.character_id, l.created_at, l.updated_at,
                   COUNT(i.id) AS memory_count
            FROM memory_libraries l
            LEFT JOIN memory_items i
              ON i.library_id = l.id
             AND i.profile_id = l.profile_id
             AND i.character_id = l.character_id
            WHERE l.profile_id = ? AND l.character_id = ?
            GROUP BY l.id, l.name, l.profile_id, l.character_id, l.created_at, l.updated_at
            ORDER BY l.updated_at DESC
            """,
            (profile_id, character_id),
        )
        return [
            MemoryLibrary(
                id=str(row["id"]),
                name=str(row["name"]),
                profile_id=str(row["profile_id"]),
                character_id=str(row["character_id"]),
                memory_count=int(row["memory_count"] or 0),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )
            for row in rows
        ]

    async def create_library(
        self,
        *,
        library_id: str | None,
        name: str | None,
        profile_id: str,
        character_id: str,
    ) -> MemoryLibrary:
        lid = (library_id or uuid.uuid4().hex[:12]).strip() or uuid.uuid4().hex[:12]
        display_name = (name or "默认记忆库").strip() or "默认记忆库"
        now = utc_now_iso()
        async with self._lock:
            await asyncio.to_thread(self._ensure_schema)
            existing = await asyncio.to_thread(
                self._fetchone,
                """
                SELECT id, name, profile_id, character_id, created_at, updated_at
                FROM memory_libraries
                WHERE id = ? AND profile_id = ? AND character_id = ?
                """,
                (lid, profile_id, character_id),
            )
            if existing is None:
                await asyncio.to_thread(
                    self._execute,
                    """
                    INSERT INTO memory_libraries
                        (id, name, profile_id, character_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (lid, display_name, profile_id, character_id, now, now),
                )
                created_at = now
                updated_at = now
            else:
                created_at = str(existing["created_at"])
                updated_at = str(existing["updated_at"])
                display_name = str(existing["name"])
        return MemoryLibrary(
            id=lid,
            name=display_name,
            profile_id=profile_id,
            character_id=character_id,
            created_at=created_at,
            updated_at=updated_at,
        )

    async def get_library(
        self,
        *,
        library_id: str,
        profile_id: str,
        character_id: str,
    ) -> MemoryLibrary | None:
        rows = await self.list_libraries(profile_id=profile_id, character_id=character_id)
        return next((row for row in rows if row.id == library_id), None)

    async def list_items(
        self,
        *,
        library_id: str,
        profile_id: str,
        character_id: str,
    ) -> list[MemoryItem]:
        rows = await self._execute_fetchall(
            """
            SELECT id, text, type, metadata_json, created_at
            FROM memory_items
            WHERE library_id = ? AND profile_id = ? AND character_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (library_id, profile_id, character_id),
        )
        return [
            MemoryItem(
                id=str(row["id"]),
                text=str(row["text"]),
                type=str(row["type"] or "note"),  # type: ignore[arg-type]
                metadata=_decode_metadata(str(row["metadata_json"] or "{}")),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    async def add_items(
        self,
        *,
        library_id: str,
        profile_id: str,
        character_id: str,
        items: Sequence[MemoryItem],
    ) -> int:
        now = utc_now_iso()
        imported = 0
        async with self._lock:
            await asyncio.to_thread(self._ensure_schema)
            await asyncio.to_thread(
                self._execute,
                """
                INSERT OR IGNORE INTO memory_libraries
                    (id, name, profile_id, character_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (library_id, "默认记忆库", profile_id, character_id, now, now),
            )
            for item in items:
                text = item.text.strip()
                if not text:
                    continue
                await asyncio.to_thread(
                    self._execute,
                    """
                    INSERT INTO memory_items
                        (id, library_id, profile_id, character_id, text, type, metadata_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.id or uuid.uuid4().hex,
                        library_id,
                        profile_id,
                        character_id,
                        text,
                        item.type,
                        json.dumps(dict(item.metadata), ensure_ascii=False),
                        item.created_at or now,
                    ),
                )
                imported += 1
            if imported:
                await asyncio.to_thread(
                    self._execute,
                    """
                    UPDATE memory_libraries
                    SET updated_at = ?
                    WHERE id = ? AND profile_id = ? AND character_id = ?
                    """,
                    (utc_now_iso(), library_id, profile_id, character_id),
                )
        return imported

    async def delete_item(
        self,
        *,
        library_id: str,
        item_id: str,
        profile_id: str,
        character_id: str,
    ) -> bool:
        async with self._lock:
            await asyncio.to_thread(self._ensure_schema)
            deleted = await asyncio.to_thread(
                self._execute,
                """
                DELETE FROM memory_items
                WHERE id = ? AND library_id = ? AND profile_id = ? AND character_id = ?
                """,
                (item_id, library_id, profile_id, character_id),
            )
            if deleted:
                await asyncio.to_thread(
                    self._execute,
                    """
                    UPDATE memory_libraries
                    SET updated_at = ?
                    WHERE id = ? AND profile_id = ? AND character_id = ?
                    """,
                    (utc_now_iso(), library_id, profile_id, character_id),
                )
            return bool(deleted)

    async def close(self) -> None:
        return

    async def _execute_fetchall(
        self,
        sql: str,
        params: tuple[object, ...],
    ) -> list[sqlite3.Row]:
        async with self._lock:
            await asyncio.to_thread(self._ensure_schema)
            return await asyncio.to_thread(self._fetchall, sql, params)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_libraries (
                    id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    profile_id TEXT NOT NULL,
                    character_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (id, profile_id, character_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_items (
                    id TEXT PRIMARY KEY,
                    library_id TEXT NOT NULL,
                    profile_id TEXT NOT NULL,
                    character_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    type TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_items_scope
                ON memory_items(profile_id, character_id, library_id, created_at)
                """
            )

    def _execute(self, sql: str, params: tuple[object, ...]) -> int:
        with self._connect() as conn:
            cur = conn.execute(sql, params)
            return int(cur.rowcount if cur.rowcount is not None else 0)

    def _fetchone(self, sql: str, params: tuple[object, ...]) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(sql, params).fetchone()

    def _fetchall(self, sql: str, params: tuple[object, ...]) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return list(conn.execute(sql, params).fetchall())


def _decode_metadata(raw: str) -> dict[str, object]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
