from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

# legacy registry import removed
import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from opentalking.core.session_store import (
    apply_flashtalk_recording_start,
    apply_flashtalk_recording_stop,
)
from opentalking.pipeline.recording.recording import export_flashtalk_recording
from opentalking.pipeline.session.runner import SessionRunner
from opentalking.runtime.task_consumer import consume_task_queue

runners: dict[str, SessionRunner] = {}


class OfferBody(BaseModel):
    sdp: str
    type: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    url = os.environ.get("OPENTALKING_REDIS_URL", "redis://localhost:6379/0")
    r = redis.from_url(url, decode_responses=True)
    app.state.redis = r
    avatars = Path(os.environ.get("OPENTALKING_AVATARS_DIR", "./examples/avatars")).resolve()
    app.state.avatars_root = avatars
    device = os.environ.get("OPENTALKING_TORCH_DEVICE", "cuda")
    app.state.device = device
    consumer = asyncio.create_task(consume_task_queue(r, avatars, device, runners))
    yield
    consumer.cancel()
    try:
        await consumer
    except asyncio.CancelledError:
        pass
    for s in list(runners.values()):
        await s.close()
    runners.clear()
    await r.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="OpenTalking Worker", lifespan=lifespan)

    @app.post("/webrtc/{session_id}/offer")
    async def webrtc_offer(session_id: str, body: OfferBody, request: Request) -> dict[str, str]:
        runner = runners.get(session_id)
        if not runner:
            raise HTTPException(status_code=404, detail="session not loaded on this worker")
        return await runner.handle_webrtc_offer(body.sdp, body.type)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/sessions/{session_id}/flashtalk-recording/start")
    async def flashtalk_recording_start(session_id: str, request: Request) -> dict[str, str]:
        r = request.app.state.redis
        await apply_flashtalk_recording_start(r, session_id)
        return {"session_id": session_id, "status": "recording"}

    @app.post("/sessions/{session_id}/flashtalk-recording/stop")
    async def flashtalk_recording_stop(session_id: str, request: Request) -> dict[str, str]:
        r = request.app.state.redis
        await apply_flashtalk_recording_stop(r, session_id)
        return {"session_id": session_id, "status": "stopped"}

    @app.get("/sessions/{session_id}/flashtalk-recording")
    async def download_flashtalk_recording(session_id: str) -> FileResponse:
        try:
            path = export_flashtalk_recording(session_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="recording not ready") from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=500,
                detail=f"recording export failed: {exc}",
            ) from exc
        return FileResponse(
            path,
            media_type="video/mp4",
            filename=f"{session_id}_flashtalk_capture.mp4",
        )

    return app
