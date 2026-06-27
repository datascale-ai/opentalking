from __future__ import annotations

from pydantic import BaseModel, Field


class SceneBackgroundAsset(BaseModel):
    id: str
    name: str
    kind: str
    mime_type: str
    filename: str
    size_bytes: int
    url: str
    created_at: str


class SceneComposition(BaseModel):
    id: str
    name: str
    avatar_id: str
    background_id: str | None = None
    background_color: str = "#0f172a"
    avatar_fit: str = "contain"
    avatar_scale: float = Field(default=1.0, ge=0.5, le=2.0)
    avatar_anchor: str = "center"
    matting_required: bool = False
    subtitle_style: str = "lower-third"
    created_at: str
    updated_at: str


class CreateSceneCompositionRequest(BaseModel):
    name: str
    avatar_id: str
    background_id: str | None = None
    background_color: str = "#0f172a"
    avatar_fit: str = "contain"
    avatar_scale: float = Field(default=1.0, ge=0.5, le=2.0)
    avatar_anchor: str = "center"
    matting_required: bool = False
    subtitle_style: str = "lower-third"


class UpdateSceneCompositionRequest(BaseModel):
    name: str | None = None
    avatar_id: str | None = None
    background_id: str | None = None
    background_color: str | None = None
    avatar_fit: str | None = None
    avatar_scale: float | None = Field(default=None, ge=0.5, le=2.0)
    avatar_anchor: str | None = None
    matting_required: bool | None = None
    subtitle_style: str | None = None
