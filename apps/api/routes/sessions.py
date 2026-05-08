from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
import queue as sync_queue
import tempfile
import time
import uuid
from collections.abc import Awaitable
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
import redis.asyncio as redis
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response, StreamingResponse

from opentalking.avatars.loader import load_avatar_bundle
from apps.api.schemas.session import (
    ChatRequest,
    CreateSessionRequest,
    CreateSessionResponse,
    SpeakRequest,
    WebRTCOfferRequest,
)
from apps.api.services import session_service
from apps.api.services.worker_service import forward_webrtc_offer, forward_worker_post_empty
from apps.api.core.config import get_settings
from opentalking.core.queue_status import get_flashtalk_queue_status
from opentalking.core.redis_keys import offline_bundle_job_key
from opentalking.core.session_store import (
    apply_flashtalk_recording_start,
    apply_flashtalk_recording_stop,
)
from opentalking.stt.dashscope_asr import (
    decode_audio_file_to_pcm_i16,
    transcribe_audio_file_path,
    transcribe_pcm_chunk_queue_sync,
)
from opentalking.tts.edge_zh_voices import normalize_optional_edge_voice
from opentalking.tts.providers import BAILIAN_TTS_PROVIDERS, normalize_tts_provider
from opentalking.tts.qwen_tts_voices import normalize_optional_qwen_voice, sanitize_qwen_model
from opentalking.worker.flashtalk_recording import (
    export_flashtalk_recording,
    flashtalk_recording_session_dir,
)


def _effective_tts_provider(requested: str | None) -> str:
    r = (requested or "").strip().lower()
    if r:
        return r
    try:
        return get_settings().tts_provider.strip().lower()
    except Exception:
        return "edge"


_BAILIAN_TTS = BAILIAN_TTS_PROVIDERS


def _is_flashtalk_compatible_model(model: str | None) -> bool:
    return (model or "").strip().lower() in {"flashtalk", "flashhead"}


async def _await_result(value: Awaitable[Any] | Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _normalize_voice_for_speak(
    *,
    voice: str | None,
    tts_provider: str | None,
    tts_model: str | None,
) -> tuple[str | None, str, str | None]:
    """返回 (voice, 生效的 tts_provider, tts_model)。tts_model 仅百炼分支有值。"""
    eff = _effective_tts_provider(tts_provider)
    try:
        if eff in _BAILIAN_TTS:
            vn = normalize_optional_qwen_voice(voice)
            tm = sanitize_qwen_model(tts_model)
            return vn, eff, tm
        if eff == "elevenlabs":
            vn = str(voice).strip() if voice else None
            tm = str(tts_model).strip() if tts_model and str(tts_model).strip() else None
            return vn, eff, tm
        vn = normalize_optional_edge_voice(voice)
        if tts_model and str(tts_model).strip():
            raise HTTPException(
                status_code=400,
                detail="tts_model is only valid when using 百炼语音线路（tts_provider=dashscope、cosyvoice、sambert 等）",
            )
        return vn, eff, None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


log = logging.getLogger(__name__)


async def _stream_worker_flashtalk_recording(
    *,
    worker_url: str,
    session_id: str,
) -> StreamingResponse:
    base = worker_url.rstrip("/")
    url = f"{base}/sessions/{session_id}/flashtalk-recording"
    timeout = httpx.Timeout(120.0, connect=10.0)
    client = httpx.AsyncClient(timeout=timeout)
    stream_cm = client.stream("GET", url)

    try:
        r = await stream_cm.__aenter__()
    except httpx.RequestError as exc:
        await client.aclose()
        raise HTTPException(
            status_code=502,
            detail=f"worker recording download unreachable: {exc}",
        ) from exc

    if r.status_code != 200:
        text = (await r.aread()).decode("utf-8", errors="replace")
        await stream_cm.__aexit__(None, None, None)
        await client.aclose()
        if r.status_code == 404:
            raise HTTPException(status_code=404, detail="recording not ready")
        raise HTTPException(
            status_code=502,
            detail=(
                "worker recording download failed "
                f"({r.status_code}): {text[:500]}"
            ),
        )

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in r.aiter_bytes():
                if chunk:
                    yield chunk
        finally:
            await stream_cm.__aexit__(None, None, None)
            await client.aclose()

    return StreamingResponse(
        body(),
        media_type="video/mp4",
        headers={
            "Content-Disposition": f'attachment; filename="{session_id}_flashtalk_capture.mp4"'
        },
    )


router = APIRouter(prefix="/sessions", tags=["sessions"])


async def _flashtalk_disk_recording_control(
    session_id: str,
    request: Request,
    *,
    stop: bool,
) -> dict[str, str]:
    r: redis.Redis = request.app.state.redis
    s = await session_service.get_session(r, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    if not _is_flashtalk_compatible_model(s.get("model")):
        raise HTTPException(
            status_code=400,
            detail="FlashTalk 兼容录制仅支持 flashtalk/flashhead 模型会话",
        )
    status = "stopped" if stop else "recording"

    runners = getattr(request.app.state, "session_runners", None)
    if runners is not None:
        # Unified / 多 uvicorn worker：录制开关写在共享 Redis，避免请求落到「未加载 runner」的进程时 404
        if stop:
            await apply_flashtalk_recording_stop(r, session_id)
        else:
            await apply_flashtalk_recording_start(r, session_id)
        return {"session_id": session_id, "status": status}

    settings = request.app.state.settings
    path = (
        f"/sessions/{session_id}/flashtalk-recording/stop"
        if stop
        else f"/sessions/{session_id}/flashtalk-recording/start"
    )
    try:
        data = await forward_worker_post_empty(settings.worker_url, path)
        if isinstance(data, dict) and data.get("session_id") == session_id:
            return data  # type: ignore[return-value]
        return {"session_id": session_id, "status": status}
    except httpx.HTTPStatusError as e:
        detail = (e.response.text or str(e))[:800]
        raise HTTPException(status_code=e.response.status_code, detail=detail) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"worker error: {e}") from e

_MAX_AUDIO_BYTES = 15 * 1024 * 1024


def _session_customizations(request: Request) -> dict[str, dict[str, str]]:
    custom = getattr(request.app.state, "session_customizations", None)
    if custom is None:
        custom = {}
        request.app.state.session_customizations = custom
    return custom


def _resolve_avatar_dir(settings: object, avatar_id: str) -> tuple[Path, Path]:
    avatars_root = Path(getattr(settings, "avatars_dir")).resolve()
    avatar_dir = (avatars_root / avatar_id).resolve()
    try:
        avatar_dir.relative_to(avatars_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid avatar_id") from exc
    return avatars_root, avatar_dir


async def _wait_for_session_worker_ready(
    r: redis.Redis,
    session_id: str,
    *,
    max_wait_sec: float,
    poll_interval: float = 0.1,
) -> bool:
    deadline = time.monotonic() + max(0.0, max_wait_sec)
    while time.monotonic() < deadline:
        rec = await session_service.get_session(r, session_id)
        state = (rec or {}).get("state")
        if state in {"worker_ready", "ready", "speaking"}:
            return True
        if state == "error":
            raise HTTPException(status_code=503, detail="Session worker failed to initialize.")
        await asyncio.sleep(poll_interval)
    return False


@router.post("", response_model=CreateSessionResponse)
async def create_session(body: CreateSessionRequest, request: Request) -> CreateSessionResponse:
    r: redis.Redis = request.app.state.redis
    settings = request.app.state.settings
    _, avatar_dir = _resolve_avatar_dir(settings, body.avatar_id)
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
                "Use demo-avatar/wav2lip for the quickstart path, or switch "
                "OPENTALKING_FLASHTALK_MODE to remote/local."
            ),
        )
    try:
        tts_provider = normalize_tts_provider(body.tts_provider, default=None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    tts_voice = (body.tts_voice or "").strip() or None

    custom = _session_customizations(request).get(body.avatar_id, {})
    llm_system_prompt = (body.llm_system_prompt or "").strip() or custom.get("llm_system_prompt")
    custom_ref_image_path = custom.get("custom_ref_image_path")
    if custom_ref_image_path and not Path(custom_ref_image_path).exists():
        custom_ref_image_path = None

    sid = await session_service.create_session(
        r,
        avatar_id=body.avatar_id,
        model=body.model,
        tts_provider=tts_provider,
        tts_voice=tts_voice,
        llm_system_prompt=llm_system_prompt,
        custom_ref_image_path=custom_ref_image_path,
    )
    # Single-process mode: WebRTC offer runs immediately after; wait until init task
    # has created the SessionRunner (avoids 404 "session not loaded").
    is_flashtalk = _is_flashtalk_compatible_model(body.model)
    runners = getattr(request.app.state, "session_runners", None)
    if runners is not None:
        settings = request.app.state.settings

        if is_flashtalk:
            from opentalking.worker.task_consumer import slot_is_occupied
            if slot_is_occupied():
                # Slot busy: return immediately, client waits via SSE session.queued
                return CreateSessionResponse(session_id=sid, status="queued")
            else:
                # Slot free: wait for runner to be ready (fast path, ~1-2s)
                max_wait_sec = 30
                poll_interval = 0.1
                elapsed = 0.0
                while elapsed < max_wait_sec:
                    runner = runners.get(sid)
                    ready_event = getattr(runner, "ready_event", None) if runner is not None else None
                    if runner is not None and (ready_event is None or ready_event.is_set()):
                        break
                    await asyncio.sleep(poll_interval)
                    elapsed += poll_interval
                else:
                    raise HTTPException(status_code=503, detail="FlashTalk init timed out.")
                return CreateSessionResponse(session_id=sid, status="created")

        if body.model == "quicktalk":
            return CreateSessionResponse(session_id=sid, status="initializing")

        # Non-FlashTalk: wait synchronously until runner is ready (fast, local model).
        max_wait_sec = 90
        poll_interval = 0.025
        elapsed = 0.0
        while elapsed < max_wait_sec:
            runner = runners.get(sid)
            ready_event = getattr(runner, "ready_event", None) if runner is not None else None
            if runner is not None and (ready_event is None or ready_event.is_set()):
                break
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        else:
            raise HTTPException(
                status_code=503,
                detail="Session worker did not become ready in time.",
            )
    elif is_flashtalk:
        qs = await get_flashtalk_queue_status(r)
        if qs["slot_occupied"] or qs["queue_size"] > 0:
            return CreateSessionResponse(session_id=sid, status="queued")
        if await _wait_for_session_worker_ready(r, sid, max_wait_sec=3.0):
            return CreateSessionResponse(session_id=sid, status="created")
        return CreateSessionResponse(session_id=sid, status="queued")
    return CreateSessionResponse(session_id=sid, status="created")


@router.post("/customize")
async def customize_session(
    request: Request,
    avatar_id: str = Form(...),
    llm_system_prompt: str | None = Form(default=None),
    reference_image: UploadFile | None = File(default=None),
) -> dict[str, str | bool]:
    settings = request.app.state.settings
    _, avatar_dir = _resolve_avatar_dir(settings, avatar_id)
    if not avatar_dir.is_dir():
        raise HTTPException(status_code=404, detail="avatar not found")

    custom = _session_customizations(request)
    entry = dict(custom.get(avatar_id, {}))

    if llm_system_prompt is not None:
        entry["llm_system_prompt"] = llm_system_prompt.strip()

    updated_image = False
    if reference_image is not None:
        raw = await reference_image.read()
        if not raw:
            raise HTTPException(status_code=400, detail="empty image")
        if len(raw) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="image too large (max 10MB)")

        suffix = Path(reference_image.filename or "").suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            suffix = ".png"
        target = avatar_dir / f"reference_custom{suffix}"
        target.write_bytes(raw)
        entry["custom_ref_image_path"] = str(target)
        updated_image = True

    custom[avatar_id] = entry
    return {
        "avatar_id": avatar_id,
        "saved": True,
        "image_updated": updated_image,
    }


@router.post("/customize/prompt")
async def customize_prompt(
    request: Request,
    body: dict[str, str],
) -> dict[str, str | bool]:
    avatar_id = (body.get("avatar_id") or "").strip()
    if not avatar_id:
        raise HTTPException(status_code=400, detail="avatar_id is required")
    llm_system_prompt = (body.get("llm_system_prompt") or "").strip()
    settings = request.app.state.settings
    _, avatar_dir = _resolve_avatar_dir(settings, avatar_id)
    if not avatar_dir.is_dir():
        raise HTTPException(status_code=404, detail="avatar not found")

    custom = _session_customizations(request)
    entry = dict(custom.get(avatar_id, {}))
    entry["llm_system_prompt"] = llm_system_prompt
    custom[avatar_id] = entry
    return {
        "avatar_id": avatar_id,
        "saved": True,
    }


@router.post("/customize/reference")
async def customize_reference(
    request: Request,
    avatar_id: str = Form(...),
    reference_image: UploadFile = File(...),
) -> dict[str, str | bool]:
    settings = request.app.state.settings
    _, avatar_dir = _resolve_avatar_dir(settings, avatar_id)
    if not avatar_dir.is_dir():
        raise HTTPException(status_code=404, detail="avatar not found")

    raw = await reference_image.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty image")
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="image too large (max 10MB)")

    suffix = Path(reference_image.filename or "").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        suffix = ".png"
    target = avatar_dir / f"reference_custom{suffix}"
    target.write_bytes(raw)

    custom = _session_customizations(request)
    entry = dict(custom.get(avatar_id, {}))
    entry["custom_ref_image_path"] = str(target)
    custom[avatar_id] = entry
    return {
        "avatar_id": avatar_id,
        "saved": True,
        "image_updated": True,
    }


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
    voice, eff_prov, tm = _normalize_voice_for_speak(
        voice=body.voice,
        tts_provider=body.tts_provider,
        tts_model=body.tts_model,
    )
    await session_service.speak(
        r,
        session_id,
        body.text,
        voice=voice,
        tts_provider=eff_prov,
        tts_model=tm,
    )
    return {"session_id": session_id, "status": "queued"}


@router.post("/{session_id}/chat")
async def chat(session_id: str, body: ChatRequest, request: Request) -> dict[str, str]:
    """LLM 流式 → 句级 TTS → 数字人渲染。当前仅 quicktalk 已对接。"""
    r: redis.Redis = request.app.state.redis
    s = await session_service.get_session(r, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    model = (s.get("model") or "").strip()
    if model != "quicktalk":
        raise HTTPException(
            status_code=400,
            detail=f"/chat 仅支持 quicktalk 会话，当前 model={model or 'unknown'}",
        )
    prompt = (body.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is empty")
    voice, eff_prov, tm = _normalize_voice_for_speak(
        voice=body.voice,
        tts_provider=body.tts_provider,
        tts_model=body.tts_model,
    )
    await session_service.chat(
        r,
        session_id,
        prompt,
        voice=voice,
        tts_provider=eff_prov,
        tts_model=tm,
    )
    return {"session_id": session_id, "status": "queued"}


@router.post("/{session_id}/transcribe")
async def transcribe(
    session_id: str,
    request: Request,
    file: UploadFile = File(...),
) -> dict[str, str]:
    """上传短音频 → 百炼 DashScope ASR → 返回识别文本（不触发数字人播报）。"""
    r: redis.Redis = request.app.state.redis
    s = await session_service.get_session(r, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")

    body = await file.read()
    if len(body) > _MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="audio too large (max 15MB)")
    if not body:
        raise HTTPException(status_code=400, detail="empty audio")

    suffix = Path(file.filename or "speech.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(body)
        upload_path = Path(tmp.name)

    try:
        text = await transcribe_audio_file_path(upload_path)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        log.exception("transcribe failed")
        raise HTTPException(status_code=502, detail=f"stt error: {e}") from e
    finally:
        try:
            upload_path.unlink(missing_ok=True)
        except OSError:
            pass

    return {"session_id": session_id, "text": text.strip()}


@router.post("/{session_id}/speak_audio")
async def speak_audio(
    session_id: str,
    request: Request,
    file: UploadFile = File(...),
    voice: str | None = Form(default=None),
    tts_provider: str | None = Form(default=None),
    tts_model: str | None = Form(default=None),
) -> dict[str, str]:
    """上传语音 → 百炼 ASR → 将识别文本送入与会话相同的 speak 流水线（LLM→TTS→FlashTalk）。"""
    r: redis.Redis = request.app.state.redis
    s = await session_service.get_session(r, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")

    body = await file.read()
    if len(body) > _MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="audio too large (max 15MB)")
    if not body:
        raise HTTPException(status_code=400, detail="empty audio")

    suffix = Path(file.filename or "speech.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(body)
        upload_path = Path(tmp.name)

    try:
        text = await transcribe_audio_file_path(upload_path)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        log.exception("speak_audio stt failed")
        raise HTTPException(status_code=502, detail=f"stt error: {e}") from e
    finally:
        try:
            upload_path.unlink(missing_ok=True)
        except OSError:
            pass

    stripped = text.strip()
    if not stripped:
        raise HTTPException(status_code=400, detail="未能识别有效语音，请重试。")

    v, eff_prov, tm = _normalize_voice_for_speak(
        voice=voice,
        tts_provider=tts_provider,
        tts_model=tts_model,
    )
    await session_service.speak(
        r,
        session_id,
        stripped,
        voice=v,
        tts_provider=eff_prov,
        tts_model=tm,
    )
    return {"session_id": session_id, "status": "queued", "text": stripped}


@router.post("/{session_id}/speak_flashtalk_audio")
async def speak_flashtalk_audio(
    session_id: str,
    request: Request,
    file: UploadFile = File(...),
) -> dict[str, str]:
    """上传音频 → 解码为 16kHz mono PCM → 直接驱动 FlashTalk（不经语音识别、LLM、TTS）。

    要求会话 ``model`` 为 ``flashtalk`` 或 ``flashhead``；``pcm_path`` 写入本机临时目录，需与 Worker 共享文件系统。
    """
    r: redis.Redis = request.app.state.redis
    s = await session_service.get_session(r, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    if not _is_flashtalk_compatible_model(s.get("model")):
        raise HTTPException(
            status_code=400,
            detail="仅 flashtalk/flashhead 会话可使用本接口（上传音频直驱口型）",
        )

    body = await file.read()
    if len(body) > _MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="audio too large (max 15MB)")
    if not body:
        raise HTTPException(status_code=400, detail="empty audio")

    suffix = Path(file.filename or "speech.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(body)
        upload_path = Path(tmp.name)

    try:
        pcm = await decode_audio_file_to_pcm_i16(upload_path)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        log.exception("speak_flashtalk_audio decode failed")
        raise HTTPException(status_code=502, detail=f"audio decode error: {e}") from e
    finally:
        try:
            upload_path.unlink(missing_ok=True)
        except OSError:
            pass

    if pcm.size == 0:
        raise HTTPException(status_code=400, detail="解码后音频为空")

    await session_service.speak_flashtalk_uploaded_pcm(r, session_id, pcm.tobytes())
    return {"session_id": session_id, "status": "queued"}


@router.websocket("/{session_id}/speak_audio_stream")
async def speak_audio_stream_ws(websocket: WebSocket, session_id: str) -> None:
    """浏览器经 WebSocket 推送 PCM s16le mono 16kHz 分块 → DashScope 流式 ASR → speak 流水线。"""
    await websocket.accept()
    try:
        r: redis.Redis = websocket.app.state.redis  # type: ignore[attr-defined]
    except AttributeError:
        await websocket.send_json({"error": "server misconfigured"})
        await websocket.close(code=1011)
        return

    s = await session_service.get_session(r, session_id)
    if not s:
        await websocket.send_json({"error": "session not found"})
        await websocket.close(code=4004)
        return

    try:
        first = await websocket.receive()
    except WebSocketDisconnect:
        return

    if first.get("type") != "websocket.receive" or "text" not in first:
        await websocket.send_json({"error": "first frame must be JSON meta"})
        await websocket.close(code=4400)
        return

    try:
        meta = json.loads(first["text"])
    except json.JSONDecodeError:
        await websocket.send_json({"error": "invalid JSON"})
        await websocket.close(code=4400)
        return

    if meta.get("type") != "meta":
        await websocket.send_json({"error": "expected {\"type\":\"meta\", ...}"})
        await websocket.close(code=4400)
        return

    try:
        v, eff_prov, tm = _normalize_voice_for_speak(
            voice=meta.get("voice"),
            tts_provider=meta.get("tts_provider"),
            tts_model=meta.get("tts_model"),
        )
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, str) else str(e.detail)
        await websocket.send_json({"error": detail})
        await websocket.close(code=4400)
        return

    sq: sync_queue.Queue[bytes | None] = sync_queue.Queue()
    pcm_rx_stats: dict[str, int] = {"bytes": 0}
    t_stream0 = time.perf_counter()

    async def pump() -> None:
        try:
            while True:
                msg = await websocket.receive()
                if msg.get("type") != "websocket.receive":
                    continue
                if msg.get("bytes"):
                    b = bytes(msg["bytes"])
                    pcm_rx_stats["bytes"] += len(b)
                    sq.put(b)
                elif msg.get("text"):
                    try:
                        body = json.loads(msg["text"])
                    except json.JSONDecodeError:
                        continue
                    if body.get("type") == "end":
                        sq.put(None)
                        return
        except WebSocketDisconnect:
            pass
        finally:
            sq.put(None)

    pump_task = asyncio.create_task(pump())
    text = ""
    dashscope_ms = 0.0
    try:
        text, dashscope_ms = await asyncio.wait_for(
            asyncio.to_thread(transcribe_pcm_chunk_queue_sync, sq),
            timeout=120.0,
        )
    except asyncio.TimeoutError:
        log.warning(
            "speak_audio_stream STT timeout session=%s pcm_rx_bytes=%d",
            session_id,
            pcm_rx_stats["bytes"],
        )
        try:
            await websocket.send_json({"error": "语音识别超时，请重试。"})
        except Exception:
            pass
        await websocket.close(code=4408)
        return
    except RuntimeError as e:
        await websocket.send_json({"error": str(e)})
        await websocket.close(code=4400)
        return
    except Exception as e:  # noqa: BLE001
        log.exception("speak_audio_stream stt failed")
        await websocket.send_json({"error": f"stt error: {e}"})
        await websocket.close(code=1011)
        return
    finally:
        pump_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pump_task

    total_ms = (time.perf_counter() - t_stream0) * 1000.0
    log.info(
        "STT streaming timing: pcm_rx_bytes=%d dashscope_ms=%.0f wall_total_ms=%.0f text_chars=%d",
        pcm_rx_stats["bytes"],
        dashscope_ms,
        total_ms,
        len(text.strip()),
    )

    stripped = text.strip()
    if not stripped:
        await websocket.send_json({"error": "未能识别有效语音，请重试。"})
        await websocket.close(code=4400)
        return

    await session_service.speak(
        r,
        session_id,
        stripped,
        voice=v,
        tts_provider=eff_prov,
        tts_model=tm,
    )
    await websocket.send_json({"session_id": session_id, "status": "queued", "text": stripped})


@router.post("/{session_id}/interrupt")
async def interrupt(session_id: str, request: Request) -> dict[str, str]:
    r: redis.Redis = request.app.state.redis
    s = await session_service.get_session(r, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    await session_service.interrupt(r, session_id)
    return {"session_id": session_id, "status": "interrupted"}


@router.post("/{session_id}/flashtalk-recording/start")
async def flashtalk_recording_start(session_id: str, request: Request) -> dict[str, str]:
    return await _flashtalk_disk_recording_control(session_id, request, stop=False)


@router.post("/{session_id}/flashtalk-recording/stop")
async def flashtalk_recording_stop(session_id: str, request: Request) -> dict[str, str]:
    return await _flashtalk_disk_recording_control(session_id, request, stop=True)


@router.get("/{session_id}/flashtalk-recording", response_model=None)
async def download_flashtalk_recording(session_id: str, request: Request) -> Response:
    r: redis.Redis = request.app.state.redis
    s = await session_service.get_session(r, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    try:
        path = export_flashtalk_recording(session_id)
    except FileNotFoundError as exc:
        runners = getattr(request.app.state, "session_runners", None)
        if runners is None:
            settings = request.app.state.settings
            return await _stream_worker_flashtalk_recording(
                worker_url=settings.worker_url,
                session_id=session_id,
            )
        raise HTTPException(status_code=404, detail="recording not ready") from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("Failed to export FlashTalk recording: session=%s", session_id)
        raise HTTPException(status_code=500, detail=f"recording export failed: {exc}") from exc
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=f"{session_id}_flashtalk_capture.mp4",
    )


def _offline_bundle_job_dir(session_id: str, job_id: str) -> Path:
    return (flashtalk_recording_session_dir(session_id) / "offline" / job_id).resolve()


def _offline_bundle_artifact_path(session_id: str, job_id: str, artifact: str) -> tuple[Path, str, str]:
    """返回 (绝对路径, media_type, download_filename)。"""
    base = _offline_bundle_job_dir(session_id, job_id)
    table: dict[str, tuple[str, str, str]] = {
        "bundle": ("bundle.mp4", "video/mp4", f"{session_id}_offline_{job_id}_bundle.mp4"),
        "zip": ("offline_bundle.zip", "application/zip", f"{session_id}_offline_{job_id}.zip"),
        "audio": ("aligned_audio.wav", "audio/wav", f"{session_id}_offline_{job_id}_audio.wav"),
        "video": ("video_only.mp4", "video/mp4", f"{session_id}_offline_{job_id}_video_only.mp4"),
    }
    if artifact not in table:
        raise HTTPException(status_code=400, detail="artifact must be bundle|zip|audio|video")
    name, mime, fname = table[artifact]
    path = (base / name).resolve()
    try:
        path.relative_to(base)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid artifact path") from e
    return path, mime, fname


@router.post("/{session_id}/flashtalk-offline-bundle")
async def flashtalk_offline_bundle_enqueue(
    session_id: str,
    request: Request,
    file: UploadFile = File(...),
) -> dict[str, str]:
    """上传音频 → 入队离线推理；完成后音视频对齐保存在服务端目录，并可下载。

    需 **flashtalk/flashhead** 会话且 Worker 已加载该 session；PCM 临时文件须与 Worker 共享文件系统。
    进度与结果见 ``GET .../flashtalk-offline-bundle/{job_id}``。
    """
    r: redis.Redis = request.app.state.redis
    s = await session_service.get_session(r, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    if not _is_flashtalk_compatible_model(s.get("model")):
        raise HTTPException(
            status_code=400,
            detail="仅 flashtalk/flashhead 会话可使用离线导出",
        )

    body = await file.read()
    if len(body) > _MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="audio too large (max 15MB)")
    if not body:
        raise HTTPException(status_code=400, detail="empty audio")

    suffix = Path(file.filename or "speech.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(body)
        upload_path = Path(tmp.name)

    try:
        pcm = await decode_audio_file_to_pcm_i16(upload_path)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        log.exception("flashtalk offline bundle decode failed")
        raise HTTPException(status_code=502, detail=f"audio decode error: {e}") from e
    finally:
        try:
            upload_path.unlink(missing_ok=True)
        except OSError:
            pass

    if pcm.size == 0:
        raise HTTPException(status_code=400, detail="解码后音频为空")

    job_id = uuid.uuid4().hex[:16]
    base = Path(tempfile.gettempdir()) / "opentalking_upload_pcm"
    base.mkdir(parents=True, exist_ok=True)
    pcm_path = base / f"{session_id}_offline_{job_id}.pcm"
    try:
        pcm_path.write_bytes(pcm.tobytes())
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"failed to write pcm: {e}") from e

    k = offline_bundle_job_key(job_id)
    await _await_result(r.hset(
        k,
        mapping={
            "session_id": session_id,
            "job_id": job_id,
            "status": "queued",
        },
    ))
    await session_service.enqueue_flashtalk_offline_bundle(
        r,
        session_id,
        pcm_path=str(pcm_path.resolve()),
        job_id=job_id,
    )
    return {"session_id": session_id, "job_id": job_id, "status": "queued"}


@router.get("/{session_id}/flashtalk-offline-bundle/{job_id}")
async def flashtalk_offline_bundle_status(
    session_id: str,
    job_id: str,
    request: Request,
) -> dict[str, str]:
    r: redis.Redis = request.app.state.redis
    k = offline_bundle_job_key(job_id)
    raw = await _await_result(r.hgetall(k))
    if not raw:
        raise HTTPException(status_code=404, detail="job not found")

    def _txt(key: str) -> str:
        v = raw.get(key) or raw.get(key.encode("utf-8"))
        if v is None:
            return ""
        return v.decode("utf-8", errors="replace") if isinstance(v, (bytes, bytearray)) else str(v)

    if _txt("session_id") != session_id:
        raise HTTPException(status_code=404, detail="job not found")

    out: dict[str, str] = {
        "session_id": session_id,
        "job_id": job_id,
        "status": _txt("status"),
    }
    for field in ("message", "bundle_mp4", "aligned_audio_wav", "video_only_mp4", "zip", "work_dir"):
        v = _txt(field)
        if v:
            out[field] = v
    return out


@router.get("/{session_id}/flashtalk-offline-bundle/{job_id}/download")
async def flashtalk_offline_bundle_download(
    session_id: str,
    job_id: str,
    request: Request,
    artifact: str = Query("bundle", description="bundle | zip | audio | video"),
) -> FileResponse:
    r: redis.Redis = request.app.state.redis
    k = offline_bundle_job_key(job_id)
    raw = await _await_result(r.hgetall(k))
    if not raw:
        raise HTTPException(status_code=404, detail="job not found")

    def _txt(key: str) -> str:
        v = raw.get(key) or raw.get(key.encode("utf-8"))
        if v is None:
            return ""
        return v.decode("utf-8", errors="replace") if isinstance(v, (bytes, bytearray)) else str(v)

    if _txt("session_id") != session_id:
        raise HTTPException(status_code=404, detail="job not found")
    if _txt("status") != "done":
        raise HTTPException(status_code=409, detail="job not finished or failed")

    path, media_type, filename = _offline_bundle_artifact_path(session_id, job_id, artifact.strip().lower())
    if not path.is_file():
        raise HTTPException(status_code=404, detail="artifact file missing")
    return FileResponse(path, media_type=media_type, filename=filename)


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
