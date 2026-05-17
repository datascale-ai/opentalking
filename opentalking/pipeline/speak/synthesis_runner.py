"""
FlashTalkSessionRunner – drives the full conversation pipeline:

    user text → LLM → TTS (Edge 或 OPENTALKING_TTS_PROVIDER) → FlashTalk backend → WebRTC
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import numpy as np

from opentalking.avatar.wav2lip_config import (
    normalize_wav2lip_postprocess_mode,
    optional_wav2lip_postprocess_mode,
    read_manifest_preferred_wav2lip_postprocess_mode,
)
from opentalking.avatar.fasterliveportrait_config import (
    normalize_fasterliveportrait_runtime_config,
)
from opentalking.core.config import get_settings
from opentalking.core.session_store import (
    FLASHTALK_DISK_RECORDING_FIELD,
    session_key,
)
from opentalking.providers.synthesis.flashtalk.idle_generator import IdleVideoGenerator
from opentalking.core.session_store import set_session_state
from opentalking.providers.llm.openai_compatible.adapter import OpenAICompatibleLLMClient
from opentalking.providers.llm.openai_compatible.sentence_splitter import SentenceSplitter
from opentalking.providers.llm.openai_compatible.conversation import ConversationHistory
from opentalking.providers.synthesis.flashtalk.ws_client import FlashTalkWSClient
from opentalking.providers.rtc.aiortc.adapter import WebRTCSession
from opentalking.providers.tts.factory import create_tts_adapter, tts_log_profile
from opentalking.runtime.bus import publish_event
from opentalking.pipeline.speak.text_sanitize import sanitize_tts_text, strip_emoji

log = logging.getLogger(__name__)

_IDLE_CACHE_VERSION = 6
_IDLE_FRAME_CACHE: dict[str, list[np.ndarray]] = {}
_IDLE_CACHE_LOCKS: dict[str, asyncio.Lock] = {}
_TTS_OPENER_PCM_CACHE: dict[str, np.ndarray] = {}
_TTS_OPENER_CACHE_LOCKS: dict[str, asyncio.Lock] = {}
_TTS_OPENER_PRELOAD_TASK: asyncio.Task[None] | None = None
_SENTINEL = object()  # unique marker for "not yet set"

from opentalking.pipeline.speak.tts_openers import (
    TTS_OPENER_FALLBACKS as _TTS_OPENER_FALLBACKS,
    TTS_OPENER_RULES as _TTS_OPENER_RULES,
)


from opentalking.pipeline.speak.env_helpers import (
    default_flashtalk_ws_url as _default_flashtalk_ws_url,
    env_bool as _env_bool,
    env_float as _env_float,
    env_int as _env_int,
)


def _idle_cache_dir() -> Path:
    s = get_settings()
    if s.flashtalk_idle_cache_dir:
        return Path(s.flashtalk_idle_cache_dir)
    return Path(s.models_dir) / ".idle_cache"


from opentalking.pipeline.speak.audio_utils import (
    fade_edges_i16 as _fade_edges_i16,
    fade_head_i16 as _fade_head_i16,
    fade_tail_i16 as _fade_tail_i16,
)


def _idle_cache_lock(cache_key: str) -> asyncio.Lock:
    lock = _IDLE_CACHE_LOCKS.get(cache_key)
    if lock is None:
        lock = asyncio.Lock()
        _IDLE_CACHE_LOCKS[cache_key] = lock
    return lock


def _tts_opener_cache_lock(cache_key: str) -> asyncio.Lock:
    lock = _TTS_OPENER_CACHE_LOCKS.get(cache_key)
    if lock is None:
        lock = asyncio.Lock()
        _TTS_OPENER_CACHE_LOCKS[cache_key] = lock
    return lock


def _build_idle_driver_pcm(
    *,
    total_samples: int,
    level: float,
) -> np.ndarray:
    """Generate a low-energy periodic driver so the idle clip loops cleanly."""
    if total_samples <= 0:
        return np.zeros(0, dtype=np.int16)

    phase = np.linspace(0.0, 2.0 * np.pi, total_samples, endpoint=False, dtype=np.float32)
    envelope = 0.35 + 0.65 * (0.5 - 0.5 * np.cos(phase))
    harmonic = (
        0.58 * np.sin(phase)
        + 0.27 * np.sin(2.0 * phase + 0.65)
        + 0.15 * np.sin(3.0 * phase + 1.35)
    )
    shimmer = 0.08 * np.sin(5.0 * phase + 0.2)
    signal = envelope * (harmonic + shimmer)

    peak = float(np.max(np.abs(signal))) if signal.size else 1.0
    peak = max(peak, 1e-6)
    pcm = np.clip(signal / peak * level, -32767.0, 32767.0)
    return pcm.astype(np.int16)


from opentalking.pipeline.speak.idle_frames import (
    blend_frames as _blend_frames,
    build_idle_playback_indices as _build_idle_playback_indices,
    build_soft_ellipse_mask as _build_soft_ellipse_mask,
    idle_frame_signature as _idle_frame_signature,
    motion_score as _motion_score,
    optimize_idle_loop as _optimize_idle_loop,
    stabilize_idle_mouth as _stabilize_idle_mouth,
)


from opentalking.pipeline.speak.tts_openers import (
    build_tts_opener_candidates as _build_tts_opener_candidates,
    contains_any as _contains_any,
    iter_tts_opener_variants as _iter_tts_opener_variants,
    join_tts_fragments as _join_tts_fragments,
    normalize_tts_lookup_text as _normalize_tts_lookup_text,
    speech_char_count as _speech_char_count,
)


from opentalking.pipeline.speak.audio_utils import trim_trailing_silence_i16 as _trim_trailing_silence_i16


from opentalking.pipeline.speak.tts_openers import (
    merge_spoken_reply as _merge_spoken_reply,
    strip_redundant_greeting_lead as _strip_redundant_greeting_lead,
)


async def _synthesize_tts_opener_pcm(
    text: str,
    *,
    sample_rate: int,
    default_voice: str | None = None,
) -> tuple[np.ndarray, bool]:
    cache_key = f"v2:{sample_rate}:{default_voice or '_'}:{text}"
    cached = _TTS_OPENER_PCM_CACHE.get(cache_key)
    if cached is not None:
        return np.array(cached, copy=True), True

    lock = _tts_opener_cache_lock(cache_key)
    async with lock:
        cached = _TTS_OPENER_PCM_CACHE.get(cache_key)
        if cached is not None:
            return np.array(cached, copy=True), True

        tts = create_tts_adapter(
            sample_rate=sample_rate, chunk_ms=400.0, default_voice=default_voice
        )
        parts: list[np.ndarray] = []
        try:
            async for chunk in tts.synthesize_stream(text):
                pcm = np.asarray(chunk.data, dtype=np.int16)
                if pcm.size:
                    parts.append(np.ascontiguousarray(pcm))
        finally:
            if hasattr(tts, "aclose"):
                await tts.aclose()
        if not parts:
            raise RuntimeError(f"Failed to synthesize TTS opener: {text}")

        pcm = np.concatenate(parts).astype(np.int16, copy=False)
        _TTS_OPENER_PCM_CACHE[cache_key] = np.ascontiguousarray(pcm)
        return np.array(pcm, copy=True), False


async def _preload_tts_openers(sample_rate: int, default_voice: str | None = None) -> None:
    for _, opener_text in _iter_tts_opener_variants():
        try:
            await _synthesize_tts_opener_pcm(
                opener_text,
                sample_rate=sample_rate,
                default_voice=default_voice,
            )
        except Exception:
            log.warning("Failed to preload TTS opener %r", opener_text, exc_info=True)


class FlashTalkRunner:
    """Session runner that uses a FlashTalk backend for video generation."""

    def __init__(
        self,
        *,
        session_id: str,
        avatar_id: str,
        avatars_root: Path,
        redis: Any,
        flashtalk_ws_url: str | None = None,
        flashtalk_client: Any | None = None,
        custom_ref_image_path: str = "",
        llm_base_url: str = "",
        llm_api_key: str = "",
        llm_model: str = "qwen-turbo",
        system_prompt: str = "你是一个友好的数字人助手，请用简洁的语言回答问题。",
        model_type: str = "flashtalk",
        wav2lip_postprocess_mode: str | None = None,
        fasterliveportrait_config: dict[str, object] | None = None,
    ) -> None:
        self.session_id = session_id
        self.avatar_id = avatar_id
        self.model_type = model_type
        self._wav2lip_postprocess_mode_override = optional_wav2lip_postprocess_mode(wav2lip_postprocess_mode)
        self._fasterliveportrait_config_override = normalize_fasterliveportrait_runtime_config(
            fasterliveportrait_config
        )
        self.avatars_root = avatars_root
        self.redis = redis
        self._flashtalk_ws_url = flashtalk_ws_url or _default_flashtalk_ws_url()
        self._custom_ref_image_path = custom_ref_image_path.strip()
        # Auth headers for OmniRT (empty when OMNIRT_API_KEY is unset).
        from opentalking.providers.synthesis.omnirt import auth_headers as _omnirt_auth_headers
        self._extra_ws_headers = _omnirt_auth_headers(get_settings())

        self.flashtalk = flashtalk_client or FlashTalkWSClient(
            self._flashtalk_ws_url,
            extra_headers=self._extra_ws_headers,
        )
        # Remote FlashTalk serves a single active session; a second background
        # init for idle-cache building can replace the live session underneath us.
        self._allow_background_idle_cache = flashtalk_client is not None and self.model_type == "flashtalk"

        # LLM client
        self.llm = OpenAICompatibleLLMClient(
            base_url=llm_base_url,
            api_key=llm_api_key,
            model=llm_model,
        )
        self.conversation = ConversationHistory(
            system_prompt=system_prompt,
            max_turns=20,
        )

        # WebRTC (created in prepare)
        self.webrtc: WebRTCSession | None = None

        # State
        self._speak_lock = asyncio.Lock()
        self._interrupt = asyncio.Event()
        self.ready_event = asyncio.Event()
        self._prepared = self.ready_event
        self._webrtc_started = asyncio.Event()
        self.speech_tasks: set[asyncio.Task[None]] = set()
        self._speaking = False
        self._speech_started = False
        self._closed = False
        self._idle_task: asyncio.Task[None] | None = None
        self._generate_lock = asyncio.Lock()
        self._ref_image_path: Path | None = None
        self._idle_cache_key: str | None = None
        self._idle_frames: list[np.ndarray] = []
        self._idle_playback_indices: list[int] = []
        self._idle_frame_idx = 0
        self._reference_frame: np.ndarray | None = None
        self._last_frame: np.ndarray | None = None  # cached for idle loop
        self._tts_opener_recent_ids: list[str] = []
        self._tts_opener_warm_task: asyncio.Task[None] | None = None
        self._media_clock_started = False
        self._av_ts_ms = 0.0
        self._speech_media_active = False
        #: Background dynamic idle cache (closes main WS briefly); speak() must await this.
        self._dynamic_idle_prepare_task: asyncio.Task[None] | None = None
        self._recording_frame_index = 0
        self._debug_frame_trace = os.environ.get("OPENTALKING_RTC_DEBUG_FRAMES", "").strip().lower() in {"1", "true", "yes", "on"}
        self._debug_queued_video_count = 0
        self._debug_prev_video_mean: float | None = None

    def _wav2lip_mouth_metadata(self) -> dict[str, Any] | None:
        if self.model_type != "wav2lip":
            return None
        manifest_path = self.avatar_path() / "manifest.json"
        if not manifest_path.exists():
            return None
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            log.warning("Failed to read wav2lip avatar metadata: %s", manifest_path, exc_info=True)
            return None
        metadata = raw.get("metadata")
        if not isinstance(metadata, dict):
            return None
        animation = metadata.get("animation")
        if not isinstance(animation, dict):
            return None
        source_image_hash = metadata.get("source_image_hash")
        if source_image_hash:
            try:
                from opentalking.avatar.mouth_metadata import image_file_sha256

                reference_path = self._wav2lip_reference_image_path()
                if reference_path is None or image_file_sha256(reference_path) != source_image_hash:
                    log.warning("Ignoring stale wav2lip mouth metadata: %s", manifest_path)
                    return None
            except Exception:
                log.warning("Failed to validate wav2lip mouth metadata hash: %s", manifest_path, exc_info=True)
                return None
        return {
            "source_image_hash": source_image_hash,
            "source_image_path": metadata.get("source_image_path"),
            "face_box": metadata.get("face_box"),
            "animation": animation,
        }

    def _wav2lip_reference_image_path(self) -> Path | None:
        custom = getattr(self, "_custom_ref_image_path", "")
        if custom:
            path = Path(custom).expanduser().resolve()
            return path if path.exists() else None
        cached = getattr(self, "_ref_image_path", None)
        if isinstance(cached, Path) and cached.exists():
            return cached
        avatar_dir = self.avatar_path()
        for name in ("reference.png", "reference.jpg", "reference.jpeg", "reference.webp"):
            path = avatar_dir / name
            if path.exists():
                return path
        return None

    def _wav2lip_postprocess_mode(self) -> str | None:
        if self.model_type != "wav2lip":
            return None
        override = getattr(self, "_wav2lip_postprocess_mode_override", None)
        if override:
            return override
        raw = os.environ.get("OPENTALKING_WAV2LIP_POSTPROCESS_MODE", "easy_improved")
        default = normalize_wav2lip_postprocess_mode(raw)
        return read_manifest_preferred_wav2lip_postprocess_mode(
            self.avatar_path() / "manifest.json",
            default=default,
        )

    @staticmethod
    def _even_video_dim(value: int) -> int:
        value = max(2, int(value))
        return value + (value % 2)

    def _manifest_video_config(self, *, model_type: str) -> dict[str, int] | None:
        if self.model_type != model_type:
            return None
        manifest_path = self.avatar_path() / "manifest.json"
        if not manifest_path.exists():
            return None
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            log.warning(
                "Failed to read %s avatar video config: %s",
                model_type,
                manifest_path,
                exc_info=True,
            )
            return None
        out: dict[str, int] = {}
        for key in ("width", "height", "fps"):
            try:
                value = int(raw.get(key) or 0)
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                out[key] = value
        return out or None

    def _fasterliveportrait_video_config(
        self,
        ref_image_path: Path | None = None,
    ) -> dict[str, Any] | None:
        if self.model_type != "fasterliveportrait":
            return None
        try:
            from opentalking.core.model_config import get_model_config

            config = get_model_config("fasterliveportrait")
        except Exception:
            log.warning("Failed to load fasterliveportrait config", exc_info=True)
            return None
        out: dict[str, Any] = {}
        for key in (
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
            "flag_normalize_lip",
            "flag_relative_motion",
            "flag_lip_retargeting",
            "lip_retargeting_multiplier",
            "lip_retargeting_min",
            "lip_retargeting_max",
            "lip_retargeting_noise_floor",
            "head_only_pasteback",
            "lookahead_ms",
        ):
            value = config.get(key)
            if value is not None:
                out[key] = value
        out.update(getattr(self, "_fasterliveportrait_config_override", {}) or {})
        if out.get("flag_stitching"):
            image_path = ref_image_path or self._ref_image_path
            if image_path is not None and image_path.exists():
                try:
                    from PIL import Image

                    with Image.open(image_path) as image:
                        image_w, image_h = image.size
                    target_w = self._even_video_dim(int(out.get("width") or 512))
                    if image_w > 0 and image_h > 0:
                        out["width"] = target_w
                        out["height"] = self._even_video_dim(
                            round(target_w * image_h / image_w)
                        )
                except Exception:
                    log.warning(
                        "Failed to preserve fasterliveportrait reference aspect ratio: %s",
                        image_path,
                        exc_info=True,
                    )
        return out or None

    async def update_fasterliveportrait_runtime_config(
        self,
        config: dict[str, object],
    ) -> dict[str, object]:
        if self.model_type != "fasterliveportrait":
            raise RuntimeError("session is not fasterliveportrait")
        normalized = normalize_fasterliveportrait_runtime_config(config)
        if not normalized:
            return {"type": "config_ok", "updated": {}}
        async with self._generate_lock:
            update = getattr(self.flashtalk, "update_runtime_config", None)
            if callable(update):
                response = await update(normalized)
                self._fasterliveportrait_config_override.update(normalized)
                return response
        self._fasterliveportrait_config_override.update(normalized)
        return {"type": "config_ok", "updated": normalized}

    def _fasterliveportrait_ref_image_payload(
        self,
        ref_image_path: Path,
        video_config: dict[str, Any] | None,
    ) -> bytes | Path:
        if self.model_type != "fasterliveportrait" or not video_config:
            return ref_image_path
        try:
            target_w = int(video_config.get("width") or 0)
            target_h = int(video_config.get("height") or 0)
        except (TypeError, ValueError):
            return ref_image_path
        if target_w <= 0 or target_h <= 0:
            return ref_image_path
        try:
            from PIL import Image
            from opentalking.media.frame_avatar import resize_reference_image_to_video

            with Image.open(ref_image_path) as image:
                resized = resize_reference_image_to_video(
                    image.convert("RGB"), width=target_w, height=target_h
                )
            buffer = io.BytesIO()
            resized.save(buffer, format="PNG")
            return buffer.getvalue()
        except Exception:
            log.warning(
                "Failed to resize fasterliveportrait reference payload: %s",
                ref_image_path,
                exc_info=True,
            )
            return ref_image_path

    def _wav2lip_video_config(self) -> dict[str, int] | None:
        return self._manifest_video_config(model_type="wav2lip")

    def _quicktalk_video_config(self) -> dict[str, int] | None:
        config = self._manifest_video_config(model_type="quicktalk")
        if config is None:
            config = {}
        config["fps"] = 25
        return config

    def _wav2lip_manifest_metadata(self) -> dict[str, Any]:
        if self.model_type != "wav2lip":
            return {}
        return self._avatar_manifest_metadata()

    def _avatar_manifest_metadata(self) -> dict[str, Any]:
        manifest_path = self.avatar_path() / "manifest.json"
        if not manifest_path.exists():
            return {}
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            log.warning("Failed to read wav2lip avatar manifest: %s", manifest_path, exc_info=True)
            return {}
        metadata = raw.get("metadata")
        return metadata if isinstance(metadata, dict) else {}

    def _quicktalk_manifest_metadata(self) -> dict[str, Any]:
        if self.model_type != "quicktalk":
            return {}
        return self._avatar_manifest_metadata()

    def _resolve_avatar_relative_path(self, raw: str) -> Path | None:
        raw = raw.strip()
        if not raw:
            return None
        path = (self.avatar_path() / raw).resolve()
        try:
            path.relative_to(self.avatar_path())
        except ValueError:
            log.warning("Ignoring avatar path outside avatar directory: %s", path)
            return None
        return path

    def _quicktalk_manifest_section(self) -> dict[str, Any]:
        metadata = self._quicktalk_manifest_metadata()
        quicktalk = metadata.get("quicktalk")
        return quicktalk if isinstance(quicktalk, dict) else {}

    def _quicktalk_face_cache(self) -> Path | None:
        if self.model_type != "quicktalk":
            return None
        quicktalk = self._quicktalk_manifest_section()
        path = self._resolve_avatar_relative_path(str(quicktalk.get("face_cache") or ""))
        if path is not None and path.is_file():
            return path
        if path is not None:
            log.warning("Ignoring missing quicktalk face_cache: %s", path)
        return None

    def _quicktalk_template_video(self) -> Path | None:
        metadata = self._quicktalk_manifest_metadata()
        quicktalk = self._quicktalk_manifest_section()
        for source in (quicktalk, metadata):
            for key in ("template_video", "source_video"):
                path = self._resolve_avatar_relative_path(str(source.get(key) or ""))
                if path is not None and path.is_file():
                    return path
                if path is not None:
                    log.warning("Ignoring missing quicktalk template video: %s", path)
        for name in ("idle.mp4", "idle.mov", "idle.webm", "idle.avi", "source.mp4"):
            path = self.avatar_path() / name
            if path.is_file():
                return path.resolve()
        return None

    def _quicktalk_template_frame_dir(self) -> Path | None:
        metadata = self._quicktalk_manifest_metadata()
        if str(metadata.get("reference_mode") or "").strip().lower() != "frames":
            return None
        raw = str(metadata.get("frame_dir") or "frames").strip() or "frames"
        frame_dir = self._resolve_avatar_relative_path(raw)
        if frame_dir is None:
            return None
        if not frame_dir.is_dir():
            log.warning("Ignoring missing quicktalk template frame_dir: %s", frame_dir)
            return None
        return frame_dir

    def _quicktalk_template_mode(self) -> str | None:
        if self.model_type != "quicktalk":
            return None
        if self._quicktalk_template_video() is not None:
            return "video"
        if self._quicktalk_template_frame_dir() is not None:
            return "frames"
        return "image"

    def _wav2lip_reference_mode(self) -> str | None:
        metadata = self._wav2lip_manifest_metadata()
        mode = str(metadata.get("reference_mode") or "").strip().lower()
        return mode if mode in {"frames"} else None

    def _wav2lip_reference_frame_dir(self) -> Path | None:
        if self._wav2lip_reference_mode() != "frames":
            return None
        metadata = self._wav2lip_manifest_metadata()
        raw = str(metadata.get("frame_dir") or "frames").strip() or "frames"
        frame_dir = (self.avatar_path() / raw).resolve()
        try:
            frame_dir.relative_to(self.avatar_path())
        except ValueError:
            log.warning("Ignoring wav2lip frame_dir outside avatar directory: %s", frame_dir)
            return None
        if not frame_dir.is_dir():
            log.warning("Ignoring missing wav2lip frame_dir: %s", frame_dir)
            return None
        return frame_dir

    def _wav2lip_reference_frame_metadata_path(self) -> Path | None:
        if self._wav2lip_reference_mode() != "frames":
            return None
        metadata = self._wav2lip_manifest_metadata()
        raw = str(metadata.get("frame_metadata") or "").strip()
        if not raw:
            return None
        path = (self.avatar_path() / raw).resolve()
        try:
            path.relative_to(self.avatar_path())
        except ValueError:
            log.warning("Ignoring wav2lip frame_metadata outside avatar directory: %s", path)
            return None
        if not path.is_file():
            log.warning("Ignoring missing wav2lip frame_metadata: %s", path)
            return None
        return path

    def _wav2lip_preprocessed(self) -> bool:
        if self._wav2lip_reference_mode() != "frames":
            return False
        metadata = self._wav2lip_manifest_metadata()
        return bool(metadata.get("preprocessed"))

    def avatar_path(self) -> Path:
        return (self.avatars_root / self.avatar_id).resolve()

    def _resolve_idle_ref_image(self, avatar_dir: Path, fallback: Path) -> Path:
        """Return the idle-specific reference image if declared in manifest or present on disk.

        Priority:
          1. manifest.json  "idle_reference" field  (relative to avatar_dir)
          2. idle_reference.png / idle_reference.jpg  (convention)
          3. fallback (the speech reference image)
        """
        # 1. manifest field
        manifest = avatar_dir / "manifest.json"
        if manifest.exists():
            try:
                import json
                data = json.loads(manifest.read_text(encoding="utf-8"))
                idle_ref = data.get("idle_reference", "")
                if idle_ref:
                    p = (avatar_dir / idle_ref).resolve()
                    if p.exists():
                        log.info("Using idle_reference from manifest: %s", p)
                        return p
                    log.warning("manifest idle_reference not found: %s", p)
            except Exception:
                log.exception("Failed to read manifest for idle_reference")

        # 2. convention filenames
        for name in ("idle_reference.png", "idle_reference.jpg"):
            p = avatar_dir / name
            if p.exists():
                log.info("Using idle_reference by convention: %s", p)
                return p

        # 3. fall back to speech reference
        return fallback

    async def prepare(self) -> None:
        """Load avatar, connect to FlashTalk server, init session."""
        avatar_dir = self.avatar_path()

        # Read reference image (used for speech generation); optional API 上传的 reference_custom.*
        if self._custom_ref_image_path:
            ref_image_path = Path(self._custom_ref_image_path).expanduser().resolve()
        else:
            ref_image_path = avatar_dir / "reference.png"
            if not ref_image_path.exists():
                ref_image_path = avatar_dir / "reference.jpg"
        if not ref_image_path.exists():
            raise FileNotFoundError(
                f"No reference image (custom or {avatar_dir}/reference.png|.jpg)"
            )

        self._ref_image_path = ref_image_path

        # Connect and init FlashTalk session
        await self.flashtalk.connect()
        await self._init_flashtalk_session(ref_image_path)

        # Create WebRTC session matching FlashTalk output
        self.webrtc = WebRTCSession(
            fps=float(self.flashtalk.fps),
            sample_rate=16000,
        )

        # Auto-close session when WebRTC peer disconnects (releases the slot lock)
        @self.webrtc.pc.on("connectionstatechange")
        async def _on_connection_state_change() -> None:
            state = self.webrtc.pc.connectionState if self.webrtc else None
            if state in ("failed", "closed", "disconnected"):
                log.info(
                    "WebRTC connection %s for session %s, auto-closing",
                    state, self.session_id,
                )
                if not self._closed:
                    await self.close()

        # Load reference image as initial idle frame
        try:
            from PIL import Image
            from opentalking.media.frame_avatar import resize_reference_image_to_video

            pil_img = Image.open(ref_image_path).convert("RGB")
            target_w = int(getattr(self.flashtalk, "width", 0) or 0)
            target_h = int(getattr(self.flashtalk, "height", 0) or 0)
            pil_img = resize_reference_image_to_video(pil_img, width=target_w, height=target_h)
            img = np.asarray(pil_img)
            # Convert RGB to BGR for WebRTC.
            self._reference_frame = img[:, :, ::-1].copy()
            self._last_frame = self._reference_frame.copy()
        except Exception:
            log.exception("Failed to load reference frame for idle preview: %s", ref_image_path)
            self._reference_frame = None
            self._last_frame = None

        if self.model_type == "wav2lip" and self._wav2lip_reference_mode() == "frames":
            idle_frames = self._load_wav2lip_reference_idle_frames()
            if idle_frames:
                self._set_idle_frames(idle_frames)
                log.info(
                    "Loaded wav2lip reference frames for idle playback: avatar=%s frames=%d",
                    self.avatar_id,
                    len(idle_frames),
                )

        if self.model_type == "fasterliveportrait" and self._reference_frame is not None:
            self._set_idle_frames(self._build_fasterliveportrait_idle_frames(self._reference_frame))
            log.info(
                "Built fasterliveportrait local idle frames: avatar=%s frames=%d",
                self.avatar_id,
                len(self._idle_frames),
            )

        # Start idle loop after init; it replays local cached frames when WebRTC is live.
        if self._idle_task is None:
            self._idle_task = asyncio.create_task(self._idle_loop())

        self.ready_event.set()
        log.info(
            "FlashTalkRunner prepared: session=%s, avatar=%s model=%s",
            self.session_id,
            self.avatar_id,
            self.model_type,
        )

        # Build idle cache in background for all modes (local and remote).
        # IdleVideoGenerator opens its own WS connection so it never evicts
        # the live session.
        if self.model_type == "flashtalk" and get_settings().flashtalk_idle_enable:
            self._dynamic_idle_prepare_task = asyncio.create_task(
                self._prepare_dynamic_idle_cache(ref_image_path)
            )
        elif self._allow_background_idle_cache:
            asyncio.create_task(self._prepare_idle_cache_background(ref_image_path))

        global _TTS_OPENER_PRELOAD_TASK
        if self._tts_opener_enabled_for_model() and self._tts_opener_preload_enabled_for_model():
            task = _TTS_OPENER_PRELOAD_TASK
            if task is None or task.done():
                _TTS_OPENER_PRELOAD_TASK = asyncio.create_task(
                    _preload_tts_openers(
                        sample_rate=16000,
                        default_voice=self._tts_opener_preload_voice(),
                    )
                )
            self._tts_opener_warm_task = _TTS_OPENER_PRELOAD_TASK

    async def _await_dynamic_idle_prepare_done(self) -> None:
        """Avoid speak() while dynamic idle prep has closed the main FlashTalk socket."""
        task = self._dynamic_idle_prepare_task
        if task is None or task.done():
            return
        log.info(
            "Waiting for dynamic idle cache build before speak (session=%s)",
            self.session_id,
        )
        try:
            await task
        except Exception:
            pass

    async def _prepare_dynamic_idle_cache(self, ref_image_path: Path) -> None:
        """Build idle clip via IdleVideoGenerator (background, non-blocking)."""
        try:
            # Check for pre-recorded idle video first.
            idle_video = self._load_idle_video(ref_image_path.parent)
            if idle_video:
                self._set_idle_frames(idle_video)
                log.info(
                    "Loaded pre-recorded idle video: avatar=%s frames=%d",
                    self.avatar_id, len(idle_video),
                )
                return

            s = get_settings()
            gen = IdleVideoGenerator(
                ws_url=self._flashtalk_ws_url,
                avatar_id=self.avatar_id,
                ref_image_path=ref_image_path,
                cache_dir=_idle_cache_dir(),
                chunks=max(1, _env_int("FLASHTALK_IDLE_CACHE_CHUNKS", 4)),
                level=max(10.0, _env_float("FLASHTALK_IDLE_CACHE_LEVEL", 80.0)),
                crossfade=max(2, _env_int("FLASHTALK_IDLE_CACHE_CROSSFADE_FRAMES", 6)),
                mouth_lock=max(0.0, min(1.0, s.flashtalk_idle_mouth_lock)),
                mouth_temporal=max(0.0, min(1.0, _env_float("FLASHTALK_IDLE_MOUTH_TEMPORAL", 0.85))),
                reference_frame=self._reference_frame,
                extra_headers=self._extra_ws_headers,
            )

            # Try disk cache first — no need to touch the main WS connection.
            w = self.flashtalk.width
            h = self.flashtalk.height
            fps = self.flashtalk.fps
            cs = self.flashtalk.audio_chunk_samples
            key = gen._cache_key(w, h, fps, cs)
            cached = gen.load_from_disk(key)
            if cached:
                from opentalking.providers.synthesis.flashtalk.idle_generator import _prompt_fingerprint
                fp = _prompt_fingerprint(gen._init_prompt)
                log.info(
                    "Idle cache hit (disk): avatar=%s frames=%d cache_key=%s prompt_fp=%s seed=%d prompt_len=%d",
                    self.avatar_id, len(cached), key[:16], fp, gen._init_seed, len(gen._init_prompt),
                )
                self._set_idle_frames(cached)
                log.info(
                    "Dynamic idle cache ready: avatar=%s frames=%d",
                    self.avatar_id, len(cached),
                )
                return

            # Cache miss — must generate.  Close main session so the server
            # (single-session architecture) doesn't deadlock on concurrent HCCL.
            await self.flashtalk.close()
            frames = await gen.get_or_build(
                width=w, height=h, fps=fps, chunk_samples=cs,
            )
            # Re-init main session so speech generation can proceed.
            await self._reset_flashtalk_session(ref_image_path)
            if frames:
                self._set_idle_frames(frames)
                log.info(
                    "Dynamic idle cache ready: avatar=%s frames=%d",
                    self.avatar_id, len(frames),
                )
        except Exception:
            log.exception(
                "Dynamic idle cache build failed (non-fatal): avatar=%s", self.avatar_id
            )

    async def _prepare_idle_cache_background(self, ref_image_path: Path) -> None:
        """Build idle cache without blocking session readiness."""
        try:
            await self._prepare_idle_cache(ref_image_path)
        except Exception:
            log.exception("Background idle cache build failed (non-fatal)")

    async def _idle_loop(self) -> None:
        """Replay cached idle frames locally for smooth visual continuity."""
        fps = float(self.flashtalk.fps) if self.flashtalk.fps else 25.0
        interval = 1.0 / fps
        while not self._closed:
            if self.model_type == "fasterliveportrait":
                await asyncio.sleep(interval)
                continue
            if (
                (self._speaking and self._speech_media_active)
                or not self.webrtc
                or not self._webrtc_started.is_set()
            ):
                await asyncio.sleep(interval)
                continue
            try:
                await self._idle_tick()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("Idle playback tick failed: session=%s", self.session_id)
                await asyncio.sleep(interval)
                continue

    async def _idle_tick(self) -> None:
        if not self.webrtc:
            return
        if self.webrtc.draining:   # block idle injection during queue drain
            return
        from opentalking.core.types.frames import VideoFrameData
        if self._idle_frames:
            if self._idle_playback_indices:
                frame_idx = self._idle_playback_indices[
                    self._idle_frame_idx % len(self._idle_playback_indices)
                ]
            else:
                frame_idx = self._idle_frame_idx % len(self._idle_frames)
            idle_frame = self._idle_frames[frame_idx]
            self._idle_frame_idx += 1
        elif self._last_frame is not None:
            idle_frame = self._last_frame
        else:
            return

        self._ensure_media_clock_started()
        frame = VideoFrameData(
            data=idle_frame,
            width=idle_frame.shape[1],
            height=idle_frame.shape[0],
            timestamp_ms=0.0,
        )
        await self._video_put_safe(frame)

    def _idle_cache_path(self, avatar_dir: Path) -> Path:
        return avatar_dir / f".flashtalk_idle_cache_v{_IDLE_CACHE_VERSION}.npz"

    def _load_idle_video(self, avatar_dir: Path) -> list[np.ndarray] | None:
        """Load a pre-recorded idle video from the avatar directory.

        Looks for idle.mp4 / idle.webm / idle.avi.  Resizes frames to match
        the FlashTalk output resolution and converts RGB→BGR.
        """
        for ext in ("mp4", "webm", "avi", "mov"):
            p = avatar_dir / f"idle.{ext}"
            if p.exists():
                break
        else:
            return None

        import cv2
        cap = cv2.VideoCapture(str(p))
        if not cap.isOpened():
            log.warning("Cannot open idle video: %s", p)
            return None

        target_w = self.flashtalk.width
        target_h = self.flashtalk.height
        frames: list[np.ndarray] = []
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            h, w = frame.shape[:2]
            if (w, h) != (target_w, target_h):
                import math
                scale = max(target_h / h, target_w / w)
                fw = math.ceil(scale * w)
                fh = math.ceil(scale * h)
                frame = cv2.resize(
                    frame, (fw, fh),
                    interpolation=cv2.INTER_AREA,
                )
                top = (fh - target_h) // 2
                left = (fw - target_w) // 2
                frame = frame[
                    top:top + target_h,
                    left:left + target_w,
                ]
            frames.append(np.ascontiguousarray(frame))
        cap.release()

        if not frames:
            log.warning("Idle video has no frames: %s", p)
            return None
        log.info(
            "Read idle video: %s frames=%d size=%dx%d",
            p.name, len(frames), target_w, target_h,
        )
        return frames

    def _load_wav2lip_reference_idle_frames(self) -> list[np.ndarray] | None:
        frame_dir = self._wav2lip_reference_frame_dir()
        if frame_dir is None:
            return None
        frame_paths = sorted(
            path
            for path in frame_dir.iterdir()
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        )
        max_frames = max(1, _env_int("OPENTALKING_WAV2LIP_IDLE_MAX_FRAMES", 125))
        frame_paths = frame_paths[:max_frames]
        if not frame_paths:
            return None

        from PIL import Image
        from opentalking.media.frame_avatar import resize_reference_image_to_video

        target_w = int(getattr(self.flashtalk, "width", 0) or 0)
        target_h = int(getattr(self.flashtalk, "height", 0) or 0)
        frames: list[np.ndarray] = []
        for path in frame_paths:
            try:
                pil_img = Image.open(path).convert("RGB")
                pil_img = resize_reference_image_to_video(pil_img, width=target_w, height=target_h)
                img = np.asarray(pil_img)
                frames.append(np.ascontiguousarray(img[:, :, ::-1]))
            except Exception:
                log.warning("Skipping unreadable wav2lip idle frame: %s", path, exc_info=True)
                continue
        return frames or None

    def _build_fasterliveportrait_idle_frames(self, reference_frame: np.ndarray) -> list[np.ndarray]:
        return [np.ascontiguousarray(reference_frame)]

    def _set_idle_frames(self, frames: list[np.ndarray]) -> None:
        self._idle_frames = frames
        playback_mode = os.environ.get("FLASHTALK_IDLE_CACHE_PLAYBACK", "pingpong").strip().lower()
        self._idle_playback_indices = _build_idle_playback_indices(len(frames), playback_mode)
        self._idle_frame_idx = 0

    def _make_idle_cache_key(self, ref_image_path: Path) -> str:
        stat = ref_image_path.stat()
        idle_chunks = max(1, _env_int("FLASHTALK_IDLE_CACHE_CHUNKS", 4))
        crossfade_frames = max(2, _env_int("FLASHTALK_IDLE_CACHE_CROSSFADE_FRAMES", 6))
        playback_mode = os.environ.get("FLASHTALK_IDLE_CACHE_PLAYBACK", "pingpong").strip().lower()
        mouth_lock = max(0.0, min(1.0, _env_float("FLASHTALK_IDLE_MOUTH_LOCK", 0.97)))
        mouth_temporal = max(0.0, min(1.0, _env_float("FLASHTALK_IDLE_MOUTH_TEMPORAL", 0.85)))
        return "::".join([
            str(self.avatar_path()),
            str(stat.st_mtime_ns),
            str(stat.st_size),
            str(self.flashtalk.width),
            str(self.flashtalk.height),
            str(self.flashtalk.fps),
            str(self.flashtalk.audio_chunk_samples),
            str(idle_chunks),
            str(crossfade_frames),
            playback_mode,
            f"{mouth_lock:.3f}",
            f"{mouth_temporal:.3f}",
            str(_IDLE_CACHE_VERSION),
        ])

    def _load_idle_frames_from_disk(self, cache_path: Path, cache_key: str) -> list[np.ndarray]:
        if not cache_path.exists():
            return []
        try:
            with np.load(cache_path, allow_pickle=False) as data:
                stored_key = str(data["cache_key"].item())
                if stored_key != cache_key:
                    return []
                frames = np.asarray(data["frames"], dtype=np.uint8)
        except Exception:
            log.exception("Failed to load idle cache: %s", cache_path)
            return []

        if frames.ndim != 4 or frames.shape[0] == 0:
            return []
        loaded = [np.ascontiguousarray(frame) for frame in frames]
        log.info(
            "Loaded avatar idle cache: avatar=%s frames=%d path=%s",
            self.avatar_id,
            len(loaded),
            cache_path,
        )
        return loaded

    def _save_idle_frames_to_disk(
        self,
        cache_path: Path,
        cache_key: str,
        frames: list[np.ndarray],
    ) -> None:
        if not frames:
            return
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            arr = np.stack(frames, axis=0).astype(np.uint8, copy=False)
            np.savez_compressed(cache_path, cache_key=np.array(cache_key), frames=arr)
        except Exception:
            log.exception("Failed to save idle cache: %s", cache_path)

    async def _reset_flashtalk_session(self, ref_image_path: Path) -> None:
        await self.flashtalk.close()
        await self.flashtalk.connect()
        await self._init_flashtalk_session(ref_image_path)

    async def _init_flashtalk_session(self, ref_image_path: Path) -> None:
        video_config = self._fasterliveportrait_video_config(ref_image_path) or self._wav2lip_video_config()
        await self.flashtalk.init_session(
            ref_image=self._fasterliveportrait_ref_image_payload(ref_image_path, video_config),
            wav2lip_postprocess_mode=self._wav2lip_postprocess_mode(),
            mouth_metadata=self._wav2lip_mouth_metadata(),
            video_config=video_config or self._quicktalk_video_config(),
            reference_mode=self._wav2lip_reference_mode(),
            ref_frame_dir=self._wav2lip_reference_frame_dir(),
            ref_frame_metadata_path=self._wav2lip_reference_frame_metadata_path(),
            preprocessed=self._wav2lip_preprocessed(),
            template_mode=self._quicktalk_template_mode(),
            template_video=self._quicktalk_template_video(),
            template_frame_dir=self._quicktalk_template_frame_dir(),
            quicktalk_face_cache=self._quicktalk_face_cache(),
        )

    async def _build_idle_frames(self) -> list[np.ndarray]:
        idle_chunks = max(1, _env_int("FLASHTALK_IDLE_CACHE_CHUNKS", 4))
        idle_level = max(40.0, _env_float("FLASHTALK_IDLE_CACHE_LEVEL", 480.0))
        crossfade_frames = max(2, _env_int("FLASHTALK_IDLE_CACHE_CROSSFADE_FRAMES", 6))
        playback_mode = os.environ.get("FLASHTALK_IDLE_CACHE_PLAYBACK", "pingpong").strip().lower()
        mouth_lock = max(0.0, min(1.0, _env_float("FLASHTALK_IDLE_MOUTH_LOCK", 0.97)))
        mouth_temporal = max(0.0, min(1.0, _env_float("FLASHTALK_IDLE_MOUTH_TEMPORAL", 0.85)))
        temp_client = FlashTalkWSClient(self._flashtalk_ws_url, extra_headers=self._extra_ws_headers)
        try:
            # Close the main session first so the server (single-session
            # architecture) doesn't deadlock on a concurrent HCCL broadcast.
            await self.flashtalk.close()
            await temp_client.connect()
            ref_image_path = self.avatar_path() / "reference.png"
            if not ref_image_path.exists():
                ref_image_path = self.avatar_path() / "reference.jpg"
            video_config = self._fasterliveportrait_video_config(ref_image_path) or self._wav2lip_video_config()
            await temp_client.init_session(
                ref_image=self._fasterliveportrait_ref_image_payload(ref_image_path, video_config),
                wav2lip_postprocess_mode=self._wav2lip_postprocess_mode(),
                mouth_metadata=self._wav2lip_mouth_metadata(),
                video_config=video_config,
            )

            chunk_samples = int(temp_client.audio_chunk_samples)
            if chunk_samples <= 0:
                return []

            total_samples = chunk_samples * idle_chunks
            driver = _build_idle_driver_pcm(
                total_samples=total_samples,
                level=idle_level,
            )

            built: list[np.ndarray] = []
            for chunk_idx in range(idle_chunks):
                start = chunk_idx * chunk_samples
                stop = start + chunk_samples
                pcm_chunk = driver[start:stop]
                frames = await temp_client.generate(pcm_chunk)
                built.extend(np.ascontiguousarray(frame.data) for frame in frames)

            built = _optimize_idle_loop(
                built,
                crossfade_frames=crossfade_frames,
            )
            built = _stabilize_idle_mouth(
                built,
                self._reference_frame,
                strength=mouth_lock,
                temporal_strength=mouth_temporal,
            )

            if built:
                log.info(
                    "Built avatar idle cache: avatar=%s chunks=%d frames=%d level=%.0f crossfade=%d playback=%s mouth_lock=%.2f mouth_temporal=%.2f",
                    self.avatar_id,
                    idle_chunks,
                    len(built),
                    idle_level,
                    crossfade_frames,
                    playback_mode,
                    mouth_lock,
                    mouth_temporal,
                )
            return built
        finally:
            await temp_client.close(send_close_msg=False)

    async def _prepare_idle_cache(self, ref_image_path: Path) -> None:
        avatar_dir = self.avatar_path()
        cache_path = self._idle_cache_path(avatar_dir)
        cache_key = self._make_idle_cache_key(ref_image_path)
        self._idle_cache_key = cache_key

        cached = _IDLE_FRAME_CACHE.get(cache_key)
        if cached:
            self._set_idle_frames(cached)
            return

        lock = _idle_cache_lock(cache_key)
        async with lock:
            cached = _IDLE_FRAME_CACHE.get(cache_key)
            if cached:
                self._set_idle_frames(cached)
                return

            disk_frames = self._load_idle_frames_from_disk(cache_path, cache_key)
            if disk_frames:
                _IDLE_FRAME_CACHE[cache_key] = disk_frames
                self._set_idle_frames(disk_frames)
                return

            built = await self._build_idle_frames()
            if not built:
                return

            _IDLE_FRAME_CACHE[cache_key] = built
            self._set_idle_frames(built)
            self._save_idle_frames_to_disk(cache_path, cache_key, built)

            # The temp client used by _build_idle_frames sends a "close"
            # message which destroys the server-side session (single-session
            # architecture).  Re-init the main client so it can generate.
            await self._reset_flashtalk_session(ref_image_path)

    def _remember_tts_opener(self, opener_id: str) -> None:
        max_history = max(0, int(get_settings().flashtalk_tts_opener_max_history))
        if max_history == 0:
            self._tts_opener_recent_ids.clear()
            return
        self._tts_opener_recent_ids = [
            existing for existing in self._tts_opener_recent_ids if existing != opener_id
        ]
        self._tts_opener_recent_ids.append(opener_id)
        if len(self._tts_opener_recent_ids) > max_history:
            self._tts_opener_recent_ids = self._tts_opener_recent_ids[-max_history:]

    @staticmethod
    def _legacy_bool_setting_declared(*names: str) -> bool:
        if any(name in os.environ for name in names):
            return True
        try:
            from dotenv import dotenv_values

            values = dotenv_values(".env")
        except Exception:
            return False
        return any(values.get(name) not in (None, "") for name in names)

    def _tts_opener_enabled_for_model(self) -> bool:
        settings = get_settings()
        if self._legacy_bool_setting_declared(
            "FLASHTALK_TTS_OPENER_ENABLE",
            "OPENTALKING_FLASHTALK_TTS_OPENER_ENABLE",
        ):
            return bool(settings.flashtalk_tts_opener_enable)
        if settings.flashtalk_tts_opener_enable:
            return True
        return self.model_type == "fasterliveportrait"

    def _tts_opener_preload_enabled_for_model(self) -> bool:
        settings = get_settings()
        if self._legacy_bool_setting_declared(
            "FLASHTALK_TTS_OPENER_PRELOAD",
            "OPENTALKING_FLASHTALK_TTS_OPENER_PRELOAD",
        ):
            return bool(settings.flashtalk_tts_opener_preload)
        if settings.flashtalk_tts_opener_preload:
            return True
        return self.model_type == "fasterliveportrait"

    def _tts_opener_preload_voice(self) -> str | None:
        return get_settings().tts_voice or None

    async def _select_tts_opener(
        self,
        user_text: str,
        *,
        sample_rate: int,
        chunk_samples: int,
        default_voice: str | None = None,
    ) -> tuple[str, str, np.ndarray, bool, bool] | None:
        s = get_settings()
        if not self._tts_opener_enabled_for_model():
            return None

        min_fill_ratio = min(
            max(float(s.flashtalk_tts_opener_min_fill_ratio), 0.0),
            1.0,
        )
        pad_to_chunk = bool(s.flashtalk_tts_opener_pad_to_chunk)
        ordered_candidates = _build_tts_opener_candidates(user_text)
        if not ordered_candidates:
            return None

        recent_ids = set(self._tts_opener_recent_ids)
        ordered_candidates = [
            *[item for item in ordered_candidates if item[0] not in recent_ids],
            *[item for item in ordered_candidates if item[0] in recent_ids],
        ]

        best_candidate: tuple[str, str, np.ndarray, bool] | None = None
        for opener_id, opener_text in ordered_candidates:
            try:
                pcm, cache_hit = await _synthesize_tts_opener_pcm(
                    opener_text,
                    sample_rate=sample_rate,
                    default_voice=default_voice,
                )
            except Exception:
                log.warning("Failed to synthesize TTS opener %r", opener_text, exc_info=True)
                continue

            if best_candidate is None or pcm.size > best_candidate[2].size:
                best_candidate = (opener_id, opener_text, pcm, cache_hit)

            if chunk_samples <= 0:
                chosen_pcm = pcm
                self._remember_tts_opener(opener_id)
                return opener_id, opener_text, chosen_pcm, cache_hit, False

            if (pcm.size / chunk_samples) >= min_fill_ratio:
                chosen_pcm = pcm
                padded = False
                if pad_to_chunk and chosen_pcm.size < chunk_samples:
                    chosen_pcm = np.concatenate(
                        [
                            chosen_pcm,
                            np.zeros(chunk_samples - chosen_pcm.size, dtype=np.int16),
                        ]
                    )
                    padded = True
                self._remember_tts_opener(opener_id)
                return opener_id, opener_text, chosen_pcm, cache_hit, padded

        if best_candidate is None:
            return None

        opener_id, opener_text, pcm, cache_hit = best_candidate
        chosen_pcm = pcm
        padded = False
        if pad_to_chunk and chunk_samples > 0 and chosen_pcm.size < chunk_samples:
            chosen_pcm = np.concatenate(
                [
                    chosen_pcm,
                    np.zeros(chunk_samples - chosen_pcm.size, dtype=np.int16),
                ]
            )
            padded = True
        self._remember_tts_opener(opener_id)
        return opener_id, opener_text, chosen_pcm, cache_hit, padded

    async def handle_webrtc_offer(self, sdp: str, type_: str) -> dict[str, str]:
        # Wait for prepare() to finish (may take ~25s for FlashTalk init)
        await asyncio.wait_for(self.ready_event.wait(), timeout=60)
        assert self.webrtc is not None
        ans = await self.webrtc.handle_offer(sdp, type_)
        self._webrtc_started.set()
        await self._queue_initial_video_frame()
        return {"sdp": ans.sdp, "type": ans.type}

    async def _queue_initial_video_frame(self) -> None:
        """Send one still frame immediately after WebRTC starts.

        The regular idle loop also replays the latest/reference frame, but
        queueing the first frame here makes the browser paint the avatar as
        soon as the peer connection is established, before the user speaks.
        """
        if not self.webrtc or self.webrtc.draining:
            return
        idle_frame = self._last_frame if self._last_frame is not None else self._reference_frame
        if idle_frame is None:
            return
        from opentalking.core.types.frames import VideoFrameData

        self._ensure_media_clock_started()
        frame = VideoFrameData(
            data=idle_frame,
            width=idle_frame.shape[1],
            height=idle_frame.shape[0],
            timestamp_ms=0.0,
        )
        await self._video_put_safe(frame)
        log.info("Initial WebRTC video frame queued: session=%s", self.session_id)

    async def _queue_fasterliveportrait_rest_frame(self) -> None:
        """Return FLP playback to the neutral reference frame after speech.

        FasterLivePortrait does not run the generic idle loop, so without this
        the browser holds the final generated frame. If the last phoneme is a
        rounded vowel, that leaves the avatar stuck with puckered lips.
        """
        if self.model_type != "fasterliveportrait" or not self.webrtc:
            return
        if self.webrtc.draining or self._reference_frame is None:
            return
        from opentalking.core.types.frames import VideoFrameData

        rest = np.ascontiguousarray(self._reference_frame.copy())
        self._last_frame = rest.copy()
        frame = VideoFrameData(
            data=rest,
            width=rest.shape[1],
            height=rest.shape[0],
            timestamp_ms=self._av_ts_ms,
        )
        await self._video_put_safe(frame)
        log.info("FasterLivePortrait rest frame queued: session=%s", self.session_id)

    def _ensure_media_clock_started(self) -> None:
        if self.webrtc is None or self._media_clock_started:
            return
        self.webrtc.reset_clocks()
        self._media_clock_started = True

    def _prebuffer_chunks(
        self,
        *,
        speech_text: str | None = None,
        pcm_samples: int | None = None,
    ) -> int:
        """Choose a startup prebuffer that balances first response vs smoothness.

        Explicit env override still wins. Otherwise:
        - FlashTalk keeps the configured default.
        - FlashHead uses a lightweight heuristic:
          short text / short uploaded audio -> 1 chunk
          medium length                    -> 2 chunks
          long-form output                 -> 3 chunks
        """
        raw = os.environ.get("FLASHTALK_PREBUFFER_CHUNKS")
        if raw and raw.strip():
            return max(1, _env_int("FLASHTALK_PREBUFFER_CHUNKS", 1))
        if self.model_type == "flashhead":
            if pcm_samples is not None:
                chunk_samples = max(1, int(getattr(self.flashtalk, "audio_chunk_samples", 17920) or 17920))
                if pcm_samples <= chunk_samples * 2:
                    return 1
                if pcm_samples <= chunk_samples * 6:
                    return 2
                return 3

            chars = _speech_char_count(speech_text or "")
            if chars <= 12:
                return 1
            if chars <= 48:
                return 2
            return 3
        return max(1, int(getattr(get_settings(), "flashtalk_prebuffer_chunks", 1)))

    def _playback_backpressure_config(self) -> tuple[int, int, float]:
        if self.model_type != "fasterliveportrait":
            return (0, 0, 0.0)
        target = max(0, _env_int("FLP_PLAYBACK_TARGET_QUEUE_FRAMES", 8))
        max_frames = max(target, _env_int("FLP_PLAYBACK_MAX_QUEUE_FRAMES", 24))
        max_wait_ms = max(0.0, _env_float("FLP_PLAYBACK_MAX_WAIT_MS", 900.0))
        return (target, max_frames, max_wait_ms)

    async def _wait_for_playback_capacity(
        self,
        *,
        n_frames: int,
        first_media_this_speak: bool,
    ) -> float:
        """Keep FLP near real-time without dropping or inventing frames."""
        if (
            first_media_this_speak
            or n_frames <= 0
            or not self.webrtc
            or self.webrtc.draining
            or not self._speech_media_active
            or not self._webrtc_started.is_set()
        ):
            return 0.0

        target, max_frames, max_wait_ms = self._playback_backpressure_config()
        if max_frames <= 0 or max_wait_ms <= 0:
            return 0.0

        vq = self.webrtc.video._queue.qsize()
        if vq + n_frames <= max_frames:
            return 0.0

        deadline = time.perf_counter() + (max_wait_ms / 1000.0)
        waited_ms = 0.0
        while self.webrtc and not self._interrupt.is_set():
            vq = self.webrtc.video._queue.qsize()
            if vq <= target or time.perf_counter() >= deadline:
                break
            await asyncio.sleep(0.02)
            waited_ms += 20.0
        return waited_ms

    def create_speak_task(
        self,
        text: str,
        tts_voice: str | None = None,
        *,
        tts_provider: str | None = None,
        tts_model: str | None = None,
        enqueue_unix: float | None = None,
    ) -> asyncio.Task[None]:
        task = asyncio.create_task(
            self._run_speak_task(text, tts_voice, tts_provider, tts_model, enqueue_unix)
        )
        self.speech_tasks.add(task)
        task.add_done_callback(self.speech_tasks.discard)
        return task

    def create_speak_uploaded_pcm_task(
        self,
        pcm_path: str,
        *,
        enqueue_unix: float | None = None,
    ) -> asyncio.Task[None]:
        task = asyncio.create_task(
            self._run_speak_uploaded_pcm_task(pcm_path, enqueue_unix)
        )
        self.speech_tasks.add(task)
        task.add_done_callback(self.speech_tasks.discard)
        return task

    async def _run_speak_uploaded_pcm_task(
        self,
        pcm_path: str,
        enqueue_unix: float | None = None,
    ) -> None:
        path = Path(pcm_path)
        pcm: np.ndarray | None = None
        try:
            raw = path.read_bytes()
            if not raw:
                raise RuntimeError("empty pcm upload")
            pcm = np.frombuffer(raw, dtype=np.int16).copy()
        except Exception as e:  # noqa: BLE001
            log.exception("read uploaded pcm failed: session=%s path=%s", self.session_id, pcm_path)
            if not self._closed:
                await set_session_state(self.redis, self.session_id, "error")
                await publish_event(
                    self.redis,
                    self.session_id,
                    "error",
                    {"session_id": self.session_id, "code": "UPLOAD_PCM_READ_FAILED", "message": str(e)},
                )
            return
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

        assert pcm is not None
        log.info("speak_uploaded_pcm start: session=%s samples=%d", self.session_id, pcm.size)
        try:
            await self.speak_uploaded_pcm(pcm, enqueue_unix=enqueue_unix)
            log.info("speak_uploaded_pcm done: session=%s", self.session_id)
        except asyncio.CancelledError:
            log.info("speak_uploaded_pcm cancelled: session=%s", self.session_id)
        except Exception:  # noqa: BLE001
            log.exception("speak_uploaded_pcm failed: session=%s", self.session_id)
            if not self._closed:
                await set_session_state(self.redis, self.session_id, "error")

    async def _run_speak_task(
        self,
        text: str,
        tts_voice: str | None = None,
        tts_provider: str | None = None,
        tts_model: str | None = None,
        enqueue_unix: float | None = None,
    ) -> None:
        log.info("speak start: %s (session=%s)", text[:30], self.session_id)
        try:
            await self.speak(
                text,
                tts_voice=tts_voice,
                tts_provider=tts_provider,
                tts_model=tts_model,
                enqueue_unix=enqueue_unix,
            )
            log.info("speak done: session=%s", self.session_id)
        except asyncio.CancelledError:
            log.info("speak cancelled: session=%s", self.session_id)
        except Exception:  # noqa: BLE001
            log.exception("speak failed: session=%s", self.session_id)
            if not self._closed:
                await set_session_state(self.redis, self.session_id, "error")

    async def _publish_speech_ended(self, reply_text: str | None = None) -> None:
        if not self._speech_started:
            return
        self._speech_started = False
        payload: dict[str, str] = {"session_id": self.session_id}
        if reply_text is not None:
            payload["text"] = reply_text
        await publish_event(
            self.redis,
            self.session_id,
            "speech.ended",
            payload,
        )

    async def speak(
        self,
        text: str,
        tts_voice: str | None = None,
        *,
        tts_provider: str | None = None,
        tts_model: str | None = None,
        enqueue_unix: float | None = None,
    ) -> None:
        """Full pipeline: user text → LLM → TTS → FlashTalk → WebRTC.

        Uses a producer-consumer pattern:
          Producer: LLM stream → sentence split → TTS → audio chunks into queue
          Consumer: dequeue audio chunks → FlashTalk generate → WebRTC frames
        This eliminates inter-sentence gaps.
        """
        async with self._speak_lock:
            if self._closed:
                return
            await self._await_dynamic_idle_prepare_done()
            self._interrupt.clear()
            self._speaking = True
            if self.webrtc:
                # Stop idle loop first, then drain queues atomically.
                self._speech_media_active = True
                self.webrtc.draining = True
                self.webrtc.clear_media_queues()
                self.webrtc.reset_clocks()
                self.webrtc.draining = False
                self._media_clock_started = False
                self._av_ts_ms = 0.0
                self._speech_media_active = False  # consumer will re-set after prebuffer

            await set_session_state(self.redis, self.session_id, "speaking")
            await publish_event(
                self.redis, self.session_id,
                "speech.started",
                {"session_id": self.session_id, "text": text},
            )
            self._speech_started = True

            self.conversation.add_user(text)

            full_response = ""
            spoken_prefix = ""
            chunk_samples = self.flashtalk.audio_chunk_samples  # 17920
            # Queue: (pcm_chunk, subtitle_for_playback) | None. Subtitle is emitted in the
            # consumer immediately before the matching A/V is queued to WebRTC so UI tracks
            # lip sync better than publishing at TTS start.
            audio_q: asyncio.Queue[tuple[np.ndarray, str | None] | None] = asyncio.Queue(maxsize=8)
            opener_chunk_count: list[int] = [0]
            sample_rate = 16000
            prebuffer_chunks = self._prebuffer_chunks(speech_text=text)
            log.info(
                "FlashHead prebuffer: session=%s chars=%d chunks=%d",
                self.session_id,
                _speech_char_count(text),
                prebuffer_chunks,
            )
            boundary_fade_ms = _env_float("FLASHTALK_TTS_BOUNDARY_FADE_MS", 18.0)
            tail_fade_ms = _env_float("FLASHTALK_TTS_TAIL_FADE_MS", 80.0)
            trailing_silence_ms = _env_float("FLASHTALK_TTS_TRAILING_SILENCE_MS", 320.0)
            coalesce_max_chars = max(1, _env_int("FLASHTALK_TTS_COALESCE_MAX_CHARS", 80))
            coalesce_min_chars = min(
                max(0, _env_int("FLASHTALK_TTS_COALESCE_MIN_CHARS", 6)),
                coalesce_max_chars,
            )

            # 本轮 speak 各阶段耗时（毫秒），供日志一行汇总；dict 在 speak 闭包内共享
            t_speak_wall0 = time.perf_counter()
            timing: dict[str, float] = {}
            self._speak_enqueue_unix = enqueue_unix
            if enqueue_unix is not None:
                timing["api_enqueue_to_speak_enter_wall_ms"] = (
                    time.time() - enqueue_unix
                ) * 1000.0
            # 供 _queue_av_chunk 记录首帧进 WebRTC 队列的墙钟（相对本轮 speak 起点）
            self._speak_t0_wall = t_speak_wall0
            self._speak_milestones = timing

            async def _producer():
                """LLM → sentence split → TTS → fixed-size audio chunks into queue.

                Uses a two-stage pipeline to overlap TTS startup with audio
                streaming:
                  Stage 1 (LLM feeder): LLM deltas → sentence split → sentence_q
                  Stage 2 (TTS worker): sentence_q → TTS adapter → audio chunks → audio_q
                This eliminates the ~300-800ms TTS startup gap between sentences.
                """
                nonlocal full_response
                t_producer_wall0 = time.perf_counter()
                audio_buffer = np.zeros(0, dtype=np.int16)
                text_buffer = ""
                splitter = SentenceSplitter()
                tts = create_tts_adapter(
                    sample_rate=sample_rate,
                    chunk_ms=400.0,
                    default_voice=tts_voice,
                    tts_provider=tts_provider,
                    tts_model=tts_model,
                )
                log.info(
                    "TTS pipeline start | %s",
                    tts_log_profile(
                        request_voice=tts_voice,
                        tts_provider_override=tts_provider,
                        tts_model_override=tts_model,
                    ),
                )
                # Sentence queue: decouples LLM stream from TTS so next sentence
                # can be queued while current sentence is still being synthesised.
                sentence_q: asyncio.Queue[str | None] = asyncio.Queue(maxsize=4)
                trim_lead_after_opener = {"applied": False}

                async def _append_pcm(pcm: np.ndarray, *, subtitle: str | None = None) -> int:
                    nonlocal audio_buffer
                    if pcm.size == 0:
                        return 0

                    audio_buffer = np.concatenate([audio_buffer, pcm.astype(np.int16)])
                    chunks = 0
                    first = True
                    while len(audio_buffer) >= chunk_samples:
                        chunk = audio_buffer[:chunk_samples]
                        audio_buffer = audio_buffer[chunk_samples:]
                        tag = subtitle if first else None
                        first = False
                        await audio_q.put((chunk, tag))
                        if "first_chunk_queued_ms" not in timing:
                            timing["first_chunk_queued_ms"] = (
                                time.perf_counter() - t_speak_wall0
                            ) * 1000.0
                        chunks += 1
                    return chunks

                async def _emit_cached_opener() -> None:
                    nonlocal spoken_prefix
                    opener = await self._select_tts_opener(
                        text,
                        sample_rate=sample_rate,
                        chunk_samples=chunk_samples,
                        default_voice=tts_voice,
                    )
                    if opener is None or self._interrupt.is_set():
                        return

                    opener_id, opener_text, opener_pcm, cache_hit, padded = opener
                    spoken_prefix = opener_text
                    # Trim trailing silence from TTS output, then fade head.
                    opener_pcm_trimmed = _trim_trailing_silence_i16(
                        opener_pcm, sample_rate
                    )
                    opener_pcm_faded = _fade_head_i16(
                        opener_pcm_trimmed, sample_rate, boundary_fade_ms
                    )
                    # Pad to whole chunk so no audio is truncated (e.g. last syllable).
                    remainder = opener_pcm_faded.size % chunk_samples
                    if remainder > 0:
                        opener_pcm_faded = np.concatenate([
                            opener_pcm_faded,
                            np.zeros(chunk_samples - remainder, dtype=np.int16),
                        ])
                    produced = await _append_pcm(
                        opener_pcm_faded,
                        subtitle=opener_text,
                    )
                    opener_chunk_count[0] = produced
                    log.info(
                        "TTS opener: id=%s cache_hit=%s padded=%s samples=%d produced=%d text=%r",
                        opener_id,
                        cache_hit,
                        padded,
                        opener_pcm.size,
                        produced,
                        opener_text,
                    )

                async def _tts_sentence(sentence: str):
                    nonlocal audio_buffer
                    import time as _t
                    tts_text = sanitize_tts_text(sentence)
                    if not tts_text:
                        log.info("Skipping empty TTS text after sanitize: %r", sentence[:40])
                        return

                    if spoken_prefix.strip() and not trim_lead_after_opener["applied"]:
                        trim_lead_after_opener["applied"] = True
                        stripped = _strip_redundant_greeting_lead(tts_text)
                        if stripped != tts_text:
                            log.info(
                                "TTS lead trim (opener active): %r -> %r",
                                tts_text[:80],
                                stripped[:80],
                            )
                        tts_text = stripped
                        if not tts_text:
                            log.info("Skipping first LLM sentence after opener lead trim (empty)")
                            return

                    log.info(
                        "TTS input: sentence=%r -> tts_text=%r",
                        sentence[:30],
                        tts_text[:30] if tts_text else "",
                    )
                    t0 = _t.monotonic()
                    chunks_produced = 0
                    first_pcm_ms: float | None = None
                    seen_audio = False
                    held_tail = np.zeros(0, dtype=np.int16)
                    hold_samples = int(sample_rate * max(0.0, boundary_fade_ms) / 1000.0)
                    pending_subtitle: str | None = tts_text
                    async for tts_chunk in tts.synthesize_stream(tts_text):
                        if self._interrupt.is_set():
                            return
                        pcm = np.asarray(tts_chunk.data, dtype=np.int16)
                        if pcm.size == 0:
                            continue

                        if not seen_audio:
                            seen_audio = True
                            first_pcm_ms = (_t.monotonic() - t0) * 1000.0
                            pcm = _fade_head_i16(pcm, sample_rate, boundary_fade_ms)

                        if hold_samples > 1:
                            combined = np.concatenate([held_tail, pcm]) if held_tail.size else pcm
                            if combined.size <= hold_samples:
                                held_tail = combined
                                continue
                            emit = combined[:-hold_samples]
                            held_tail = combined[-hold_samples:]
                            n = await _append_pcm(emit, subtitle=pending_subtitle)
                            chunks_produced += n
                            if n > 0 and pending_subtitle is not None:
                                pending_subtitle = None
                        else:
                            n = await _append_pcm(pcm, subtitle=pending_subtitle)
                            chunks_produced += n
                            if n > 0 and pending_subtitle is not None:
                                pending_subtitle = None

                    if not seen_audio:
                        return

                    if held_tail.size > 0 and not self._interrupt.is_set():
                        held_tail = _fade_tail_i16(held_tail, sample_rate, boundary_fade_ms)
                        n = await _append_pcm(held_tail, subtitle=pending_subtitle)
                        chunks_produced += n
                        if n > 0 and pending_subtitle is not None:
                            pending_subtitle = None

                    t1 = _t.monotonic()
                    log.info(
                        "TTS sentence done | %s | text_preview=%r | "
                        "first_pcm=%.0fms total=%.2fs chunks=%d buf=%d",
                        tts_log_profile(
                            request_voice=tts_voice,
                            tts_provider_override=tts_provider,
                            tts_model_override=tts_model,
                        ),
                        sentence[:48],
                        first_pcm_ms if first_pcm_ms is not None else -1.0,
                        t1 - t0,
                        chunks_produced,
                        len(audio_buffer),
                    )

                async def _queue_sentence_for_tts(sentence: str, *, force: bool = False):
                    nonlocal text_buffer
                    if not sentence and not force:
                        return

                    if sentence:
                        text_buffer = _join_tts_fragments(text_buffer, sentence)
                    char_count = _speech_char_count(text_buffer)
                    if not text_buffer:
                        return

                    should_hold = (
                        not force
                        and char_count < coalesce_min_chars
                        and char_count < coalesce_max_chars
                    )
                    if should_hold:
                        log.info(
                            "TTS coalesce: holding short text (%d/%d chars): %r",
                            char_count, coalesce_min_chars, text_buffer[:40],
                        )
                        return

                    text = text_buffer
                    text_buffer = ""
                    await sentence_q.put(text)

                async def _tts_worker():
                    """Drain sentence_q and run TTS for each sentence."""
                    t_tts0 = time.perf_counter()
                    try:
                        while True:
                            sentence = await sentence_q.get()
                            if sentence is None or self._interrupt.is_set():
                                break
                            await _tts_sentence(sentence)
                    finally:
                        timing["tts_worker_wall_ms"] = (time.perf_counter() - t_tts0) * 1000.0

                def _llm_request_messages() -> list[dict[str, str]]:
                    """Messages for this completion only (not persisted).

                    When a TTS opener was already spoken: extend system with an explicit
                    anti-repetition hint, then append the opener as a synthetic assistant
                    turn so the model continues instead of echoing the same greeting.
                    """
                    base = list(self.conversation.get_messages())
                    prefix = spoken_prefix.strip()
                    if not prefix:
                        return base
                    if base and base[0].get("role") == "system":
                        sys = base[0]["content"]
                        nudge = (
                            f"\n\n【本轮】你已通过语音对用户说过：「{prefix}」。"
                            "请在此之后**只**输出对用户有用的正文；"
                            "禁止再用「你好」「您好」「哈喽」「嗨」或与之同义的寒暄起头，也不要复述上述垫话。"
                        )
                        base[0] = {"role": "system", "content": sys + nudge}
                    base.append({"role": "assistant", "content": prefix})
                    log.info(
                        "LLM request: opener_hint msgs=%d prefix_chars=%d",
                        len(base),
                        len(prefix),
                    )
                    return base

                async def _llm_feeder():
                    """Stream LLM deltas, split into sentences, push to sentence_q."""
                    nonlocal full_response, text_buffer
                    t_llm0 = time.perf_counter()
                    t_first_token: float | None = None
                    try:
                        log.info("LLM streaming started for: %s", text[:50])
                        async for delta in self.llm.chat_stream(_llm_request_messages()):
                            if self._interrupt.is_set():
                                break
                            piece = strip_emoji(delta)
                            if t_first_token is None and piece.strip():
                                t_first_token = time.perf_counter()
                            full_response += piece
                            for sentence in splitter.feed(delta):
                                if self._interrupt.is_set():
                                    break
                                await _queue_sentence_for_tts(sentence)

                        if not self._interrupt.is_set():
                            remainder = splitter.flush()
                            log.info(
                                "Splitter flush: remainder=%r",
                                remainder[:50] if remainder else None,
                            )
                            if remainder:
                                await _queue_sentence_for_tts(remainder, force=True)
                            elif text_buffer:
                                await _queue_sentence_for_tts("", force=True)

                        if spoken_prefix.strip() and full_response.strip():
                            agg = full_response.strip()
                            trimmed = _strip_redundant_greeting_lead(agg)
                            if trimmed != agg:
                                log.info(
                                    "LLM aggregate lead trim: %r -> %r",
                                    agg[:100],
                                    trimmed[:100],
                                )
                                full_response = trimmed

                        log.info("LLM feeder done, full_response=%r", full_response[:100])
                    except Exception:
                        log.exception("LLM feeder failed")
                        if not self._interrupt.is_set() and not full_response:
                            fallback_text = "抱歉，我暂时无法连接语言服务。请稍后再试。"
                            full_response = fallback_text
                            text_buffer = ""
                            await _queue_sentence_for_tts(fallback_text, force=True)
                    finally:
                        t_llm1 = time.perf_counter()
                        timing["llm_stream_ms"] = (t_llm1 - t_llm0) * 1000.0
                        if t_first_token is not None:
                            timing["llm_first_token_ms"] = (t_first_token - t_llm0) * 1000.0
                        await sentence_q.put(None)  # signal TTS worker to stop

                try:
                    t_opener0 = time.perf_counter()
                    await _emit_cached_opener()
                    timing["opener_ms"] = (time.perf_counter() - t_opener0) * 1000.0
                    # Run LLM feeder and TTS worker concurrently within
                    # the producer; the TTS worker processes sentences as
                    # fast as Edge TTS can generate audio while the LLM
                    # feeder keeps streaming deltas into sentence_q.
                    t_gather0 = time.perf_counter()
                    await asyncio.gather(_llm_feeder(), _tts_worker())
                    timing["llm_tts_gather_ms"] = (time.perf_counter() - t_gather0) * 1000.0

                    # Flush leftover audio with a short silence tail so the mouth can settle.
                    log.info("Audio buffer leftover: %d samples", len(audio_buffer))
                    if not self._interrupt.is_set():
                        silence_samples = int(sample_rate * max(0.0, trailing_silence_ms) / 1000.0)
                        if len(audio_buffer) > 0:
                            audio_buffer = _fade_tail_i16(audio_buffer, sample_rate, tail_fade_ms)
                        if silence_samples > 0:
                            audio_buffer = np.concatenate([
                                audio_buffer,
                                np.zeros(silence_samples, dtype=np.int16),
                            ])
                        if len(audio_buffer) > 0:
                            pad_len = (-len(audio_buffer)) % chunk_samples
                            if pad_len:
                                audio_buffer = np.concatenate([
                                    audio_buffer,
                                    np.zeros(pad_len, dtype=np.int16),
                                ])
                            while len(audio_buffer) >= chunk_samples:
                                chunk = audio_buffer[:chunk_samples]
                                audio_buffer = audio_buffer[chunk_samples:]
                                await audio_q.put((chunk, None))
                                if "first_chunk_queued_ms" not in timing:
                                    timing["first_chunk_queued_ms"] = (
                                        time.perf_counter() - t_speak_wall0
                                    ) * 1000.0

                    timing["producer_wall_ms"] = (time.perf_counter() - t_producer_wall0) * 1000.0
                    log.info("Producer done, full_response=%r", full_response[:100])
                except Exception:
                    log.exception("Producer failed")
                finally:
                    if hasattr(tts, "aclose"):
                        try:
                            await tts.aclose()
                        except Exception:
                            log.exception("TTS adapter aclose failed")
                    await audio_q.put(None)  # signal done

            async def _consumer():
                """Dequeue audio chunks → FlashTalk generate → WebRTC.

                Pre-buffers chunks before starting the pacing clock so WebRTC
                does not consume the first frames/audio without timing.
                """
                t_consumer0 = time.perf_counter()
                flashtalk_gen_sum_s = 0.0
                flashtalk_chunks = 0
                generated = 0
                pending: list[tuple[np.ndarray, list[Any], str | None]] = []
                n_opener = opener_chunk_count[0]
                pacing_started = False

                async def _publish_subtitle_chunk(text: str) -> None:
                    await publish_event(
                        self.redis, self.session_id, "subtitle.chunk",
                        {"session_id": self.session_id, "text": text, "is_final": False},
                    )

                def _start_pacing() -> None:
                    nonlocal pacing_started
                    if pacing_started:
                        return
                    pacing_started = True
                    self._speech_media_active = True
                    if self.webrtc:
                        self.webrtc.draining = True
                        self.webrtc.clear_media_queues()
                        self.webrtc.reset_clocks()
                    self._av_ts_ms = 0.0
                    self._media_clock_started = True

                while True:
                    item = await audio_q.get()
                    if item is None:
                        break
                    pcm_chunk, sub_tag = item
                    if self._interrupt.is_set():
                        break
                    await self._wait_media_backpressure()
                    g0 = time.perf_counter()
                    frames = await self._generate_flashtalk_frames(pcm_chunk)
                    flashtalk_gen_sum_s += time.perf_counter() - g0
                    if "first_flashtalk_return_ms" not in timing:
                        timing["first_flashtalk_return_ms"] = (
                            time.perf_counter() - t_speak_wall0
                        ) * 1000.0
                    flashtalk_chunks += 1
                    generated += 1

                    if generated <= n_opener:
                        # Opener chunk: start pacing immediately.
                        _start_pacing()
                        if sub_tag:
                            await _publish_subtitle_chunk(sub_tag)
                        await self._queue_av_chunk(pcm_chunk, frames)
                        continue

                    # TTS chunks: if pacing already started (opener present),
                    # send straight through.
                    if pacing_started:
                        if sub_tag:
                            await _publish_subtitle_chunk(sub_tag)
                        await self._queue_av_chunk(pcm_chunk, frames)
                        continue

                    # No opener — original prebuffer path.
                    pending.append((pcm_chunk, frames, sub_tag))
                    if generated < prebuffer_chunks:
                        continue

                    log.info(
                        "Pre-buffer done (%d chunks, %.2fs audio), starting pacing",
                        generated,
                        (generated * chunk_samples) / sample_rate,
                    )
                    _start_pacing()
                    for pc, bf, st in pending:
                        if st:
                            await _publish_subtitle_chunk(st)
                        await self._queue_av_chunk(pc, bf)
                    pending.clear()

                if pending and not self._interrupt.is_set():
                    log.info(
                        "Flushing short pre-buffer (%d chunks, %.2fs audio), starting pacing",
                        len(pending),
                        (len(pending) * chunk_samples) / sample_rate,
                    )
                    _start_pacing()
                    for pc, buffered_frames, st in pending:
                        if st:
                            await _publish_subtitle_chunk(st)
                        await self._queue_av_chunk(pc, buffered_frames)

                timing["flashtalk_generate_sum_ms"] = flashtalk_gen_sum_s * 1000.0
                timing["flashtalk_chunks"] = float(flashtalk_chunks)
                timing["consumer_wall_ms"] = (time.perf_counter() - t_consumer0) * 1000.0
                log.info("Consumer done")

            try:
                # Run producer and consumer concurrently
                t_parallel0 = time.perf_counter()
                await asyncio.gather(_producer(), _consumer())
                timing["parallel_total_ms"] = (time.perf_counter() - t_parallel0) * 1000.0
                await self._queue_fasterliveportrait_rest_frame()
            except Exception as e:
                log.exception("FlashTalk speak failed: session=%s", self.session_id)
                await publish_event(
                    self.redis, self.session_id,
                    "error",
                    {"session_id": self.session_id, "code": "SPEAK_FAILED", "message": str(e)},
                )
                raise
            finally:
                self._speaking = False
                self._speech_media_active = False
                self._speak_t0_wall = None
                self._speak_milestones = None
                self._speak_enqueue_unix = None

            timing["speak_wall_ms"] = (time.perf_counter() - t_speak_wall0) * 1000.0
            _tc = len((full_response or "").strip())
            log.info(
                "Speak pipeline timing: session=%s speak_wall_ms=%.0f parallel_total_ms=%.0f "
                "llm_first_token_ms=%s llm_stream_ms=%.0f tts_worker_wall_ms=%.0f opener_ms=%.0f "
                "llm_tts_gather_ms=%.0f producer_wall_ms=%.0f "
                "flashtalk_generate_sum_ms=%.0f flashtalk_chunks=%d consumer_wall_ms=%.0f "
                "first_chunk_queued_ms=%s first_flashtalk_return_ms=%s first_webrtc_queue_ms=%s "
                "api_enqueue_to_speak_enter_wall_ms=%s first_frame_from_api_wall_ms=%s "
                "response_chars=%d",
                self.session_id,
                timing.get("speak_wall_ms", -1.0),
                timing.get("parallel_total_ms", -1.0),
                (
                    "%.0f" % timing["llm_first_token_ms"]
                    if "llm_first_token_ms" in timing
                    else "n/a"
                ),
                timing.get("llm_stream_ms", -1.0),
                timing.get("tts_worker_wall_ms", -1.0),
                timing.get("opener_ms", -1.0),
                timing.get("llm_tts_gather_ms", -1.0),
                timing.get("producer_wall_ms", -1.0),
                timing.get("flashtalk_generate_sum_ms", -1.0),
                int(timing.get("flashtalk_chunks", 0.0)),
                timing.get("consumer_wall_ms", -1.0),
                (
                    "%.0f" % timing["first_chunk_queued_ms"]
                    if "first_chunk_queued_ms" in timing
                    else "n/a"
                ),
                (
                    "%.0f" % timing["first_flashtalk_return_ms"]
                    if "first_flashtalk_return_ms" in timing
                    else "n/a"
                ),
                (
                    "%.0f" % timing["first_webrtc_queue_ms"]
                    if "first_webrtc_queue_ms" in timing
                    else "n/a"
                ),
                (
                    "%.0f" % timing["api_enqueue_to_speak_enter_wall_ms"]
                    if "api_enqueue_to_speak_enter_wall_ms" in timing
                    else "n/a"
                ),
                (
                    "%.0f" % timing["first_frame_from_api_wall_ms"]
                    if "first_frame_from_api_wall_ms" in timing
                    else "n/a"
                ),
                _tc,
            )

            stored_response = _merge_spoken_reply(spoken_prefix, full_response)
            if stored_response:
                self.conversation.add_assistant(stored_response)

            await self._publish_speech_ended(stored_response)
            if not self._closed:
                await set_session_state(self.redis, self.session_id, "ready")

    async def speak_uploaded_pcm(
        self,
        pcm: np.ndarray,
        *,
        enqueue_unix: float | None = None,
    ) -> None:
        """仅 FlashTalk：将用户上传解码后的 16 kHz mono int16 PCM 直接对口型，不经 LLM/TTS。"""
        async with self._speak_lock:
            if self._closed:
                return
            await self._await_dynamic_idle_prepare_done()
            self._interrupt.clear()
            self._speaking = True
            if self.webrtc:
                self._speech_media_active = True
                self.webrtc.draining = True
                self.webrtc.clear_media_queues()
                self.webrtc.reset_clocks()
                self.webrtc.draining = False
                self._media_clock_started = False
                self._av_ts_ms = 0.0
                self._speech_media_active = False

            await set_session_state(self.redis, self.session_id, "speaking")
            await publish_event(
                self.redis,
                self.session_id,
                "speech.started",
                {"session_id": self.session_id, "text": "[上传音频]"},
            )
            self._speech_started = True

            chunk_samples = self.flashtalk.audio_chunk_samples
            audio_q: asyncio.Queue[tuple[np.ndarray, str | None] | None] = asyncio.Queue(maxsize=8)
            n_opener_chunks = 0
            sample_rate = 16000
            prebuffer_chunks = self._prebuffer_chunks(pcm_samples=int(pcm.size))
            log.info(
                "FlashHead prebuffer(upload): session=%s samples=%d chunks=%d",
                self.session_id,
                int(pcm.size),
                prebuffer_chunks,
            )
            boundary_fade_ms = _env_float("FLASHTALK_TTS_BOUNDARY_FADE_MS", 18.0)
            tail_fade_ms = _env_float("FLASHTALK_TTS_TAIL_FADE_MS", 80.0)
            trailing_silence_ms = _env_float("FLASHTALK_TTS_TRAILING_SILENCE_MS", 320.0)

            t_speak_wall0 = time.perf_counter()
            timing: dict[str, float] = {}
            self._speak_enqueue_unix = enqueue_unix
            if enqueue_unix is not None:
                timing["api_enqueue_to_speak_enter_wall_ms"] = (
                    time.time() - enqueue_unix
                ) * 1000.0
            self._speak_t0_wall = t_speak_wall0
            self._speak_milestones = timing

            async def _producer() -> None:
                t0 = time.perf_counter()
                pcm_arr = np.asarray(pcm, dtype=np.int16)
                if pcm_arr.size == 0:
                    timing["producer_wall_ms"] = 0.0
                    await audio_q.put(None)
                    return
                faded = _fade_head_i16(pcm_arr, sample_rate, boundary_fade_ms)
                audio_buffer = faded
                if audio_buffer.size > 0:
                    audio_buffer = _fade_tail_i16(audio_buffer, sample_rate, tail_fade_ms)
                silence_samples = int(sample_rate * max(0.0, trailing_silence_ms) / 1000.0)
                if silence_samples > 0:
                    audio_buffer = np.concatenate(
                        [audio_buffer, np.zeros(silence_samples, dtype=np.int16)]
                    )
                pad_len = (-len(audio_buffer)) % chunk_samples
                if pad_len:
                    audio_buffer = np.concatenate(
                        [audio_buffer, np.zeros(pad_len, dtype=np.int16)]
                    )
                while len(audio_buffer) >= chunk_samples:
                    chunk = audio_buffer[:chunk_samples]
                    audio_buffer = audio_buffer[chunk_samples:]
                    await audio_q.put((chunk, None))
                    if "first_chunk_queued_ms" not in timing:
                        timing["first_chunk_queued_ms"] = (
                            time.perf_counter() - t_speak_wall0
                        ) * 1000.0
                timing["producer_wall_ms"] = (time.perf_counter() - t0) * 1000.0
                await audio_q.put(None)

            async def _consumer() -> None:
                t_consumer0 = time.perf_counter()
                flashtalk_gen_sum_s = 0.0
                flashtalk_chunks = 0
                generated = 0
                pending: list[tuple[np.ndarray, list[Any], str | None]] = []
                pacing_started = False

                async def _publish_subtitle_chunk(text: str) -> None:
                    await publish_event(
                        self.redis,
                        self.session_id,
                        "subtitle.chunk",
                        {"session_id": self.session_id, "text": text, "is_final": False},
                    )

                def _start_pacing() -> None:
                    nonlocal pacing_started
                    if pacing_started:
                        return
                    pacing_started = True
                    self._speech_media_active = True
                    if self.webrtc:
                        self.webrtc.draining = True
                        self.webrtc.clear_media_queues()
                        self.webrtc.reset_clocks()
                    self._av_ts_ms = 0.0
                    self._media_clock_started = True

                while True:
                    item = await audio_q.get()
                    if item is None:
                        break
                    pcm_chunk, sub_tag = item
                    if self._interrupt.is_set():
                        break
                    g0 = time.perf_counter()
                    frames = await self._generate_flashtalk_frames(pcm_chunk)
                    flashtalk_gen_sum_s += time.perf_counter() - g0
                    if "first_flashtalk_return_ms" not in timing:
                        timing["first_flashtalk_return_ms"] = (
                            time.perf_counter() - t_speak_wall0
                        ) * 1000.0
                    flashtalk_chunks += 1
                    generated += 1

                    if generated <= n_opener_chunks:
                        _start_pacing()
                        if sub_tag:
                            await _publish_subtitle_chunk(sub_tag)
                        await self._queue_av_chunk(pcm_chunk, frames)
                        continue

                    if pacing_started:
                        if sub_tag:
                            await _publish_subtitle_chunk(sub_tag)
                        await self._queue_av_chunk(pcm_chunk, frames)
                        continue

                    pending.append((pcm_chunk, frames, sub_tag))
                    if generated < prebuffer_chunks:
                        continue

                    log.info(
                        "Pre-buffer done (%d chunks, %.2fs audio), starting pacing",
                        generated,
                        (generated * chunk_samples) / sample_rate,
                    )
                    _start_pacing()
                    for pc, bf, st in pending:
                        if st:
                            await _publish_subtitle_chunk(st)
                        await self._queue_av_chunk(pc, bf)
                    pending.clear()

                if pending and not self._interrupt.is_set():
                    log.info(
                        "Flushing short pre-buffer (%d chunks, %.2fs audio), starting pacing",
                        len(pending),
                        (len(pending) * chunk_samples) / sample_rate,
                    )
                    _start_pacing()
                    for pc, buffered_frames, st in pending:
                        if st:
                            await _publish_subtitle_chunk(st)
                        await self._queue_av_chunk(pc, buffered_frames)

                timing["flashtalk_generate_sum_ms"] = flashtalk_gen_sum_s * 1000.0
                timing["flashtalk_chunks"] = float(flashtalk_chunks)
                timing["consumer_wall_ms"] = (time.perf_counter() - t_consumer0) * 1000.0
                log.info("speak_uploaded_pcm consumer done session=%s", self.session_id)

            try:
                t_parallel0 = time.perf_counter()
                await asyncio.gather(_producer(), _consumer())
                timing["parallel_total_ms"] = (time.perf_counter() - t_parallel0) * 1000.0
                await self._queue_fasterliveportrait_rest_frame()
            except Exception as e:
                log.exception("FlashTalk speak_uploaded_pcm failed: session=%s", self.session_id)
                await publish_event(
                    self.redis,
                    self.session_id,
                    "error",
                    {"session_id": self.session_id, "code": "SPEAK_UPLOAD_FAILED", "message": str(e)},
                )
                raise
            finally:
                self._speaking = False
                self._speech_media_active = False
                self._speak_t0_wall = None
                self._speak_milestones = None
                self._speak_enqueue_unix = None

            timing["speak_wall_ms"] = (time.perf_counter() - t_speak_wall0) * 1000.0
            log.info(
                "speak_uploaded_pcm timing: session=%s wall_ms=%.0f parallel_ms=%.0f "
                "producer_ms=%.0f flashtalk_sum_ms=%.0f chunks=%d consumer_ms=%.0f "
                "first_chunk_ms=%s first_ft_ms=%s first_webrtc_ms=%s",
                self.session_id,
                timing.get("speak_wall_ms", -1.0),
                timing.get("parallel_total_ms", -1.0),
                timing.get("producer_wall_ms", -1.0),
                timing.get("flashtalk_generate_sum_ms", -1.0),
                int(timing.get("flashtalk_chunks", 0.0)),
                timing.get("consumer_wall_ms", -1.0),
                (
                    "%.0f" % timing["first_chunk_queued_ms"]
                    if "first_chunk_queued_ms" in timing
                    else "n/a"
                ),
                (
                    "%.0f" % timing["first_flashtalk_return_ms"]
                    if "first_flashtalk_return_ms" in timing
                    else "n/a"
                ),
                (
                    "%.0f" % timing["first_webrtc_queue_ms"]
                    if "first_webrtc_queue_ms" in timing
                    else "n/a"
                ),
            )

            await self._publish_speech_ended(None)
            if not self._closed:
                await set_session_state(self.redis, self.session_id, "ready")

    async def _video_put_safe(self, frame) -> None:
        """Queue video safely.

        During active speech with a live WebRTC peer, block for backpressure so
        model generation cannot outrun real-time playback and accumulate a large
        A/V backlog. Outside that path, keep the older drop-oldest behavior so
        idle preview never wedges on a stale peer.
        """
        if not self.webrtc:
            return
        if self._speech_media_active and self._webrtc_started.is_set() and not self.webrtc.draining:
            await self.webrtc.video._queue.put(frame)
            return
        try:
            self.webrtc.video._queue.put_nowait(frame)
        except asyncio.QueueFull:
            # Drop oldest frame to make room
            try:
                self.webrtc.video._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self.webrtc.video._queue.put_nowait(frame)
            except asyncio.QueueFull:
                pass

    async def _audio_put_safe(self, pcm: np.ndarray) -> None:
        """Queue audio samples in small chunks for smooth WebRTC playback."""
        if not self.webrtc:
            return
        arr = np.asarray(pcm, dtype=np.int16)
        # Split into ~20ms chunks (320 samples at 16kHz) for smooth playback
        chunk_size = 320
        block_for_backpressure = (
            self._speech_media_active
            and self._webrtc_started.is_set()
            and not self.webrtc.draining
        )
        for i in range(0, len(arr), chunk_size):
            part = arr[i:i + chunk_size]
            if len(part) == 0:
                continue
            if block_for_backpressure:
                await self.webrtc.audio._queue.put(part)
                continue
            try:
                self.webrtc.audio._queue.put_nowait(part)
            except asyncio.QueueFull:
                try:
                    self.webrtc.audio._queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    self.webrtc.audio._queue.put_nowait(part)
                except asyncio.QueueFull:
                    pass

    async def _send_audio_chunk(self, pcm_chunk: np.ndarray) -> None:
        """Send one audio chunk to FlashTalk server, push resulting frames to WebRTC."""
        frames = await self._generate_flashtalk_frames(pcm_chunk)
        await self._queue_av_chunk(pcm_chunk, frames)

    async def _generate_flashtalk_frames(
        self,
        pcm_chunk: np.ndarray,
        *,
        source: str = "live",
    ) -> list[Any]:
        """Generate frames for one audio chunk without enqueueing playback."""
        import time as _t
        t0 = _t.monotonic()
        if source == "idle" and (self._speaking or self._closed):
            return []
        async with self._generate_lock:
            if source == "idle" and (self._speaking or self._closed):
                return []
            try:
                frames = await self.flashtalk.generate(pcm_chunk)
            except RuntimeError as e:
                msg = str(e).lower()
                if (
                    "no active session" in msg
                    or "send 'init'" in msg
                    or "send init" in msg
                    or "not connected" in msg
                ):
                    ref = self._ref_image_path
                    if ref is not None and ref.exists():
                        log.warning(
                            "FlashTalk generate lost session (%s); re-init and retry once",
                            e,
                        )
                        await self._reset_flashtalk_session(ref)
                        frames = await self.flashtalk.generate(pcm_chunk)
                    else:
                        raise
                else:
                    raise
        t1 = _t.monotonic()
        log.info(
            "FlashTalk %s generate: %d frames in %.2fs, vq=%d aq=%d",
            source,
            len(frames),
            t1 - t0,
            self.webrtc.video._queue.qsize() if self.webrtc else -1,
            self.webrtc.audio._queue.qsize() if self.webrtc else -1,
        )
        return frames

    async def _wait_media_backpressure(self) -> None:
        """Throttle MuseTalk generation when WebRTC queues are already ahead."""
        if self.model_type != "musetalk" or not self.webrtc:
            return
        if not _env_bool("MUSETALK_BACKPRESSURE_ENABLE", True):
            return

        video_high = max(1, _env_int("MUSETALK_VIDEO_HIGH_WATERMARK", 50))
        video_low = max(0, min(video_high, _env_int("MUSETALK_VIDEO_LOW_WATERMARK", 30)))
        audio_high = max(1, _env_int("MUSETALK_AUDIO_HIGH_WATERMARK", 100))
        audio_low = max(0, min(audio_high, _env_int("MUSETALK_AUDIO_LOW_WATERMARK", 60)))
        sleep_s = max(0.005, _env_float("MUSETALK_BACKPRESSURE_SLEEP_MS", 20.0) / 1000.0)
        log_every_s = max(0.25, _env_float("MUSETALK_BACKPRESSURE_LOG_INTERVAL_MS", 1000.0) / 1000.0)

        waited = 0.0
        last_log = time.monotonic()
        while not self._interrupt.is_set() and not self._closed and self.webrtc:
            vq = self.webrtc.video._queue.qsize()
            aq = self.webrtc.audio._queue.qsize()
            if vq <= video_high and aq <= audio_high:
                break

            now = time.monotonic()
            if now - last_log >= log_every_s:
                log.info(
                    "MuseTalk backpressure: wait %.2fs vq=%d/%d->%d aq=%d/%d->%d",
                    waited, vq, video_high, video_low, aq, audio_high, audio_low,
                )
                last_log = now

            await asyncio.sleep(sleep_s)
            waited += sleep_s

            vq = self.webrtc.video._queue.qsize()
            aq = self.webrtc.audio._queue.qsize()
            if vq <= video_low and aq <= audio_low:
                break

        if waited > 0.0 and self.webrtc:
            log.info(
                "MuseTalk backpressure released: waited=%.2fs vq=%d aq=%d",
                waited, self.webrtc.video._queue.qsize(), self.webrtc.audio._queue.qsize(),
            )

    async def _queue_av_chunk(self, pcm_chunk: np.ndarray, frames: list[Any]) -> None:
        """Queue generated video frames interleaved with matching audio.

        Each video frame is paired with a proportional slice of the audio
        chunk so that the video and audio queues advance at the same pace.
        This prevents lip movement from running ahead of the audio.
        """
        t0 = getattr(self, "_speak_t0_wall", None)
        ms = getattr(self, "_speak_milestones", None)
        eu = getattr(self, "_speak_enqueue_unix", None)
        first_media_this_speak = False
        queue_t0 = time.perf_counter()
        vq_before = self.webrtc.video._queue.qsize() if self.webrtc else -1
        aq_before = self.webrtc.audio._queue.qsize() if self.webrtc else -1
        if (
            t0 is not None
            and isinstance(ms, dict)
            and "first_webrtc_queue_ms" not in ms
        ):
            ms["first_webrtc_queue_ms"] = (time.perf_counter() - t0) * 1000.0
            first_media_this_speak = True
        if (
            eu is not None
            and isinstance(ms, dict)
            and "first_frame_from_api_wall_ms" not in ms
        ):
            ms["first_frame_from_api_wall_ms"] = (time.time() - eu) * 1000.0

        if first_media_this_speak:
            try:
                await publish_event(
                    self.redis,
                    self.session_id,
                    "speech.media_started",
                    {"session_id": self.session_id},
                )
            except Exception:
                log.exception("publish speech.media_started failed")

        arr = np.asarray(pcm_chunk, dtype=np.int16)
        total_samples = len(arr)
        n_frames = len(frames)
        if n_frames == 0:
            await self._audio_put_safe(arr)
            return

        await self._append_recording_frames_if_enabled(frames)
        playback_wait_ms = await self._wait_for_playback_capacity(
            n_frames=n_frames,
            first_media_this_speak=first_media_this_speak,
        )

        sample_rate = max(1, int(getattr(self.flashtalk, "sample_rate", 16000) or 16000))
        default_frame_interval_ms = 1000.0 / max(1.0, float(getattr(self.flashtalk, "fps", 25) or 25))
        av_offset_ms = _env_float("AV_OFFSET_MS", 0.0)

        for i, frame in enumerate(frames):
            if self._interrupt.is_set():
                break
            audio_start = i * total_samples // n_frames
            audio_end = (i + 1) * total_samples // n_frames
            audio_slice = arr[audio_start:audio_end]
            audio_duration_ms = (
                (len(audio_slice) * 1000.0) / sample_rate
                if len(audio_slice) > 0
                else default_frame_interval_ms
            )
            frame.timestamp_ms = max(0.0, self._av_ts_ms + av_offset_ms)
            self._trace_queued_video_frame(frame)
            await self._video_put_safe(frame)
            # Pair each frame with its proportional audio slice.
            # Use _audio_put_safe (20ms sub-chunks) for clean opus encoding,
            # but feed them right after the matching video frame so A/V stay
            # in lockstep within the queue.
            if len(audio_slice) > 0:
                await self._audio_put_safe(audio_slice)
            self._av_ts_ms += audio_duration_ms

        # Cache last frame for idle loop
        if frames:
            self._last_frame = frames[-1].data
        queue_ms = (time.perf_counter() - queue_t0) * 1000.0
        audio_ms = total_samples * 1000.0 / sample_rate if total_samples else 0.0
        vq_after = self.webrtc.video._queue.qsize() if self.webrtc else -1
        aq_after = self.webrtc.audio._queue.qsize() if self.webrtc else -1
        log.info(
            "FlashTalk queue AV chunk: session=%s model=%s frames=%d audio_ms=%.1f "
            "queue_ms=%.1f playback_wait_ms=%.1f queue_fps=%.2f vq=%d->%d aq=%d->%d av_ts_ms=%.1f",
            self.session_id,
            self.model_type,
            n_frames,
            audio_ms,
            queue_ms,
            playback_wait_ms,
            n_frames / max(queue_ms / 1000.0, 1e-6),
            vq_before,
            vq_after,
            aq_before,
            aq_after,
            self._av_ts_ms,
        )

    async def _append_recording_frames_if_enabled(self, frames: list[Any]) -> None:
        try:
            recording = await self.redis.hget(
                session_key(self.session_id),
                FLASHTALK_DISK_RECORDING_FIELD,
            )
        except Exception:
            log.exception("FlashTalk recording flag read failed: session=%s", self.session_id)
            return
        if str(recording or "").strip() != "1":
            return
        try:
            from opentalking.pipeline.recording.recording import append_flashtalk_frames

            self._recording_frame_index = append_flashtalk_frames(
                self.session_id,
                frames,
                start_index=self._recording_frame_index,
                fps=float(getattr(self.flashtalk, "fps", 25) or 25),
            )
        except Exception:
            log.exception("FlashTalk recording append failed: session=%s", self.session_id)

    def _trace_queued_video_frame(self, frame: Any) -> None:
        if not self._debug_frame_trace:
            return
        data = getattr(frame, "data", frame)
        arr = np.asarray(data)
        mean = float(arr.mean()) if arr.size else 0.0
        delta = 0.0 if self._debug_prev_video_mean is None else abs(mean - self._debug_prev_video_mean)
        self._debug_prev_video_mean = mean
        self._debug_queued_video_count += 1
        if self._debug_queued_video_count <= 12 or self._debug_queued_video_count % 32 == 0:
            log.info(
                "RTC video queue: n=%d ts=%.1f vq=%d shape=%s mean=%.2f dmean=%.2f",
                self._debug_queued_video_count,
                float(getattr(frame, "timestamp_ms", 0.0) or 0.0),
                self.webrtc.video._queue.qsize() if self.webrtc else -1,
                tuple(arr.shape),
                mean,
                delta,
            )

    async def interrupt(self) -> None:
        self._interrupt.set()
        pending_speech_tasks = [task for task in self.speech_tasks if not task.done()]
        # 仅在「确有口播在进行」时需要整段重建 FlashTalk 会话；空闲时跳过可省 ~1s（close/reconnect/init）。
        was_busy = self._speaking or bool(pending_speech_tasks)
        for task in pending_speech_tasks:
            task.cancel()
        if pending_speech_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending_speech_tasks, return_exceptions=True),
                    timeout=2.0,
                )
            except asyncio.TimeoutError:
                pass
        self._speaking = False
        self._speech_media_active = False

        # WebRTC：清缓冲并重置时钟，避免打断后仍播放旧一段的音画。
        if self.webrtc:
            try:
                self.webrtc.clear_media_queues()
                self.webrtc.reset_clocks()
            except Exception:
                log.exception("webrtc reset after interrupt failed")

        # FlashTalk：服务端会话沿时间轴连续时，下一轮语音会从「半截嘴型」接着算，容易与新音频
        # 不对齐。此处重新 init，使下一轮 generate 与**新**口播从零对齐。
        # 不把 ``_last_frame`` 设回 reference：待机仍显示打断前最后一帧，避免画面闪回初始脸；
        # 新一句的第一批生成帧到来后再更新。
        #
        # 若当前无口播任务（常见：用户在上一条说完后再发纯文本），不必 close/reconnect/init，
        # 否则会每次 speak 先跑 interrupt 白白耗 ~1s。
        ref = self._ref_image_path
        if ref is not None and ref.exists():
            if was_busy:
                try:
                    await self._reset_flashtalk_session(ref)
                except Exception:
                    log.exception("FlashTalk session reset after interrupt failed")
            else:
                log.info(
                    "FlashTalk interrupt: idle path, skip session reset (session=%s)",
                    self.session_id,
                )

        await self._publish_speech_ended()
        if not self._closed:
            await set_session_state(self.redis, self.session_id, "ready")

    async def close(self) -> None:
        self._closed = True
        self._webrtc_started.set()
        await self.interrupt()
        if (
            self._tts_opener_warm_task
            and self._tts_opener_warm_task is not _TTS_OPENER_PRELOAD_TASK
        ):
            self._tts_opener_warm_task.cancel()
            try:
                await self._tts_opener_warm_task
            except asyncio.CancelledError:
                pass
        if self._idle_task:
            self._idle_task.cancel()
            try:
                await self._idle_task
            except asyncio.CancelledError:
                pass
        await self.flashtalk.close()
        if self.webrtc:
            await self.webrtc.close()
        await set_session_state(self.redis, self.session_id, "closed")


FlashTalkSessionRunner = FlashTalkRunner
