from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from opentalking.core.model_paths import local_audio_model_root, model_root


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
        "avatar": {
            "matting_provider": "avatar_matting_provider",
            "matting_device": "avatar_matting_device",
            "matting_model_path": "avatar_matting_model_path",
            "matting_timeout_sec": "avatar_matting_timeout_sec",
        },
        "flashtalk": {
            "ws_url": "flashtalk_ws_url",
            "ckpt_dir": "flashtalk_ckpt_dir",
            "wav2vec_dir": "flashtalk_wav2vec_dir",
            "port": "flashtalk_port",
            "device": "flashtalk_device",
            "gpu_count": "flashtalk_gpu_count",
            "jpeg_quality": "flashtalk_jpeg_quality",
        },
        "flashhead": {
            "ws_url": "flashhead_ws_url",
            "base_url": "flashhead_base_url",
            "model": "flashhead_model",
            "shared_local_dir": "flashhead_shared_local_dir",
            "shared_remote_dir": "flashhead_shared_remote_dir",
            "output_local_dir": "flashhead_output_local_dir",
            "output_remote_dir": "flashhead_output_remote_dir",
            "output_base_url": "flashhead_output_base_url",
            "timeout_sec": "flashhead_timeout_sec",
            "fps": "flashhead_fps",
            "sample_rate": "flashhead_sample_rate",
            "width": "flashhead_width",
            "height": "flashhead_height",
            "frame_num": "flashhead_frame_num",
            "chunk_samples": "flashhead_chunk_samples",
        },
        "llm": {
            "provider": "llm_provider",
            "base_url": "llm_base_url",
            "api_key": "llm_api_key",
            "model": "llm_model",
            "system_prompt": "llm_system_prompt",
        },
        "agent": {
            "memory_sqlite_path": "agent_memory_sqlite_path",
            "knowledge_root": "agent_knowledge_root",
            "persona_root": "persona_root",
            "lightrag_root": "agent_lightrag_root",
            "lightrag_query_mode": "agent_lightrag_query_mode",
            "lightrag_llm_base_url": "agent_lightrag_llm_base_url",
            "lightrag_llm_api_key": "agent_lightrag_llm_api_key",
            "lightrag_llm_model": "agent_lightrag_llm_model",
            "lightrag_embedding_base_url": "agent_lightrag_embedding_base_url",
            "lightrag_embedding_api_key": "agent_lightrag_embedding_api_key",
            "lightrag_embedding_model": "agent_lightrag_embedding_model",
            "lightrag_embedding_dim": "agent_lightrag_embedding_dim",
            "lightrag_embedding_max_token_size": "agent_lightrag_embedding_max_token_size",
            "lightrag_language": "agent_lightrag_language",
            "lightrag_chunk_fallback_enabled": "agent_lightrag_chunk_fallback_enabled",
        },
        "memory": {
            "provider": "memory_provider",
            "enabled": "memory_enabled",
            "default_profile_id": "memory_default_profile_id",
            "default_library_id": "memory_default_library_id",
            "recall_limit": "memory_recall_limit",
            "recall_min_score": "memory_recall_min_score",
            "recall_timeout_ms": "memory_recall_timeout_ms",
            "recall_backend": "memory_recall_backend",
            "write_mode": "memory_write_mode",
            "decision_mode": "memory_decision_mode",
            "decision_timeout_ms": "memory_decision_timeout_ms",
            "smart_write_enabled": "memory_smart_write_enabled",
            "summary_enabled": "memory_summary_enabled",
            "summary_turn_window": "memory_summary_turn_window",
            "summary_max_items": "memory_summary_max_items",
            "mem0_config": "memory_mem0_config",
            "mem0_llm_provider": "memory_mem0_llm_provider",
            "mem0_llm_base_url": "memory_mem0_llm_base_url",
            "mem0_llm_api_key": "memory_mem0_llm_api_key",
            "mem0_llm_model": "memory_mem0_llm_model",
            "mem0_embedder_provider": "memory_mem0_embedder_provider",
            "mem0_embedder_base_url": "memory_mem0_embedder_base_url",
            "mem0_embedder_api_key": "memory_mem0_embedder_api_key",
            "mem0_embedder_model": "memory_mem0_embedder_model",
            "mem0_embedder_embedding_dims": "memory_mem0_embedder_embedding_dims",
            "mem0_vector_store_provider": "memory_mem0_vector_store_provider",
            "mem0_vector_store_collection_name": "memory_mem0_vector_store_collection_name",
            "mem0_vector_store_path": "memory_mem0_vector_store_path",
            "mem0_vector_store_host": "memory_mem0_vector_store_host",
            "mem0_vector_store_port": "memory_mem0_vector_store_port",
            "mem0_vector_store_embedding_model_dims": "memory_mem0_vector_store_embedding_model_dims",
            "sqlite_path": "memory_sqlite_path",
        },
        "tts": {
            "default_provider": "tts_default_provider",
            "enabled_providers": "tts_enabled_providers",
            "provider": "tts_provider",
            "model": "tts_model",
            "api_key": "tts_api_key",
            "voice": "tts_voice",
            "sample_rate": "tts_sample_rate",
            "streaming_decode": "tts_streaming_decode",
            "elevenlabs_api_key": "tts_elevenlabs_api_key",
            "elevenlabs_base_url": "tts_elevenlabs_base_url",
            "elevenlabs_model_id": "tts_elevenlabs_model_id",
            "elevenlabs_voice_id": "tts_elevenlabs_voice_id",
            "elevenlabs_output_format": "tts_elevenlabs_output_format",
            "dashscope_model": "tts_dashscope_model",
            "dashscope_api_key": "tts_dashscope_api_key",
            "dashscope_voice": "tts_dashscope_voice",
            "dashscope_service_url": "tts_dashscope_service_url",
            "cosyvoice_model": "tts_cosyvoice_model",
            "cosyvoice_service_url": "tts_cosyvoice_service_url",
            "sambert_model": "tts_sambert_model",
            "edge_voice": "tts_edge_voice",
            "indextts_backend": "tts_indextts_backend",
            "local_cosyvoice_model": "tts_local_cosyvoice_model",
            "local_cosyvoice_model_dir": "tts_local_cosyvoice_model_dir",
            "local_cosyvoice_runtime_dir": "tts_local_cosyvoice_runtime_dir",
            "local_cosyvoice_service_url": "tts_local_cosyvoice_service_url",
            "local_cosyvoice_service_urls": "tts_local_cosyvoice_service_urls",
            "local_cosyvoice_device": "tts_local_cosyvoice_device",
            "local_cosyvoice_fp16": "tts_local_cosyvoice_fp16",
            "local_cosyvoice_load_jit": "tts_local_cosyvoice_load_jit",
            "local_cosyvoice_load_trt": "tts_local_cosyvoice_load_trt",
            "local_cosyvoice_load_vllm": "tts_local_cosyvoice_load_vllm",
            "local_cosyvoice_trt_concurrent": "tts_local_cosyvoice_trt_concurrent",
            "local_cosyvoice_token_hop_len": "tts_local_cosyvoice_token_hop_len",
            "local_cosyvoice_token_max_hop_len": "tts_local_cosyvoice_token_max_hop_len",
            "local_cosyvoice_stream_scale_factor": "tts_local_cosyvoice_stream_scale_factor",
            "local_cosyvoice_flow_n_timesteps": "tts_local_cosyvoice_flow_n_timesteps",
            "local_cosyvoice_max_token_text_ratio": "tts_local_cosyvoice_max_token_text_ratio",
            "local_cosyvoice_min_token_text_ratio": "tts_local_cosyvoice_min_token_text_ratio",
            "local_cosyvoice_mask_stop_tokens": "tts_local_cosyvoice_mask_stop_tokens",
            "local_f5_tts_model": "tts_local_f5_tts_model",
            "local_f5_tts_model_dir": "tts_local_f5_tts_model_dir",
            "local_f5_tts_runtime_dir": "tts_local_f5_tts_runtime_dir",
            "local_f5_tts_service_url": "tts_local_f5_tts_service_url",
            "local_f5_tts_ckpt_file": "tts_local_f5_tts_ckpt_file",
            "local_f5_tts_vocoder_local_path": "tts_local_f5_tts_vocoder_local_path",
            "local_f5_tts_prompt_audio": "tts_local_f5_tts_prompt_audio",
            "local_f5_tts_prompt_text": "tts_local_f5_tts_prompt_text",
            "local_f5_tts_device": "tts_local_f5_tts_device",
            "local_indextts_model": "tts_local_indextts_model",
            "local_indextts_model_dir": "tts_local_indextts_model_dir",
            "local_indextts_cfg_path": "tts_local_indextts_cfg_path",
            "local_indextts_service_url": "tts_local_indextts_service_url",
            "local_indextts_prompt_audio": "tts_local_indextts_prompt_audio",
            "local_indextts_w2v_bert_dir": "tts_local_indextts_w2v_bert_dir",
            "local_indextts_maskgct_dir": "tts_local_indextts_maskgct_dir",
            "local_indextts_campplus_dir": "tts_local_indextts_campplus_dir",
            "local_indextts_bigvgan_dir": "tts_local_indextts_bigvgan_dir",
            "local_indextts_device": "tts_local_indextts_device",
            "local_indextts_use_fp16": "tts_local_indextts_use_fp16",
            "local_indextts_use_cuda_kernel": "tts_local_indextts_use_cuda_kernel",
            "local_indextts_use_deepspeed": "tts_local_indextts_use_deepspeed",
            "omnirt_indextts_model": "tts_omnirt_indextts_model",
            "omnirt_indextts_service_url": "tts_omnirt_indextts_service_url",
            "omnirt_indextts_streaming": "tts_omnirt_indextts_streaming",
            "omnirt_indextts_streaming_mode": "tts_omnirt_indextts_streaming_mode",
            "omnirt_indextts_max_text_tokens_per_segment": "tts_omnirt_indextts_max_text_tokens_per_segment",
            "omnirt_indextts_quick_streaming_tokens": "tts_omnirt_indextts_quick_streaming_tokens",
            "omnirt_indextts_interval_silence_ms": "tts_omnirt_indextts_interval_silence_ms",
            "omnirt_indextts_token_window_size": "tts_omnirt_indextts_token_window_size",
            "omnirt_indextts_token_window_hop": "tts_omnirt_indextts_token_window_hop",
            "omnirt_indextts_token_window_context": "tts_omnirt_indextts_token_window_context",
            "omnirt_indextts_token_window_overlap_ms": "tts_omnirt_indextts_token_window_overlap_ms",
            "openai_base_url": "tts_openai_base_url",
            "openai_api_key": "tts_openai_api_key",
            "openai_model": "tts_openai_model",
            "openai_voice": "tts_openai_voice",
            "openai_response_format": "tts_openai_response_format",
            "openai_protocol": "tts_openai_protocol",
            "openai_prompt": "tts_openai_prompt",
            "xiaomi_base_url": "tts_xiaomi_base_url",
            "xiaomi_api_key": "tts_xiaomi_api_key",
            "xiaomi_model": "tts_xiaomi_model",
            "xiaomi_voice": "tts_xiaomi_voice",
            "xiaomi_response_format": "tts_xiaomi_response_format",
            "xiaomi_protocol": "tts_xiaomi_protocol",
            "xiaomi_prompt": "tts_xiaomi_prompt",
        },
        "stt": {
            "default_provider": "stt_default_provider",
            "enabled_providers": "stt_enabled_providers",
            "provider": "stt_provider",
            "model": "stt_model",
            "api_key": "stt_api_key",
            "device": "stt_device",
            "sensevoice_model": "stt_sensevoice_model",
            "sensevoice_model_dir": "stt_sensevoice_model_dir",
            "sensevoice_device": "stt_sensevoice_device",
            "dashscope_model": "stt_dashscope_model",
            "dashscope_api_key": "stt_dashscope_api_key",
            "openai_base_url": "stt_openai_base_url",
            "openai_api_key": "stt_openai_api_key",
            "openai_model": "stt_openai_model",
            "openai_language": "stt_openai_language",
            "openai_response_format": "stt_openai_response_format",
            "openai_protocol": "stt_openai_protocol",
            "openai_audio_format": "stt_openai_audio_format",
        },
        "local_audio": {
            "model_root": "local_audio_model_root",
            "device": "local_audio_device",
            "qwen3_tts_model": "local_qwen3_tts_model",
            "qwen3_tts_service_url": "local_qwen3_tts_service_url",
        },
        "model": {"torch_device": "torch_device", "default_model": "default_model"},
    }

    for key, value in raw.items():
        if key == "models":
            flattened[key] = value
            continue
        if key in section_map and isinstance(value, dict):
            for inner_key, inner_value in value.items():
                mapped_key = section_map[key].get(inner_key)
                if mapped_key:
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


def _legacy_env_mapping() -> dict[str, str]:
    return {
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
        "FLASHHEAD_BASE_URL": "flashhead_base_url",
        "FLASHHEAD_WS_URL": "flashhead_ws_url",
        "FLASHHEAD_MODEL": "flashhead_model",
        "FLASHHEAD_SHARED_LOCAL_DIR": "flashhead_shared_local_dir",
        "FLASHHEAD_SHARED_REMOTE_DIR": "flashhead_shared_remote_dir",
        "FLASHHEAD_OUTPUT_LOCAL_DIR": "flashhead_output_local_dir",
        "FLASHHEAD_OUTPUT_REMOTE_DIR": "flashhead_output_remote_dir",
        "FLASHHEAD_OUTPUT_BASE_URL": "flashhead_output_base_url",
        "FLASHHEAD_TIMEOUT_SEC": "flashhead_timeout_sec",
        "FLASHHEAD_FPS": "flashhead_fps",
        "FLASHHEAD_SAMPLE_RATE": "flashhead_sample_rate",
        "FLASHHEAD_WIDTH": "flashhead_width",
        "FLASHHEAD_HEIGHT": "flashhead_height",
        "FLASHHEAD_FRAME_NUM": "flashhead_frame_num",
        "FLASHHEAD_CHUNK_SAMPLES": "flashhead_chunk_samples",
        "OMNIRT_ENDPOINT": "omnirt_endpoint",
        "OMNIRT_API_KEY": "omnirt_api_key",
        "OMNIRT_AUDIO2VIDEO_MODELS_PATH": "omnirt_audio2video_models_path",
        "OMNIRT_AUDIO2VIDEO_PATH_TEMPLATE": "omnirt_audio2video_path_template",
        "OMNIRT_VIDEO_CLONE_PATH_TEMPLATE": "omnirt_video_clone_path_template",
        "WAV2LIP_PRELOAD": "wav2lip_preload",
    }


def _load_legacy_dotenv_source() -> dict[str, Any]:
    env_file = os.environ.get("OPENTALKING_ENV_FILE", ".env")
    values = dotenv_values(env_file)
    mapping = _legacy_env_mapping()
    return {
        target: value
        for name, target in mapping.items()
        if (value := values.get(name)) not in (None, "")
    }


def _load_legacy_env_source() -> dict[str, Any]:
    mapping = _legacy_env_mapping()
    return {target: os.environ[name] for name, target in mapping.items() if name in os.environ}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OPENTALKING_",
        env_file=os.environ.get("OPENTALKING_ENV_FILE", ".env"),
        extra="ignore",
    )

    log_level: str = "INFO"
    config_file: str = Field(default="./configs/default.yaml")
    models: dict[str, Any] = Field(default_factory=dict)

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str | list[str] = "*"

    redis_url: str = "redis://localhost:6379/0"
    avatars_dir: str = "./examples/avatars"
    models_dir: str = Field(default_factory=lambda: str(model_root()))
    worker_url: str = "http://127.0.0.1:9001"
    exports_dir: str = "./data/exports"
    scene_assets_dir: str = "./data/scene-assets"
    scene_asset_max_bytes: int = 200 * 1024 * 1024
    export_max_bytes: int = 1024 * 1024 * 1024
    video_creation_audio_max_bytes: int = 50 * 1024 * 1024
    video_creation_fasterliveportrait_preroll_ms: int = 400
    video_creation_light2d_max_duration_sec: int = 300
    video_creation_light2d_max_text_chars: int = 1000
    avatar_matting_provider: str = "rembg"
    avatar_matting_device: str = "cpu"
    avatar_matting_model_path: str = ""
    avatar_matting_timeout_sec: int = 60

    flashtalk_ws_url: str = ""
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

    flashhead_ws_url: str = ""
    flashhead_base_url: str = ""
    flashhead_model: str = "soulx-flashhead-1.3b"
    flashhead_shared_local_dir: str = "/tmp/opentalking_flashhead_io"
    flashhead_shared_remote_dir: str = "/tmp/opentalking_flashhead_io"
    flashhead_output_local_dir: str = ""
    flashhead_output_remote_dir: str = ""
    flashhead_output_base_url: str = ""
    flashhead_timeout_sec: float = 600.0
    flashhead_fps: int = 25
    flashhead_sample_rate: int = 16000
    flashhead_width: int = 512
    flashhead_height: int = 512
    flashhead_frame_num: int = 29
    flashhead_chunk_samples: int = 17920

    quicktalk_asset_root: str = ""
    quicktalk_model_root: str = ""
    quicktalk_backend: str = ""
    quicktalk_model_backend: str = "auto"
    quicktalk_device: str = ""
    quicktalk_hubert_device: str = ""
    quicktalk_worker_cache: bool = True
    quicktalk_slice_len: int = 0

    llm_provider: str = "openai_compatible"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "qwen-turbo"
    llm_system_prompt: str = "You are a friendly digital human assistant."

    #: edge | openai_compatible | xiaomi_mimo | dashscope | bailian | qwen | qwen_tts | cosyvoice | sambert | local_*（OPENTALKING_TTS_DEFAULT_PROVIDER）
    tts_default_provider: str = Field(default="")
    tts_enabled_providers: str = Field(default="")

    #: Legacy generic provider; overridden by OPENTALKING_TTS_DEFAULT_PROVIDER when set.
    tts_provider: str = Field(default="edge")

    #: 音色目录 SQLite；默认 ./data/opentalking.sqlite3
    sqlite_path: str = Field(default="./data/opentalking.sqlite3")
    #: Agent 长期记忆 SQLite；默认 ./data/agent_memory.sqlite
    agent_memory_sqlite_path: str = Field(default="./data/agent_memory.sqlite")
    #: Agent 默认知识库原始文档目录；默认 ./data/knowledge
    agent_knowledge_root: str = Field(default="./data/knowledge")
    #: Persona Package 本地存储目录；默认 ./data/personas
    persona_root: str = Field(default="./data/personas")
    #: LightRAG 知识库索引目录；留空时使用 agent_knowledge_root/_lightrag
    agent_lightrag_root: str = Field(default="")
    agent_lightrag_query_mode: str = Field(default="hybrid")
    agent_lightrag_llm_base_url: str = Field(default="")
    agent_lightrag_llm_api_key: str = Field(default="")
    agent_lightrag_llm_model: str = Field(default="")
    agent_lightrag_embedding_base_url: str = Field(default="")
    agent_lightrag_embedding_api_key: str = Field(default="")
    agent_lightrag_embedding_model: str = Field(default="text-embedding-v4")
    agent_lightrag_embedding_dim: int = Field(default=1024)
    agent_lightrag_embedding_max_token_size: int = Field(default=8192)
    agent_lightrag_language: str = Field(default="Chinese")
    agent_lightrag_chunk_fallback_enabled: bool = Field(default=False)

    # ---- Character memory provider ----
    memory_provider: str = "mem0"
    memory_enabled: bool = False
    memory_default_profile_id: str = "default"
    memory_default_library_id: str = "default"
    memory_recall_limit: int = 5
    memory_recall_min_score: float = 0.0
    memory_recall_timeout_ms: int = 2000
    memory_recall_backend: str = "hybrid"
    memory_write_mode: str = "hybrid"
    memory_decision_mode: str = "hybrid"
    memory_decision_timeout_ms: int = 2000
    memory_smart_write_enabled: bool = True
    memory_summary_enabled: bool = True
    memory_summary_turn_window: int = 8
    memory_summary_max_items: int = 3
    memory_mem0_config: str = ""
    memory_mem0_llm_provider: str = "openai"
    memory_mem0_llm_base_url: str = ""
    memory_mem0_llm_api_key: str = ""
    memory_mem0_llm_model: str = "qwen-flash"
    memory_mem0_embedder_provider: str = "openai"
    memory_mem0_embedder_base_url: str = ""
    memory_mem0_embedder_api_key: str = ""
    memory_mem0_embedder_model: str = "text-embedding-v4"
    memory_mem0_embedder_embedding_dims: int = 1024
    memory_mem0_vector_store_provider: str = "qdrant"
    memory_mem0_vector_store_collection_name: str = "opentalking_memories"
    memory_mem0_vector_store_path: str = "./data/mem0_qdrant"
    memory_mem0_vector_store_host: str = ""
    memory_mem0_vector_store_port: int = 0
    memory_mem0_vector_store_embedding_model_dims: int = 1024
    memory_sqlite_path: str = "./data/opentalking_memory.sqlite3"

    #: CosyVoice 复刻时，百炼需拉取公网 URL；若留空则用请求的 Host 拼 URL（内网部署请填公网可达地址）
    public_base_url: str = ""

    tts_model: str = ""
    tts_api_key: str = ""
    tts_voice: str = "zh-CN-XiaoxiaoNeural"
    tts_dashscope_model: str = "qwen3-tts-flash-realtime"
    tts_dashscope_api_key: str = ""
    tts_dashscope_voice: str = "Cherry"
    tts_dashscope_service_url: str = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
    tts_cosyvoice_model: str = "cosyvoice-v3-flash"
    tts_cosyvoice_service_url: str = ""
    tts_sambert_model: str = "sambert-zhichu-v1"
    tts_edge_voice: str = "zh-CN-XiaoxiaoNeural"
    tts_indextts_backend: str = ""
    tts_local_cosyvoice_model: str = "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"
    tts_local_cosyvoice_model_dir: str = ""
    tts_local_cosyvoice_runtime_dir: str = ""
    tts_local_cosyvoice_service_url: str = ""
    tts_local_cosyvoice_service_urls: str = ""
    tts_local_cosyvoice_device: str = "auto"
    tts_local_cosyvoice_fp16: str = "auto"
    tts_local_cosyvoice_load_jit: bool = False
    tts_local_cosyvoice_load_trt: bool = False
    tts_local_cosyvoice_load_vllm: bool = False
    tts_local_cosyvoice_trt_concurrent: int = 1
    tts_local_cosyvoice_token_hop_len: int = 0
    tts_local_cosyvoice_token_max_hop_len: int = 0
    tts_local_cosyvoice_stream_scale_factor: int = 0
    tts_local_cosyvoice_flow_n_timesteps: int = 0
    tts_local_cosyvoice_max_token_text_ratio: float = 6.0
    tts_local_cosyvoice_min_token_text_ratio: float = 0.0
    tts_local_cosyvoice_mask_stop_tokens: bool = True
    tts_local_f5_tts_model: str = "SWivid/F5-TTS/F5TTS_v1_Base"
    tts_local_f5_tts_model_dir: str = ""
    tts_local_f5_tts_runtime_dir: str = ""
    tts_local_f5_tts_service_url: str = ""
    tts_local_f5_tts_ckpt_file: str = ""
    tts_local_f5_tts_vocoder_local_path: str = ""
    tts_local_f5_tts_prompt_audio: str = ""
    tts_local_f5_tts_prompt_text: str = ""
    tts_local_f5_tts_device: str = "auto"
    tts_local_indextts_model: str = "IndexTeam/IndexTTS-2"
    tts_local_indextts_model_dir: str = ""
    tts_local_indextts_cfg_path: str = ""
    tts_local_indextts_service_url: str = ""
    tts_local_indextts_prompt_audio: str = ""
    tts_local_indextts_w2v_bert_dir: str = ""
    tts_local_indextts_maskgct_dir: str = ""
    tts_local_indextts_campplus_dir: str = ""
    tts_local_indextts_bigvgan_dir: str = ""
    tts_local_indextts_device: str = "auto"
    tts_local_indextts_use_fp16: bool = True
    tts_local_indextts_use_cuda_kernel: bool = False
    tts_local_indextts_use_deepspeed: bool = False
    tts_sample_rate: int = 16000
    tts_streaming_decode: bool = True
    tts_elevenlabs_api_key: str = ""
    tts_elevenlabs_base_url: str = "https://api.elevenlabs.io"
    tts_elevenlabs_model_id: str = "eleven_flash_v2_5"
    tts_elevenlabs_voice_id: str = ""
    tts_elevenlabs_output_format: str = "mp3_22050_32"
    tts_openai_base_url: str = ""
    tts_openai_api_key: str = ""
    tts_openai_model: str = "gpt-4o-mini-tts"
    tts_openai_voice: str = "alloy"
    tts_openai_response_format: str = "wav"
    tts_openai_protocol: str = "audio_speech"
    tts_openai_prompt: str = ""
    tts_xiaomi_base_url: str = ""
    tts_xiaomi_api_key: str = ""
    tts_xiaomi_model: str = "mimo-v2.5-tts"
    tts_xiaomi_voice: str = "mimo_default"
    tts_xiaomi_response_format: str = "wav"
    tts_xiaomi_protocol: str = "chat_completions"
    tts_xiaomi_prompt: str = "自然、清晰、口语化的普通话。"
    ffmpeg_bin: str = "ffmpeg"

    #: dashscope | openai_compatible | xiaomi_mimo | funasr | sensevoice | sherpa_onnx（OPENTALKING_STT_DEFAULT_PROVIDER）
    stt_default_provider: str = ""
    stt_enabled_providers: str = ""

    #: Legacy generic provider; overridden by OPENTALKING_STT_DEFAULT_PROVIDER when set.
    stt_provider: str = "dashscope"
    stt_model: str = "paraformer-realtime-v2"
    stt_api_key: str = ""
    stt_device: str = "auto"
    stt_sensevoice_model: str = "iic/SenseVoiceSmall"
    stt_sensevoice_model_dir: str = ""
    stt_sensevoice_device: str = "auto"
    stt_dashscope_model: str = "paraformer-realtime-v2"
    stt_dashscope_api_key: str = ""
    stt_openai_base_url: str = ""
    stt_openai_api_key: str = ""
    stt_openai_model: str = "whisper-1"
    stt_openai_language: str = ""
    stt_openai_response_format: str = "json"
    stt_openai_protocol: str = "audio_transcriptions"
    stt_openai_audio_format: str = "wav"
    stt_xiaomi_base_url: str = ""
    stt_xiaomi_api_key: str = ""
    stt_xiaomi_model: str = "mimo-v2.5-asr"
    stt_xiaomi_language: str = ""
    stt_xiaomi_response_format: str = "json"
    stt_xiaomi_protocol: str = "chat_completions"
    stt_xiaomi_audio_format: str = "wav"

    #: Shared local model root for local STT/TTS assets.
    local_audio_model_root: str = Field(default_factory=lambda: str(local_audio_model_root()))
    local_audio_device: str = "auto"
    local_qwen3_tts_model: str = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
    local_qwen3_tts_service_url: str = ""

    torch_device: str = "cpu"
    default_fps: int = 25
    default_model: str = ""

    # ---- OmniRT inference runtime ----
    # When OMNIRT_ENDPOINT is set, OpenTalking derives per-model WS URLs from
    # it instead of needing OPENTALKING_FLASHTALK_WS_URL etc. The legacy
    # *_ws_url fields above remain as a fallback when OMNIRT_ENDPOINT is unset.
    # Example: OMNIRT_ENDPOINT=http://gpu-host:9000
    omnirt_endpoint: str = ""
    omnirt_api_key: str = ""
    omnirt_audio2video_models_path: str = "/v1/audio2video/models"
    # Legacy alias kept so older deployments can still point at /v1/avatar/models.
    omnirt_avatar_models_path: str = ""
    # Path template for OmniRT's FlashTalk-compatible audio2video WebSocket routes.
    # {model} is substituted at connect time. Override only if your OmniRT
    # instance uses a different routing convention.
    omnirt_audio2video_path_template: str = "/v1/audio2video/{model}"
    # Independent WS route for FasterLivePortrait video clone (source avatar + driving frame stream).
    omnirt_video_clone_path_template: str = "/v1/avatar/video-clone/{model}"
    # Preload preprocessed Wav2Lip frame assets into OmniRT at unified startup.
    # This keeps the first user request from paying reference-frame prepare time.
    wav2lip_preload: bool = True

    # FlashTalk slot queue: max sessions waiting behind the active one (0 = unlimited)
    flashtalk_max_queue_size: int = 3
    # Seconds a session may wait in queue before being rejected (0 = no timeout)
    flashtalk_slot_timeout_sec: int = 3600
    # Max seconds a single session may hold the FlashTalk slot (0 = unlimited)
    # When exceeded the session is force-closed and the slot is released.
    flashtalk_max_session_sec: int = 600
    benchmark_timing: bool = False

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
            _load_legacy_env_source,
            _load_legacy_dotenv_source,
            _load_yaml_source,
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
    def normalized_tts_provider(self) -> str:
        from opentalking.providers.tts.providers import normalize_tts_provider

        try:
            provider = normalize_tts_provider(self.tts_provider, default="edge")
        except ValueError:
            return "auto"
        return provider or "edge"

    @property
    def normalized_tts_default_provider(self) -> str:
        from opentalking.providers.tts.providers import normalize_tts_provider

        raw = self.tts_default_provider or self.tts_provider
        try:
            provider = normalize_tts_provider(raw, default="edge")
        except ValueError:
            return "auto"
        return provider or "edge"

    @property
    def normalized_stt_provider(self) -> str:
        from opentalking.providers.stt.factory import normalize_stt_provider

        try:
            provider = normalize_stt_provider(self.stt_provider, default="dashscope")
        except ValueError:
            return "dashscope"
        return provider or "dashscope"

    @property
    def normalized_stt_default_provider(self) -> str:
        from opentalking.providers.stt.factory import normalize_stt_provider

        raw = self.stt_default_provider or self.stt_provider
        try:
            provider = normalize_stt_provider(raw, default="dashscope")
        except ValueError:
            return "dashscope"
        return provider or "dashscope"

    @property
    def normalized_flashtalk_mode(self) -> str:
        return "flashtalk"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
