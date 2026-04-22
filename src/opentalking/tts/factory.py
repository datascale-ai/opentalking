from __future__ import annotations

from opentalking.core.config import Settings, get_settings
from opentalking.core.interfaces.tts_adapter import TTSAdapter
from opentalking.tts.edge.adapter import EdgeTTSAdapter
from opentalking.tts.elevenlabs.adapter import ElevenLabsTTSAdapter


def _build_edge_adapter(
    *,
    settings: Settings,
    sample_rate: int,
    chunk_ms: float,
) -> EdgeTTSAdapter:
    return EdgeTTSAdapter(
        default_voice=settings.tts_voice,
        sample_rate=sample_rate,
        chunk_ms=chunk_ms,
    )


def _build_elevenlabs_adapter(
    *,
    settings: Settings,
    sample_rate: int,
    chunk_ms: float,
) -> ElevenLabsTTSAdapter:
    if not settings.tts_elevenlabs_api_key.strip():
        raise RuntimeError("ElevenLabs provider selected but OPENTALKING_TTS_ELEVENLABS_API_KEY is empty.")
    if not settings.tts_elevenlabs_voice_id.strip():
        raise RuntimeError("ElevenLabs provider selected but OPENTALKING_TTS_ELEVENLABS_VOICE_ID is empty.")
    return ElevenLabsTTSAdapter(
        api_key=settings.tts_elevenlabs_api_key,
        default_voice=settings.tts_elevenlabs_voice_id,
        base_url=settings.tts_elevenlabs_base_url,
        model_id=settings.tts_elevenlabs_model_id,
        output_format=settings.tts_elevenlabs_output_format,
        sample_rate=sample_rate,
        chunk_ms=chunk_ms,
    )


def build_tts_adapter(
    *,
    sample_rate: int,
    chunk_ms: float,
    settings: Settings | None = None,
) -> TTSAdapter:
    settings = settings or get_settings()
    provider = settings.normalized_tts_provider

    if provider == "edge":
        return _build_edge_adapter(settings=settings, sample_rate=sample_rate, chunk_ms=chunk_ms)

    if provider == "elevenlabs":
        return _build_elevenlabs_adapter(settings=settings, sample_rate=sample_rate, chunk_ms=chunk_ms)

    return _build_edge_adapter(settings=settings, sample_rate=sample_rate, chunk_ms=chunk_ms)
