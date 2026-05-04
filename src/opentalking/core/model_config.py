from __future__ import annotations

import os
from copy import deepcopy
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml


_ENV_OVERRIDES: dict[str, dict[str, tuple[str, ...]]] = {
    "wav2lip": {
        "use_neural": ("OPENTALKING_WAV2LIP_USE_NEURAL",),
        "force_static": ("OPENTALKING_WAV2LIP_FORCE_STATIC",),
        "min_context_frames": ("OPENTALKING_WAV2LIP_MIN_CONTEXT_FRAMES",),
        "stream_batch_size": ("OPENTALKING_WAV2LIP_STREAM_BATCH_SIZE",),
        "infer_frame_stride": ("OPENTALKING_WAV2LIP_INFER_FRAME_STRIDE",),
        "pads": ("OPENTALKING_WAV2LIP_PADS",),
        "face_box_scale": ("OPENTALKING_WAV2LIP_FACE_BOX_SCALE",),
        "face_box_center_y_bias": ("OPENTALKING_WAV2LIP_FACE_BOX_CENTER_Y_BIAS",),
        "attack": ("OPENTALKING_WAV2LIP_ATTACK",),
        "release": ("OPENTALKING_WAV2LIP_RELEASE",),
        "max_step_up": ("OPENTALKING_WAV2LIP_MAX_STEP_UP",),
        "max_step_down": ("OPENTALKING_WAV2LIP_MAX_STEP_DOWN",),
        "frame_step_up": ("OPENTALKING_WAV2LIP_FRAME_STEP_UP",),
        "frame_step_down": ("OPENTALKING_WAV2LIP_FRAME_STEP_DOWN",),
    },
    "musetalk": {
        "context_ms": ("OPENTALKING_MUSETALK_CONTEXT_MS",),
        "overlap_frames": ("OPENTALKING_MUSETALK_OVERLAP_FRAMES",),
        "silence_gate": ("OPENTALKING_MUSETALK_SILENCE_GATE",),
        "smooth_crop": ("OPENTALKING_MUSETALK_SMOOTH_CROP",),
        "energy_gain": ("OPENTALKING_MUSETALK_ENERGY_GAIN",),
        "energy_attack": ("OPENTALKING_MUSETALK_ENERGY_ATTACK",),
        "energy_release": ("OPENTALKING_MUSETALK_ENERGY_RELEASE",),
        "energy_max_step_up": ("OPENTALKING_MUSETALK_ENERGY_MAX_STEP_UP",),
        "energy_max_step_down": ("OPENTALKING_MUSETALK_ENERGY_MAX_STEP_DOWN",),
        "eye_align": ("OPENTALKING_MUSETALK_EYE_ALIGN",),
        "prepared_compose": ("OPENTALKING_MUSETALK_PREPARED_COMPOSE",),
        "prebuffer_chunks": ("OPENTALKING_MUSETALK_PREBUFFER_CHUNKS",),
    },
    "flashtalk": {
        "frame_num": ("OPENTALKING_FLASHTALK_FRAME_NUM", "FLASHTALK_FRAME_NUM"),
        "motion_frames_num": (
            "OPENTALKING_FLASHTALK_MOTION_FRAMES_NUM",
            "FLASHTALK_MOTION_FRAMES_NUM",
        ),
        "sample_steps": ("OPENTALKING_FLASHTALK_SAMPLE_STEPS", "FLASHTALK_SAMPLE_STEPS"),
        "sample_shift": ("OPENTALKING_FLASHTALK_SAMPLE_SHIFT", "FLASHTALK_SAMPLE_SHIFT"),
        "color_correction_strength": (
            "OPENTALKING_FLASHTALK_COLOR_CORRECTION_STRENGTH",
            "FLASHTALK_COLOR_CORRECTION_STRENGTH",
        ),
        "height": ("OPENTALKING_FLASHTALK_HEIGHT", "FLASHTALK_HEIGHT"),
        "width": ("OPENTALKING_FLASHTALK_WIDTH", "FLASHTALK_WIDTH"),
        "sample_rate": ("OPENTALKING_FLASHTALK_SAMPLE_RATE", "FLASHTALK_SAMPLE_RATE"),
        "tgt_fps": ("OPENTALKING_FLASHTALK_TGT_FPS", "FLASHTALK_TGT_FPS"),
        "cached_audio_duration": (
            "OPENTALKING_FLASHTALK_CACHED_AUDIO_DURATION",
            "FLASHTALK_CACHED_AUDIO_DURATION",
        ),
        "audio_loudness_norm": (
            "OPENTALKING_FLASHTALK_AUDIO_LOUDNESS_NORM",
            "FLASHTALK_AUDIO_LOUDNESS_NORM",
        ),
        "t5_quant": ("OPENTALKING_FLASHTALK_T5_QUANT", "FLASHTALK_T5_QUANT"),
        "t5_quant_dir": ("OPENTALKING_FLASHTALK_T5_QUANT_DIR", "FLASHTALK_T5_QUANT_DIR"),
        "wan_quant": ("OPENTALKING_FLASHTALK_WAN_QUANT", "FLASHTALK_WAN_QUANT"),
        "wan_quant_include": (
            "OPENTALKING_FLASHTALK_WAN_QUANT_INCLUDE",
            "FLASHTALK_WAN_QUANT_INCLUDE",
        ),
        "wan_quant_exclude": (
            "OPENTALKING_FLASHTALK_WAN_QUANT_EXCLUDE",
            "FLASHTALK_WAN_QUANT_EXCLUDE",
        ),
    },
}


def _load_yaml(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Model config YAML must contain a mapping: {path}")
    return raw


def _builtin_model_config(model_type: str) -> dict[str, Any]:
    resource = files("opentalking.configs").joinpath("models", f"{model_type}.yaml")
    try:
        with resource.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
    except FileNotFoundError as exc:
        raise ValueError(f"Unknown model config: {model_type}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Model config YAML must contain a mapping: {model_type}")
    return raw


def _project_config_path() -> Path:
    config_file = (
        os.environ.get("OPENTALKING_CONFIG_FILE")
        or os.environ.get("CONFIG_FILE")
        or "./configs/default.yaml"
    )
    path = Path(config_file).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path


def _project_model_config(model_type: str) -> dict[str, Any]:
    path = _project_config_path()
    if not path.is_file():
        return {}
    raw = _load_yaml(path)
    models = raw.get("models")
    if not isinstance(models, dict):
        return {}
    override = models.get(model_type)
    if override is None:
        return {}
    if not isinstance(override, dict):
        raise ValueError(f"models.{model_type} must be a mapping in {path}")
    return override


def _merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_config(merged[key], value)
        else:
            merged[key] = value
    return merged


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Expected boolean value, got {value!r}")


def _coerce_env_value(raw: str, default: Any) -> Any:
    if default is None:
        return raw.strip() or None
    if isinstance(default, bool):
        return _parse_bool(raw)
    if isinstance(default, int) and not isinstance(default, bool):
        return int(raw)
    if isinstance(default, float):
        return float(raw)
    if isinstance(default, list):
        parts = [part.strip() for part in raw.split(",")]
        if len(default) == 0:
            return [part for part in parts if part]
        item_default = default[0]
        return [_coerce_env_value(part, item_default) for part in parts]
    return raw


def _validate_value(model_type: str, key: str, value: Any, default: Any) -> Any:
    if default is None:
        return value
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return _parse_bool(value)
        raise ValueError(f"models.{model_type}.{key} must be a boolean")
    if isinstance(default, int) and not isinstance(default, bool):
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        raise ValueError(f"models.{model_type}.{key} must be an integer")
    if isinstance(default, float):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        raise ValueError(f"models.{model_type}.{key} must be a number")
    if isinstance(default, str):
        if value is None:
            return None
        if isinstance(value, str):
            return value
        raise ValueError(f"models.{model_type}.{key} must be a string")
    if isinstance(default, list):
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"models.{model_type}.{key} must be a list")
        if not default:
            return list(value)
        return [
            _validate_value(model_type, f"{key}[{index}]", item, default[0])
            for index, item in enumerate(value)
        ]
    return value


def _validate_config(
    model_type: str,
    config: dict[str, Any],
    defaults: dict[str, Any],
) -> dict[str, Any]:
    validated: dict[str, Any] = {}
    for key, value in config.items():
        if key in defaults:
            validated[key] = _validate_value(model_type, key, value, defaults[key])
        else:
            validated[key] = value
    if model_type == "flashtalk":
        for key in ("t5_quant", "wan_quant"):
            value = validated.get(key)
            if value is None:
                continue
            if not isinstance(value, str):
                raise ValueError(f"models.{model_type}.{key} must be a string or null")
            value = value.lower()
            if value not in {"int8", "fp8"}:
                raise ValueError(
                    f"Unsupported models.{model_type}.{key}: {value!r}. "
                    "Expected 'int8', 'fp8', or null."
                )
            validated[key] = value
        for key in ("t5_quant_dir", "wan_quant_include", "wan_quant_exclude"):
            value = validated.get(key)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"models.{model_type}.{key} must be a string or null")
    return validated


def _env_model_config(model_type: str, defaults: dict[str, Any]) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for key, env_names in _ENV_OVERRIDES.get(model_type, {}).items():
        default = defaults.get(key)
        for env_name in env_names:
            raw = os.environ.get(env_name)
            if raw is not None:
                try:
                    overrides[key] = _coerce_env_value(raw, default)
                except ValueError as exc:
                    raise ValueError(f"Invalid {env_name}: {exc}") from exc
                break
    return overrides


@lru_cache(maxsize=None)
def get_model_config(model_type: str) -> dict[str, Any]:
    model_type = model_type.strip().lower()
    defaults = _builtin_model_config(model_type)
    config = _merge_config(defaults, _project_model_config(model_type))
    config = _merge_config(config, _env_model_config(model_type, defaults))
    return _validate_config(model_type, config, defaults)


def clear_model_config_cache() -> None:
    get_model_config.cache_clear()
