from __future__ import annotations

import asyncio
from pathlib import Path

import redis.asyncio as redis
from fastapi import APIRouter, HTTPException, Request

from opentalking.avatars.loader import load_avatar_bundle
from apps.api.schemas.session import (
    CreateSessionRequest,
    CreateSessionResponse,
    SpeakRequest,
    WebRTCOfferRequest,
)
from apps.api.services import session_service
from apps.api.services.worker_service import forward_webrtc_offer

router = APIRouter(prefix="/sessions", tags=["sessions"])

_VOICE_ROOT_FALLBACK = Path("./voice")


def _voice_root(settings) -> Path:
    reference = Path(settings.tts_clone_reference_audio).expanduser()
    if reference.parent != Path("."):
        return reference.parent.resolve()
    return _VOICE_ROOT_FALLBACK.resolve()


def _resolve_reference_audio(settings, value: str) -> Path:
    voice_root = _voice_root(settings)
    candidate = (voice_root / value).resolve()
    try:
        candidate.relative_to(voice_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="reference audio must stay under the voice directory") from exc
    if not candidate.is_file():
        raise HTTPException(status_code=400, detail=f"reference audio not found: {value}")
    return candidate


@router.post("", response_model=CreateSessionResponse)
async def create_session(body: CreateSessionRequest, request: Request) -> CreateSessionResponse:
    r: redis.Redis = request.app.state.redis
    settings = request.app.state.settings
    avatar_dir = Path(settings.avatars_dir).resolve() / body.avatar_id
    if not avatar_dir.is_dir():
        raise HTTPException(status_code=404, detail="avatar not found")
    try:
        bundle = load_avatar_bundle(avatar_dir, strict=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid avatar: {exc}") from exc
    if bundle.manifest.model_type != body.model:
        raise HTTPException(
            status_code=400,
            detail=(
                f"avatar '{body.avatar_id}' requires model '{bundle.manifest.model_type}', "
                f"got '{body.model}'"
            ),
        )
    if body.model == "flashtalk" and settings.normalized_flashtalk_mode == "off":
        raise HTTPException(
            status_code=400,
            detail=(
                "FlashTalk is disabled in this deployment. "
                "Use demo-wav2lip/wav2lip for the quickstart path, or switch "
                "OPENTALKING_FLASHTALK_MODE to remote/local."
            ),
        )
    tts_provider = (body.tts_provider or "").strip().lower() or None
    tts_voice = (body.tts_voice or "").strip() or None
    tts_reference_audio: str | None = None
    if tts_provider not in {None, "edge", "elevenlabs", "xtts", "cosyvoice", "auto"}:
        raise HTTPException(status_code=400, detail=f"unsupported tts provider: {body.tts_provider}")
    if tts_provider in {"xtts", "cosyvoice"}:
        if not body.tts_reference_audio:
            raise HTTPException(status_code=400, detail="reference audio is required for the selected TTS provider")
        tts_reference_audio = str(_resolve_reference_audio(settings, body.tts_reference_audio))
    elif body.tts_reference_audio:
        tts_reference_audio = str(_resolve_reference_audio(settings, body.tts_reference_audio))

    sid = await session_service.create_session(
        r,
        avatar_id=body.avatar_id,
        model=body.model,
        tts_provider=tts_provider,
        tts_voice=tts_voice,
        tts_reference_audio=tts_reference_audio,
    )
    # Single-process mode: WebRTC offer runs immediately after; wait until init task
    # has created the SessionRunner (avoids 404 "session not loaded").
    runners = getattr(request.app.state, "session_runners", None)
    if runners is not None:
        # FlashTalk sessions: prepare() waits for WS init to complete on the
        # server side. Keep a generous safety margin for model warmup/cache work.
        max_wait = 3600  # 90 seconds
        for _ in range(max_wait):
            runner = runners.get(sid)
            ready_event = getattr(runner, "ready_event", None) if runner is not None else None
            if runner is not None and (ready_event is None or ready_event.is_set()):
                break
            await asyncio.sleep(0.025)
        else:
            raise HTTPException(
                status_code=503,
                detail="Session worker did not become ready in time (check avatar/model match and logs).",
            )
    return CreateSessionResponse(session_id=sid, status="created")


@router.get("/{session_id}")
async def get_session(session_id: str, request: Request) -> dict[str, str]:
    r: redis.Redis = request.app.state.redis
    s = await session_service.get_session(r, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    return s


@router.post("/{session_id}/start")
async def start_session(session_id: str, request: Request) -> dict[str, str]:
    """Optional hook: worker loads on create; this marks ready when client connects."""
    r: redis.Redis = request.app.state.redis
    s = await session_service.get_session(r, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    await session_service.update_session_state(r, session_id, "ready")
    return {"session_id": session_id, "status": "ready"}


@router.post("/{session_id}/speak")
async def speak(session_id: str, body: SpeakRequest, request: Request) -> dict[str, str]:
    r: redis.Redis = request.app.state.redis
    s = await session_service.get_session(r, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    await session_service.speak(r, session_id, body.text)
    return {"session_id": session_id, "status": "queued"}


@router.post("/{session_id}/interrupt")
async def interrupt(session_id: str, request: Request) -> dict[str, str]:
    r: redis.Redis = request.app.state.redis
    s = await session_service.get_session(r, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    await session_service.interrupt(r, session_id)
    return {"session_id": session_id, "status": "interrupted"}


@router.delete("/{session_id}")
async def delete_session(session_id: str, request: Request) -> dict[str, str]:
    r: redis.Redis = request.app.state.redis
    s = await session_service.get_session(r, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    await session_service.close_session(r, session_id)
    return {"session_id": session_id, "status": "closed"}


@router.post("/{session_id}/webrtc/offer")
async def webrtc_offer(
    session_id: str,
    body: WebRTCOfferRequest,
    request: Request,
) -> dict[str, str]:
    r: redis.Redis = request.app.state.redis
    s = await session_service.get_session(r, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    runners = getattr(request.app.state, "session_runners", None)
    if runners is not None:
        runner = runners.get(session_id)
        if not runner:
            raise HTTPException(
                status_code=404,
                detail="session not loaded (worker not ready yet?)",
            )
        return await runner.handle_webrtc_offer(body.sdp, body.type)
    settings = request.app.state.settings
    try:
        ans = await forward_webrtc_offer(
            settings.worker_url,
            session_id,
            body.sdp,
            body.type,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"worker error: {e}") from e
    return ans
