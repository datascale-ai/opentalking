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
from opentalking.core.config import get_settings
from opentalking.streaming.outputs import SessionOutputController

runners: dict[str, SessionRunner] = {}
output_controllers: dict[str, SessionOutputController] = {}


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
        controller = output_controllers.pop(getattr(s, "session_id", ""), None)
        if controller is not None:
            await controller.close()
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

    def _require_internal(request: Request) -> None:
        settings = get_settings()
        expected = str(
            getattr(settings, "streaming_internal_control_token", "")
            or getattr(settings, "streaming_control_token", "")
            or ""
        )
        provided = request.headers.get("authorization", "")
        token = provided[7:].strip() if provided.lower().startswith("bearer ") else ""
        if not expected or token != expected:
            raise HTTPException(status_code=401, detail="invalid worker authorization")

    async def _get_output_controller(session_id: str, request: Request) -> SessionOutputController:
        runner = runners.get(session_id)
        if runner is None:
            raise HTTPException(status_code=404, detail="session not loaded on this worker")
        existing = output_controllers.get(session_id)
        if existing is not None:
            return existing
        program = getattr(runner, "program", None)
        if program is None:
            raise HTTPException(status_code=409, detail="streaming program is not ready")
        controller = SessionOutputController(
            session_id=session_id,
            program=program,
            settings=get_settings(),
            redis=request.app.state.redis,
        )
        output_controllers[session_id] = controller
        runner.output_controller = controller
        return controller

    @app.post("/sessions/{session_id}/outputs")
    async def create_output(session_id: str, body: dict, request: Request) -> dict:
        _require_internal(request)
        controller = await _get_output_controller(session_id, request)
        try:
            record = await controller.create(body.get("body") or {}, idempotency_key=body.get("idempotency_key"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return record.public()

    @app.get("/sessions/{session_id}/outputs")
    async def list_outputs(session_id: str, request: Request) -> list[dict]:
        _require_internal(request)
        controller = await _get_output_controller(session_id, request)
        return controller.public()

    @app.get("/sessions/{session_id}/outputs/{output_id}")
    async def get_output(session_id: str, output_id: str, request: Request) -> dict:
        _require_internal(request)
        controller = await _get_output_controller(session_id, request)
        record = controller.get(output_id)
        if record is None:
            raise HTTPException(status_code=404, detail="output not found")
        return record.public()

    async def _mutate_output(session_id: str, output_id: str, request: Request, action: str) -> dict:
        _require_internal(request)
        controller = await _get_output_controller(session_id, request)
        try:
            record = await getattr(controller, action)(output_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="output not found") from exc
        return record.public()

    @app.post("/sessions/{session_id}/outputs/{output_id}/connect")
    async def connect_output(session_id: str, output_id: str, request: Request) -> dict:
        return await _mutate_output(session_id, output_id, request, "connect")

    @app.post("/sessions/{session_id}/outputs/{output_id}/disconnect")
    async def disconnect_output(session_id: str, output_id: str, request: Request) -> dict:
        return await _mutate_output(session_id, output_id, request, "disconnect")

    @app.post("/sessions/{session_id}/outputs/{output_id}/reconnect")
    async def reconnect_output(session_id: str, output_id: str, request: Request) -> dict:
        return await _mutate_output(session_id, output_id, request, "reconnect")

    @app.delete("/sessions/{session_id}/outputs/{output_id}")
    async def delete_output(session_id: str, output_id: str, request: Request) -> dict[str, str]:
        _require_internal(request)
        controller = await _get_output_controller(session_id, request)
        await controller.delete(output_id)
        return {"session_id": session_id, "output_id": output_id, "status": "deleted"}

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
