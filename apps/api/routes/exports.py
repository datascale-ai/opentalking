from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from opentalking.export_store import (
    ExportTooLargeError,
    create_video_export,
    delete_video_export,
    get_video_export,
    list_video_exports,
)

router = APIRouter(prefix="/exports", tags=["exports"])


def _exports_root(request: Request) -> Path:
    settings = request.app.state.settings
    return Path(getattr(settings, "exports_dir", "./data/exports")).expanduser().resolve()


def _export_max_bytes(request: Request) -> int:
    settings = request.app.state.settings
    try:
        return int(getattr(settings, "export_max_bytes", 1024 * 1024 * 1024))
    except (TypeError, ValueError):
        return 1024 * 1024 * 1024


def _with_download_url(item: dict[str, object]) -> dict[str, object]:
    export_id = str(item["id"])
    return {**item, "download_url": f"/exports/videos/{export_id}/download"}


@router.post("/videos", response_model=None)
async def upload_export_video(
    request: Request,
    file: UploadFile = File(...),
    kind: str = Form(...),
    title: str = Form(""),
    duration_sec: float | None = Form(default=None),
    session_id: str | None = Form(default=None),
    avatar_id: str | None = Form(default=None),
    model: str | None = Form(default=None),
) -> dict[str, object]:
    content = await file.read()
    try:
        item = create_video_export(
            _exports_root(request),
            content=content,
            mime_type=file.content_type or "application/octet-stream",
            kind=kind,
            title=title,
            duration_sec=duration_sec,
            session_id=session_id,
            avatar_id=avatar_id,
            model=model,
            max_bytes=_export_max_bytes(request),
        )
    except ExportTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _with_download_url(item)


@router.get("/videos", response_model=None)
async def list_export_videos(
    request: Request,
    kind: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    try:
        items = list_video_exports(_exports_root(request), kind=kind, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"items": [_with_download_url(item) for item in items]}


@router.get("/videos/{export_id}", response_model=None)
async def get_export_video(export_id: str, request: Request) -> dict[str, object]:
    try:
        item = get_video_export(_exports_root(request), export_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="export not found")
    return _with_download_url(item)


@router.get("/videos/{export_id}/download", response_model=None)
async def download_export_video(export_id: str, request: Request) -> FileResponse:
    try:
        item = get_video_export(_exports_root(request), export_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="export not found")
    path = Path(str(item["path"])).resolve()
    if not path.is_file():
        raise HTTPException(status_code=404, detail="export file missing")
    filename = f"{item['id']}{path.suffix}"
    return FileResponse(path, media_type=str(item.get("mime_type") or "video/webm"), filename=filename)


@router.delete("/videos/{export_id}", response_model=None)
async def delete_export_video(export_id: str, request: Request) -> dict[str, object]:
    try:
        deleted = delete_video_export(_exports_root(request), export_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="export not found")
    return {"id": export_id, "deleted": True}
