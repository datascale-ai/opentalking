from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class AvatarSummary(BaseModel):
    id: str
    name: Optional[str] = None
    model_type: str
    width: int
    height: int
    # True for avatars created via POST /avatars/custom; only these are deletable.
    is_custom: bool = False
    has_preview_video: bool = False
    matting_status: str = "unknown"
