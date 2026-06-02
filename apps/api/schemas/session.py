from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    avatar_id: str = Field(..., examples=["singer"])
    model: str = Field(..., examples=["wav2lip"])
    tts_provider: str | None = None
    stt_provider: str | None = None
    tts_voice: str | None = None
    llm_system_prompt: str | None = None
    wav2lip_postprocess_mode: str | None = None
    fasterliveportrait_config: dict[str, Any] | None = None


class FasterLivePortraitConfigRequest(BaseModel):
    head_motion_multiplier: float | None = None
    pose_motion_multiplier: float | None = None
    yaw_multiplier: float | None = None
    pitch_multiplier: float | None = None
    roll_multiplier: float | None = None
    expression_multiplier: float | None = None
    mouth_open_multiplier: float | None = None
    mouth_corner_multiplier: float | None = None
    cheek_jaw_multiplier: float | None = None
    driving_multiplier: float | None = None
    cfg_scale: float | None = None
    animation_region: str | None = None
    flag_stitching: bool | None = None
    flag_pasteback: bool | None = None
    flag_relative_motion: bool | None = None
    flag_normalize_lip: bool | None = None
    flag_lip_retargeting: bool | None = None


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


class WebRTCOfferRequest(BaseModel):
    sdp: str
    type: str
