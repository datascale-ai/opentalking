from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import uuid
import wave
from pathlib import Path
from collections.abc import Mapping
from typing import Any

import cv2
import numpy as np

from opentalking.avatar.fasterliveportrait_config import normalize_fasterliveportrait_runtime_config
from opentalking.avatar.loader import load_avatar_bundle
from opentalking.core.model_config import get_model_config
from opentalking.core.types.frames import VideoFrameData
from opentalking.export_store import create_video_export
from opentalking.models.registry import get_adapter
from opentalking.providers.stt.dashscope.adapter import decode_audio_file_to_pcm_i16
from opentalking.providers.synthesis.audio2video_client import LocalAudio2VideoClient, OmniRTAudio2VideoClient
from opentalking.providers.synthesis.backends import resolve_model_backend
from opentalking.providers.synthesis.flashtalk.ws_client import FlashTalkWSClient
from opentalking.providers.synthesis.omnirt import auth_headers, resolve_synthesis_ws_url
from opentalking.providers.tts.factory import build_tts_adapter

log = logging.getLogger(__name__)

REFERENCE_DRIVER_AUDIO_PATH = Path(__file__).resolve().parent / "assets" / "reference_drivers" / "flashtalk_default_driver.wav"

SUPPORTED_VIDEO_CREATION_MODELS = {
    "flashtalk",
    "flashhead",
    "fasterliveportrait",
    "musetalk",
    "quicktalk",
    "wav2lip",
}


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
    return np.ascontiguousarray(arr[:, :, :3].astype(np.uint8, copy=False))


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
            writer.write(arr)
    finally:
        writer.release()


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
    ) -> dict[str, Any]:
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
        )

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
    ) -> dict[str, Any]:
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
        try:
            async for chunk in tts.synthesize_stream(text_value, voice=voice):
                arr = np.asarray(chunk.data, dtype=np.int16).reshape(-1)
                if arr.size:
                    chunks.append(arr.copy())
                sample_rate = int(chunk.sample_rate or sample_rate)
        finally:
            close = getattr(tts, "aclose", None)
            if close is not None:
                await close()
        if not chunks:
            raise RuntimeError("TTS returned no audio")
        pcm = np.concatenate(chunks).astype(np.int16, copy=False)
        if sample_rate != 16000:
            pcm = await self._resample_pcm(pcm, sample_rate)
        return await self._create_from_pcm(
            model=model,
            avatar_id=avatar_id,
            pcm=pcm,
            title=title,
            source=source,
            fasterliveportrait_config=fasterliveportrait_config,
        )

    async def create_reference_video(
        self,
        *,
        model: str,
        avatar_id: str,
        duration_sec: int | None,
        title: str,
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
    ) -> dict[str, Any]:
        model_value = _normalize_model(model)
        avatar_path = _avatar_dir(self.settings, avatar_id)
        job_id = uuid.uuid4().hex
        work_dir = _settings_path(self.settings, "exports_dir", "./data/exports") / "video_creation_jobs" / job_id
        work_dir.mkdir(parents=True, exist_ok=False)
        pcm = np.asarray(pcm, dtype=np.int16).reshape(-1)
        sample_rate = 16000
        audio_wav = work_dir / "audio.wav"
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

        video_only = work_dir / "video_only.mp4"
        _write_video_only(video_only, frames, fps)
        output_mp4 = work_dir / "result.mp4"
        await _ffmpeg_mux(str(getattr(self.settings, "ffmpeg_bin", "ffmpeg") or "ffmpeg"), video_only, audio_wav, output_mp4)
        content = output_mp4.read_bytes()
        duration = float(pcm.size) / float(sample_rate) if sample_rate else None
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
