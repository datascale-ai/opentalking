from __future__ import annotations

import json

import redis.asyncio as redis
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from opentalking.core.redis_keys import events_channel

router = APIRouter(tags=["events"])


@router.get("/sessions/{session_id}/events")
async def session_events(session_id: str, request: Request) -> StreamingResponse:
    r: redis.Redis = request.app.state.redis
    exists = await r.exists(f"opentalking:session:{session_id}")
    if not exists:
        raise HTTPException(status_code=404, detail="session not found")

    async def gen():
        pubsub = r.pubsub()
        ch = events_channel(session_id)
        await pubsub.subscribe(ch)
        try:
            while True:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=30.0)
                if msg is None:
                    yield "event: ping\ndata: {}\n\n"
                    continue
                if msg.get("type") != "message":
                    continue
                raw = msg.get("data")
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                payload = json.loads(str(raw))
                ev = payload.get("event", "message")
                data = json.dumps(payload.get("data", {}), ensure_ascii=False)
                yield f"event: {ev}\ndata: {data}\n\n"
        finally:
            await pubsub.unsubscribe(ch)
            await pubsub.aclose()

    return StreamingResponse(gen(), media_type="text/event-stream")
