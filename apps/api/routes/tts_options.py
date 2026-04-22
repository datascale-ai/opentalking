from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request

from apps.api.schemas.tts import TTSVoiceOption
from opentalking.tts.elevenlabs import list_elevenlabs_voices

router = APIRouter(prefix="/tts", tags=["tts"])

_REFERENCE_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg"}


def _voice_root(request: Request) -> Path:
    settings = request.app.state.settings
    return Path(settings.tts_clone_reference_audio).expanduser().resolve().parent


@router.get("/voices", response_model=list[TTSVoiceOption])
async def list_tts_voices(request: Request) -> list[TTSVoiceOption]:
    settings = request.app.state.settings
    voice_root = _voice_root(request)
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

    if voice_root.is_dir():
        for path in sorted(voice_root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in _REFERENCE_AUDIO_SUFFIXES:
                continue
            rel = path.relative_to(voice_root).as_posix()
            options.append(
                TTSVoiceOption(
                    id=f"xtts:{rel}",
                    label=path.stem,
                    provider="xtts",
                    reference_audio=rel,
                    description=f"参考音频: {rel}",
                )
            )
    return options
