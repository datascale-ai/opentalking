from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import queue as sync_queue
import tempfile
import time
from pathlib import Path

import redis.asyncio as redis
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect

from opentalking.avatars.loader import load_avatar_bundle
from apps.api.schemas.session import (
    CreateSessionRequest,
    CreateSessionResponse,
    SpeakRequest,
    WebRTCOfferRequest,
)
from apps.api.services import session_service
from apps.api.services.worker_service import forward_webrtc_offer
from apps.api.core.config import get_settings
from opentalking.stt.dashscope_asr import transcribe_audio_file_path, transcribe_pcm_chunk_queue_sync
from opentalking.tts.edge_zh_voices import normalize_optional_edge_voice
from opentalking.tts.qwen_tts_voices import normalize_optional_qwen_voice, sanitize_qwen_model


def _effective_tts_provider(requested: str | None) -> str:
    r = (requested or "").strip().lower()
    if r:
        return r
    try:
        return get_settings().tts_provider.strip().lower()
    except Exception:
        return "edge"


_BAILIAN_TTS = frozenset(
    {
        "dashscope",
        "bailian",
        "qwen",
        "qwen_tts",
        "cosyvoice",
        "cosyvoice_http",
        "minimax",
        "sambert",
        "dashscope_sambert",
    },
)


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
        vn = normalize_optional_edge_voice(voice)
        if tts_model and str(tts_model).strip():
            raise HTTPException(
                status_code=400,
                detail="tts_model is only valid when using 百炼语音线路（tts_provider=dashscope、cosyvoice、minimax、sambert 等）",
            )
        return vn, eff, None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


log = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])

_MAX_AUDIO_BYTES = 15 * 1024 * 1024


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
                "Use demo-avatar/wav2lip for the quickstart path, or switch "
                "OPENTALKING_FLASHTALK_MODE to remote/local."
            ),
        )
    sid = await session_service.create_session(
        r,
        avatar_id=body.avatar_id,
        model=body.model,
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
