from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from opentalking.streaming.rtmps_jobs import RTMPSTargetConflict, ChunkedRTMPSJobManager
from opentalking.video_creation_jobs import VideoCreationJobManager

router = APIRouter(prefix="/streaming/rtmps-jobs", tags=["video-creation-rtmps"])


def _authorized(request: Request) -> None:
    settings = request.app.state.settings
    if not bool(getattr(settings, "streaming_enabled", False)):
        raise HTTPException(status_code=404, detail="streaming outputs are disabled")
    expected = str(getattr(settings, "streaming_control_token", "") or "")
    raw = request.headers.get("authorization", "")
    provided = raw[7:].strip() if raw.lower().startswith("bearer ") else ""
    bypass = bool(getattr(settings, "streaming_test_auth_bypass", False)) and bool(
        getattr(settings, "streaming_allow_local_targets", False)
    )
    if not (bypass and not provided) and (not expected or not hmac.compare_digest(expected, provided)):
        raise HTTPException(status_code=401, detail="invalid streaming authorization")


def _manager(request: Request) -> ChunkedRTMPSJobManager:
    manager = getattr(request.app.state, "rtmps_video_jobs", None)
    if manager is None:
        video_jobs = getattr(request.app.state, "video_creation_jobs", None)
        if video_jobs is None:
            video_jobs = VideoCreationJobManager(request.app.state.settings)
            request.app.state.video_creation_jobs = video_jobs
        manager = ChunkedRTMPSJobManager(request.app.state.settings, video_jobs)
        request.app.state.rtmps_video_jobs = manager
    return manager


@router.post("", status_code=202, response_model=None)
async def create_rtmps_job(body: dict[str, Any], request: Request) -> dict[str, Any]:
    _authorized(request)
    try:
        job = await _manager(request).create(body)
    except RTMPSTargetConflict as exc:
        raise HTTPException(status_code=409, detail=RTMPSTargetConflict.code) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="source video creation job not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"RTMPS job start failed: {type(exc).__name__}") from exc
    return _manager(request).public(job)


@router.get("/{job_id}", response_model=None)
async def get_rtmps_job(job_id: str, request: Request) -> dict[str, Any]:
    _authorized(request)
    job = _manager(request).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="RTMPS job not found")
    return _manager(request).public(job)


@router.post("/{job_id}/stop", status_code=202, response_model=None)
async def stop_rtmps_job(job_id: str, request: Request) -> dict[str, Any]:
    _authorized(request)
    try:
        job = await _manager(request).stop(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RTMPS job not found") from exc
    return _manager(request).public(job)


@router.post("/{job_id}/reconnect", status_code=202, response_model=None)
async def reconnect_rtmps_job(job_id: str, request: Request) -> dict[str, Any]:
    _authorized(request)
    try:
        job = await _manager(request).reconnect(job_id)
    except RTMPSTargetConflict as exc:
        raise HTTPException(status_code=409, detail=RTMPSTargetConflict.code) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RTMPS job not found") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"RTMPS reconnect failed: {type(exc).__name__}") from exc
    return _manager(request).public(job)


@router.delete("/{job_id}", status_code=204, response_model=None)
async def delete_rtmps_job(job_id: str, request: Request) -> Response:
    _authorized(request)
    try:
        await _manager(request).delete(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RTMPS job not found") from exc
    return Response(status_code=204)
