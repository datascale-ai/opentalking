import json
import sqlite3
import hashlib
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import Request as FastAPIRequest
from fastapi.responses import JSONResponse

from server.config import ANALYTICS_DB_PATH, ANALYTICS_HASH_SALT, MAX_FIELD_LENGTH


def clamp_text(value, max_length=MAX_FIELD_LENGTH):
    if value is None:
        return ""

    return str(value).strip()[:max_length]


def init_analytics_db():
    ANALYTICS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(ANALYTICS_DB_PATH) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS analytics_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                event_name TEXT NOT NULL,
                path TEXT NOT NULL,
                language TEXT,
                page TEXT,
                case_slug TEXT,
                video_id TEXT,
                referrer TEXT,
                referrer_host TEXT,
                user_agent TEXT,
                ip_hash TEXT,
                screen TEXT
            )
            """
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_analytics_created_at ON analytics_events(created_at)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_analytics_event_name ON analytics_events(event_name)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_analytics_path ON analytics_events(path)")


def get_client_ip(request: FastAPIRequest):
    forwarded_for = request.headers.get("x-forwarded-for", "")

    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    return request.client.host if request.client else ""


def hash_ip(ip_address):
    if not ip_address:
        return ""

    return hashlib.sha256(f"{ANALYTICS_HASH_SALT}:{ip_address}".encode("utf-8")).hexdigest()[:16]


def normalize_referrer_host(referrer):
    if not referrer:
        return "Direct / Unknown"

    parsed = urlparse(referrer)

    return parsed.netloc or "Direct / Unknown"


def query_rows(query, params=()):
    init_analytics_db()

    with sqlite3.connect(ANALYTICS_DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(query, params).fetchall()]


def query_value(query, params=()):
    rows = query_rows(query, params)

    if not rows:
        return 0

    return next(iter(rows[0].values()))


async def record_analytics_event(request: FastAPIRequest):
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        payload = {}

    event_name = clamp_text(payload.get("eventName"), 80)

    if event_name not in {"page_view", "video_play"}:
        return JSONResponse({"ok": False}, status_code=202)

    if "referrer" in payload:
        referrer = clamp_text(payload.get("referrer"))
    else:
        referrer = clamp_text(request.headers.get("referer"))
    row = (
        datetime.now(timezone.utc).isoformat(),
        event_name,
        clamp_text(payload.get("path") or "/"),
        clamp_text(payload.get("language"), 12),
        clamp_text(payload.get("page"), 80),
        clamp_text(payload.get("caseSlug"), 120),
        clamp_text(payload.get("videoId"), 160),
        referrer,
        normalize_referrer_host(referrer),
        clamp_text(request.headers.get("user-agent"), 500),
        hash_ip(get_client_ip(request)),
        clamp_text(payload.get("screen"), 32),
    )

    init_analytics_db()

    with sqlite3.connect(ANALYTICS_DB_PATH) as connection:
        connection.execute(
            """
            INSERT INTO analytics_events (
                created_at,
                event_name,
                path,
                language,
                page,
                case_slug,
                video_id,
                referrer,
                referrer_host,
                user_agent,
                ip_hash,
                screen
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            row,
        )

    return JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})
