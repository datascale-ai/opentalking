from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CreateSessionRequest(BaseModel):
    persona_id: str | None = None
    avatar_id: str | None = Field(default=None, examples=["singer"])
    model: str | None = Field(default=None, examples=["wav2lip"])
    tts_provider: str | None = None
    stt_provider: str | None = None
    tts_voice: str | None = None
    tts_model: str | None = None
    llm_system_prompt: str | None = None
    wav2lip_postprocess_mode: str | None = None
    fasterliveportrait_config: dict[str, Any] | None = None
    user_id: str | None = None
    agent_enabled: bool = True
    memory_enabled: bool = False
    memory_profile_id: str | None = None
    character_id: str | None = None
    memory_library_id: str | None = None
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
    mode: str = Field(default="replace", description="首版仅支持 replace")
    command_id: str | None = Field(default=None, description="幂等命令 ID")
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


class RTMPSOutputTransport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: str = Field(min_length=1)
    stream_key: str = Field(min_length=1)
    username: str | None = None
    password: str | None = None
    tls_verify: bool | None = None


class WHIPOutputTransport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: str = Field(min_length=1)
    bearer_token: str = Field(min_length=1)
    tls_verify: bool | None = None


class SessionOutputRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["rtmps", "whip"]
    name: str = ""
    auto_connect: bool = False
    transport: RTMPSOutputTransport | WHIPOutputTransport
    profile: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_transport(self) -> "SessionOutputRequest":
        expected = RTMPSOutputTransport if self.type == "rtmps" else WHIPOutputTransport
        if not isinstance(self.transport, expected):
            raise ValueError(f"{self.type} transport fields do not match output type")
        profile_allowed = {"width", "height", "fps", "video_bitrate_kbps", "gop_seconds"}
        if any(str(key) not in profile_allowed for key in self.profile):
            raise ValueError("unsupported profile field")
        return self


class WebRTCOfferRequest(BaseModel):
    sdp: str
    type: str
