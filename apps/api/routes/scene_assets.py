from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from apps.api.schemas.scene_assets import (
    CreateSceneCompositionRequest,
    UpdateSceneCompositionRequest,
)
from opentalking.scene_assets import SceneAssetStore


router = APIRouter(prefix="/scene-assets", tags=["scene-assets"])


def _store(request: Request) -> SceneAssetStore:
    settings = request.app.state.settings
    root = Path(getattr(settings, "scene_assets_dir", "./data/scene-assets"))
    return SceneAssetStore(root)


@router.get("/backgrounds", response_model=None)
async def list_backgrounds(request: Request) -> dict[str, object]:
    return {"items": _store(request).list_backgrounds()}


@router.post("/backgrounds", response_model=None)
async def upload_background(
    request: Request,
    file: UploadFile = File(...),
    name: str = Form(""),
) -> dict[str, object]:
    max_bytes = int(getattr(request.app.state.settings, "scene_asset_max_bytes", 200 * 1024 * 1024))
    content = await file.read(max_bytes + 1)
    if not content:
        raise HTTPException(status_code=400, detail="empty background asset")
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail="background asset exceeds size limit")
    try:
        return _store(request).create_background(
            content=content,
            filename=file.filename or "background",
            mime_type=file.content_type or "application/octet-stream",
            name=name or Path(file.filename or "background").stem,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/backgrounds/{background_id}/file", response_model=None)
async def download_background(background_id: str, request: Request) -> FileResponse:
    store = _store(request)
    path = store.background_file_path(background_id)
    if path is None:
        raise HTTPException(status_code=404, detail="background not found")
    item = next((entry for entry in store.list_backgrounds() if entry.get("id") == background_id), None)
    return FileResponse(path, media_type=str(item.get("mime_type") if item else "application/octet-stream"))


@router.delete("/backgrounds/{background_id}", response_model=None)
async def delete_background(background_id: str, request: Request) -> dict[str, object]:
    deleted = _store(request).delete_background(background_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="background not found")
    return {"id": background_id, "deleted": True}


@router.get("/compositions", response_model=None)
async def list_compositions(request: Request) -> dict[str, object]:
    return {"items": _store(request).list_compositions()}


@router.post("/compositions", response_model=None)
async def create_composition(payload: CreateSceneCompositionRequest, request: Request) -> dict[str, object]:
    try:
        return _store(request).create_composition(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/compositions/{composition_id}", response_model=None)
async def update_composition(
    composition_id: str,
    payload: UpdateSceneCompositionRequest,
    request: Request,
) -> dict[str, object]:
    data = payload.model_dump(exclude_unset=True)
    try:
        updated = _store(request).update_composition(composition_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="composition not found")
    return updated


@router.delete("/compositions/{composition_id}", response_model=None)
async def delete_composition(composition_id: str, request: Request) -> dict[str, object]:
    deleted = _store(request).delete_composition(composition_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="composition not found")
    return {"id": composition_id, "deleted": True}
