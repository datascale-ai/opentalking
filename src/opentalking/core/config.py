from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _flatten_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    if not raw:
        return {}

    flattened: dict[str, Any] = {}
    section_map = {
        "api": {"host": "api_host", "port": "api_port", "cors_origins": "cors_origins"},
        "infrastructure": {
            "redis_url": "redis_url",
            "avatars_dir": "avatars_dir",
            "models_dir": "models_dir",
            "worker_url": "worker_url",
        },
        "flashtalk": {
            "mode": "flashtalk_mode",
            "ws_url": "flashtalk_ws_url",
            "ckpt_dir": "flashtalk_ckpt_dir",
            "wav2vec_dir": "flashtalk_wav2vec_dir",
            "port": "flashtalk_port",
            "device": "flashtalk_device",
            "gpu_count": "flashtalk_gpu_count",
            "jpeg_quality": "flashtalk_jpeg_quality",
        },
        "llm": {
            "base_url": "llm_base_url",
            "api_key": "llm_api_key",
            "model": "llm_model",
            "system_prompt": "llm_system_prompt",
        },
        "tts": {
            "provider": "tts_provider",
            "voice": "tts_voice",
            "sample_rate": "tts_sample_rate",
            "streaming_decode": "tts_streaming_decode",
            "elevenlabs_api_key": "tts_elevenlabs_api_key",
            "elevenlabs_base_url": "tts_elevenlabs_base_url",
            "elevenlabs_model_id": "tts_elevenlabs_model_id",
            "elevenlabs_voice_id": "tts_elevenlabs_voice_id",
            "elevenlabs_output_format": "tts_elevenlabs_output_format",
        },
        "model": {"torch_device": "torch_device", "default_model": "default_model"},
    }

    for key, value in raw.items():
        if key in section_map and isinstance(value, dict):
            for inner_key, inner_value in value.items():
                mapped_key = section_map[key].get(inner_key)
                if mapped_key:
                    if mapped_key == "flashtalk_mode" and isinstance(inner_value, bool):
                        inner_value = "remote" if inner_value else "off"
                    flattened[mapped_key] = inner_value
            continue
        flattened[key] = value
    return flattened


def _load_yaml_source() -> dict[str, Any]:
    config_file = (
        os.environ.get("OPENTALKING_CONFIG_FILE")
        or os.environ.get("CONFIG_FILE")
        or "./configs/default.yaml"
    )
    path = Path(config_file).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if not path.is_file():
        return {}
    return _flatten_config(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def _load_legacy_env_source() -> dict[str, Any]:
    mapping = {
        "FLASHTALK_WS_URL": "flashtalk_ws_url",
        "FLASHTALK_FRAME_NUM": "flashtalk_frame_num",
        "FLASHTALK_MOTION_FRAMES_NUM": "flashtalk_motion_frames_num",
        "FLASHTALK_SAMPLE_STEPS": "flashtalk_sample_steps",
        "FLASHTALK_SAMPLE_SHIFT": "flashtalk_sample_shift",
        "FLASHTALK_COLOR_CORRECTION_STRENGTH": "flashtalk_color_correction_strength",
        "FLASHTALK_HEIGHT": "flashtalk_height",
        "FLASHTALK_WIDTH": "flashtalk_width",
        "FLASHTALK_SAMPLE_RATE": "flashtalk_sample_rate",
        "FLASHTALK_TGT_FPS": "flashtalk_tgt_fps",
        "FLASHTALK_CACHED_AUDIO_DURATION": "flashtalk_cached_audio_duration",
        "FLASHTALK_JPEG_QUALITY": "flashtalk_jpeg_quality",
        "FLASHTALK_JPEG_WORKERS": "flashtalk_jpeg_workers",
        "FLASHTALK_JPEG_DECODE_WORKERS": "flashtalk_jpeg_decode_workers",
        "FLASHTALK_AUDIO_LOUDNESS_NORM": "flashtalk_audio_loudness_norm",
        "FLASHTALK_IDLE_CACHE_CHUNKS": "flashtalk_idle_cache_chunks",
        "FLASHTALK_IDLE_PROMPT": "flashtalk_idle_prompt",
        "FLASHTALK_IDLE_SEED": "flashtalk_idle_seed",
        "FLASHTALK_IDLE_ENABLE": "flashtalk_idle_enable",
        "FLASHTALK_IDLE_SOURCE": "flashtalk_idle_source",
        "FLASHTALK_IDLE_CACHE_DIR": "flashtalk_idle_cache_dir",
        "FLASHTALK_IDLE_MOUTH_LOCK": "flashtalk_idle_mouth_lock",
        "FLASHTALK_IDLE_EYE_LOCK": "flashtalk_idle_eye_lock",
        "FLASHTALK_PREBUFFER_CHUNKS": "flashtalk_prebuffer_chunks",
        "FLASHTALK_TTS_BOUNDARY_FADE_MS": "flashtalk_tts_boundary_fade_ms",
        "FLASHTALK_TTS_COALESCE_MIN_CHARS": "flashtalk_tts_coalesce_min_chars",
        "FLASHTALK_TTS_COALESCE_MAX_CHARS": "flashtalk_tts_coalesce_max_chars",
        "FLASHTALK_TTS_TAIL_FADE_MS": "flashtalk_tts_tail_fade_ms",
        "FLASHTALK_TTS_TRAILING_SILENCE_MS": "flashtalk_tts_trailing_silence_ms",
        "FLASHTALK_TTS_OPENER_ENABLE": "flashtalk_tts_opener_enable",
        "FLASHTALK_TTS_OPENER_PRELOAD": "flashtalk_tts_opener_preload",
        "FLASHTALK_TTS_OPENER_MIN_FILL_RATIO": "flashtalk_tts_opener_min_fill_ratio",
        "FLASHTALK_TTS_OPENER_PAD_TO_CHUNK": "flashtalk_tts_opener_pad_to_chunk",
        "FLASHTALK_TTS_OPENER_MAX_HISTORY": "flashtalk_tts_opener_max_history",
        "DASHSCOPE_API_KEY": "llm_api_key",
        "DASHSCOPE_MODEL": "llm_model",
        "LLM_SYSTEM_PROMPT": "llm_system_prompt",
        "ELEVENLABS_API_KEY": "tts_elevenlabs_api_key",
        "ELEVENLABS_BASE_URL": "tts_elevenlabs_base_url",
        "ELEVENLABS_MODEL_ID": "tts_elevenlabs_model_id",
        "ELEVENLABS_VOICE_ID": "tts_elevenlabs_voice_id",
        "ELEVENLABS_OUTPUT_FORMAT": "tts_elevenlabs_output_format",
    }
    return {target: os.environ[name] for name, target in mapping.items() if name in os.environ}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OPENTALKING_",
        env_file=".env",
        extra="ignore",
    )

    log_level: str = "INFO"
    config_file: str = Field(default="./configs/default.yaml")

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str | list[str] = "*"

    redis_url: str = "redis://localhost:6379/0"
    avatars_dir: str = "./examples/avatars"
    models_dir: str = "./models"
    worker_url: str = "http://127.0.0.1:9001"

    flashtalk_mode: str = "off"
    flashtalk_ws_url: str = f"ws://{os.environ.get('SERVER_HOST', 'localhost')}:8765"
    flashtalk_ckpt_dir: str = "./models/SoulX-FlashTalk-14B"
    flashtalk_wav2vec_dir: str = "./models/chinese-wav2vec2-base"
    flashtalk_port: int = 8765
    flashtalk_device: str = "auto"
    flashtalk_gpu_count: int = 8
    flashtalk_frame_num: int = 33
    flashtalk_motion_frames_num: int = 5
    flashtalk_sample_steps: int = 2
    flashtalk_sample_shift: int = 5
    flashtalk_color_correction_strength: float = 0.0
    flashtalk_height: int = 704
    flashtalk_width: int = 416
    flashtalk_sample_rate: int = 16000
    flashtalk_tgt_fps: int = 25
    flashtalk_cached_audio_duration: int = 8
    flashtalk_jpeg_quality: int = 55
    flashtalk_jpeg_workers: int = 4
    flashtalk_jpeg_decode_workers: int = 4
    flashtalk_audio_loudness_norm: int = 0
    flashtalk_idle_cache_chunks: int = 4
    # Idle clip (IdleVideoGenerator): read from .env via OPENTALKING_FLASHTALK_IDLE_* only
    # when declared here — pydantic does not put unknown keys into os.environ.
    flashtalk_idle_enable: bool = True
    flashtalk_idle_source: str = "generated"
    flashtalk_idle_cache_dir: str | None = None
    flashtalk_idle_prompt: str | None = None
    flashtalk_idle_seed: int = 9999
    flashtalk_idle_mouth_lock: float = 0.97
    flashtalk_idle_eye_lock: float = 0.65
    flashtalk_prebuffer_chunks: int = 1
    flashtalk_tts_boundary_fade_ms: float = 18.0
    flashtalk_tts_coalesce_min_chars: int = 6
    flashtalk_tts_coalesce_max_chars: int = 80
    flashtalk_tts_tail_fade_ms: float = 80.0
    flashtalk_tts_trailing_silence_ms: float = 320.0
    flashtalk_tts_opener_enable: bool = False
    flashtalk_tts_opener_preload: bool = False
    flashtalk_tts_opener_min_fill_ratio: float = 0.78
    flashtalk_tts_opener_pad_to_chunk: bool = True
    flashtalk_tts_opener_max_history: int = 2

    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "qwen-turbo"
    llm_system_prompt: str = "You are a friendly digital human assistant."

    #: edge | dashscope | bailian | qwen | qwen_tts | cosyvoice | sambert（OPENTALKING_TTS_PROVIDER）
    tts_provider: str = Field(default="edge")

    #: 音色目录 SQLite；默认 ./data/opentalking.sqlite3
    sqlite_path: str = Field(default="./data/opentalking.sqlite3")

    #: CosyVoice 复刻时，百炼需拉取公网 URL；若留空则用请求的 Host 拼 URL（内网部署请填公网可达地址）
    public_base_url: str = ""

    tts_voice: str = "zh-CN-XiaoxiaoNeural"
    tts_sample_rate: int = 16000
    tts_streaming_decode: bool = True
    tts_elevenlabs_api_key: str = ""
    tts_elevenlabs_base_url: str = "https://api.elevenlabs.io"
    tts_elevenlabs_model_id: str = "eleven_flash_v2_5"
    tts_elevenlabs_voice_id: str = ""
    tts_elevenlabs_output_format: str = "mp3_22050_32"
    ffmpeg_bin: str = "ffmpeg"

    torch_device: str = "cpu"
    default_model: str = "wav2lip"
    default_fps: int = 25

    # FlashTalk slot queue: max sessions waiting behind the active one (0 = unlimited)
    flashtalk_max_queue_size: int = 3
    # Seconds a session may wait in queue before being rejected (0 = no timeout)
    flashtalk_slot_timeout_sec: int = 3600
    # Max seconds a single session may hold the FlashTalk slot (0 = unlimited)
    # When exceeded the session is force-closed and the slot is released.
    flashtalk_max_session_sec: int = 600

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _load_yaml_source,
            _load_legacy_env_source,
            file_secret_settings,
        )

    @property
    def cors_origin_list(self) -> list[str]:
        if isinstance(self.cors_origins, list):
            origins = [str(origin).strip() for origin in self.cors_origins if str(origin).strip()]
            return origins or ["*"]
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def normalized_flashtalk_mode(self) -> str:
        mode = self.flashtalk_mode.strip().lower()
        if mode in {"remote", "local", "off"}:
            return mode
        return "off"

    @property
    def normalized_tts_provider(self) -> str:
        from opentalking.tts.providers import normalize_tts_provider

        try:
            provider = normalize_tts_provider(self.tts_provider, default="edge")
        except ValueError:
            return "auto"
        return provider or "edge"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
