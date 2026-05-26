"""SQLite：默认用户 + 系统预设音色 + 克隆音色。"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class VoiceEntry:
    id: int
    user_id: int
    provider: str
    voice_id: str
    display_label: str
    target_model: str | None
    source: str


def get_sqlite_path() -> Path:
    try:
        from opentalking.core.config import get_settings

        raw = (get_settings().sqlite_path or "").strip()
    except Exception:
        raw = ""
    if not raw:
        raw = os.environ.get("OPENTALKING_SQLITE_PATH", "").strip()
    if not raw:
        raw = "./data/opentalking.sqlite3"
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = (Path.cwd() / p).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(get_sqlite_path()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_voice_store() -> None:
    """创建库表、默认用户，并写入系统预设音色（仅首次）。"""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY,
              label TEXT NOT NULL DEFAULT 'default'
            )
            """
        )
        cur.execute("INSERT OR IGNORE INTO users (id, label) VALUES (1, 'default')")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tts_voice_entries (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER NOT NULL DEFAULT 1,
              provider TEXT NOT NULL,
              voice_id TEXT NOT NULL,
              display_label TEXT NOT NULL,
              target_model TEXT,
              source TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_tts_voice_user_provider ON tts_voice_entries(user_id, provider)"
        )

        # 固定 id 便于 INSERT OR IGNORE 幂等
        seeds: list[tuple[int, str, str, str, str | None]] = [
            # Qwen 实时（dashscope）
            (101, "dashscope", "Cherry", "Cherry", None),
            (102, "dashscope", "Serena", "Serena", None),
            (103, "dashscope", "Ethan", "Ethan", None),
            (104, "dashscope", "Chelsie", "Chelsie", None),
            (105, "dashscope", "Dylan", "Dylan", None),
            (106, "dashscope", "Jada", "Jada", None),
            (107, "dashscope", "Roy", "Roy", None),
            # CosyVoice
            (201, "cosyvoice", "longanyang", "longanyang（示例·男）", None),
        ]
        for sid, prov, vid, label, tm in seeds:
            cur.execute(
                """
                INSERT OR IGNORE INTO tts_voice_entries
                  (id, user_id, provider, voice_id, display_label, target_model, source)
                VALUES (?, 1, ?, ?, ?, ?, 'system')
                """,
                (sid, prov, vid, label, tm),
            )
        cur.execute("DELETE FROM tts_voice_entries WHERE provider = 'minimax'")
        cur.execute(
            """
            DELETE FROM tts_voice_entries
            WHERE provider = 'local_cosyvoice'
              AND voice_id = 'local-default'
              AND source = 'system'
            """
        )
        conn.commit()
    finally:
        conn.close()


def list_voices(*, user_id: int = 1, provider: str | None = None) -> list[VoiceEntry]:
    conn = _connect()
    try:
        cur = conn.cursor()
        if provider:
            cur.execute(
                """
                SELECT id, user_id, provider, voice_id, display_label, target_model, source
                FROM tts_voice_entries
                WHERE user_id = ? AND provider = ?
                ORDER BY CASE WHEN source = 'system' THEN 0 ELSE 1 END, id ASC
                """,
                (user_id, provider.strip().lower()),
            )
        else:
            cur.execute(
                """
                SELECT id, user_id, provider, voice_id, display_label, target_model, source
                FROM tts_voice_entries
                WHERE user_id = ?
                ORDER BY provider, CASE WHEN source = 'system' THEN 0 ELSE 1 END, id ASC
                """,
                (user_id,),
            )
        rows = cur.fetchall()
        return [
            VoiceEntry(
                id=int(r["id"]),
                user_id=int(r["user_id"]),
                provider=str(r["provider"]),
                voice_id=str(r["voice_id"]),
                display_label=str(r["display_label"]),
                target_model=r["target_model"],
                source=str(r["source"]),
            )
            for r in rows
        ]
    finally:
        conn.close()


def insert_clone(
    *,
    user_id: int = 1,
    provider: str,
    voice_id: str,
    display_label: str,
    target_model: str | None,
) -> int:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO tts_voice_entries (user_id, provider, voice_id, display_label, target_model, source)
            VALUES (?, ?, ?, ?, ?, 'clone')
            """,
            (user_id, provider, voice_id, display_label, target_model),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def delete_entry(entry_id: int, *, user_id: int = 1) -> bool:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM tts_voice_entries WHERE id = ? AND user_id = ? AND source = 'clone'",
            (entry_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_entry(entry_id: int, user_id: int = 1) -> dict[str, Any] | None:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM tts_voice_entries WHERE id = ? AND user_id = ?",
            (entry_id, user_id),
        )
        r = cur.fetchone()
        return dict(r) if r else None
    finally:
        conn.close()
