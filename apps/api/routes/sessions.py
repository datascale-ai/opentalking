from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
import os
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

from opentalking.avatar import mouth_metadata
from opentalking.avatar.loader import load_avatar_bundle
from opentalking.avatar.wav2lip_preload import preload_wav2lip_avatar
from apps.api.schemas.session import (
    CreateSessionRequest,
    CreateSessionResponse,
    FasterLivePortraitConfigRequest,
    SessionKnowledgeBasesRequest,
    SessionKnowledgeBasesResponse,
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
from opentalking.avatar.fasterliveportrait_config import (
    normalize_fasterliveportrait_runtime_config,
)
from opentalking.agent.context_builder import AgentSessionConfig
from opentalking.providers.stt.dashscope.adapter import (
    decode_audio_file_to_pcm_i16,
    ensure_wav_16k_mono,
)
from opentalking.providers.stt.factory import normalize_stt_provider, stt_provider_config, transcribe_pcm_chunk_queue_sync, transcribe_wav_path_sync
from opentalking.providers.tts.edge_zh_voices import normalize_optional_edge_voice
from opentalking.providers.tts.providers import (
    BAILIAN_TTS_PROVIDERS,
    INDEXTTS_TTS_PROVIDERS,
    LOCAL_TTS_PROVIDERS,
    OMNIRT_TTS_PROVIDERS,
    XIAOMI_MIMO_TTS_PROVIDERS,
    normalize_tts_provider,
)
from opentalking.providers.tts.factory import tts_provider_config
from opentalking.providers.tts.qwen_tts_voices import normalize_optional_qwen_voice, sanitize_qwen_model
from opentalking.pipeline.recording.recording import (
    export_flashtalk_recording,
    flashtalk_recording_session_dir,
)
from opentalking.persona.session import build_session_defaults
from opentalking.persona.store import PersonaStore


def _effective_tts_provider(requested: str | None) -> str:
    r = (requested or "").strip().lower()
    if r:
        return normalize_tts_provider(r, default="edge") or "edge"
    try:
        settings = get_settings()
        return getattr(settings, "normalized_tts_default_provider", None) or settings.tts_provider.strip().lower()
    except Exception:
        return "edge"


_BAILIAN_TTS = BAILIAN_TTS_PROVIDERS
_LOCAL_TTS = LOCAL_TTS_PROVIDERS
_OMNIRT_TTS = OMNIRT_TTS_PROVIDERS
_INDEXTTS_TTS = INDEXTTS_TTS_PROVIDERS
_XIAOMI_MIMO_TTS = XIAOMI_MIMO_TTS_PROVIDERS
_AUDIO_RENDERER_MODELS = frozenset(
    {"flashtalk", "flashhead", "fasterliveportrait", "quicktalk", "musetalk", "wav2lip"}
)
_AUDIO_RENDERER_MODELS_LABEL = "flashtalk/flashhead/fasterliveportrait/quicktalk/musetalk/wav2lip"
_FLASHTALK_SLOT_MODELS = frozenset({"flashtalk", "flashhead"})


def _is_flashtalk_compatible_model(model: str | None) -> bool:
    return (model or "").strip().lower() in _AUDIO_RENDERER_MODELS


def _uses_flashtalk_slot_model(model: str | None) -> bool:
    return (model or "").strip().lower() in _FLASHTALK_SLOT_MODELS


def _settings_value(settings: object, name: str) -> str:
    return str(getattr(settings, name, "") or "").strip()


def _env_or_settings(settings: object, env_name: str, settings_name: str) -> str:
    return os.environ.get(env_name, "").strip() or _settings_value(settings, settings_name)


def _effective_stt_provider(requested: str | None, settings: object) -> str:
    try:
        return (
            normalize_stt_provider(requested, default=None)
            or _settings_value(settings, "normalized_stt_default_provider")
            or _settings_value(settings, "normalized_stt_provider")
            or "dashscope"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def _require_audio_provider_config(
    *,
    stt_provider: str,
    tts_provider: str | None,
    settings: object,
) -> None:
    if stt_provider in {"dashscope", "openai_compatible", "xiaomi_mimo"}:
        stt_status = stt_provider_config(stt_provider)
        if not stt_status.get("key_set"):
            if stt_provider == "openai_compatible":
                key_name = "OPENTALKING_STT_OPENAI_API_KEY"
            elif stt_provider == "xiaomi_mimo":
                key_name = "OPENTALKING_STT_XIAOMI_API_KEY"
            else:
                key_name = "OPENTALKING_STT_DASHSCOPE_API_KEY"
            raise HTTPException(
                status_code=400,
                detail=f"API STT 缺少 {key_name}，请在后端 .env 配置后重启服务。",
            )
        if stt_provider in {"openai_compatible", "xiaomi_mimo"} and not stt_status.get("service_url_set"):
            url_name = (
                "OPENTALKING_STT_XIAOMI_BASE_URL"
                if stt_provider == "xiaomi_mimo"
                else "OPENTALKING_STT_OPENAI_BASE_URL"
            )
            label = "小米 MiMo STT" if stt_provider == "xiaomi_mimo" else "OpenAI-compatible STT"
            raise HTTPException(
                status_code=400,
                detail=f"{label} 缺少 {url_name}，请在后端 .env 配置后重启服务。",
            )
    effective_tts = (
        tts_provider
        or _settings_value(settings, "normalized_tts_default_provider")
        or _settings_value(settings, "normalized_tts_provider")
        or "edge"
    )
    if effective_tts in _BAILIAN_TTS or effective_tts == "openai_compatible" or effective_tts in _XIAOMI_MIMO_TTS:
        tts_status = tts_provider_config(effective_tts)
        if not tts_status.get("key_set"):
            key_name = (
                "OPENTALKING_TTS_OPENAI_API_KEY"
                if effective_tts == "openai_compatible"
                else "OPENTALKING_TTS_XIAOMI_API_KEY"
                if effective_tts in _XIAOMI_MIMO_TTS
                else "OPENTALKING_TTS_DASHSCOPE_API_KEY"
            )
            raise HTTPException(
                status_code=400,
                detail=f"API TTS 缺少 {key_name}，请在后端 .env 配置后重启服务。",
            )
        if effective_tts == "openai_compatible" and not tts_status.get("service_url_set"):
            raise HTTPException(
                status_code=400,
                detail="OpenAI-compatible TTS 缺少 OPENTALKING_TTS_OPENAI_BASE_URL，请在后端 .env 配置后重启服务。",
            )
        if effective_tts in _XIAOMI_MIMO_TTS and not tts_status.get("service_url_set"):
            raise HTTPException(
                status_code=400,
                detail="小米 MiMo TTS 缺少 OPENTALKING_TTS_XIAOMI_BASE_URL，请在后端 .env 配置后重启服务。",
            )


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
        if eff in _XIAOMI_MIMO_TTS:
            vn = str(voice).strip() if voice else None
            tm = str(tts_model).strip() if tts_model and str(tts_model).strip() else None
            return vn, eff, tm
        if eff in _BAILIAN_TTS or eff in _LOCAL_TTS or eff in _OMNIRT_TTS or eff in _INDEXTTS_TTS:
            vn = normalize_optional_qwen_voice(voice)
            tm = sanitize_qwen_model(tts_model)
            return vn, eff, tm
        if eff in {"elevenlabs", "openai_compatible"}:
            vn = str(voice).strip() if voice else None
            tm = str(tts_model).strip() if tts_model and str(tts_model).strip() else None
            return vn, eff, tm
        vn = normalize_optional_edge_voice(voice)
        # tts_model has no meaning for Edge TTS — silently drop it instead of
        # 400ing, so users can flip provider without manually clearing the field.
        return vn, eff, None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def _normalize_agent_user_id(value: str | None) -> str | None:
    user_id = (value or "").strip()
    if not user_id:
        return None
    if len(user_id) > 128:
        raise HTTPException(status_code=400, detail="user_id is too long")
    if any(ch.isspace() for ch in user_id):
        raise HTTPException(status_code=400, detail="user_id must not contain whitespace")
    return user_id


def _normalize_knowledge_base_ids(
    *,
    knowledge_base_id: str | None,
    knowledge_base_ids: list[str] | None,
) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    candidates = knowledge_base_ids if knowledge_base_ids else [knowledge_base_id]
    for candidate in candidates:
        kb_id = str(candidate or "").strip()
        if not kb_id or kb_id in seen:
            continue
        selected.append(kb_id)
        seen.add(kb_id)
    return selected


def _normalize_agent_session_config(
    body: CreateSessionRequest,
) -> tuple[str | None, bool, bool, bool, str | None, list[str]]:
    agent_user_id = _normalize_agent_user_id(body.user_id)
    memory_enabled = bool(body.memory_enabled)
    knowledge_enabled = body.knowledge_enabled is not False
    agent_enabled = bool(body.agent_enabled or memory_enabled or knowledge_enabled)
    knowledge_base_ids = _normalize_knowledge_base_ids(
        knowledge_base_id=body.knowledge_base_id,
        knowledge_base_ids=body.knowledge_base_ids,
    )
    knowledge_base_id = knowledge_base_ids[0] if knowledge_base_ids else None
    return (
        agent_user_id,
        agent_enabled,
        memory_enabled,
        knowledge_enabled,
        knowledge_base_id,
        knowledge_base_ids,
    )


def _update_runner_agent_knowledge_bases(runner: object, knowledge_base_ids: list[str]) -> None:
    current = getattr(runner, "agent_config", None)
    if current is None:
        return
    knowledge_enabled = bool(knowledge_base_ids)
    setattr(
        runner,
        "agent_config",
        AgentSessionConfig(
            user_id=getattr(current, "user_id", None),
            agent_enabled=bool(getattr(current, "agent_enabled", False) or knowledge_enabled),
            memory_enabled=bool(getattr(current, "memory_enabled", False)),
            knowledge_enabled=knowledge_enabled,
            knowledge_base_id=knowledge_base_ids[0] if knowledge_base_ids else None,
            knowledge_base_ids=knowledge_base_ids,
        ),
    )


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
            detail=f"音频驱动录制仅支持 {_AUDIO_RENDERER_MODELS_LABEL} 模型会话",
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


def _wav2lip_postprocess_mode_for_preload(raw: str | None) -> str:
    value = (
        (raw or "").strip()
        or os.environ.get("OPENTALKING_WAV2LIP_POSTPROCESS_MODE", "easy_improved")
    )
    return value.strip().lower().replace("-", "_") or "easy_improved"


def _wav2lip_preload_state(request: Request) -> tuple[set[str], set[str]]:
    done = getattr(request.app.state, "wav2lip_preloaded_avatars", None)
    if done is None:
        done = set()
        request.app.state.wav2lip_preloaded_avatars = done
    scheduled = getattr(request.app.state, "wav2lip_preload_scheduled_avatars", None)
    if scheduled is None:
        scheduled = set()
        request.app.state.wav2lip_preload_scheduled_avatars = scheduled
    return done, scheduled


async def _wav2lip_selected_preload_task(
    *,
    request: Request,
    avatar_id: str,
    postprocess_mode: str,
) -> None:
    settings = request.app.state.settings
    await preload_wav2lip_avatar(
        Path(getattr(settings, "avatars_dir")).resolve(),
        avatar_id,
        omnirt_endpoint=(getattr(settings, "omnirt_endpoint", "") or "").strip(),
        postprocess_mode=postprocess_mode,
        attempts=1,
        retry_delay_seconds=0.0,
    )


async def _preload_selected_wav2lip_avatar(
    *,
    request: Request,
    avatar_id: str,
    model: str,
    wav2lip_postprocess_mode: str | None,
) -> None:
    if model != "wav2lip":
        return
    settings = request.app.state.settings
    endpoint = (getattr(settings, "omnirt_endpoint", "") or "").strip()
    if not endpoint or not getattr(settings, "wav2lip_preload", True):
        return

    postprocess_mode = _wav2lip_postprocess_mode_for_preload(wav2lip_postprocess_mode)
    done, scheduled = _wav2lip_preload_state(request)
    key = f"{avatar_id}:{postprocess_mode}"
    if key in done:
        log.info("Selected Wav2Lip avatar preload skipped: avatar=%s cache_state=done", avatar_id)
        return

    tasks = getattr(request.app.state, "wav2lip_selected_preload_tasks", None)
    if tasks is None:
        tasks = {}
        request.app.state.wav2lip_selected_preload_tasks = tasks
    existing_task = tasks.get(key)
    if existing_task is not None and not existing_task.done():
        log.info("Selected Wav2Lip avatar preload join: avatar=%s", avatar_id)
        try:
            await existing_task
            done.add(key)
            done.add(avatar_id)
        except Exception:
            log.warning(
                "Selected Wav2Lip avatar preload failed; continuing session init: avatar=%s",
                avatar_id,
                exc_info=True,
            )
        return
    if key in scheduled:
        return

    scheduled.add(key)
    task = None
    try:
        task = asyncio.create_task(
            _wav2lip_selected_preload_task(
                request=request,
                avatar_id=avatar_id,
                postprocess_mode=postprocess_mode,
            )
        )
        tasks[key] = task
        await task
        done.add(key)
        done.add(avatar_id)
    except Exception:
        log.warning(
            "Selected Wav2Lip avatar preload failed; continuing session init: avatar=%s",
            avatar_id,
            exc_info=True,
        )
    finally:
        scheduled.discard(key)
        task = tasks.get(key)
        if task is not None and task.done():
            tasks.pop(key, None)


@router.post("", response_model=CreateSessionResponse)
async def create_session(body: CreateSessionRequest, request: Request) -> CreateSessionResponse:
    r: redis.Redis = request.app.state.redis
    settings = request.app.state.settings
    explicit_fields: set[str] = set(getattr(body, "model_fields_set", set()))
    persona_id = (body.persona_id or "").strip() or None
    persona_defaults = None
    if persona_id:
        try:
            persona_store = PersonaStore(Path(getattr(settings, "persona_root", "./data/personas")))
            persona_defaults = build_session_defaults(persona_store.get_persona(persona_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="persona not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    avatar_id = (
        (body.avatar_id or "").strip()
        or (persona_defaults.avatar_id if persona_defaults is not None else "")
    )
    model = (
        (body.model or "").strip()
        or (persona_defaults.model if persona_defaults is not None else "")
    )
    if not avatar_id or not model:
        raise HTTPException(status_code=400, detail="avatar_id and model are required unless persona_id is provided")

    persona_tts_provider = persona_defaults.tts_provider if persona_defaults is not None else None
    persona_stt_provider = persona_defaults.stt_provider if persona_defaults is not None else None
    persona_tts_voice = persona_defaults.tts_voice if persona_defaults is not None else None
    tts_provider_request = (body.tts_provider or "").strip() or persona_tts_provider
    stt_provider_request = (body.stt_provider or "").strip() or persona_stt_provider
    tts_voice_request = (body.tts_voice or "").strip() or persona_tts_voice
    tts_model_request = (body.tts_model or "").strip() or (persona_defaults.tts_model if persona_defaults is not None else None)

    _, avatar_dir = _resolve_avatar_dir(settings, avatar_id)
    if not avatar_dir.is_dir():
        raise HTTPException(status_code=404, detail="avatar not found")
    try:
        load_avatar_bundle(avatar_dir, strict=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid avatar: {exc}") from exc
    # Avatar / model decoupling: every avatar bundle has a reference image, and
    # every supported model (mock / flashtalk / flashhead / musetalk / wav2lip)
    # can consume that reference image as its starting frame. The avatar's
    # manifest.model_type is now treated as a *suggestion* for the UI, not a
    # hard gate. If a chosen model genuinely needs assets that the avatar lacks
    # (e.g. wav2lip prepared frames), the failure surfaces downstream with a
    # clearer error than a generic 400 here.

    # Deployment guard: only allow models the upstream backend actually serves.
    from opentalking.providers.synthesis.availability import connected_model_ids

    available_models = await connected_model_ids(settings)
    if model not in available_models:
        raise HTTPException(
            status_code=400,
            detail=(
                f"model '{model}' is not yet supported on this deployment. "
                f"Currently available: {', '.join(available_models)}."
            ),
        )
    try:
        tts_provider = normalize_tts_provider(tts_provider_request, default=None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    stt_provider = _effective_stt_provider(stt_provider_request, settings)
    _require_audio_provider_config(
        stt_provider=stt_provider,
        tts_provider=tts_provider,
        settings=settings,
    )
    try:
        fasterliveportrait_config = (
            normalize_fasterliveportrait_runtime_config(body.fasterliveportrait_config)
            if model == "fasterliveportrait"
            else {}
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    tts_voice = tts_voice_request or None
    tts_model = tts_model_request or None

    agent_user_id = _normalize_agent_user_id(body.user_id)
    if persona_defaults is not None and "memory_enabled" not in explicit_fields:
        memory_enabled = bool(persona_defaults.memory_enabled)
    else:
        memory_enabled = bool(body.memory_enabled)
    if persona_defaults is not None and "knowledge_enabled" not in explicit_fields:
        knowledge_enabled = bool(persona_defaults.knowledge_enabled)
    else:
        knowledge_enabled = body.knowledge_enabled is not False
    if (
        persona_defaults is not None
        and "knowledge_base_id" not in explicit_fields
        and "knowledge_base_ids" not in explicit_fields
    ):
        knowledge_base_ids = list(persona_defaults.knowledge_base_ids)
    else:
        knowledge_base_ids = _normalize_knowledge_base_ids(
            knowledge_base_id=body.knowledge_base_id,
            knowledge_base_ids=body.knowledge_base_ids,
        )
    knowledge_base_id = knowledge_base_ids[0] if knowledge_base_ids else None
    if persona_defaults is not None and "agent_enabled" not in explicit_fields:
        agent_enabled = bool(memory_enabled or knowledge_enabled)
    else:
        agent_enabled = bool(body.agent_enabled or memory_enabled or knowledge_enabled)

    custom = _session_customizations(request).get(avatar_id, {})
    persona_prompt = persona_defaults.llm_system_prompt if persona_defaults is not None else None
    llm_system_prompt = persona_prompt or (body.llm_system_prompt or "").strip() or custom.get("llm_system_prompt")
    custom_ref_image_path = custom.get("custom_ref_image_path")
    if custom_ref_image_path and not Path(custom_ref_image_path).exists():
        custom_ref_image_path = None

    await _preload_selected_wav2lip_avatar(
        request=request,
        avatar_id=avatar_id,
        model=model,
        wav2lip_postprocess_mode=body.wav2lip_postprocess_mode,
    )

    sid = await session_service.create_session(
        r,
        persona_id=persona_id,
        avatar_id=avatar_id,
        model=model,
        tts_provider=tts_provider,
        stt_provider=stt_provider,
        tts_voice=tts_voice,
        tts_model=tts_model,
        llm_system_prompt=llm_system_prompt,
        custom_ref_image_path=custom_ref_image_path,
        wav2lip_postprocess_mode=body.wav2lip_postprocess_mode,
        fasterliveportrait_config=fasterliveportrait_config or None,
        user_id=agent_user_id,
        agent_enabled=agent_enabled,
        memory_enabled=memory_enabled,
        memory_profile_id=body.memory_profile_id,
        character_id=body.character_id or avatar_id,
        memory_library_id=body.memory_library_id,
        knowledge_enabled=knowledge_enabled,
        knowledge_base_id=knowledge_base_id,
        knowledge_base_ids=knowledge_base_ids,
    )
    # Single-process mode: WebRTC offer runs immediately after; wait until init task
    # has created the SessionRunner (avoids 404 "session not loaded").
    uses_flashtalk_slot = _uses_flashtalk_slot_model(model)
    runners = getattr(request.app.state, "session_runners", None)
    if runners is not None:
        settings = request.app.state.settings

        if uses_flashtalk_slot:
            from opentalking.runtime.task_consumer import slot_is_occupied
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

        backend_name = ""
        try:
            from opentalking.providers.synthesis.backends import resolve_model_backend

            backend_name = resolve_model_backend(model, settings).backend
        except Exception:
            log.warning("Failed to resolve model backend for session wait policy: model=%s", model, exc_info=True)

        if (
            (
                _is_flashtalk_compatible_model(model)
                and not uses_flashtalk_slot
                and backend_name in {"omnirt", "direct_ws"}
            )
            or model == "quicktalk"
            or (model == "musetalk" and backend_name == "local")
        ):
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
    elif uses_flashtalk_slot:
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
        mouth_metadata.update_manifest_mouth_metadata(avatar_dir / "manifest.json", target, force=True)
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
    mouth_metadata.update_manifest_mouth_metadata(avatar_dir / "manifest.json", target, force=True)

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


@router.post("/{session_id}/knowledge-bases", response_model=SessionKnowledgeBasesResponse)
async def update_session_knowledge_bases(
    session_id: str,
    body: SessionKnowledgeBasesRequest,
    request: Request,
) -> SessionKnowledgeBasesResponse:
    r: redis.Redis = request.app.state.redis
    s = await session_service.get_session(r, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    selected_ids = await session_service.update_agent_knowledge_bases(
        r,
        session_id,
        knowledge_base_ids=body.knowledge_base_ids,
    )
    runners = getattr(request.app.state, "session_runners", None)
    runner = runners.get(session_id) if isinstance(runners, dict) else None
    if runner is not None:
        _update_runner_agent_knowledge_bases(runner, selected_ids)
    return SessionKnowledgeBasesResponse(
        session_id=session_id,
        knowledge_base_ids=selected_ids,
    )


@router.post("/{session_id}/start")
async def start_session(session_id: str, request: Request) -> dict[str, str]:
    """Optional hook: worker loads on create; this marks ready when client connects."""
    r: redis.Redis = request.app.state.redis
    s = await session_service.get_session(r, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    await session_service.update_session_state(r, session_id, "ready")
    return {"session_id": session_id, "status": "ready"}


@router.post("/{session_id}/fasterliveportrait-config")
async def update_fasterliveportrait_config(
    session_id: str,
    body: FasterLivePortraitConfigRequest,
    request: Request,
) -> dict[str, object]:
    r: redis.Redis = request.app.state.redis
    s = await session_service.get_session(r, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    if (s.get("model") or "").strip() != "fasterliveportrait":
        raise HTTPException(status_code=400, detail="session is not fasterliveportrait")
    try:
        config = normalize_fasterliveportrait_runtime_config(
            body.model_dump(exclude_none=True)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not config:
        raise HTTPException(status_code=400, detail="no supported FasterLivePortrait config fields")

    runners = getattr(request.app.state, "session_runners", None)
    runner = runners.get(session_id) if isinstance(runners, dict) else None
    if runner is None:
        # Split API/worker mode: enqueue the update for the worker process.
        await session_service.update_fasterliveportrait_config(r, session_id, config)
        return {"session_id": session_id, "status": "queued", "updated": config}

    update_fn = getattr(runner, "update_fasterliveportrait_runtime_config", None)
    if not callable(update_fn):
        raise HTTPException(status_code=400, detail="runner does not support FasterLivePortrait config updates")
    try:
        await update_fn(config)
    except Exception as e:  # noqa: BLE001
        log.exception("Failed to update FasterLivePortrait config: session=%s", session_id)
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"session_id": session_id, "status": "updated", "updated": config}


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


def _normalize_requested_stt_provider(value: str | None) -> str | None:
    try:
        return normalize_stt_provider(value, default=None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


async def _transcribe_upload_path(upload_path: Path, *, stt_provider: str | None = None) -> str:
    """Uploaded audio file -> 16k WAV -> configured STT provider."""
    t_total0 = time.perf_counter()
    upload_sz = upload_path.stat().st_size
    requested_stt_provider = _normalize_requested_stt_provider(stt_provider)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = Path(tmp.name)
    try:
        t_ff0 = time.perf_counter()
        await ensure_wav_16k_mono(upload_path, wav_path)
        ffmpeg_ms = (time.perf_counter() - t_ff0) * 1000.0
        text, stt_ms = await asyncio.to_thread(
            transcribe_wav_path_sync,
            wav_path,
            provider=requested_stt_provider,
        )
        total_ms = (time.perf_counter() - t_total0) * 1000.0
        log.info(
            "STT upload timing: provider=%s upload_bytes=%d ffmpeg_ms=%.0f stt_ms=%.0f total_ms=%.0f text_chars=%d",
            requested_stt_provider or "configured",
            upload_sz,
            ffmpeg_ms,
            stt_ms,
            total_ms,
            len(text.strip()),
        )
        return text
    finally:
        try:
            wav_path.unlink(missing_ok=True)
        except OSError:
            pass


@router.post("/{session_id}/transcribe")
async def transcribe(
    session_id: str,
    request: Request,
    file: UploadFile = File(...),
    stt_provider: str | None = Form(default=None),
) -> dict[str, str]:
    """上传短音频 → STT provider → 返回识别文本（不触发数字人播报）。"""
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
        text = await _transcribe_upload_path(upload_path, stt_provider=stt_provider)
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
    stt_provider: str | None = Form(default=None),
) -> dict[str, str]:
    """上传语音 → STT provider → 将识别文本送入与会话相同的 speak 流水线（LLM→TTS→FlashTalk）。"""
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
        text = await _transcribe_upload_path(upload_path, stt_provider=stt_provider)
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
    """上传音频 → 解码为 16kHz mono PCM → 直接驱动兼容音频数字人（不经语音识别、LLM、TTS）。

    要求会话 ``model`` 为音频驱动数字人模型。
    """
    r: redis.Redis = request.app.state.redis
    s = await session_service.get_session(r, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    if not _is_flashtalk_compatible_model(s.get("model")):
        raise HTTPException(
            status_code=400,
            detail=f"仅 {_AUDIO_RENDERER_MODELS_LABEL} 会话可使用本接口（上传音频直驱口型）",
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
    """浏览器经 WebSocket 推送 PCM s16le mono 16kHz 分块 → 流式 STT → speak 流水线。"""
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
        requested_stt_provider = _normalize_requested_stt_provider(meta.get("stt_provider"))
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
            asyncio.to_thread(
                transcribe_pcm_chunk_queue_sync,
                sq,
                provider=requested_stt_provider,
            ),
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
        "STT streaming timing: provider=%s pcm_rx_bytes=%d stt_ms=%.0f wall_total_ms=%.0f text_chars=%d",
        requested_stt_provider or "configured",
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

    需音频驱动数字人会话且 Worker 已加载该 session；PCM 临时文件须与 Worker 共享文件系统。
    进度与结果见 ``GET .../flashtalk-offline-bundle/{job_id}``。
    """
    r: redis.Redis = request.app.state.redis
    s = await session_service.get_session(r, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    if not _is_flashtalk_compatible_model(s.get("model")):
        raise HTTPException(
            status_code=400,
            detail=f"仅 {_AUDIO_RENDERER_MODELS_LABEL} 会话可使用离线导出",
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
    log.info(
        "flashtalk offline bundle queued: session=%s job=%s model=%s pcm_samples=%d pcm_path=%s",
        session_id,
        job_id,
        s.get("model"),
        int(pcm.size),
        pcm_path.resolve(),
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
