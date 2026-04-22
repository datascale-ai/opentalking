from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class AvatarSummary(BaseModel):
    id: str
    name: Optional[str] = None
    manifest_id: Optional[str] = None
    model_type: str
    width: int
    height: int
