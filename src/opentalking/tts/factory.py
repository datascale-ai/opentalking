from __future__ import annotations

import logging
from pathlib import Path

from opentalking.core.config import Settings, get_settings
from opentalking.core.interfaces.tts_adapter import TTSAdapter
from opentalking.tts.cosyvoice import CosyVoiceAdapter, cosyvoice_runtime_available
from opentalking.tts.coqui import CoquiXTTSAdapter, xtts_runtime_available
from opentalking.tts.edge.adapter import EdgeTTSAdapter
from opentalking.tts.elevenlabs.adapter import ElevenLabsTTSAdapter

log = logging.getLogger(__name__)


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

    if provider == "cosyvoice":
        ref_path = Path(settings.tts_clone_reference_audio).expanduser()
        repo_dir = Path(settings.tts_cosyvoice_repo_dir).expanduser()
        model_dir = Path(settings.tts_cosyvoice_model_dir).expanduser()
        available, error = cosyvoice_runtime_available(repo_dir)
        if not available:
            raise RuntimeError("CosyVoice runtime unavailable") from error
        return CosyVoiceAdapter(
            model_dir=model_dir,
            repo_dir=repo_dir,
            reference_audio=ref_path,
            mode=settings.tts_cosyvoice_mode,
            prompt_source=settings.tts_cosyvoice_prompt_source,
            prompt_prefix=settings.tts_cosyvoice_prompt_prefix,
            prompt_text=settings.tts_cosyvoice_prompt_text,
            prompt_max_seconds=settings.tts_cosyvoice_prompt_max_seconds,
            sample_rate=sample_rate,
            chunk_ms=chunk_ms,
            speed=settings.tts_cosyvoice_speed,
            asr_model_path=Path(settings.tts_asr_model_path).expanduser(),
            asr_language=settings.tts_asr_language,
            cache_dir=Path(settings.tts_clone_cache_dir).expanduser(),
            ffmpeg_bin=settings.ffmpeg_bin,
        )

    if provider in {"auto", "xtts"}:
        ref_path = Path(settings.tts_clone_reference_audio).expanduser()
        if ref_path.is_file():
            try:
                if not settings.tts_xtts_python_bin.strip():
                    available, error = xtts_runtime_available()
                    if not available:
                        raise RuntimeError("XTTS runtime unavailable") from error
                return CoquiXTTSAdapter(
                    model_name=settings.tts_clone_model_name,
                    language=settings.tts_language,
                    reference_audio=ref_path,
                    sample_rate=sample_rate,
                    chunk_ms=chunk_ms,
                    device=settings.tts_clone_device,
                    cache_dir=Path(settings.tts_clone_cache_dir).expanduser(),
                    ffmpeg_bin=settings.ffmpeg_bin,
                    python_bin=settings.tts_xtts_python_bin,
                )
            except Exception:
                if provider == "xtts":
                    raise
                log.warning(
                    "XTTS voice cloning unavailable, falling back to Edge TTS",
                    exc_info=True,
                )
        elif provider == "xtts":
            raise RuntimeError(
                "XTTS is enabled but the reference audio does not exist: "
                f"{ref_path}"
            )

    return _build_edge_adapter(settings=settings, sample_rate=sample_rate, chunk_ms=chunk_ms)
