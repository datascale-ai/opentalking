from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    persona_id: str | None = None
    avatar_id: str | None = Field(default=None, examples=["singer"])
    model: str | None = Field(default=None, examples=["wav2lip"])
    tts_provider: str | None = None
    stt_provider: str | None = None
    tts_voice: str | None = None
    llm_system_prompt: str | None = None
    wav2lip_postprocess_mode: str | None = None
    fasterliveportrait_config: dict[str, Any] | None = None
    user_id: str | None = None
    agent_enabled: bool = True
    memory_enabled: bool = False
    knowledge_enabled: bool = True
    knowledge_base_id: str | None = None
    knowledge_base_ids: list[str] | None = None


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


class SessionKnowledgeBasesRequest(BaseModel):
    knowledge_base_ids: list[str] = Field(default_factory=list)


class SessionKnowledgeBasesResponse(BaseModel):
    session_id: str
    knowledge_base_ids: list[str]


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
            "edge | elevenlabs | openai_compatible | xiaomi_mimo | dashscope | cosyvoice | sambert | bailian | qwen | "
            "qwen_tts；不传则用 OPENTALKING_TTS_PROVIDER"
        ),
    )
    tts_model: str | None = Field(
        default=None,
        description="TTS 模型覆盖：如 qwen3-tts-flash-realtime、cosyvoice-v3-flash、mimo-v2.5-tts、mimo-v2.5-tts-voiceclone、eleven_flash_v2_5",
    )


class WebRTCOfferRequest(BaseModel):
    sdp: str
    type: str
