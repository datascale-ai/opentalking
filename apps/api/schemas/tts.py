from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class TTSVoiceOption(BaseModel):
    id: str
    label: str
    provider: str
    voice: Optional[str] = None
    reference_audio: Optional[str] = None
    description: Optional[str] = None
