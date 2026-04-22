from __future__ import annotations

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    avatar_id: str = Field(..., examples=["demo-avatar"])
    model: str = Field(..., examples=["wav2lip"])


class CreateSessionResponse(BaseModel):
    session_id: str
    status: str = "created"


class SpeakRequest(BaseModel):
    text: str
    voice: str | None = Field(
        default=None,
        description=(
            "Edge：zh-CN-* Neural 短名；百炼：音色名（Qwen/CosyVoice/MiniMax 等与控制台一致）；不传则用服务端默认。"
        ),
    )
    tts_provider: str | None = Field(
        default=None,
        description=(
            "edge | dashscope | cosyvoice | minimax | sambert | bailian | qwen | "
            "qwen_tts；不传则用 OPENTALKING_TTS_PROVIDER"
        ),
    )
    tts_model: str | None = Field(
        default=None,
        description="百炼各线路均有：如 qwen3-tts-flash-realtime、cosyvoice-v3-flash、MiniMax/speech-02-turbo、sambert-zhichu-v1",
    )


class WebRTCOfferRequest(BaseModel):
    sdp: str
    type: str
