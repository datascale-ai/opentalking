from __future__ import annotations

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    avatar_id: str = Field(..., examples=["demo-avatar"])
    model: str = Field(..., examples=["wav2lip"])
    tts_provider: str | None = None
    tts_voice: str | None = None
    llm_system_prompt: str | None = None


class CreateSessionResponse(BaseModel):
    session_id: str
    status: str = "created"


class SpeakRequest(BaseModel):
    text: str
    voice: str | None = Field(
        default=None,
        description=(
            "Edge：zh-CN-* Neural 短名；百炼：音色名（Qwen/CosyVoice 等与控制台一致）；不传则用服务端默认。"
            "ElevenLabs：voice_id。"
        ),
    )
    tts_provider: str | None = Field(
        default=None,
        description=(
            "edge | elevenlabs | dashscope | cosyvoice | sambert | bailian | qwen | "
            "qwen_tts；不传则用 OPENTALKING_TTS_PROVIDER"
        ),
    )
    tts_model: str | None = Field(
        default=None,
        description="百炼各线路或 ElevenLabs 可用：如 qwen3-tts-flash-realtime、cosyvoice-v3-flash、eleven_flash_v2_5",
    )


class ChatRequest(BaseModel):
    prompt: str
    voice: str | None = None
    tts_provider: str | None = None
    tts_model: str | None = None


class WebRTCOfferRequest(BaseModel):
    sdp: str
    type: str
