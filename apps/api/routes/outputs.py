from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, Response

from apps.api.services import session_service
from apps.api.services.worker_service import forward_worker_json
from apps.api.schemas.session import SessionOutputRequest
from opentalking.streaming.outputs import SessionOutputController
from opentalking.core.redis_keys import streaming_output_index_key

router = APIRouter(prefix="/sessions", tags=["session-outputs"])


def _worker_token(request: Request) -> str:
    settings = request.app.state.settings
    return str(getattr(settings, "streaming_internal_control_token", "") or "")


def _authorized(request: Request) -> None:
    settings = request.app.state.settings
    if not bool(getattr(settings, "streaming_enabled", False)):
        raise HTTPException(status_code=404, detail="streaming outputs are disabled")
    expected = str(getattr(settings, "streaming_control_token", "") or "")
    auth = request.headers.get("authorization", "")
    provided = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    bypass = bool(getattr(settings, "streaming_test_auth_bypass", False)) and bool(
        getattr(settings, "streaming_allow_local_targets", False)
    )
    if not (bypass and not provided) and (not expected or not hmac.compare_digest(expected, provided)):
        raise HTTPException(status_code=401, detail="invalid streaming authorization")


async def _controller(request: Request, session_id: str) -> SessionOutputController:
    runners = getattr(request.app.state, "session_runners", None)
    runner = runners.get(session_id) if isinstance(runners, dict) else None
    if runner is None:
        # A restarted worker may still have a short-lived, secret-free
        # snapshot. Expose it as stale/failed for GET and DELETE; creation or
        # reconnect remains rejected until a new ready runner receives the
        # secret-bearing create request.
        redis = getattr(request.app.state, "redis", None)
        if redis is not None:
            index = await redis.hgetall(streaming_output_index_key(session_id))
            if index:
                controller = SessionOutputController(
                    session_id=session_id,
                    program=None,
                    settings=request.app.state.settings,
                    redis=redis,
                    worker_boot_id=getattr(request.app.state, "worker_boot_id", None),
                    allow_snapshot_only=True,
                )
                await controller.load_stale_state()
                if controller.public():
                    return controller
        raise LookupError("runner")
    existing = getattr(runner, "output_controller", None)
    if existing is not None:
        return existing
    program = getattr(runner, "program", None)
    if program is None:
        raise RuntimeError("streaming program is not ready")
    controller = SessionOutputController(
        session_id=session_id,
        program=program,
        settings=request.app.state.settings,
        redis=request.app.state.redis,
        worker_boot_id=getattr(request.app.state, "worker_boot_id", None),
    )
    runner.output_controller = controller
    await controller.load_stale_state()
    return controller


async def _session_exists(request: Request, session_id: str) -> None:
    record = await session_service.get_session(request.app.state.redis, session_id)
    if not record:
        raise HTTPException(status_code=404, detail="session not found")


async def _split_or_unified(
    request: Request,
    session_id: str,
    *,
    path: str,
    payload: dict[str, Any] | None = None,
    method: str = "POST",
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    try:
        controller = await _controller(request, session_id)
    except LookupError:
        settings = request.app.state.settings
        try:
            return await forward_worker_json(
                settings.worker_url,
                path,
                payload or {},
                internal_token=_worker_token(request),
                method=method,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"worker output control failed: {type(exc).__name__}") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"_controller": controller}  # internal sentinel; callers handle it


async def _ensure_session_runner_ready(request: Request, session_id: str) -> None:
    """Reject output creation before the Program is ready.

    `auto_connect` is a lifecycle preference, not permission to attach a
    publisher to a half-created runner.  Unified can inspect the in-memory
    runner directly; split mode relies on the worker route to return the same
    409 until its runner has a Program.
    """
    runners = getattr(request.app.state, "session_runners", None)
    runner = runners.get(session_id) if isinstance(runners, dict) else None
    if runner is None:
        return
    ready = getattr(runner, "ready_event", None)
    if ready is not None and not ready.is_set():
        raise HTTPException(status_code=409, detail="session runner is not ready")
    if getattr(runner, "program", None) is None:
        raise HTTPException(status_code=409, detail="streaming program is not ready")


def _public(record: Any) -> dict[str, Any]:
    return record.public()


@router.post("/{session_id}/outputs", status_code=201)
async def create_output(
    session_id: str,
    body: SessionOutputRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    _authorized(request)
    await _session_exists(request, session_id)
    await _ensure_session_runner_ready(request, session_id)
    result = await _split_or_unified(
        request,
        session_id,
        path=f"/sessions/{session_id}/outputs",
        payload={"body": body.model_dump(exclude_none=True)},
        idempotency_key=idempotency_key,
    )
    if "_controller" not in result:
        return result
    if getattr(result["_controller"], "program", None) is None:
        raise HTTPException(status_code=409, detail="streaming program is not ready")
    try:
        record = await result["_controller"].create(body.model_dump(exclude_none=True), idempotency_key=idempotency_key)
    except (ValueError, RuntimeError) as exc:
        status = 409 if "Idempotency-Key" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return _public(record)


@router.get("/{session_id}/outputs")
async def list_outputs(session_id: str, request: Request) -> list[dict[str, Any]]:
    _authorized(request)
    await _session_exists(request, session_id)
    try:
        result = await _controller(request, session_id)
    except LookupError:
        settings = request.app.state.settings
        return await forward_worker_json(
            settings.worker_url,
            f"/sessions/{session_id}/outputs",
            {},
            internal_token=_worker_token(request),
            method="GET",
        )  # type: ignore[return-value]
    except RuntimeError:
        return []
    return result.public()


@router.get("/{session_id}/outputs/{output_id}")
async def get_output(session_id: str, output_id: str, request: Request) -> dict[str, Any]:
    _authorized(request)
    await _session_exists(request, session_id)
    try:
        controller = await _controller(request, session_id)
    except LookupError:
        settings = request.app.state.settings
        return await forward_worker_json(
            settings.worker_url,
            f"/sessions/{session_id}/outputs/{output_id}",
            {},
            internal_token=_worker_token(request),
            method="GET",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record = controller.get(output_id)
    if record is None:
        raise HTTPException(status_code=404, detail="output not found")
    return _public(record)


async def _mutate_output(
    session_id: str,
    output_id: str,
    request: Request,
    action: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    _authorized(request)
    await _session_exists(request, session_id)
    try:
        controller = await _controller(request, session_id)
    except LookupError:
        settings = request.app.state.settings
        return await forward_worker_json(
            settings.worker_url,
            f"/sessions/{session_id}/outputs/{output_id}/{action}",
            {},
            internal_token=_worker_token(request),
            idempotency_key=idempotency_key,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if getattr(controller, "program", None) is None and action != "delete":
        raise HTTPException(status_code=409, detail="stale_worker_state")
    try:
        if idempotency_key and await controller.reserve_action_idempotency(output_id, action, idempotency_key):
            existing = controller.get(output_id)
            if existing is None:
                raise KeyError(output_id)
            return _public(existing)
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
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"output {action} failed: {type(exc).__name__}") from exc
    return _public(record)


@router.post("/{session_id}/outputs/{output_id}/connect", status_code=202)
async def connect_output(
    session_id: str,
    output_id: str,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    return await _mutate_output(session_id, output_id, request, "connect", idempotency_key)


@router.post("/{session_id}/outputs/{output_id}/disconnect", status_code=202)
async def disconnect_output(
    session_id: str,
    output_id: str,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    return await _mutate_output(session_id, output_id, request, "disconnect", idempotency_key)


@router.post("/{session_id}/outputs/{output_id}/reconnect", status_code=202)
async def reconnect_output(
    session_id: str,
    output_id: str,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    return await _mutate_output(session_id, output_id, request, "reconnect", idempotency_key)


@router.delete("/{session_id}/outputs/{output_id}", status_code=204, response_model=None)
async def delete_output(
    session_id: str,
    output_id: str,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Response:
    _authorized(request)
    await _session_exists(request, session_id)
    try:
        controller = await _controller(request, session_id)
    except LookupError:
        settings = request.app.state.settings
        await forward_worker_json(
            settings.worker_url,
            f"/sessions/{session_id}/outputs/{output_id}",
            {},
            internal_token=_worker_token(request),
            method="DELETE",
            idempotency_key=idempotency_key,
        )
        return Response(status_code=204)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        await controller.delete(output_id, idempotency_key=idempotency_key)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=204)
