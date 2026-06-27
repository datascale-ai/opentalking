from __future__ import annotations

from collections.abc import Mapping
from typing import Any


INDEXTTS_EMOTION_KEYS = (
    "happy",
    "angry",
    "sad",
    "afraid",
    "disgusted",
    "melancholic",
    "surprised",
    "calm",
)



def _clamp_float(value: object, *, default: float, minimum: float, maximum: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if out < minimum:
        return minimum
    if out > maximum:
        return maximum
    return out


def _clamp_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError):
        return default
    if out < minimum:
        return minimum
    if out > maximum:
        return maximum
    return out


def _clean_streaming_mode(value: object) -> str:
    mode = str(value or "").strip().lower().replace("-", "_")
    if mode in {"segment", "token_window"}:
        return mode
    return ""


def _normalize_vector(raw: object) -> list[float]:
    if not isinstance(raw, (list, tuple)) or len(raw) != len(INDEXTTS_EMOTION_KEYS):
        raise ValueError("indextts_config.emo_vector must contain 8 numeric values")
    values = [_clamp_float(value, default=0.0, minimum=0.0, maximum=1.0) for value in raw]
    total = sum(values)
    if total > 1.5:
        scale = 1.5 / total
        values = [value * scale for value in values]
    return [round(value, 6) for value in values]


def _coerce_normalized_vector(raw: object) -> list[float]:
    if not isinstance(raw, (list, tuple)) or len(raw) != len(INDEXTTS_EMOTION_KEYS):
        raise ValueError("indextts_config.emo_vector must contain 8 numeric values")
    return [round(_clamp_float(value, default=0.0, minimum=0.0, maximum=1.0), 6) for value in raw]


def normalize_indextts_config(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    if not raw:
        return {}
    explicit_mode = raw.get("emotion_mode") or raw.get("mode")
    mode = str(explicit_mode or "").strip().lower()
    out: dict[str, Any] = {}

    if "interval_silence_ms" in raw:
        out["interval_silence_ms"] = _clamp_int(raw.get("interval_silence_ms"), default=0, minimum=0, maximum=2000)
    mode_value = _clean_streaming_mode(raw.get("streaming_mode"))
    if mode_value:
        out["streaming_mode"] = mode_value
    if "max_text_tokens_per_segment" in raw:
        out["max_text_tokens_per_segment"] = _clamp_int(raw.get("max_text_tokens_per_segment"), default=80, minimum=1, maximum=240)
    if "quick_streaming_tokens" in raw:
        out["quick_streaming_tokens"] = _clamp_int(raw.get("quick_streaming_tokens"), default=4, minimum=0, maximum=240)

    if not mode:
        if raw.get("use_emo_text") or "emo_text" in raw:
            mode = "text"
        elif "emo_audio_prompt" in raw:
            mode = "audio"
        elif "emo_vector" in raw:
            mode = "normalized_vector"
        else:
            mode = "voice"

    if mode in {"voice", "follow_voice", "none", ""}:
        return out

    out["emo_alpha"] = _clamp_float(raw.get("emo_alpha"), default=0.6, minimum=0.0, maximum=1.0)
    if "use_random" in raw:
        out["use_random"] = bool(raw.get("use_random"))

    if mode in {"text", "emo_text", "emotion_text"}:
        out["use_emo_text"] = True
        emo_text = str(raw.get("emo_text") or "").strip()
        if emo_text:
            out["emo_text"] = emo_text[:240]
        return out

    if mode in {"audio", "emotion_audio", "audio_prompt", "emo_audio"}:
        prompt = str(raw.get("emo_audio_prompt") or "").strip()
        if not prompt:
            raise ValueError("indextts_config.emo_audio_prompt is required for audio emotion mode")
        out["emo_audio_prompt"] = prompt
        return out

    if mode == "normalized_vector":
        out["emo_vector"] = _coerce_normalized_vector(raw.get("emo_vector"))
        return out

    if mode in {"vector", "manual", "emo_vector"}:
        out["emo_vector"] = _normalize_vector(raw.get("emo_vector"))
        return out

    raise ValueError("indextts_config.emotion_mode must be voice, text, vector, or audio")


def indextts_infer_kwargs(config: Mapping[str, Any] | None) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    for key in ("emo_alpha", "emo_audio_prompt", "emo_vector", "use_emo_text", "emo_text", "use_random"):
        if config and key in config:
            kwargs[key] = config[key]
    if config and "interval_silence_ms" in config:
        kwargs["interval_silence"] = int(config["interval_silence_ms"])
    if config and "max_text_tokens_per_segment" in config:
        kwargs["max_text_tokens_per_segment"] = int(config["max_text_tokens_per_segment"])
    if config and "quick_streaming_tokens" in config:
        kwargs["more_segment_before"] = int(config["quick_streaming_tokens"])
    return kwargs
