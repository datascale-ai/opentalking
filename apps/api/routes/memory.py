from __future__ import annotations

from dataclasses import asdict
from typing import Literal
import uuid

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from opentalking.core.config import get_settings
from opentalking.providers.memory.decision_agent import MemoryDecisionAgent
from opentalking.providers.memory.factory import build_memory_provider
from opentalking.providers.memory.runtime import MemoryRuntime, normalize_memory_scope

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


@router.get("/libraries")
async def list_libraries(
    profile_id: str = Query("default"),
    character_id: str = Query(...),
) -> dict[str, list[dict[str, object]]]:
    provider = build_memory_provider()
    items = await provider.list_libraries(
        profile_id=_profile(profile_id),
        character_id=_ensure_character(character_id),
    )
    return {"items": [asdict(item) for item in items]}


@router.post("/libraries")
async def create_library(body: MemoryLibraryRequest) -> dict[str, object]:
    provider = build_memory_provider()
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
    provider = build_memory_provider()
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
    provider = build_memory_provider()
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
        provider=build_memory_provider(),
        decision_agent=MemoryDecisionAgent(),
    )
    imported = await runtime.import_turns(
        [turn.model_dump() for turn in body.turns],
        source=body.source,
    )
    return {"imported": imported}
