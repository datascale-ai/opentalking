from __future__ import annotations

from fastapi import APIRouter, Request

from apps.api.schemas.tts import TTSVoiceOption
from opentalking.tts.elevenlabs import list_elevenlabs_voices

router = APIRouter(prefix="/tts", tags=["tts"])


@router.get("/voices", response_model=list[TTSVoiceOption])
async def list_tts_voices(request: Request) -> list[TTSVoiceOption]:
    settings = request.app.state.settings
    edge_options: list[TTSVoiceOption] = [
        TTSVoiceOption(
            id="edge:zh-CN-XiaoxiaoNeural",
            label="Edge 晓晓",
            provider="edge",
            voice="zh-CN-XiaoxiaoNeural",
            description="默认在线女声，不使用参考音频。",
        ),
        TTSVoiceOption(
            id="edge:zh-CN-YunxiNeural",
            label="Edge 云希",
            provider="edge",
            voice="zh-CN-YunxiNeural",
            description="默认在线男声，不使用参考音频。",
        ),
    ]
    elevenlabs_options: list[TTSVoiceOption] = []
    options: list[TTSVoiceOption] = []

    if settings.tts_elevenlabs_api_key.strip():
        try:
            for voice in await list_elevenlabs_voices(
                api_key=settings.tts_elevenlabs_api_key,
                base_url=settings.tts_elevenlabs_base_url,
            ):
                elevenlabs_options.append(
                    TTSVoiceOption(
                        id=f"elevenlabs:{voice['voice_id']}",
                        label=f"ElevenLabs {voice['name']}",
                        provider="elevenlabs",
                        voice=voice["voice_id"],
                        description=voice["description"],
                    )
                )
        except Exception:
            if settings.tts_elevenlabs_voice_id.strip():
                elevenlabs_options.append(
                    TTSVoiceOption(
                        id=f"elevenlabs:{settings.tts_elevenlabs_voice_id}",
                        label="ElevenLabs 默认声线",
                        provider="elevenlabs",
                        voice=settings.tts_elevenlabs_voice_id,
                        description="ElevenLabs 在线声线（回退配置项）",
                    )
                )

    if settings.normalized_tts_provider == "elevenlabs":
        options.extend(elevenlabs_options)
        options.extend(edge_options)
    else:
        options.extend(edge_options)
        options.extend(elevenlabs_options)
    return options
