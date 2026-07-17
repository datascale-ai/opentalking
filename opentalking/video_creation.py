from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import uuid
import wave
from pathlib import Path
from collections.abc import Mapping
from typing import Any, cast, cast

import cv2
import numpy as np

from opentalking.avatar.duo_dialog import duo_dialog_summary_from_metadata, normalize_duo_dialog_payload
from opentalking.avatar.light2d import (
    CANONICAL_DOGO_AVATAR_ID,
    LIGHT2D_MODEL_TYPE,
    Light2DRenderer,
    load_canonical_dogo_renderer,
)
from opentalking.avatar.fasterliveportrait_config import normalize_fasterliveportrait_runtime_config
from opentalking.avatar.loader import load_avatar_bundle
from opentalking.core.model_config import get_model_config
from opentalking.core.types.frames import VideoFrameData
from opentalking.export_store import create_video_export, create_video_export_from_file
from opentalking.models.quicktalk.paths import resolve_quicktalk_asset_root
from opentalking.models.registry import get_adapter
from opentalking.providers.stt.dashscope.adapter import decode_audio_file_to_pcm_i16
from opentalking.providers.synthesis.audio2video_client import LocalAudio2VideoClient, OmniRTAudio2VideoClient
from opentalking.providers.synthesis.backends import resolve_model_backend
from opentalking.providers.synthesis.flashtalk.ws_client import FlashTalkWSClient
from opentalking.providers.synthesis.omnirt import auth_headers, resolve_synthesis_ws_url
from opentalking.providers.tts.factory import build_tts_adapter
from opentalking.scene_assets import SceneAssetStore

log = logging.getLogger(__name__)

REFERENCE_DRIVER_AUDIO_PATH = Path(__file__).resolve().parent / "assets" / "reference_drivers" / "flashtalk_default_driver.wav"

SUPPORTED_VIDEO_CREATION_MODELS = {
    "flashtalk",
    "flashhead",
    "fasterliveportrait",
    "musetalk",
    "quicktalk",
    "wav2lip",
    LIGHT2D_MODEL_TYPE,
}


def preflight_light2d_video_creation(
    settings: object,
    *,
    model: str,
    avatar_id: str,
    source: str,
    text: str | None = None,
    composition_config: Mapping[str, object] | None = None,
) -> Light2DRenderer | None:
    model_value = (model or "").strip().lower()
    avatar_value = (avatar_id or "").strip()
    is_light2d_request = model_value == LIGHT2D_MODEL_TYPE or avatar_value == CANONICAL_DOGO_AVATAR_ID
    if not is_light2d_request:
        return None
    if model_value != LIGHT2D_MODEL_TYPE or avatar_value != CANONICAL_DOGO_AVATAR_ID:
        raise ValueError("DOGO Light2D only supports model mock")
    if source not in {"upload", "tts_text", "voice_clone"}:
        raise ValueError("DOGO Light2D only supports upload, tts_text, or voice_clone")
    if composition_config and str(composition_config.get("background_id") or "").strip():
        raise ValueError("DOGO Light2D does not support background_id")
    if source in {"tts_text", "voice_clone"}:
        max_chars = _settings_int(settings, "video_creation_light2d_max_text_chars", 1000)
        if len(text or "") > max(0, max_chars):
            raise ValueError(f"Light2D text exceeds maximum length of {max_chars} characters")
    avatar_path = _avatar_dir(settings, avatar_value)
    context = load_canonical_dogo_renderer(avatar_path)
    return Light2DRenderer(context)


def _settings_path(settings: object, name: str, default: str) -> Path:
    return Path(str(getattr(settings, name, default) or default)).expanduser().resolve()


def _settings_int(settings: object, name: str, default: int) -> int:
    try:
        return int(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default


def _settings_float(settings: object, name: str, default: float) -> float:
    try:
        return float(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default


def _export_with_download_url(item: dict[str, Any]) -> dict[str, Any]:
    return {**item, "download_url": f"/exports/videos/{item['id']}/download"}


def _safe_title(title: str | None, *, model: str, avatar_id: str) -> str:
    value = (title or "").strip()
    return value or f"视频创作 · {model} · {avatar_id}"


def _reference_duration_options(settings: object) -> set[int]:
    raw = str(getattr(settings, "video_creation_reference_durations", "") or "10,30,60")
    options: set[int] = set()
    for part in raw.split(","):
        try:
            value = int(part.strip())
        except ValueError:
            continue
        if value > 0:
            options.add(value)
    return options or {10, 30, 60}


def _validate_reference_duration(settings: object, duration_sec: int | None) -> int:
    options = _reference_duration_options(settings)
    value = min(options) if duration_sec is None else int(duration_sec)
    if value not in options:
        allowed = ", ".join(str(item) for item in sorted(options))
        raise ValueError(f"duration_sec must be one of: {allowed}")
    return value


def _coerce_composition_float(
    payload: Mapping[str, object],
    key: str,
    default: float,
    *,
    min_value: float,
    max_value: float,
) -> float:
    raw = payload.get(key)
    if raw in (None, ""):
        return default
    if not isinstance(raw, str | int | float):
        raise ValueError(f"{key} must be a number")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number") from exc
    if value < min_value or value > max_value:
        raise ValueError(f"{key} must be between {min_value:g} and {max_value:g}")
    return value


def _coerce_composition_int(
    payload: Mapping[str, object],
    key: str,
    default: int,
    *,
    min_value: int,
    max_value: int,
) -> int:
    raw = payload.get(key)
    if raw in (None, ""):
        value = default
    elif isinstance(raw, str | int | float):
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} must be an integer") from exc
    else:
        raise ValueError(f"{key} must be an integer")
    if value < min_value or value > max_value:
        raise ValueError(f"{key} must be between {min_value:g} and {max_value:g}")
    return value + (value % 2)


def _normalize_video_composition_config(
    settings: object,
    avatar_path: Path,
    config: Mapping[str, object] | None,
) -> dict[str, object] | None:
    if not config:
        return None
    background_id = str(config.get("background_id") or "").strip()
    background_path: Path | None = None
    if background_id:
        store = SceneAssetStore(_settings_path(settings, "scene_assets_dir", "./data/scene-assets"))
        background = next((item for item in store.list_backgrounds() if item.get("id") == background_id), None)
        if background is None:
            raise ValueError("background_id not found")
        if str(background.get("kind") or "") == "video":
            raise ValueError("video backgrounds are not supported for video creation")
        background_path = store.background_file_path(background_id)
        if background_path is None:
            raise FileNotFoundError("background file not found")
    avatar_fit = str(config.get("avatar_fit") or "contain").strip()
    avatar_anchor = str(config.get("avatar_anchor") or "center").strip()
    if avatar_fit not in {"contain", "cover"}:
        raise ValueError("invalid avatar_fit")
    if avatar_anchor not in {"center", "bottom", "left", "right"}:
        raise ValueError("invalid avatar_anchor")
    return {
        "background_path": background_path,
        "background_color": str(config.get("background_color") or "#ffffff"),
        "avatar_mask_path": _reference_image_path(avatar_path),
        "avatar_fit": avatar_fit,
        "avatar_anchor": avatar_anchor,
        "avatar_scale": _coerce_composition_float(config, "avatar_scale", 1.0, min_value=0.1, max_value=4.0),
        "avatar_offset_x": _coerce_composition_float(config, "avatar_offset_x", 0.0, min_value=-2000.0, max_value=2000.0),
        "avatar_offset_y": _coerce_composition_float(config, "avatar_offset_y", 0.0, min_value=-2000.0, max_value=2000.0),
        "output_width": _coerce_composition_int(config, "output_width", 1280, min_value=320, max_value=3840),
        "output_height": _coerce_composition_int(config, "output_height", 720, min_value=180, max_value=2160),
    }


def _resize_cover(image: np.ndarray, width: int, height: int) -> np.ndarray:
    src_h, src_w = image.shape[:2]
    scale = max(float(width) / float(src_w), float(height) / float(src_h))
    new_w = max(1, int(round(src_w * scale)))
    new_h = max(1, int(round(src_h * scale)))
    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
    left = max(0, (new_w - width) // 2)
    top = max(0, (new_h - height) // 2)
    return np.ascontiguousarray(resized[top:top + height, left:left + width])


def _composition_background_color(value: object) -> tuple[int, int, int]:
    raw = str(value or "#ffffff").strip()
    if raw.startswith("#") and len(raw) == 7:
        try:
            r = int(raw[1:3], 16)
            g = int(raw[3:5], 16)
            b = int(raw[5:7], 16)
            return (b, g, r)
        except ValueError:
            pass
    return (255, 255, 255)


def _solid_background(width: int, height: int, color: object) -> np.ndarray:
    bgr = _composition_background_color(color)
    return np.full((int(height), int(width), 3), bgr, dtype=np.uint8)


def _avatar_anchor_origin(anchor: str, canvas_w: int, canvas_h: int, layer_w: int, layer_h: int) -> tuple[int, int]:
    if anchor == "bottom":
        return (canvas_w - layer_w) // 2, canvas_h - layer_h
    if anchor == "left":
        return 0, (canvas_h - layer_h) // 2
    if anchor == "right":
        return canvas_w - layer_w, (canvas_h - layer_h) // 2
    return (canvas_w - layer_w) // 2, (canvas_h - layer_h) // 2


def _load_avatar_alpha_mask(path: object) -> np.ndarray | None:
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None or image.ndim != 3 or image.shape[2] < 4:
        return None
    return image[:, :, 3].astype(np.float32) / 255.0


def _composite_avatar_layer(
    background: np.ndarray,
    frame: np.ndarray,
    *,
    avatar_fit: str,
    avatar_anchor: str,
    avatar_scale: float,
    avatar_offset_x: float,
    avatar_offset_y: float,
    fallback_alpha: np.ndarray | None = None,
) -> np.ndarray:
    canvas_h, canvas_w = background.shape[:2]
    layer = np.asarray(frame, dtype=np.uint8)
    if layer.ndim != 3 or layer.shape[2] < 3:
        return background
    bgr = layer[:, :, :3]
    if layer.shape[2] >= 4:
        alpha = layer[:, :, 3].astype(np.float32) / 255.0
    elif fallback_alpha is not None:
        alpha = fallback_alpha
        if alpha.shape[:2] != bgr.shape[:2]:
            alpha = cv2.resize(alpha, (bgr.shape[1], bgr.shape[0]), interpolation=cv2.INTER_AREA).astype(np.float32)
    else:
        alpha = np.ones(layer.shape[:2], dtype=np.float32)
    fit_scale = min(float(canvas_w) / float(bgr.shape[1]), float(canvas_h) / float(bgr.shape[0]))
    if avatar_fit == "cover":
        fit_scale = max(float(canvas_w) / float(bgr.shape[1]), float(canvas_h) / float(bgr.shape[0]))
    scale = max(0.01, fit_scale * float(avatar_scale))
    layer_w = max(1, int(round(bgr.shape[1] * scale)))
    layer_h = max(1, int(round(bgr.shape[0] * scale)))
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    opaque = bool(np.all(alpha >= 1.0))
    premultiplied_resized: np.ndarray
    alpha_resized: np.ndarray
    if opaque:
        bgr_resized = cv2.resize(bgr, (layer_w, layer_h), interpolation=interpolation)
        premultiplied_resized = bgr_resized.astype(np.float32)
        alpha_resized = np.ones((layer_h, layer_w), dtype=np.float32)
    else:
        premultiplied = bgr.astype(np.float32) * alpha[:, :, None]
        premultiplied_resized = cv2.resize(
            premultiplied,
            (layer_w, layer_h),
            interpolation=interpolation,
        )
        alpha_resized = cv2.resize(alpha, (layer_w, layer_h), interpolation=interpolation)
    origin_x, origin_y = _avatar_anchor_origin(avatar_anchor, canvas_w, canvas_h, layer_w, layer_h)
    left = int(round(origin_x + avatar_offset_x))
    top = int(round(origin_y + avatar_offset_y))
    dst_left = max(0, left)
    dst_top = max(0, top)
    dst_right = min(canvas_w, left + layer_w)
    dst_bottom = min(canvas_h, top + layer_h)
    if dst_left >= dst_right or dst_top >= dst_bottom:
        return background
    src_left = dst_left - left
    src_top = dst_top - top
    src_right = src_left + (dst_right - dst_left)
    src_bottom = src_top + (dst_bottom - dst_top)
    out = background.copy()
    fg = premultiplied_resized[src_top:src_bottom, src_left:src_right].astype(np.float32)
    mask = alpha_resized[src_top:src_bottom, src_left:src_right].astype(np.float32)[:, :, None]
    bg = out[dst_top:dst_bottom, dst_left:dst_right].astype(np.float32)
    out[dst_top:dst_bottom, dst_left:dst_right] = np.rint(
        np.clip(fg + (bg * (1.0 - mask)), 0, 255)
    ).astype(np.uint8)
    return out


def _apply_video_composition(
    frames: list[np.ndarray],
    *,
    config: Mapping[str, object] | None,
) -> list[np.ndarray]:
    if not frames or not config:
        return frames
    first = np.asarray(frames[0])
    frame_height, frame_width = first.shape[:2]
    width = _coerce_composition_int(config, "output_width", int(frame_width), min_value=320, max_value=3840)
    height = _coerce_composition_int(config, "output_height", int(frame_height), min_value=180, max_value=2160)
    background_path = config.get("background_path")
    if background_path:
        background_raw = cv2.imread(str(background_path), cv2.IMREAD_COLOR)
        if background_raw is None:
            raise FileNotFoundError("background file not found")
        background = _resize_cover(background_raw, int(width), int(height))
    else:
        background = _solid_background(int(width), int(height), config.get("background_color"))
    fallback_alpha = _load_avatar_alpha_mask(config.get("avatar_mask_path"))
    avatar_scale = _coerce_composition_float(config, "avatar_scale", 1.0, min_value=0.1, max_value=4.0)
    avatar_offset_x = _coerce_composition_float(config, "avatar_offset_x", 0.0, min_value=-2000.0, max_value=2000.0)
    avatar_offset_y = _coerce_composition_float(config, "avatar_offset_y", 0.0, min_value=-2000.0, max_value=2000.0)
    return [
        _composite_avatar_layer(
            background,
            frame,
            avatar_fit=str(config.get("avatar_fit") or "contain"),
            avatar_anchor=str(config.get("avatar_anchor") or "center"),
            avatar_scale=avatar_scale,
            avatar_offset_x=avatar_offset_x,
            avatar_offset_y=avatar_offset_y,
            fallback_alpha=fallback_alpha,
        )
        for frame in frames
    ]


def _build_reference_driver_pcm(total_samples: int, *, level: float = 480.0) -> np.ndarray:
    samples = max(0, int(total_samples))
    if samples == 0:
        return np.zeros(0, dtype=np.int16)
    amplitude = max(1.0, min(float(level), 32767.0))
    t = np.arange(samples, dtype=np.float32) / 16000.0
    carrier = np.sin(2.0 * np.pi * 120.0 * t) + 0.35 * np.sin(2.0 * np.pi * 240.0 * t)
    envelope = 0.55 + 0.45 * np.sin(2.0 * np.pi * 1.8 * t) ** 2
    pcm = carrier * envelope * (amplitude / 1.35)
    return np.clip(np.rint(pcm), -32768, 32767).astype(np.int16)


def _reference_driver_audio_path(settings: object) -> Path:
    raw = str(getattr(settings, "video_creation_reference_driver_audio", "") or "").strip()
    return Path(raw).expanduser().resolve() if raw else REFERENCE_DRIVER_AUDIO_PATH


def _fit_reference_driver_pcm(pcm: np.ndarray, total_samples: int) -> np.ndarray:
    target = max(0, int(total_samples))
    if target == 0:
        return np.zeros(0, dtype=np.int16)
    source = np.asarray(pcm, dtype=np.int16).reshape(-1)
    if source.size == 0:
        raise ValueError("reference driver audio decoded to empty PCM")
    repeats = int(np.ceil(float(target) / float(source.size)))
    return np.tile(source, repeats)[:target].astype(np.int16, copy=False)


def _read_pcm16_mono_wav(path: Path) -> np.ndarray | None:
    try:
        with wave.open(str(path), "rb") as wf:
            if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() != 16000:
                return None
            raw = wf.readframes(wf.getnframes())
    except (wave.Error, OSError):
        return None
    return np.frombuffer(raw, dtype="<i2").copy()


async def _load_reference_driver_pcm(settings: object, total_samples: int) -> np.ndarray | None:
    path = _reference_driver_audio_path(settings)
    if not path.is_file():
        return None
    direct_pcm = _read_pcm16_mono_wav(path)
    if direct_pcm is not None:
        return _fit_reference_driver_pcm(direct_pcm, total_samples)
    try:
        pcm = await decode_audio_file_to_pcm_i16(path)
        return _fit_reference_driver_pcm(pcm, total_samples)
    except Exception as exc:  # noqa: BLE001
        log.warning("reference driver audio unavailable, falling back to synthetic PCM: path=%s error=%s", path, exc)
        return None


def _avatar_dir(settings: object, avatar_id: str) -> Path:
    value = avatar_id.strip()
    if not value:
        raise ValueError("avatar_id is required")
    avatars_root = _settings_path(settings, "avatars_dir", "./examples/avatars")
    target = (avatars_root / value).resolve()
    try:
        target.relative_to(avatars_root)
    except ValueError as exc:
        raise ValueError("invalid avatar_id") from exc
    if not target.is_dir():
        raise FileNotFoundError("avatar not found")
    load_avatar_bundle(target, strict=False)
    return target


def _normalize_model(model: str) -> str:
    value = (model or "").strip().lower()
    if value not in SUPPORTED_VIDEO_CREATION_MODELS:
        raise ValueError(
            "video creation only supports flashtalk, flashhead, fasterliveportrait, musetalk, quicktalk, and wav2lip"
        )
    return value


def _reference_image_path(avatar_path: Path) -> Path:
    for name in ("reference.png", "reference.jpg", "reference.jpeg", "reference.webp", "preview.png"):
        path = avatar_path / name
        if path.is_file():
            return path.resolve()
    raise FileNotFoundError("avatar reference image not found")


_FASTLIVEPORTRAIT_VIDEO_CONFIG_KEYS = (
    "width",
    "height",
    "fps",
    "chunk_samples",
    "emit_frames_per_chunk",
    "render_keyframes_per_chunk",
    "disable_frame_interpolation",
    "head_motion_multiplier",
    "pose_motion_multiplier",
    "yaw_multiplier",
    "pitch_multiplier",
    "roll_multiplier",
    "animation_region",
    "expression_multiplier",
    "mouth_open_multiplier",
    "mouth_corner_multiplier",
    "cheek_jaw_multiplier",
    "driving_multiplier",
    "cfg_scale",
    "cfg_cond",
    "flag_stitching",
    "flag_pasteback",
    "flag_normalize_lip",
    "flag_relative_motion",
    "flag_lip_retargeting",
    "lip_retargeting_multiplier",
    "lip_retargeting_min",
    "lip_retargeting_max",
    "lip_retargeting_noise_floor",
    "head_only_pasteback",
    "lookahead_ms",
)

VIDEO_CREATION_FASTLIVEPORTRAIT_DEFAULT_CONFIG: dict[str, object] = {
    "head_motion_multiplier": 0.3,
    "pose_motion_multiplier": 0.35,
    "yaw_multiplier": 0.85,
    "pitch_multiplier": 1.0,
    "roll_multiplier": 0.85,
    "animation_region": "lip",
    "expression_multiplier": 1.0,
    "mouth_open_multiplier": 0.9,
    "mouth_corner_multiplier": 0.85,
    "cheek_jaw_multiplier": 0.9,
    "driving_multiplier": 1.0,
    "cfg_scale": 3.0,
    "flag_stitching": True,
    "flag_pasteback": True,
    "flag_relative_motion": True,
    "flag_normalize_lip": False,
    "flag_lip_retargeting": False,
}


def _fasterliveportrait_video_config(
    raw: Mapping[str, object] | None,
) -> dict[str, object] | None:
    base = get_model_config("fasterliveportrait")
    out: dict[str, object] = {}
    for key in _FASTLIVEPORTRAIT_VIDEO_CONFIG_KEYS:
        value = base.get(key)
        if value is not None:
            out[key] = value
    out.update(VIDEO_CREATION_FASTLIVEPORTRAIT_DEFAULT_CONFIG)
    out.update(normalize_fasterliveportrait_runtime_config(dict(raw or {})))
    return out or None


def _fasterliveportrait_preroll_samples(settings: object, model: str, sample_rate: int) -> int:
    if model != "fasterliveportrait":
        return 0
    preroll_ms = _settings_int(settings, "video_creation_fasterliveportrait_preroll_ms", 400)
    if preroll_ms <= 0 or sample_rate <= 0:
        return 0
    return max(0, int(round(float(sample_rate) * float(preroll_ms) / 1000.0)))


def _audio2video_client(settings: object, model: str, sample_rate: int, backend: object | None = None):
    backend = backend or resolve_model_backend(model, settings)
    backend_name = str(getattr(backend, "backend", "") or "").strip().lower()
    if backend_name in {"omnirt", "direct_ws"}:
        if model == "flashhead":
            from opentalking.providers.synthesis.flashhead import FlashHeadWSClient

            return OmniRTAudio2VideoClient(
                FlashHeadWSClient(
                    ws_url=str(getattr(backend, "ws_url", "") or getattr(settings, "flashhead_ws_url", "") or ""),
                    model=str(getattr(settings, "flashhead_model", "") or "soulx-flashhead-1.3b"),
                    config={
                        "fps": int(getattr(settings, "flashhead_fps", 25) or 25),
                        "sample_rate": int(getattr(settings, "flashhead_sample_rate", 16000) or 16000),
                        "width": int(getattr(settings, "flashhead_width", 416) or 416),
                        "height": int(getattr(settings, "flashhead_height", 704) or 704),
                        "frame_num": int(getattr(settings, "flashhead_frame_num", 25) or 25),
                        "chunk_samples": int(getattr(settings, "flashhead_chunk_samples", 16000) or 16000),
                    },
                )
            )
        ws_url = str(getattr(backend, "ws_url", "") or "") if backend_name == "direct_ws" else resolve_synthesis_ws_url(model, settings)
        headers = auth_headers(settings)
        return OmniRTAudio2VideoClient(
            FlashTalkWSClient(ws_url, extra_headers=headers or None)
        )
    if backend_name != "local":
        raise ValueError(f"video creation does not support {model} backend: {backend_name or 'unknown'}")
    return LocalAudio2VideoClient(
        get_adapter(model),
        device=_device_for_model(settings, model),
        sample_rate=sample_rate,
    )


def _remote_audio2video_backend(backend: object) -> bool:
    return str(getattr(backend, "backend", "") or "").strip().lower() in {"omnirt", "direct_ws"}


def _avatar_manifest(avatar_path: Path):
    return load_avatar_bundle(avatar_path, strict=False).manifest


def _resolve_avatar_relative_path(avatar_path: Path, raw: object) -> Path | None:
    value = str(raw or "").strip()
    if not value:
        return None
    avatar_root = avatar_path.resolve()
    path = (avatar_root / value).resolve()
    try:
        path.relative_to(avatar_root)
    except ValueError:
        return None
    return path


def _avatar_manifest_metadata(avatar_path: Path) -> dict[str, Any]:
    metadata = _avatar_manifest(avatar_path).metadata
    return dict(metadata or {}) if isinstance(metadata, dict) else {}


def _quicktalk_manifest_section(avatar_path: Path) -> dict[str, Any]:
    quicktalk = _avatar_manifest_metadata(avatar_path).get("quicktalk")
    return dict(quicktalk) if isinstance(quicktalk, dict) else {}


def _quicktalk_video_config(avatar_path: Path) -> dict[str, int]:
    manifest = _avatar_manifest(avatar_path)
    out: dict[str, int] = {}
    for key in ("width", "height"):
        try:
            value = int(getattr(manifest, key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            out[key] = value
    out["fps"] = 25
    return out


def _settings_or_env_int(settings: object, attr: str, env_names: tuple[str, ...], default: int) -> int:
    raw: Any = getattr(settings, attr, None)
    if raw in (None, ""):
        for env_name in env_names:
            env_value = os.environ.get(env_name)
            if env_value not in (None, ""):
                raw = env_value
                break
    try:
        value: Any = raw if raw not in (None, "") else default
        return int(value)
    except (TypeError, ValueError):
        return default


def _settings_or_env_float(settings: object, attr: str, env_names: tuple[str, ...]) -> float | None:
    raw: Any = getattr(settings, attr, None)
    if raw in (None, ""):
        for env_name in env_names:
            env_value = os.environ.get(env_name)
            if env_value not in (None, ""):
                raw = env_value
                break
    if raw in (None, ""):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _settings_or_env_str(settings: object, attr: str, env_names: tuple[str, ...], default: str) -> str:
    raw: Any = getattr(settings, attr, None)
    if raw in (None, ""):
        for env_name in env_names:
            env_value = os.environ.get(env_name)
            if env_value not in (None, ""):
                raw = env_value
                break
    value = str(raw if raw not in (None, "") else default).strip()
    return value or default


def _even_video_dim(value: int) -> int:
    value = max(2, int(value))
    return value + (value % 2)


def _quicktalk_cache_video_size(settings: object, avatar_path: Path) -> tuple[int, int] | None:
    config = _quicktalk_video_config(avatar_path)
    width = int(config.get("width") or 0)
    height = int(config.get("height") or 0)
    if width <= 0 or height <= 0:
        return None
    max_long_edge = _settings_or_env_int(
        settings,
        "quicktalk_max_long_edge",
        ("OPENTALKING_QUICKTALK_MAX_LONG_EDGE", "OMNIRT_QUICKTALK_MAX_LONG_EDGE"),
        900,
    )
    if max_long_edge <= 0:
        max_long_edge = 900
    long_edge = max(width, height)
    if long_edge > max_long_edge:
        scale = float(max_long_edge) / float(long_edge)
        width = max(2, int(round(width * scale)))
        height = max(2, int(round(height * scale)))
        width -= width % 2
        height -= height % 2
    else:
        width = _even_video_dim(width)
        height = _even_video_dim(height)
    return width, height


def _prepared_quicktalk_path(settings: object, avatar_path: Path, prefix: str, suffix: str) -> Path | None:
    quicktalk_dir = avatar_path / "quicktalk"
    cache_size = _quicktalk_cache_video_size(settings, avatar_path)
    if not quicktalk_dir.is_dir() or cache_size is None:
        return None
    width, height = cache_size
    path = (quicktalk_dir / f"{prefix}_{width}x{height}.{suffix}").resolve()
    try:
        path.relative_to(avatar_path.resolve())
    except ValueError:
        return None
    return path if path.is_file() else None


def _quicktalk_declared_video_source(avatar_path: Path) -> Path | None:
    metadata = _avatar_manifest_metadata(avatar_path)
    quicktalk = _quicktalk_manifest_section(avatar_path)
    for source in (metadata, quicktalk):
        for key in ("source_video", "template_video"):
            path = _resolve_avatar_relative_path(avatar_path, source.get(key))
            if path is not None and path.is_file():
                return path
    return None


def _quicktalk_prepared_template_video(settings: object, avatar_path: Path) -> Path | None:
    prepared = _prepared_quicktalk_path(settings, avatar_path, "template", "mp4")
    if prepared is not None:
        return prepared

    quicktalk_dir = avatar_path / "quicktalk"
    preferred = quicktalk_dir / "template_900.mp4"
    if preferred.is_file():
        return preferred.resolve()
    if quicktalk_dir.is_dir():
        for candidate in sorted(quicktalk_dir.glob("template_*.mp4")):
            candidate = candidate.resolve()
            try:
                candidate.relative_to(avatar_path.resolve())
            except ValueError:
                continue
            if candidate.is_file():
                return candidate

    for name in ("idle.mp4", "idle.mov", "idle.webm", "idle.avi", "source.mp4"):
        path = avatar_path / name
        if path.is_file():
            return path.resolve()
    source_dir = avatar_path / "source"
    if source_dir.is_dir():
        for pattern in ("*.mp4", "*.mov", "*.webm", "*.avi"):
            for candidate in sorted(source_dir.glob(pattern)):
                if candidate.is_file():
                    return candidate.resolve()
    return None


def _quicktalk_template_video(settings: object, avatar_path: Path) -> Path | None:
    declared = _quicktalk_declared_video_source(avatar_path)
    if declared is not None:
        return declared
    return _quicktalk_prepared_template_video(settings, avatar_path)


def _quicktalk_template_frame_dir(avatar_path: Path) -> Path | None:
    metadata = _avatar_manifest_metadata(avatar_path)
    if str(metadata.get("reference_mode") or "").strip().lower() != "frames":
        return None
    raw = str(metadata.get("frame_dir") or "frames").strip() or "frames"
    frame_dir = _resolve_avatar_relative_path(avatar_path, raw)
    return frame_dir if frame_dir is not None and frame_dir.is_dir() else None


def _quicktalk_face_cache(settings: object, avatar_path: Path) -> Path | None:
    prepared = _prepared_quicktalk_path(settings, avatar_path, "face_cache_v3", "npz")
    if prepared is not None:
        return prepared

    quicktalk = _quicktalk_manifest_section(avatar_path)
    path = _resolve_avatar_relative_path(avatar_path, quicktalk.get("face_cache"))
    if path is not None and path.is_file():
        return path

    quicktalk_dir = avatar_path / "quicktalk"
    if not quicktalk_dir.is_dir():
        return None
    candidates = [quicktalk_dir / "face_cache_v3_900.npz", *sorted(quicktalk_dir.glob("face_cache_v3_*.npz"))]
    seen: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            candidate.relative_to(avatar_path.resolve())
        except ValueError:
            continue
        if candidate.is_file():
            return candidate
    return None


def _quicktalk_init_session_kwargs(settings: object, avatar_path: Path) -> dict[str, object]:
    kwargs: dict[str, object] = {"video_config": _quicktalk_video_config(avatar_path)}
    declared_video = _quicktalk_declared_video_source(avatar_path)
    template_video = declared_video or _quicktalk_prepared_template_video(settings, avatar_path)
    template_frame_dir = _quicktalk_template_frame_dir(avatar_path)
    if template_video is not None:
        kwargs["template_mode"] = "video"
        kwargs["template_video"] = template_video
    elif template_frame_dir is not None:
        kwargs["template_mode"] = "frames"
        kwargs["template_frame_dir"] = template_frame_dir
    else:
        kwargs["template_mode"] = "image"
    if declared_video is None:
        face_cache = _quicktalk_face_cache(settings, avatar_path)
        if face_cache is not None:
            kwargs["quicktalk_face_cache"] = face_cache
    return kwargs


def _init_session_kwargs(
    *,
    settings: object,
    model: str,
    avatar_path: Path,
    backend: object,
    fasterliveportrait_config: Mapping[str, object] | None,
) -> dict[str, object]:
    kwargs: dict[str, object] = {"avatar_path": avatar_path}
    if model == "quicktalk":
        kwargs.update(_quicktalk_init_session_kwargs(settings, avatar_path))
    if not _remote_audio2video_backend(backend):
        return kwargs

    kwargs["ref_image"] = _reference_image_path(avatar_path)
    if model == "quicktalk":
        return kwargs
    if model != "fasterliveportrait":
        return kwargs

    video_config = _fasterliveportrait_video_config(fasterliveportrait_config)
    if video_config:
        kwargs["video_config"] = video_config
    return kwargs


def _device_for_model(settings: object, model: str) -> str:
    if model == "quicktalk":
        return str(
            getattr(settings, "quicktalk_device", "")
            or getattr(settings, "torch_device", "")
            or "cuda:0"
        )
    if model == "wav2lip":
        return str(
            getattr(settings, "wav2lip_device", "")
            or getattr(settings, "torch_device", "")
            or "cuda"
        )
    return str(getattr(settings, "torch_device", "") or "cuda")


def _frame_array(frame: VideoFrameData | Any) -> np.ndarray | None:
    data = getattr(frame, "data", frame)
    arr = np.asarray(data)
    if arr.ndim != 3 or arr.shape[2] < 3:
        return None
    channels = 4 if arr.shape[2] >= 4 else 3
    return np.ascontiguousarray(arr[:, :, :channels].astype(np.uint8, copy=False))


def _write_wav(path: Path, pcm: np.ndarray, sample_rate: int = 16000) -> None:
    arr = np.asarray(pcm, dtype="<i2").reshape(-1)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(arr.tobytes())


def _write_video_only(path: Path, frames: list[np.ndarray], fps: float) -> None:
    if not frames:
        raise RuntimeError("video creation produced zero frames")
    first = np.asarray(frames[0], dtype=np.uint8)
    height, width = first.shape[:2]
    path.parent.mkdir(parents=True, exist_ok=True)
    fourcc = getattr(cv2, "VideoWriter_fourcc")
    writer = cv2.VideoWriter(
        str(path),
        fourcc(*"mp4v"),
        max(1.0, float(fps)),
        (int(width), int(height)),
    )
    if not writer.isOpened():
        raise RuntimeError(f"cannot open video writer: {path}")
    try:
        for frame in frames:
            arr = np.asarray(frame, dtype=np.uint8)
            if arr.shape[:2] != (height, width):
                resized = cv2.resize(arr, (width, height), interpolation=cv2.INTER_AREA)
                arr = np.asarray(resized, dtype=np.uint8)
            if arr.ndim == 3 and arr.shape[2] >= 4:
                arr = arr[:, :, :3]
            writer.write(arr)
    finally:
        writer.release()


def _light2d_composition_config(
    renderer: Light2DRenderer,
    config: Mapping[str, object] | None,
) -> dict[str, object]:
    canvas = renderer.context.config["canvas"]
    raw = dict(config or {})
    return {
        "background_color": str(raw.get("background_color") or "#ffffff"),
        "avatar_fit": str(raw.get("avatar_fit") or "contain"),
        "avatar_anchor": str(raw.get("avatar_anchor") or "center"),
        "avatar_scale": _coerce_composition_float(
            raw, "avatar_scale", 1.0, min_value=0.1, max_value=4.0
        ),
        "avatar_offset_x": _coerce_composition_float(
            raw, "avatar_offset_x", 0.0, min_value=-2000.0, max_value=2000.0
        ),
        "avatar_offset_y": _coerce_composition_float(
            raw, "avatar_offset_y", 0.0, min_value=-2000.0, max_value=2000.0
        ),
        "output_width": _coerce_composition_int(
            raw, "output_width", int(canvas["width"]), min_value=320, max_value=3840
        ),
        "output_height": _coerce_composition_int(
            raw, "output_height", int(canvas["height"]), min_value=180, max_value=2160
        ),
    }


def _write_light2d_video_only(
    path: Path,
    renderer: Light2DRenderer,
    pcm: np.ndarray,
    *,
    config: Mapping[str, object] | None,
) -> None:
    normalized = _light2d_composition_config(renderer, config)
    width = cast(int, normalized["output_width"])
    height = cast(int, normalized["output_height"])
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(path),
        getattr(cv2, "VideoWriter_fourcc")(*"mp4v"),
        max(1.0, float(renderer.fps)),
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError(f"cannot open video writer: {path}")
    wrote_frame = False
    try:
        for rendered in renderer.iter_frames(np.asarray(pcm, dtype=np.int16).reshape(-1)):
            rgba = np.asarray(rendered.rgba, dtype=np.uint8)
            if rgba.ndim != 3 or rgba.shape[2] != 4:
                raise RuntimeError("Light2D renderer produced an invalid RGBA frame")
            background = _solid_background(width, height, normalized["background_color"])
            bgr_alpha = np.ascontiguousarray(rgba[:, :, [2, 1, 0, 3]])
            composed = _composite_avatar_layer(
                background,
                bgr_alpha,
                avatar_fit=str(normalized["avatar_fit"]),
                avatar_anchor=str(normalized["avatar_anchor"]),
                avatar_scale=cast(float, normalized["avatar_scale"]),
                avatar_offset_x=cast(float, normalized["avatar_offset_x"]),
                avatar_offset_y=cast(float, normalized["avatar_offset_y"]),
            )
            writer.write(np.ascontiguousarray(composed))
            wrote_frame = True
    finally:
        writer.release()
    if not wrote_frame:
        raise RuntimeError("video creation produced zero frames")


MultiFaceRealtimeV3Worker: Any | None = None


def _quicktalk_multiface_worker_class():
    global MultiFaceRealtimeV3Worker
    if MultiFaceRealtimeV3Worker is None:
        from opentalking.models.quicktalk.runtime import MultiFaceRealtimeV3Worker as worker_cls

        MultiFaceRealtimeV3Worker = worker_cls
    return MultiFaceRealtimeV3Worker


async def _ffmpeg_mux(ffmpeg_bin: str, video_in: Path, audio_in: Path, out_mp4: Path) -> None:
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_in),
        "-i",
        str(audio_in),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(out_mp4),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        detail = (stderr or b"").decode("utf-8", errors="replace")[:1200]
        raise RuntimeError(f"ffmpeg mux failed ({proc.returncode}): {detail}")


async def _probe_audio_duration_sec(settings: object, path: Path) -> float | None:
    ffmpeg_bin = str(getattr(settings, "ffmpeg_bin", "ffmpeg") or "ffmpeg")
    ffprobe_bin = str(getattr(settings, "ffprobe_bin", "") or "").strip()
    if not ffprobe_bin:
        ffprobe_bin = str(Path(ffmpeg_bin).with_name("ffprobe")) if "/" in ffmpeg_bin else "ffprobe"
    proc = await asyncio.create_subprocess_exec(
        ffprobe_bin,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        detail = (stderr or b"").decode("utf-8", errors="replace")[-800:]
        raise ValueError(f"audio duration probe failed: {detail}")
    try:
        duration = float((stdout or b"").decode("utf-8").strip())
    except ValueError as exc:
        raise ValueError("audio duration probe returned an invalid duration") from exc
    return duration if np.isfinite(duration) and duration >= 0 else None


async def _decode_audio_file_to_pcm_i16_limited(
    settings: object,
    path: Path,
    *,
    max_samples: int,
) -> np.ndarray:
    sample_limit = max(0, int(max_samples))
    duration = await _probe_audio_duration_sec(settings, path)
    if duration is not None and duration > float(sample_limit) / 16000.0:
        raise ValueError("Light2D audio exceeds maximum duration")
    proc = await asyncio.create_subprocess_exec(
        str(getattr(settings, "ffmpeg_bin", "ffmpeg") or "ffmpeg"),
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "s16le",
        "pipe:1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    if proc.stdout is None:
        proc.kill()
        await proc.wait()
        raise RuntimeError("ffmpeg audio decoder did not expose stdout")
    stderr_task = (
        asyncio.create_task(proc.stderr.read())
        if proc.stderr is not None
        else None
    )
    chunks: list[bytes] = []
    total_bytes = 0
    byte_limit = sample_limit * 2
    try:
        while True:
            chunk = await proc.stdout.read(min(64 * 1024, byte_limit - total_bytes + 2))
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > byte_limit:
                proc.kill()
                await proc.wait()
                raise ValueError("Light2D audio exceeds maximum duration")
            chunks.append(chunk)
        returncode = await proc.wait()
        if returncode != 0:
            stderr = await stderr_task if stderr_task is not None else b""
            detail = stderr.decode("utf-8", errors="replace")[-800:]
            raise RuntimeError(f"ffmpeg failed ({returncode}): {detail}")
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        if stderr_task is not None and not stderr_task.done():
            stderr_task.cancel()
    raw = b"".join(chunks)
    if len(raw) % 2:
        raw = raw[:-1]
    return np.frombuffer(raw, dtype="<i2").copy()


class VideoCreationService:
    def __init__(self, settings: object) -> None:
        self.settings = settings

    async def create_from_audio_file(
        self,
        *,
        model: str,
        avatar_id: str,
        upload_path: Path,
        title: str,
        mime_type: str | None = None,
        fasterliveportrait_config: Mapping[str, object] | None = None,
        composition_config: Mapping[str, object] | None = None,
        light2d_renderer: Light2DRenderer | None = None,
    ) -> dict[str, Any]:
        if light2d_renderer is None:
            light2d_renderer = preflight_light2d_video_creation(
                self.settings,
                model=model,
                avatar_id=avatar_id,
                source="upload",
                composition_config=composition_config,
            )
        if light2d_renderer is not None:
            max_samples = 16000 * max(
                0,
                _settings_int(self.settings, "video_creation_light2d_max_duration_sec", 300),
            )
            pcm = await _decode_audio_file_to_pcm_i16_limited(
                self.settings,
                upload_path,
                max_samples=max_samples,
            )
        else:
            pcm = await decode_audio_file_to_pcm_i16(upload_path)
        if pcm.size == 0:
            raise ValueError("audio decoded to empty PCM")
        return await self._create_from_pcm(
            model=model,
            avatar_id=avatar_id,
            pcm=pcm,
            title=title,
            source="upload",
            fasterliveportrait_config=fasterliveportrait_config,
            composition_config=composition_config,
            light2d_renderer=light2d_renderer,
        )

    async def _synthesize_tts_pcm(
        self,
        *,
        text: str,
        voice: str | None,
        tts_provider: str | None,
        tts_model: str | None,
        indextts_config: Mapping[str, object] | None = None,
        max_samples: int | None = None,
    ) -> np.ndarray:
        text_value = text.strip()
        if not text_value:
            raise ValueError("text is required")
        sample_rate = int(getattr(self.settings, "tts_sample_rate", 16000) or 16000)
        tts = build_tts_adapter(
            sample_rate=sample_rate,
            chunk_ms=40.0,
            settings=self.settings,
            default_voice=voice,
            tts_provider=tts_provider,
            tts_model=tts_model,
            indextts_config=indextts_config,
        )
        chunks: list[np.ndarray] = []
        stream_sample_rate: int | None = None
        total_duration_sec = 0.0
        max_duration_sec = None if max_samples is None else float(max_samples) / 16000.0
        try:
            async for chunk in tts.synthesize_stream(text_value, voice=voice):
                arr = np.asarray(chunk.data, dtype=np.int16).reshape(-1)
                if arr.size:
                    chunk_sample_rate = int(chunk.sample_rate or sample_rate)
                    if chunk_sample_rate <= 0:
                        raise ValueError("TTS chunk sample rate must be positive")
                    if stream_sample_rate is None:
                        stream_sample_rate = chunk_sample_rate
                    elif chunk_sample_rate != stream_sample_rate:
                        raise ValueError("TTS returned mixed chunk sample rates")
                    total_duration_sec += float(arr.size) / float(chunk_sample_rate)
                    if max_duration_sec is not None and total_duration_sec > max_duration_sec:
                        raise ValueError("Light2D audio exceeds maximum duration")
                    chunks.append(arr.copy())
        finally:
            close = getattr(tts, "aclose", None)
            if close is not None:
                await close()
        if not chunks:
            raise RuntimeError("TTS returned no audio")
        pcm = np.concatenate(chunks).astype(np.int16, copy=False)
        sample_rate = stream_sample_rate or sample_rate
        if sample_rate != 16000:
            pcm = await self._resample_pcm(pcm, sample_rate)
        return pcm

    async def create_from_tts_text(
        self,
        *,
        model: str,
        avatar_id: str,
        text: str,
        title: str,
        tts_provider: str | None,
        tts_model: str | None,
        voice: str | None,
        source: str = "tts_text",
        fasterliveportrait_config: Mapping[str, object] | None = None,
        indextts_config: Mapping[str, object] | None = None,
        composition_config: Mapping[str, object] | None = None,
        light2d_renderer: Light2DRenderer | None = None,
    ) -> dict[str, Any]:
        if light2d_renderer is None:
            light2d_renderer = preflight_light2d_video_creation(
                self.settings,
                model=model,
                avatar_id=avatar_id,
                source=source,
                text=text,
                composition_config=composition_config,
            )
        max_samples = None
        if light2d_renderer is not None:
            max_samples = 16000 * max(
                0,
                _settings_int(self.settings, "video_creation_light2d_max_duration_sec", 300),
            )
        pcm = await self._synthesize_tts_pcm(
            text=text,
            voice=voice,
            tts_provider=tts_provider,
            tts_model=tts_model,
            indextts_config=indextts_config,
            max_samples=max_samples,
        )
        return await self._create_from_pcm(
            model=model,
            avatar_id=avatar_id,
            pcm=pcm,
            title=title,
            source=source,
            fasterliveportrait_config=fasterliveportrait_config,
            composition_config=composition_config,
            light2d_renderer=light2d_renderer,
        )

    async def create_from_duo_dialog(
        self,
        *,
        model: str,
        avatar_id: str,
        title: str,
        duo_dialog: Mapping[str, object],
        tts_provider: str | None,
        tts_model: str | None,
        indextts_config: Mapping[str, object] | None = None,
        composition_config: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        model_value = _normalize_model(model)
        if model_value != "quicktalk":
            raise ValueError("duo_dialog only supports quicktalk")

        avatar_path = _avatar_dir(self.settings, avatar_id)
        capability = duo_dialog_summary_from_metadata(_avatar_manifest_metadata(avatar_path))
        if capability is None:
            raise ValueError("avatar does not support duo_dialog")
        speaker_faces_raw = capability.get('speaker_faces')
        if not isinstance(speaker_faces_raw, Mapping):
            raise ValueError('avatar duo_dialog speaker_faces is required')
        speaker_faces = {str(key): str(value) for key, value in speaker_faces_raw.items()}
        default_voices_raw = capability.get('default_voices')
        default_voices = (
            {str(key): str(value) for key, value in default_voices_raw.items()}
            if isinstance(default_voices_raw, Mapping)
            else None
        )
        normalized = normalize_duo_dialog_payload(
            duo_dialog,
            speaker_faces=speaker_faces,
            default_voices=default_voices,
        )

        backend = resolve_model_backend(model_value, self.settings)
        backend_name = str(getattr(backend, "backend", "") or "").strip().lower()
        if backend_name != "local":
            raise ValueError("duo_dialog only supports quicktalk local backend")

        normalized_composition_config = _normalize_video_composition_config(self.settings, avatar_path, composition_config)
        template_video = _quicktalk_template_video(self.settings, avatar_path)
        if template_video is None:
            raise FileNotFoundError("quicktalk template video not found")

        job_id = uuid.uuid4().hex
        work_dir = _settings_path(self.settings, "exports_dir", "./data/exports") / "video_creation_jobs" / job_id
        segments_dir = work_dir / "segments"
        segments_dir.mkdir(parents=True, exist_ok=False)
        sample_rate = 16000
        raw_gap_ms = normalized['gap_ms']
        gap_ms = int(raw_gap_ms) if isinstance(raw_gap_ms, (str, int, float)) else 0
        gap_samples = int(round(float(gap_ms) * float(sample_rate) / 1000.0))
        cursor = 0
        total_parts: list[np.ndarray] = []
        script_segments: list[dict[str, object]] = []
        voices = normalized["voices"]
        assert isinstance(voices, Mapping)
        speaker_tts = normalized.get("speakers")
        if not isinstance(speaker_tts, Mapping):
            speaker_tts = {}
        lines = normalized["lines"]
        assert isinstance(lines, list)

        for index, line in enumerate(lines):
            role = str(line["role"])
            text_value = str(line["text"])
            role_config_raw = speaker_tts.get(role)
            role_config = role_config_raw if isinstance(role_config_raw, Mapping) else {}
            voice = str(role_config.get("voice") or voices.get(role) or "") or None
            role_provider = str(role_config.get("tts_provider") or tts_provider or "") or None
            role_model = str(role_config.get("tts_model") or tts_model or "") or None
            role_indextts_config = role_config.get("indextts_config")
            if not isinstance(role_indextts_config, Mapping):
                role_indextts_config = indextts_config
            pcm = await self._synthesize_tts_pcm(
                text=text_value,
                voice=voice,
                tts_provider=role_provider,
                tts_model=role_model,
                indextts_config=role_indextts_config,
            )
            if pcm.size == 0:
                raise RuntimeError("TTS returned no audio")
            segment_wav = segments_dir / f"{index + 1:03d}-{role}.wav"
            _write_wav(segment_wav, pcm, sample_rate)
            start = cursor
            end = start + int(pcm.size)
            script_segments.append(
                {
                    "speaker_id": role,
                    "start_ms": int(round(float(start) * 1000.0 / float(sample_rate))),
                    "end_ms": int(round(float(end) * 1000.0 / float(sample_rate))),
                    "audio": str(segment_wav),
                }
            )
            total_parts.append(pcm)
            cursor = end
            if index < len(lines) - 1 and gap_samples > 0:
                total_parts.append(np.zeros(gap_samples, dtype=np.int16))
                cursor += gap_samples

        total_pcm = np.concatenate(total_parts).astype(np.int16, copy=False) if total_parts else np.zeros(0, dtype=np.int16)
        if total_pcm.size == 0:
            raise RuntimeError("TTS returned no audio")
        audio_wav = work_dir / "audio.wav"
        _write_wav(audio_wav, total_pcm, sample_rate)

        normalized_speaker_faces = normalized.get("speaker_faces")
        script_speaker_faces = (
            {str(key): str(value) for key, value in normalized_speaker_faces.items()}
            if isinstance(normalized_speaker_faces, Mapping)
            else dict(speaker_faces)
        )
        script = {"speaker_faces": script_speaker_faces, "segments": script_segments}
        asset_root = resolve_quicktalk_asset_root(self.settings)
        if asset_root is None:
            raise FileNotFoundError("quicktalk asset root not found")
        worker_cls = _quicktalk_multiface_worker_class()
        worker = worker_cls(
            asset_root=asset_root,
            template_video=template_video,
            face_cache_dir=asset_root / ".face_cache_v3",
            device=_device_for_model(self.settings, model_value),
            hubert_device=str(
                getattr(self.settings, "quicktalk_hubert_device", "")
                or getattr(self.settings, "quicktalk_device", "")
                or getattr(self.settings, "torch_device", "")
                or "cuda:0"
            ),
            max_template_seconds=_settings_or_env_float(
                self.settings,
                "quicktalk_max_template_seconds",
                ("OPENTALKING_QUICKTALK_MAX_TEMPLATE_SECONDS", "OMNIRT_QUICKTALK_MAX_TEMPLATE_SECONDS"),
            ),
            model_backend=_settings_or_env_str(
                self.settings,
                "quicktalk_model_backend",
                ("OPENTALKING_QUICKTALK_MODEL_BACKEND", "OMNIRT_QUICKTALK_MODEL_BACKEND"),
                "auto",
            ),
        )
        frames: list[np.ndarray] = []
        for frame in worker.generate_frames_from_script(script):
            frame_array = _frame_array(frame)
            if frame_array is not None:
                frames.append(frame_array)
        fps = float(getattr(worker, 'fps', 25) or 25)
        composed_frames = _apply_video_composition(frames, config=normalized_composition_config)

        video_only = work_dir / 'video_only.mp4'
        _write_video_only(video_only, composed_frames, fps)
        output_mp4 = work_dir / "result.mp4"
        await _ffmpeg_mux(str(getattr(self.settings, "ffmpeg_bin", "ffmpeg") or "ffmpeg"), video_only, audio_wav, output_mp4)
        content = output_mp4.read_bytes()
        duration = float(total_pcm.size) / float(sample_rate) if sample_rate else None
        item = create_video_export(
            _settings_path(self.settings, "exports_dir", "./data/exports"),
            content=content,
            mime_type="video/mp4",
            kind="video_creation",
            title=_safe_title(title, model=model_value, avatar_id=avatar_id),
            duration_sec=duration,
            session_id=None,
            avatar_id=avatar_id,
            model=model_value,
            max_bytes=_settings_int(self.settings, "export_max_bytes", 1024 * 1024 * 1024),
        )
        log.info(
            "quicktalk duo_dialog export complete: job=%s export_id=%s avatar=%s path=%s",
            job_id,
            item.get("id"),
            avatar_id,
            item.get("path"),
        )
        return {
            "job_id": job_id,
            "status": "done",
            "source": "duo_dialog",
            "export_video": _export_with_download_url(item),
        }

    async def create_reference_video(
        self,
        *,
        model: str,
        avatar_id: str,
        duration_sec: int | None,
        title: str,
        composition_config: Mapping[str, object] | None = None,
        light2d_renderer: Light2DRenderer | None = None,
    ) -> dict[str, Any]:
        model_value = _normalize_model(model)
        if model_value != "flashtalk":
            raise ValueError("reference video generation only supports flashtalk")
        duration = _validate_reference_duration(self.settings, duration_sec)
        sample_rate = 16000
        total_samples = duration * sample_rate
        pcm = await _load_reference_driver_pcm(self.settings, total_samples)
        if pcm is None:
            level = _settings_float(self.settings, "video_creation_reference_driver_level", 480.0)
            pcm = _build_reference_driver_pcm(total_samples, level=level)
        return await self._create_from_pcm(
            model=model_value,
            avatar_id=avatar_id,
            pcm=pcm,
            title=title,
            source="reference_video",
            composition_config=composition_config,
            light2d_renderer=light2d_renderer,
        )

    async def _resample_pcm(self, pcm: np.ndarray, sample_rate: int) -> np.ndarray:
        with tempfile.TemporaryDirectory(prefix="opentalking_vc_resample_") as tmp:
            tmpdir = Path(tmp)
            src = tmpdir / "src.wav"
            out = tmpdir / "out.wav"
            _write_wav(src, pcm, sample_rate)
            proc = await asyncio.create_subprocess_exec(
                str(getattr(self.settings, "ffmpeg_bin", "ffmpeg") or "ffmpeg"),
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(src),
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "wav",
                str(out),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                detail = (stderr or b"").decode("utf-8", errors="replace")[:1200]
                raise RuntimeError(f"ffmpeg resample failed ({proc.returncode}): {detail}")
            with wave.open(str(out), "rb") as wf:
                raw = wf.readframes(wf.getnframes())
            return np.frombuffer(raw, dtype="<i2").copy()

    async def _create_from_pcm(
        self,
        *,
        model: str,
        avatar_id: str,
        pcm: np.ndarray,
        title: str,
        source: str,
        fasterliveportrait_config: Mapping[str, object] | None = None,
        composition_config: Mapping[str, object] | None = None,
        light2d_renderer: Light2DRenderer | None = None,
    ) -> dict[str, Any]:
        model_value = _normalize_model(model)
        if light2d_renderer is None:
            light2d_renderer = preflight_light2d_video_creation(
                self.settings,
                model=model_value,
                avatar_id=avatar_id,
                source=source,
                composition_config=composition_config,
            )
        avatar_path = _avatar_dir(self.settings, avatar_id)
        normalized_composition_config = _normalize_video_composition_config(self.settings, avatar_path, composition_config)
        pcm = np.asarray(pcm, dtype=np.int16).reshape(-1)
        sample_rate = 16000
        if light2d_renderer is not None:
            max_samples = sample_rate * max(
                0,
                _settings_int(self.settings, "video_creation_light2d_max_duration_sec", 300),
            )
            if pcm.size > max_samples:
                raise ValueError("Light2D audio exceeds maximum duration")
        job_id = uuid.uuid4().hex
        work_dir = _settings_path(self.settings, "exports_dir", "./data/exports") / "video_creation_jobs" / job_id
        work_dir.mkdir(parents=True, exist_ok=False)
        audio_wav = work_dir / "audio.wav"

        if light2d_renderer is not None:
            try:
                _write_wav(audio_wav, pcm, sample_rate)
                video_only = work_dir / "video_only.mp4"
                _write_light2d_video_only(
                    video_only,
                    light2d_renderer,
                    pcm,
                    config=normalized_composition_config,
                )
                output_mp4 = work_dir / "result.mp4"
                await _ffmpeg_mux(
                    str(getattr(self.settings, "ffmpeg_bin", "ffmpeg") or "ffmpeg"),
                    video_only,
                    audio_wav,
                    output_mp4,
                )
                duration = float(pcm.size) / float(sample_rate)
                item = create_video_export_from_file(
                    _settings_path(self.settings, "exports_dir", "./data/exports"),
                    source=output_mp4,
                    mime_type="video/mp4",
                    kind="video_creation",
                    title=_safe_title(title, model=model_value, avatar_id=avatar_id),
                    duration_sec=duration,
                    session_id=None,
                    avatar_id=avatar_id,
                    model=model_value,
                    max_bytes=_settings_int(
                        self.settings, "export_max_bytes", 1024 * 1024 * 1024
                    ),
                )
                return {
                    "job_id": job_id,
                    "status": "done",
                    "source": source,
                    "export_video": _export_with_download_url(item),
                }
            finally:
                shutil.rmtree(work_dir, ignore_errors=True)

        _write_wav(audio_wav, pcm, sample_rate)

        backend = resolve_model_backend(model_value, self.settings)
        backend_name = str(getattr(backend, "backend", "") or "").strip().lower()
        ws_url = ""
        if backend_name in {"omnirt", "direct_ws"}:
            ws_url = (
                str(getattr(backend, "ws_url", "") or "")
                if backend_name == "direct_ws"
                else resolve_synthesis_ws_url(model_value, self.settings)
            )
        log.info(
            "video creation audio2video backend: job=%s model=%s avatar=%s backend=%s ws_url=%s",
            job_id,
            model_value,
            avatar_id,
            backend_name or "unknown",
            ws_url,
        )
        client = _audio2video_client(self.settings, model_value, sample_rate, backend=backend)
        preroll_samples = _fasterliveportrait_preroll_samples(self.settings, model_value, sample_rate)
        render_source_pcm = pcm
        if preroll_samples:
            render_source_pcm = np.concatenate([np.zeros(preroll_samples, dtype=np.int16), pcm])

        frames: list[np.ndarray] = []
        try:
            await client.init_session(
                **_init_session_kwargs(
                    model=model_value,
                    avatar_path=avatar_path,
                    settings=self.settings,
                    backend=backend,
                    fasterliveportrait_config=fasterliveportrait_config,
                )
            )
            await client.prewarm()
            chunk_samples = max(1, int(client.audio_chunk_samples or round(sample_rate / max(1, client.fps))))
            pad_len = (-len(render_source_pcm)) % chunk_samples
            render_pcm = render_source_pcm if not pad_len else np.concatenate([
                render_source_pcm,
                np.zeros(pad_len, dtype=np.int16),
            ])
            for start in range(0, len(render_pcm), chunk_samples):
                chunk = render_pcm[start:start + chunk_samples]
                for frame in await client.generate(chunk):
                    arr = _frame_array(frame)
                    if arr is not None:
                        frames.append(arr)
            fps = float(client.fps or 25)
        finally:
            await client.close()

        if preroll_samples:
            drop_frames = max(0, int(round(float(preroll_samples) * fps / float(sample_rate))))
            if drop_frames:
                frames = frames[drop_frames:]
        target_frames = max(1, int(round(float(pcm.size) * fps / float(sample_rate))))
        if len(frames) > target_frames:
            frames = frames[:target_frames]
        frames = _apply_video_composition(frames, config=normalized_composition_config)

        video_only = work_dir / "video_only.mp4"
        _write_video_only(video_only, frames, fps)
        output_mp4 = work_dir / "result.mp4"
        await _ffmpeg_mux(str(getattr(self.settings, "ffmpeg_bin", "ffmpeg") or "ffmpeg"), video_only, audio_wav, output_mp4)
        content = output_mp4.read_bytes()
        duration = float(pcm.size) / float(sample_rate)
        item = create_video_export(
            _settings_path(self.settings, "exports_dir", "./data/exports"),
            content=content,
            mime_type="video/mp4",
            kind="video_creation",
            title=_safe_title(title, model=model_value, avatar_id=avatar_id),
            duration_sec=duration,
            session_id=None,
            avatar_id=avatar_id,
            model=model_value,
            max_bytes=_settings_int(self.settings, "export_max_bytes", 1024 * 1024 * 1024),
        )
        log.info(
            "video creation export complete: job=%s export_id=%s model=%s avatar=%s path=%s",
            job_id,
            item.get("id"),
            model_value,
            avatar_id,
            item.get("path"),
        )
        return {
            "job_id": job_id,
            "status": "done",
            "source": source,
            "export_video": _export_with_download_url(item),
        }
