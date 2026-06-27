from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import tempfile
from typing import Literal
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from opentalking.core.config import get_settings
from opentalking.persona.session import default_persona_store
from opentalking.persona.wechat_import import WeChatImportJobRegistry
from opentalking.providers.memory.decision_agent import MemoryDecisionAgent
from opentalking.providers.memory.factory import build_memory_provider
from opentalking.providers.memory.runtime import MemoryRuntime, normalize_memory_scope
from opentalking.providers.memory.sqlite_provider import SQLiteMemoryProvider

router = APIRouter(prefix="/memory", tags=["memory"])


class MemoryLibraryRequest(BaseModel):
    id: str | None = None
    name: str | None = None
    profile_id: str | None = None
    character_id: str


class MemoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class MemoryImportRequest(BaseModel):
    profile_id: str | None = None
    character_id: str
    turns: list[MemoryTurn]
    source: str | None = None


def _profile(value: str | None) -> str:
    return (value or get_settings().memory_default_profile_id or "default").strip() or "default"


def _ensure_character(value: str | None) -> str:
    character_id = (value or "").strip()
    if not character_id:
        raise HTTPException(status_code=400, detail="character_id is required")
    return character_id


def _library_id(value: str | None) -> str:
    return (value or "").strip() or f"lib_{uuid.uuid4().hex[:12]}"


def _wechat_registry(request: Request) -> WeChatImportJobRegistry:
    registry = getattr(request.app.state, "wechat_import_registry", None)
    if registry is not None:
        return registry
    persona_store = getattr(request.app.state, "persona_store", None) or default_persona_store()
    registry = WeChatImportJobRegistry(
        persona_store=persona_store,
        memory_provider=build_memory_provider(),
    )
    request.app.state.wechat_import_registry = registry
    return registry


def _fallback_memory_provider() -> SQLiteMemoryProvider:
    settings = get_settings()
    return SQLiteMemoryProvider(settings.memory_sqlite_path)


async def _memory_provider():
    try:
        return build_memory_provider()
    except Exception:  # noqa: BLE001
        return _fallback_memory_provider()


class WeChatSpeakerSelectionRequest(BaseModel):
    target_speaker_id: str


class WeChatImportCommitRequest(BaseModel):
    persona_id: str
    persona_name: str | None = None
    description: str | None = None


@router.post("/wechat-import")
async def create_wechat_import_job(
    request: Request,
    file: UploadFile | None = File(default=None),
    profile_id: str = Form(default="default"),
    memory_library_id: str = Form(default="default"),
    avatar_id: str = Form(default=""),
    avatar_model: str = Form(default="mock"),
    character_id: str | None = Form(default=None),
    target_speaker_id: str | None = Form(default=None),
    source_format: str = Form(default="auto"),
    timezone: str = Form(default="Asia/Shanghai"),
    source_url: str | None = Form(default=None),
) -> dict[str, object]:
    if (source_url or "").strip():
        raise HTTPException(status_code=400, detail="please upload a WeFlow export file; API URLs are not supported")
    if file is None:
        raise HTTPException(status_code=400, detail="WeFlow export file upload is required")
    clean_avatar_id = (avatar_id or "").strip()
    if not clean_avatar_id:
        raise HTTPException(status_code=400, detail="avatar_id is required")
    suffix = Path(file.filename or "").suffix or ".json"
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="opentalking-wechat-upload-", suffix=suffix, delete=False) as tmp:
            tmp.write(await file.read())
            tmp_path = Path(tmp.name)
        job = await _wechat_registry(request).create_job_async(
            tmp_path,
            profile_id=profile_id,
            memory_library_id=memory_library_id,
            avatar_id=clean_avatar_id,
            avatar_model=(avatar_model or "mock").strip() or "mock",
            character_id=character_id,
            target_speaker_id=target_speaker_id,
            source_format=source_format,
            timezone=timezone,
        )
        return job.to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass


@router.get("/wechat-import/{job_id}")
async def get_wechat_import_job(request: Request, job_id: str) -> dict[str, object]:
    try:
        return _wechat_registry(request).get_job(job_id).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="wechat import job not found") from exc


@router.post("/wechat-import/{job_id}/speaker")
async def select_wechat_import_speaker(
    request: Request,
    job_id: str,
    body: WeChatSpeakerSelectionRequest,
) -> dict[str, object]:
    try:
        return (await _wechat_registry(request).select_speaker_async(job_id, body.target_speaker_id)).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="wechat import job not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wechat-import/{job_id}/commit")
async def commit_wechat_import_job(
    request: Request,
    job_id: str,
    body: WeChatImportCommitRequest,
) -> dict[str, object]:
    try:
        result = await _wechat_registry(request).commit(
            job_id,
            persona_id=body.persona_id,
            persona_name=body.persona_name,
            description=body.description,
        )
        return asdict(result)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="wechat import job not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/libraries")
async def list_libraries(
    profile_id: str = Query("default"),
    character_id: str = Query(...),
) -> dict[str, list[dict[str, object]]]:
    provider = await _memory_provider()
    items = await provider.list_libraries(
        profile_id=_profile(profile_id),
        character_id=_ensure_character(character_id),
    )
    return {"items": [asdict(item) for item in items]}


@router.post("/libraries")
async def create_library(body: MemoryLibraryRequest) -> dict[str, object]:
    provider = await _memory_provider()
    library = await provider.create_library(
        library_id=_library_id(body.id),
        name=(body.name or "").strip() or None,
        profile_id=_profile(body.profile_id),
        character_id=_ensure_character(body.character_id),
    )
    return asdict(library)


@router.get("/libraries/{library_id}/items")
async def list_items(
    library_id: str,
    profile_id: str = Query("default"),
    character_id: str = Query(...),
) -> dict[str, list[dict[str, object]]]:
    provider = await _memory_provider()
    items = await provider.list_items(
        library_id=library_id,
        profile_id=_profile(profile_id),
        character_id=_ensure_character(character_id),
    )
    return {"items": [asdict(item) for item in items]}


@router.delete("/libraries/{library_id}/items/{item_id}")
async def delete_item(
    library_id: str,
    item_id: str,
    profile_id: str = Query("default"),
    character_id: str = Query(...),
) -> dict[str, bool]:
    provider = await _memory_provider()
    deleted = await provider.delete_item(
        library_id=library_id,
        item_id=item_id,
        profile_id=_profile(profile_id),
        character_id=_ensure_character(character_id),
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="memory item not found")
    return {"deleted": True}


@router.post("/libraries/{library_id}/import")
async def import_items(library_id: str, body: MemoryImportRequest) -> dict[str, int]:
    scope = normalize_memory_scope(
        memory_enabled=True,
        profile_id=body.profile_id,
        character_id=body.character_id,
        avatar_id=body.character_id,
        library_id=library_id,
    )
    runtime = MemoryRuntime(
        scope=scope,
        provider=await _memory_provider(),
        decision_agent=MemoryDecisionAgent(),
    )
    imported = await runtime.import_turns(
        [turn.model_dump() for turn in body.turns],
        source=body.source,
    )
    return {"imported": imported}
