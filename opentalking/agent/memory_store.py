from __future__ import annotations

import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class TurnRecord:
    id: str
    user_id: str
    avatar_id: str
    session_id: str
    user_text: str
    assistant_text: str
    created_at: str


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    user_id: str
    avatar_id: str
    kind: str
    content: str
    importance: float
    confidence: float
    source_turn_id: str | None
    created_at: str
    updated_at: str


_EXPLICIT_MEMORY_PATTERNS = [
    re.compile(r"(?:请你?|麻烦你)?记住[：:\s]*(?P<content>.+)", re.IGNORECASE),
    re.compile(r"(?:请你?)?记得[：:\s]*(?P<content>.+)", re.IGNORECASE),
    re.compile(r"(?:please\s+)?remember(?:\s+this|\s+that)?[：:\s]*(?P<content>.+)", re.IGNORECASE),
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _normalize_scope_value(value: str) -> str:
    return value.strip()[:512]


def extract_explicit_memory(user_text: str) -> str | None:
    text = " ".join((user_text or "").strip().split())
    if not text:
        return None
    for pattern in _EXPLICIT_MEMORY_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        content = match.group("content").strip(" ，。,.!！?？\"'“”‘’")
        content = _normalize_scope_value(content)
        return content or None
    return None


class AgentMemoryStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    async def initialize(self) -> None:
        self._initialize_sync()

    async def save_turn(
        self,
        *,
        user_id: str,
        avatar_id: str,
        session_id: str,
        user_text: str,
        assistant_text: str,
    ) -> TurnRecord:
        return self._save_turn_sync(user_id, avatar_id, session_id, user_text, assistant_text)

    async def save_memory(
        self,
        *,
        user_id: str,
        avatar_id: str,
        kind: str,
        content: str,
        importance: float = 0.5,
        confidence: float = 1.0,
        source_turn_id: str | None = None,
    ) -> MemoryRecord:
        return self._save_memory_sync(
            user_id,
            avatar_id,
            kind,
            content,
            float(importance),
            float(confidence),
            source_turn_id,
        )

    async def save_explicit_memory_from_turn(
        self,
        *,
        user_id: str,
        avatar_id: str,
        source_turn_id: str,
        user_text: str,
    ) -> MemoryRecord | None:
        content = extract_explicit_memory(user_text)
        if not content:
            return None
        return await self.save_memory(
            user_id=user_id,
            avatar_id=avatar_id,
            kind="preference",
            content=content,
            importance=0.8,
            confidence=0.75,
            source_turn_id=source_turn_id,
        )

    async def list_memories(
        self,
        *,
        user_id: str,
        avatar_id: str,
        limit: int = 8,
    ) -> list[MemoryRecord]:
        return self._list_memories_sync(user_id, avatar_id, int(limit))

    async def clear_memories(self, *, user_id: str, avatar_id: str) -> int:
        return self._clear_memories_sync(user_id, avatar_id)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_sync(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_turns (
                  id TEXT PRIMARY KEY,
                  user_id TEXT NOT NULL,
                  avatar_id TEXT NOT NULL,
                  session_id TEXT NOT NULL,
                  user_text TEXT NOT NULL,
                  assistant_text TEXT NOT NULL,
                  created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_memories (
                  id TEXT PRIMARY KEY,
                  user_id TEXT NOT NULL,
                  avatar_id TEXT NOT NULL,
                  kind TEXT NOT NULL,
                  content TEXT NOT NULL,
                  importance REAL DEFAULT 0.5,
                  confidence REAL DEFAULT 1.0,
                  source_turn_id TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_memories_identity
                ON agent_memories(user_id, avatar_id, kind, content)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_agent_memories_lookup
                ON agent_memories(user_id, avatar_id, importance DESC, updated_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_agent_turns_lookup
                ON agent_turns(user_id, avatar_id, created_at DESC)
                """
            )

    def _save_turn_sync(
        self,
        user_id: str,
        avatar_id: str,
        session_id: str,
        user_text: str,
        assistant_text: str,
    ) -> TurnRecord:
        self._initialize_sync()
        record = TurnRecord(
            id=_new_id("turn"),
            user_id=_normalize_scope_value(user_id),
            avatar_id=_normalize_scope_value(avatar_id),
            session_id=_normalize_scope_value(session_id),
            user_text=user_text,
            assistant_text=assistant_text,
            created_at=_utc_now(),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_turns(id, user_id, avatar_id, session_id, user_text, assistant_text, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.user_id,
                    record.avatar_id,
                    record.session_id,
                    record.user_text,
                    record.assistant_text,
                    record.created_at,
                ),
            )
        return record

    def _save_memory_sync(
        self,
        user_id: str,
        avatar_id: str,
        kind: str,
        content: str,
        importance: float,
        confidence: float,
        source_turn_id: str | None,
    ) -> MemoryRecord:
        self._initialize_sync()
        now = _utc_now()
        user_id = _normalize_scope_value(user_id)
        avatar_id = _normalize_scope_value(avatar_id)
        kind = _normalize_scope_value(kind or "preference") or "preference"
        content = _normalize_scope_value(content)
        if not user_id or not avatar_id or not content:
            raise ValueError("user_id, avatar_id and content are required")
        memory_id = _new_id("mem")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_memories(
                  id, user_id, avatar_id, kind, content, importance, confidence,
                  source_turn_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, avatar_id, kind, content) DO UPDATE SET
                  importance=max(agent_memories.importance, excluded.importance),
                  confidence=max(agent_memories.confidence, excluded.confidence),
                  source_turn_id=coalesce(excluded.source_turn_id, agent_memories.source_turn_id),
                  updated_at=excluded.updated_at
                """,
                (
                    memory_id,
                    user_id,
                    avatar_id,
                    kind,
                    content,
                    importance,
                    confidence,
                    source_turn_id,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT id, user_id, avatar_id, kind, content, importance, confidence,
                       source_turn_id, created_at, updated_at
                FROM agent_memories
                WHERE user_id = ? AND avatar_id = ? AND kind = ? AND content = ?
                """,
                (user_id, avatar_id, kind, content),
            ).fetchone()
        if row is None:
            raise RuntimeError("failed to save agent memory")
        return _memory_from_row(row)

    def _list_memories_sync(self, user_id: str, avatar_id: str, limit: int) -> list[MemoryRecord]:
        self._initialize_sync()
        safe_limit = min(32, max(1, limit))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, user_id, avatar_id, kind, content, importance, confidence,
                       source_turn_id, created_at, updated_at
                FROM agent_memories
                WHERE user_id = ? AND avatar_id = ?
                ORDER BY importance DESC, updated_at DESC
                LIMIT ?
                """,
                (_normalize_scope_value(user_id), _normalize_scope_value(avatar_id), safe_limit),
            ).fetchall()
        return [_memory_from_row(row) for row in rows]

    def _clear_memories_sync(self, user_id: str, avatar_id: str) -> int:
        self._initialize_sync()
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM agent_memories WHERE user_id = ? AND avatar_id = ?",
                (_normalize_scope_value(user_id), _normalize_scope_value(avatar_id)),
            )
            return int(cursor.rowcount or 0)


def _memory_from_row(row: sqlite3.Row) -> MemoryRecord:
    return MemoryRecord(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        avatar_id=str(row["avatar_id"]),
        kind=str(row["kind"]),
        content=str(row["content"]),
        importance=float(row["importance"]),
        confidence=float(row["confidence"]),
        source_turn_id=str(row["source_turn_id"]) if row["source_turn_id"] is not None else None,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )
