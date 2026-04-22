from __future__ import annotations

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    avatar_id: str = Field(..., examples=["demo-wav2lip"])
    model: str = Field(..., examples=["wav2lip"])
    tts_provider: str | None = None
    tts_voice: str | None = None


class CreateSessionResponse(BaseModel):
    session_id: str
    status: str = "created"


class SpeakRequest(BaseModel):
    text: str


class WebRTCOfferRequest(BaseModel):
    sdp: str
    type: str
