from __future__ import annotations

import asyncio
import hmac
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

# legacy registry import removed
import redis.asyncio as redis
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, Response
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
from opentalking.core.redis_keys import streaming_output_index_key

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
    app.state.worker_boot_id = uuid.uuid4().hex
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
        expected = str(getattr(settings, "streaming_internal_control_token", "") or "")
        provided = request.headers.get("authorization", "")
        token = provided[7:].strip() if provided.lower().startswith("bearer ") else ""
        bypass = bool(getattr(settings, "streaming_test_auth_bypass", False)) and bool(
            getattr(settings, "streaming_allow_local_targets", False)
        )
        if not (bypass and not token) and (not expected or not hmac.compare_digest(expected, token)):
            raise HTTPException(status_code=401, detail="invalid worker authorization")

    async def _get_output_controller(session_id: str, request: Request) -> SessionOutputController:
        runner = runners.get(session_id)
        existing = output_controllers.get(session_id)
        if existing is not None and runner is not None and getattr(existing, "program", None) is not None:
            return existing
        if runner is None:
            index = await request.app.state.redis.hgetall(streaming_output_index_key(session_id))
            if not index:
                raise HTTPException(status_code=404, detail="session not loaded on this worker")
            controller = SessionOutputController(
                session_id=session_id,
                program=None,
                settings=get_settings(),
                redis=request.app.state.redis,
                worker_boot_id=getattr(request.app.state, "worker_boot_id", None),
                allow_snapshot_only=True,
            )
            await controller.load_stale_state()
            output_controllers[session_id] = controller
            return controller
        if existing is not None:
            output_controllers.pop(session_id, None)
        program = getattr(runner, "program", None)
        if program is None:
            raise HTTPException(status_code=409, detail="streaming program is not ready")
        controller = SessionOutputController(
            session_id=session_id,
            program=program,
            settings=get_settings(),
            redis=request.app.state.redis,
            worker_boot_id=getattr(request.app.state, "worker_boot_id", None),
        )
        output_controllers[session_id] = controller
        runner.output_controller = controller
        await controller.load_stale_state()
        return controller

    @app.post("/sessions/{session_id}/outputs", status_code=201)
    async def create_output(
        session_id: str,
        body: dict,
        request: Request,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict:
        _require_internal(request)
        controller = await _get_output_controller(session_id, request)
        if getattr(controller, "program", None) is None:
            raise HTTPException(status_code=409, detail="streaming program is not ready")
        try:
            record = await controller.create(
                body.get("body") or {},
                idempotency_key=idempotency_key or body.get("idempotency_key"),
            )
        except ValueError as exc:
            status = 409 if "Idempotency-Key" in str(exc) else 400
            raise HTTPException(status_code=status, detail=str(exc)) from exc
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

    async def _mutate_output(
        session_id: str,
        output_id: str,
        request: Request,
        action: str,
        idempotency_key: str | None = None,
    ) -> dict:
        _require_internal(request)
        controller = await _get_output_controller(session_id, request)
        if getattr(controller, "program", None) is None and action != "delete":
            raise HTTPException(status_code=409, detail="stale_worker_state")
        try:
            if idempotency_key and await controller.reserve_action_idempotency(output_id, action, idempotency_key):
                existing = controller.get(output_id)
                if existing is None:
                    raise KeyError(output_id)
                return existing.public()
            if action == "connect":
                record = controller.request_connect(output_id)
            elif action == "disconnect":
                record = controller.request_disconnect(output_id)
            elif action == "reconnect":
                record = controller.request_reconnect(output_id)
            else:
                record = await getattr(controller, action)(output_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="output not found") from exc
        except ValueError as exc:
            status = 409 if "Idempotency-Key" in str(exc) else 400
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        return record.public()

    @app.post("/sessions/{session_id}/outputs/{output_id}/connect", status_code=202)
    async def connect_output(
        session_id: str,
        output_id: str,
        request: Request,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict:
        return await _mutate_output(session_id, output_id, request, "connect", idempotency_key)

    @app.post("/sessions/{session_id}/outputs/{output_id}/disconnect", status_code=202)
    async def disconnect_output(
        session_id: str,
        output_id: str,
        request: Request,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict:
        return await _mutate_output(session_id, output_id, request, "disconnect", idempotency_key)

    @app.post("/sessions/{session_id}/outputs/{output_id}/reconnect", status_code=202)
    async def reconnect_output(
        session_id: str,
        output_id: str,
        request: Request,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict:
        return await _mutate_output(session_id, output_id, request, "reconnect", idempotency_key)

    @app.delete("/sessions/{session_id}/outputs/{output_id}", status_code=204, response_model=None)
    async def delete_output(
        session_id: str,
        output_id: str,
        request: Request,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> Response:
        _require_internal(request)
        controller = await _get_output_controller(session_id, request)
        try:
            await controller.delete(output_id, idempotency_key=idempotency_key)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return Response(status_code=204)

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
