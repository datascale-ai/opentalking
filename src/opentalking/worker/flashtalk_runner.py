"""
FlashTalkSessionRunner – drives the full conversation pipeline:

    user text → LLM (百炼) → TTS → FlashTalk backend → WebRTC
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import numpy as np

from opentalking.avatars.loader import load_avatar_bundle
from opentalking.core.config import get_settings
from opentalking.core.session_store import set_session_state
from opentalking.llm.openai_compatible import OpenAICompatibleLLMClient
from opentalking.llm.sentence_splitter import SentenceSplitter
from opentalking.llm.conversation import ConversationHistory
from opentalking.models.flashtalk.ws_client import FlashTalkWSClient
from opentalking.rtc.aiortc_adapter import WebRTCSession
from opentalking.tts.edge.adapter import EdgeTTSAdapter
from opentalking.tts.elevenlabs.adapter import ElevenLabsTTSAdapter
from opentalking.worker.bus import publish_event
from opentalking.worker.text_sanitize import sanitize_tts_text, strip_emoji, strip_markdown

log = logging.getLogger(__name__)

_IDLE_CACHE_VERSION = 6
_IDLE_FRAME_CACHE: dict[str, list[np.ndarray]] = {}
_IDLE_CACHE_LOCKS: dict[str, asyncio.Lock] = {}
_TTS_OPENER_PCM_CACHE: dict[str, np.ndarray] = {}
_TTS_OPENER_CACHE_LOCKS: dict[str, asyncio.Lock] = {}
_TTS_OPENER_PRELOAD_TASK: asyncio.Task[None] | None = None

_TTS_OPENER_RULES: tuple[tuple[str, tuple[str, ...], tuple[tuple[str, str], ...]], ...] = (
    (
        "greeting",
        ("你好", "您好", "哈喽", "嗨", "在吗"),
        (
            ("greeting_1", "你好，我在这边。"),
            ("greeting_2", "你好，我听着呢。"),
        ),
    ),
    (
        "task",
        ("帮我", "处理", "看下", "看看", "怎么弄", "怎么办", "查一下", "帮忙"),
        (
            ("task_1", "好的，我来看看。"),
            ("task_2", "明白，我帮你处理。"),
        ),
    ),
    (
        "explain",
        ("为什么", "怎么", "是什么", "原理", "区别", "原因"),
        (
            ("explain_1", "这个我来解释。"),
            ("explain_2", "好，我给你说明。"),
        ),
    ),
    (
        "confirm",
        ("能不能", "可以吗", "是否", "有没有", "行不行"),
        (
            ("confirm_1", "可以，我告诉你。"),
            ("confirm_2", "这个我来确认。"),
        ),
    ),
)
_TTS_OPENER_FALLBACKS: tuple[tuple[str, str], ...] = (
    ("fallback_1", "明白，我帮你处理。"),
    ("fallback_2", "好的，我来看看。"),
    ("fallback_3", "这个我来解释。"),
)


def _default_flashtalk_ws_url() -> str:
    server_host = os.environ.get("SERVER_HOST", "localhost")
    return os.environ.get("OPENTALKING_FLASHTALK_WS_URL", f"ws://{server_host}:8765")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None and name.startswith("FLASHTALK_"):
        raw = os.environ.get(f"OPENTALKING_{name}")
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        log.warning("Invalid %s=%r, using %.1f", name, raw, default)
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None and name.startswith("FLASHTALK_"):
        raw = os.environ.get(f"OPENTALKING_{name}")
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        log.warning("Invalid %s=%r, using %d", name, raw, default)
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None and name.startswith("FLASHTALK_"):
        raw = os.environ.get(f"OPENTALKING_{name}")
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


async def _wait_for_queue_empty(
    q: asyncio.Queue[Any],
    *,
    poll_interval_s: float,
    timeout_s: float,
    interrupted: asyncio.Event | None = None,
) -> bool:
    loop = asyncio.get_running_loop()
    started = loop.time()
    while q.qsize() > 0:
        if interrupted is not None and interrupted.is_set():
            return False
        if (loop.time() - started) >= timeout_s:
            return False
        await asyncio.sleep(poll_interval_s)
    return True


def _fade_edges_i16(pcm: np.ndarray, sample_rate: int, fade_ms: float) -> np.ndarray:
    """Apply a tiny sentence-boundary fade to reduce TTS splice clicks."""
    arr = np.asarray(pcm, dtype=np.int16)
    fade_samples = int(sample_rate * max(0.0, fade_ms) / 1000.0)
    if arr.size == 0 or fade_samples <= 1:
        return arr

    fade_samples = min(fade_samples, arr.size // 2)
    if fade_samples <= 1:
        return arr

    out = arr.astype(np.float32, copy=True)
    out[:fade_samples] *= np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
    out[-fade_samples:] *= np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
    return np.clip(out, -32768, 32767).astype(np.int16)


def _fade_head_i16(pcm: np.ndarray, sample_rate: int, fade_ms: float) -> np.ndarray:
    """Fade the first samples of a streamed sentence."""
    arr = np.asarray(pcm, dtype=np.int16)
    fade_samples = int(sample_rate * max(0.0, fade_ms) / 1000.0)
    if arr.size == 0 or fade_samples <= 1:
        return arr

    fade_samples = min(fade_samples, arr.size)
    out = arr.astype(np.float32, copy=True)
    out[:fade_samples] *= np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
    return np.clip(out, -32768, 32767).astype(np.int16)


def _fade_tail_i16(pcm: np.ndarray, sample_rate: int, fade_ms: float) -> np.ndarray:
    """Fade the remaining tail before padding with silence."""
    arr = np.asarray(pcm, dtype=np.int16)
    fade_samples = int(sample_rate * max(0.0, fade_ms) / 1000.0)
    if arr.size == 0 or fade_samples <= 1:
        return arr

    fade_samples = min(fade_samples, arr.size)
    out = arr.astype(np.float32, copy=True)
    out[-fade_samples:] *= np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
    return np.clip(out, -32768, 32767).astype(np.int16)


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


def _idle_frame_signature(frame: np.ndarray) -> np.ndarray:
    """Downsample frames for loop-point search."""
    arr = np.asarray(frame, dtype=np.float32)
    if arr.ndim == 3 and arr.shape[2] >= 3:
        gray = arr[:, :, 0] * 0.114 + arr[:, :, 1] * 0.587 + arr[:, :, 2] * 0.299
    else:
        gray = arr

    h, w = gray.shape[:2]
    step_y = max(1, h // 24)
    step_x = max(1, w // 24)
    sampled = gray[::step_y, ::step_x]
    return sampled[:24, :24].astype(np.float32, copy=False)


def _blend_frames(left: np.ndarray, right: np.ndarray, alpha: float) -> np.ndarray:
    mixed = np.asarray(left, dtype=np.float32) * (1.0 - alpha)
    mixed += np.asarray(right, dtype=np.float32) * alpha
    return np.clip(mixed, 0.0, 255.0).astype(np.uint8)


def _motion_score(signatures: list[np.ndarray], start: int, end: int) -> float:
    score = 0.0
    steps = 0
    for idx in range(start, min(end, len(signatures) - 1)):
        score += float(np.mean(np.abs(signatures[idx + 1] - signatures[idx])))
        steps += 1
    return score / max(1, steps)


def _optimize_idle_loop(
    frames: list[np.ndarray],
    *,
    crossfade_frames: int,
) -> list[np.ndarray]:
    """Choose a smoother loop segment and soften the loop boundary."""
    if len(frames) < 12:
        return [np.ascontiguousarray(frame) for frame in frames]

    signatures = [_idle_frame_signature(frame) for frame in frames]
    total = len(signatures)
    compare_span = max(3, min(8, crossfade_frames))
    min_loop_frames = max(compare_span * 3, total // 2)
    best_score: float | None = None
    best_start = 0
    best_end = total - 1

    for start in range(max(1, total // 3)):
        min_end = start + min_loop_frames - 1
        if min_end >= total:
            break
        for end in range(min_end, total):
            score = 0.0
            for offset in range(compare_span):
                head = signatures[start + offset]
                tail = signatures[end - compare_span + 1 + offset]
                score += float(np.mean(np.abs(head - tail)))
            edge_motion = _motion_score(signatures, start, start + compare_span)
            edge_motion += _motion_score(
                signatures,
                max(start + 1, end - compare_span),
                end,
            )
            score += edge_motion * 0.35
            if best_score is None or score < best_score:
                best_score = score
                best_start = start
                best_end = end

    segment = [np.ascontiguousarray(frame) for frame in frames[best_start:best_end + 1]]
    overlap = max(2, min(crossfade_frames, len(segment) // 4))
    if len(segment) <= overlap + 2:
        return segment

    smoothed = list(segment[:-overlap])
    tail = segment[-overlap:]
    head = segment[:overlap]
    for idx in range(overlap):
        alpha = (idx + 1) / (overlap + 1)
        smoothed.append(_blend_frames(tail[idx], head[idx], alpha))

    smoothed.append(segment[0])
    return smoothed


def _build_idle_playback_indices(frame_count: int, mode: str) -> list[int]:
    if frame_count <= 1:
        return [0] if frame_count == 1 else []
    if mode == "pingpong":
        return list(range(frame_count)) + list(range(frame_count - 2, 0, -1))
    return list(range(frame_count))


def _build_soft_ellipse_mask(
    height: int,
    width: int,
    *,
    center_x: float,
    center_y: float,
    radius_x: float,
    radius_y: float,
    feather: float = 0.35,
) -> np.ndarray:
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    xx = (xx - center_x) / max(radius_x, 1.0)
    yy = (yy - center_y) / max(radius_y, 1.0)
    dist = np.sqrt(xx * xx + yy * yy)
    outer = 1.0 + max(0.05, feather)
    mask = np.clip((outer - dist) / max(outer - 1.0, 1e-6), 0.0, 1.0)
    return mask.astype(np.float32)


def _stabilize_idle_mouth(
    frames: list[np.ndarray],
    reference_frame: np.ndarray | None,
    *,
    strength: float,
    temporal_strength: float,
) -> list[np.ndarray]:
    if not frames or reference_frame is None or strength <= 0.0:
        return [np.ascontiguousarray(frame) for frame in frames]

    ref_arr = np.asarray(reference_frame)
    sample_h, sample_w = frames[0].shape[:2]
    if ref_arr.shape[:2] != (sample_h, sample_w):
        try:
            import cv2

            ref_arr = cv2.resize(ref_arr, (sample_w, sample_h), interpolation=cv2.INTER_AREA)
        except Exception:
            y_idx = np.linspace(0, ref_arr.shape[0] - 1, sample_h).astype(np.int32)
            x_idx = np.linspace(0, ref_arr.shape[1] - 1, sample_w).astype(np.int32)
            ref_arr = ref_arr[y_idx][:, x_idx]

    ref = np.asarray(ref_arr, dtype=np.float32)
    h, w = ref.shape[:2]
    mask = _build_soft_ellipse_mask(
        h,
        w,
        center_x=w * 0.5,
        center_y=h * 0.69,
        radius_x=w * 0.16,
        radius_y=h * 0.10,
        feather=0.42,
    )[:, :, None] * min(max(strength, 0.0), 1.0)

    stabilized: list[np.ndarray] = []
    prev_stable: np.ndarray | None = None
    temporal_strength = min(max(temporal_strength, 0.0), 1.0)
    for frame in frames:
        cur = np.asarray(frame, dtype=np.float32)
        blended = cur * (1.0 - mask) + ref * mask
        if prev_stable is not None and temporal_strength > 0.0:
            stable_mix = blended * (1.0 - temporal_strength) + prev_stable * temporal_strength
            blended = blended * (1.0 - mask) + stable_mix * mask
        prev_stable = blended
        stabilized.append(np.clip(blended, 0.0, 255.0).astype(np.uint8))
    return stabilized


def _join_tts_fragments(left: str, right: str) -> str:
    left = left.strip()
    right = right.strip()
    if not left:
        return right
    if not right:
        return left

    if left[-1].isascii() and left[-1].isalnum() and right[0].isascii() and right[0].isalnum():
        return f"{left} {right}"
    return f"{left}{right}"


def _speech_char_count(text: str) -> int:
    return sum(1 for ch in text if not ch.isspace())


def _normalize_tts_lookup_text(text: str) -> str:
    return "".join(ch.lower() for ch in text.strip() if not ch.isspace())


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _iter_tts_opener_variants() -> list[tuple[str, str]]:
    variants: list[tuple[str, str]] = []
    seen: set[str] = set()
    for _, _, choices in _TTS_OPENER_RULES:
        for opener_id, opener_text in choices:
            if opener_id in seen:
                continue
            variants.append((opener_id, opener_text))
            seen.add(opener_id)
    for opener_id, opener_text in _TTS_OPENER_FALLBACKS:
        if opener_id in seen:
            continue
        variants.append((opener_id, opener_text))
        seen.add(opener_id)
    return variants


def _build_tts_opener_candidates(user_text: str) -> list[tuple[str, str]]:
    normalized = _normalize_tts_lookup_text(user_text)
    for _, keywords, choices in _TTS_OPENER_RULES:
        if _contains_any(normalized, keywords):
            return list(choices) + list(_TTS_OPENER_FALLBACKS)
    return list(_TTS_OPENER_FALLBACKS)


def _merge_spoken_reply(prefix: str, body: str) -> str:
    prefix = prefix.strip()
    body = body.strip()
    if not prefix:
        return body
    if not body:
        return prefix
    if body.startswith(prefix):
        return body
    return _join_tts_fragments(prefix, body)


async def _synthesize_tts_opener_pcm(
    text: str,
    *,
    sample_rate: int,
    voice: str = "zh-CN-XiaoxiaoNeural",
) -> tuple[np.ndarray, bool]:
    cache_key = f"{sample_rate}:{voice}:{text}"
    cached = _TTS_OPENER_PCM_CACHE.get(cache_key)
    if cached is not None:
        return np.array(cached, copy=True), True

    lock = _tts_opener_cache_lock(cache_key)
    async with lock:
        cached = _TTS_OPENER_PCM_CACHE.get(cache_key)
        if cached is not None:
            return np.array(cached, copy=True), True

        tts = EdgeTTSAdapter(default_voice=voice, sample_rate=sample_rate, chunk_ms=20.0)
        parts: list[np.ndarray] = []
        async for chunk in tts.synthesize_stream(text, voice=voice):
            pcm = np.asarray(chunk.data, dtype=np.int16)
            if pcm.size:
                parts.append(np.ascontiguousarray(pcm))
        if not parts:
            raise RuntimeError(f"Failed to synthesize TTS opener: {text}")

        pcm = np.concatenate(parts).astype(np.int16, copy=False)
        _TTS_OPENER_PCM_CACHE[cache_key] = np.ascontiguousarray(pcm)
        return np.array(pcm, copy=True), False


async def _preload_tts_openers(sample_rate: int, voice: str) -> None:
    for _, opener_text in _iter_tts_opener_variants():
        try:
            await _synthesize_tts_opener_pcm(opener_text, sample_rate=sample_rate, voice=voice)
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
        tts_provider: str = "edge",
        tts_voice: str = "zh-CN-XiaoxiaoNeural",
        llm_base_url: str = "",
        llm_api_key: str = "",
        llm_model: str = "qwen-turbo",
        system_prompt: str = "你是一个友好的数字人助手，请用简洁的语言回答问题。",
    ) -> None:
        self.session_id = session_id
        self.avatar_id = avatar_id
        self.avatars_root = avatars_root
        self.redis = redis
        self._flashtalk_ws_url = flashtalk_ws_url or _default_flashtalk_ws_url()

        self.flashtalk = flashtalk_client or FlashTalkWSClient(
            self._flashtalk_ws_url
        )
        self._tts_provider = (tts_provider or "edge").strip().lower()
        self._tts_voice = tts_voice.strip() or "zh-CN-XiaoxiaoNeural"
        self._tts_chunk_ms = max(20.0, _env_float("FLASHTALK_TTS_CHUNK_MS", 120.0))
        # Remote FlashTalk serves a single active session; a second background
        # init for idle-cache building can replace the live session underneath us.
        self._allow_background_idle_cache = flashtalk_client is not None

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
        self._idle_cache_key: str | None = None
        self._idle_frames: list[np.ndarray] = []
        self._idle_playback_indices: list[int] = []
        self._idle_frame_idx = 0
        self._reference_frame: np.ndarray | None = None
        self._last_frame: np.ndarray | None = None  # cached for idle loop
        self._tts_opener_recent_ids: list[str] = []
        self._tts_opener_warm_task: asyncio.Task[None] | None = None
        self._media_clock_started = False
        self._speech_media_active = False
        self._has_completed_speech = False
        self._avatar_metadata: dict[str, Any] = {}
        self._reference_image_path: Path | None = None
        self._reset_session_each_turn = False

    def avatar_path(self) -> Path:
        return (self.avatars_root / self.avatar_id).resolve()

    def _tts_runtime_voice(self) -> str:
        return self._tts_voice

    def _tts_supports_cached_openers(self) -> bool:
        return self._tts_provider in {"edge", "elevenlabs"}

    def _build_tts_adapter(self, *, sample_rate: int) -> Any:
        settings = get_settings()
        if self._tts_provider == "elevenlabs":
            return ElevenLabsTTSAdapter(
                api_key=settings.tts_elevenlabs_api_key,
                default_voice=self._tts_voice or settings.tts_elevenlabs_voice_id,
                base_url=settings.tts_elevenlabs_base_url,
                model_id=settings.tts_elevenlabs_model_id,
                output_format=settings.tts_elevenlabs_output_format,
                sample_rate=sample_rate,
                chunk_ms=self._tts_chunk_ms,
            )
        return EdgeTTSAdapter(
            default_voice=self._tts_voice,
            sample_rate=sample_rate,
            chunk_ms=self._tts_chunk_ms,
        )

    async def _prewarm_tts(self, *, sample_rate: int) -> None:
        return

    async def prepare(self) -> None:
        """Load avatar, connect to FlashTalk server, init session."""
        avatar_dir = self.avatar_path()
        bundle = load_avatar_bundle(avatar_dir, strict=False)
        self._avatar_metadata = dict(bundle.manifest.metadata or {})
        self._reset_session_each_turn = _coerce_bool(
            self._avatar_metadata.get("reset_session_each_turn"),
            False,
        )

        # Read reference image
        ref_image_path = avatar_dir / "reference.png"
        if not ref_image_path.exists():
            # Try jpg
            ref_image_path = avatar_dir / "reference.jpg"
        if not ref_image_path.exists():
            raise FileNotFoundError(
                f"No reference image in {avatar_dir} (expected reference.png or .jpg)"
            )
        self._reference_image_path = ref_image_path.resolve()

        # Connect and init FlashTalk session
        await self.flashtalk.connect()
        await self.flashtalk.init_session(ref_image=ref_image_path)

        # Create WebRTC session matching FlashTalk output
        self.webrtc = WebRTCSession(
            fps=float(self.flashtalk.fps),
            sample_rate=16000,
            mode="legacy",
        )

        # Load reference image as initial idle frame
        try:
            import imageio.v3 as iio
            img = iio.imread(ref_image_path)
            if img.shape[2] == 4:  # RGBA → RGB
                img = img[:, :, :3]
            # Convert RGB to BGR for WebRTC
            self._reference_frame = img[:, :, ::-1].copy()
            self._last_frame = self._reference_frame.copy()
        except Exception:
            self._reference_frame = None
            self._last_frame = None

        # Remote FlashTalk backends cannot safely rebuild idle cache in the
        # background, but they can and should reuse an existing on-disk cache.
        cache_path = self._idle_cache_path(avatar_dir)
        cache_key = self._make_idle_cache_key(ref_image_path)
        self._idle_cache_key = cache_key
        disk_frames = self._load_idle_frames_from_disk(cache_path, cache_key)
        if disk_frames:
            self._set_idle_frames(disk_frames)

        # Start idle loop after init; it replays local cached frames when WebRTC is live.
        if self._idle_task is None:
            self._idle_task = asyncio.create_task(self._idle_loop())

        self.ready_event.set()
        log.info("FlashTalkRunner prepared: session=%s, avatar=%s", self.session_id, self.avatar_id)

        # Only build idle cache in-process for local deployments. Remote
        # FlashTalk backends keep a single active session, so a background init
        # would evict the live user session.
        if self._allow_background_idle_cache and not self._idle_frames:
            asyncio.create_task(self._prepare_idle_cache_background(ref_image_path))

        global _TTS_OPENER_PRELOAD_TASK
        if _env_bool("FLASHTALK_TTS_OPENER_ENABLE", False) and _env_bool(
            "FLASHTALK_TTS_OPENER_PRELOAD",
            False,
        ) and self._tts_supports_cached_openers():
            task = _TTS_OPENER_PRELOAD_TASK
            if task is None or task.done():
                _TTS_OPENER_PRELOAD_TASK = asyncio.create_task(
                    _preload_tts_openers(sample_rate=16000, voice=self._tts_runtime_voice())
                )
            self._tts_opener_warm_task = _TTS_OPENER_PRELOAD_TASK

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
            if (
                self._speaking
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
                frames = np.asarray(data["frames"], dtype=np.uint8)
        except Exception:
            log.exception("Failed to load idle cache: %s", cache_path)
            return []

        if frames.ndim != 4 or frames.shape[0] == 0:
            return []

        if stored_key != cache_key:
            stored_parts = stored_key.split("::")
            expected_parts = cache_key.split("::")
            compatible = (
                len(stored_parts) == len(expected_parts)
                and stored_parts[3:] == expected_parts[3:]
            )
            if not compatible:
                return []
            log.warning(
                "Using compatible stale idle cache despite key mismatch: avatar=%s path=%s",
                self.avatar_id,
                cache_path,
            )
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
        await self.flashtalk.init_session(ref_image=ref_image_path)

    async def _build_idle_frames(self) -> list[np.ndarray]:
        idle_chunks = max(1, _env_int("FLASHTALK_IDLE_CACHE_CHUNKS", 4))
        idle_level = max(40.0, _env_float("FLASHTALK_IDLE_CACHE_LEVEL", 480.0))
        crossfade_frames = max(2, _env_int("FLASHTALK_IDLE_CACHE_CROSSFADE_FRAMES", 6))
        playback_mode = os.environ.get("FLASHTALK_IDLE_CACHE_PLAYBACK", "pingpong").strip().lower()
        mouth_lock = max(0.0, min(1.0, _env_float("FLASHTALK_IDLE_MOUTH_LOCK", 0.97)))
        mouth_temporal = max(0.0, min(1.0, _env_float("FLASHTALK_IDLE_MOUTH_TEMPORAL", 0.85)))
        temp_client = FlashTalkWSClient(self._flashtalk_ws_url)
        try:
            await temp_client.connect()
            ref_image_path = self.avatar_path() / "reference.png"
            if not ref_image_path.exists():
                ref_image_path = self.avatar_path() / "reference.jpg"
            await temp_client.init_session(ref_image=ref_image_path)

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
            await temp_client.close()

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
        max_history = max(0, _env_int("FLASHTALK_TTS_OPENER_MAX_HISTORY", 2))
        if max_history == 0:
            self._tts_opener_recent_ids.clear()
            return
        self._tts_opener_recent_ids = [
            existing for existing in self._tts_opener_recent_ids if existing != opener_id
        ]
        self._tts_opener_recent_ids.append(opener_id)
        if len(self._tts_opener_recent_ids) > max_history:
            self._tts_opener_recent_ids = self._tts_opener_recent_ids[-max_history:]

    async def _select_tts_opener(
        self,
        user_text: str,
        *,
        sample_rate: int,
        chunk_samples: int,
    ) -> tuple[str, str, np.ndarray, bool, bool] | None:
        if not _env_bool("FLASHTALK_TTS_OPENER_ENABLE", False):
            return None
        if not self._tts_supports_cached_openers():
            return None

        min_fill_ratio = min(
            max(_env_float("FLASHTALK_TTS_OPENER_MIN_FILL_RATIO", 0.78), 0.0),
            1.0,
        )
        pad_to_chunk = _env_bool("FLASHTALK_TTS_OPENER_PAD_TO_CHUNK", True)
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
                    voice=self._tts_runtime_voice(),
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
        return {"sdp": ans.sdp, "type": ans.type}

    def _ensure_media_clock_started(self) -> None:
        if self.webrtc is None or self._media_clock_started:
            return
        self.webrtc.reset_clocks()
        self._media_clock_started = True

    def create_speak_task(self, text: str) -> asyncio.Task[None]:
        task = asyncio.create_task(self._run_speak_task(text))
        self.speech_tasks.add(task)
        task.add_done_callback(self.speech_tasks.discard)
        return task

    async def _run_speak_task(self, text: str) -> None:
        log.info("speak start: %s (session=%s)", text[:30], self.session_id)
        try:
            await self.speak(text)
            log.info("speak done: session=%s", self.session_id)
        except asyncio.CancelledError:
            log.info("speak cancelled: session=%s", self.session_id)
        except Exception:  # noqa: BLE001
            log.exception("speak failed: session=%s", self.session_id)
            if not self._closed:
                await set_session_state(self.redis, self.session_id, "error")

    async def _publish_speech_ended(self) -> None:
        if not self._speech_started:
            return
        self._speech_started = False
        await publish_event(
            self.redis,
            self.session_id,
            "speech.ended",
            {"session_id": self.session_id},
        )

    async def speak(self, text: str) -> None:
        """Full pipeline: user text → LLM → TTS → FlashTalk → WebRTC.

        Uses a producer-consumer pattern:
          Producer: LLM stream → sentence split → TTS → audio chunks into queue
          Consumer: dequeue audio chunks → FlashTalk generate → WebRTC frames
        This eliminates inter-sentence gaps.
        """
        async with self._speak_lock:
            if self._closed:
                return
            self._interrupt.clear()
            self._speaking = True
            if self._has_completed_speech and self._reset_session_each_turn:
                await self._reset_session_before_turn()
            if self.webrtc:
                # Drop queued idle frames so speech starts from a clean A/V boundary.
                self.webrtc.clear_media_queues()
                self._media_clock_started = False
                self._speech_media_active = False

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
            # Queue of fixed-size audio chunks ready for FlashTalk; None = done
            audio_q: asyncio.Queue[np.ndarray | None] = asyncio.Queue(maxsize=8)
            sample_rate = 16000
            configured_prebuffer_chunks = max(1, _env_int("FLASHTALK_PREBUFFER_CHUNKS", 1))
            prebuffer_chunks = (
                configured_prebuffer_chunks
                if self._has_completed_speech
                else 1
            )
            if prebuffer_chunks != configured_prebuffer_chunks:
                log.info(
                    "First speech warm start: override prebuffer_chunks %d -> %d",
                    configured_prebuffer_chunks,
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

            async def _producer():
                """LLM → sentence split → TTS → fixed-size audio chunks into queue.

                Uses a two-stage pipeline to overlap TTS startup with audio
                streaming:
                  Stage 1 (LLM feeder): LLM deltas → sentence split → sentence_q
                  Stage 2 (TTS worker): sentence_q → Edge TTS → audio chunks → audio_q
                This eliminates the ~300-800ms TTS startup gap between sentences.
                """
                nonlocal full_response
                audio_buffer = np.zeros(0, dtype=np.int16)
                text_buffer = ""
                splitter = SentenceSplitter()
                tts = self._build_tts_adapter(sample_rate=sample_rate)
                # Sentence queue: decouples LLM stream from TTS so next sentence
                # can be queued while current sentence is still being synthesised.
                sentence_q: asyncio.Queue[str | None] = asyncio.Queue(maxsize=4)

                async def _append_pcm(pcm: np.ndarray) -> int:
                    nonlocal audio_buffer
                    if pcm.size == 0:
                        return 0

                    audio_buffer = np.concatenate([audio_buffer, pcm.astype(np.int16)])
                    chunks = 0
                    while len(audio_buffer) >= chunk_samples:
                        chunk = audio_buffer[:chunk_samples]
                        audio_buffer = audio_buffer[chunk_samples:]
                        await audio_q.put(chunk)
                        chunks += 1
                    return chunks

                async def _emit_cached_opener() -> None:
                    nonlocal spoken_prefix
                    opener = await self._select_tts_opener(
                        text,
                        sample_rate=sample_rate,
                        chunk_samples=chunk_samples,
                    )
                    if opener is None or self._interrupt.is_set():
                        return

                    opener_id, opener_text, opener_pcm, cache_hit, padded = opener
                    spoken_prefix = opener_text
                    await publish_event(
                        self.redis,
                        self.session_id,
                        "subtitle.chunk",
                        {
                            "session_id": self.session_id,
                            "text": opener_text,
                            "is_final": False,
                        },
                    )
                    produced = await _append_pcm(
                        _fade_head_i16(opener_pcm, sample_rate, boundary_fade_ms)
                    )
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

                    await publish_event(
                        self.redis, self.session_id,
                        "subtitle.chunk",
                        {"session_id": self.session_id, "text": tts_text, "is_final": False},
                    )
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
                    async for tts_chunk in tts.synthesize_stream(
                        tts_text,
                        voice=self._tts_runtime_voice(),
                    ):
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
                            chunks_produced += await _append_pcm(emit)
                        else:
                            chunks_produced += await _append_pcm(pcm)

                    if not seen_audio:
                        return

                    if held_tail.size > 0 and not self._interrupt.is_set():
                        held_tail = _fade_tail_i16(held_tail, sample_rate, boundary_fade_ms)
                        chunks_produced += await _append_pcm(held_tail)

                    t1 = _t.monotonic()
                    log.info(
                        "TTS '%s': first_pcm=%.0fms total=%.2fs, %d chunks, buf=%d",
                        sentence[:20],
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
                    while True:
                        sentence = await sentence_q.get()
                        if sentence is None or self._interrupt.is_set():
                            break
                        await _tts_sentence(sentence)

                async def _llm_feeder():
                    """Stream LLM deltas, split into sentences, push to sentence_q."""
                    nonlocal full_response, text_buffer
                    try:
                        log.info("LLM streaming started for: %s", text[:50])
                        async for delta in self.llm.chat_stream(self.conversation.get_messages()):
                            if self._interrupt.is_set():
                                break
                            full_response += strip_emoji(delta)
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

                        log.info("LLM feeder done, full_response=%r", full_response[:100])
                    except Exception:
                        log.exception("LLM feeder failed")
                        if not self._interrupt.is_set() and not full_response:
                            fallback_text = "抱歉，我暂时无法连接语言服务。请稍后再试。"
                            full_response = fallback_text
                            text_buffer = ""
                            await _queue_sentence_for_tts(fallback_text, force=True)
                    finally:
                        await sentence_q.put(None)  # signal TTS worker to stop

                try:
                    await _emit_cached_opener()
                    # Run LLM feeder and TTS worker concurrently within
                    # the producer; the TTS worker processes sentences as
                    # fast as Edge TTS can generate audio while the LLM
                    # feeder keeps streaming deltas into sentence_q.
                    await asyncio.gather(_llm_feeder(), _tts_worker())

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
                                await audio_q.put(chunk)

                    log.info("Producer done, full_response=%r", full_response[:100])
                except Exception:
                    log.exception("Producer failed")
                finally:
                    await audio_q.put(None)  # signal done

            async def _consumer():
                """Dequeue audio chunks → FlashTalk generate → WebRTC.

                Pre-buffers chunks before starting the pacing clock so WebRTC
                does not consume the first frames/audio without timing.
                """
                generated = 0
                pending: list[tuple[np.ndarray, list[Any]]] = []

                while True:
                    chunk = await audio_q.get()
                    if chunk is None or self._interrupt.is_set():
                        break
                    frames = await self._generate_flashtalk_frames(chunk)
                    generated += 1

                    if generated <= prebuffer_chunks:
                        pending.append((chunk, frames))
                        if generated < prebuffer_chunks:
                            continue

                        log.info("Pre-buffer done (%d chunks), starting pacing", generated)
                        if self.webrtc:
                            self.webrtc.clear_media_queues()
                            self.webrtc.reset_clocks()
                            self._media_clock_started = True
                            self._speech_media_active = True
                        for pcm_chunk, buffered_frames in pending:
                            await self._queue_av_chunk(pcm_chunk, buffered_frames)
                        pending.clear()
                        continue

                    await self._queue_av_chunk(chunk, frames)

                if pending and not self._interrupt.is_set():
                    log.info("Flushing short pre-buffer (%d chunks), starting pacing", len(pending))
                    if self.webrtc:
                        self.webrtc.clear_media_queues()
                        self.webrtc.reset_clocks()
                        self._media_clock_started = True
                        self._speech_media_active = True
                    for pcm_chunk, buffered_frames in pending:
                        await self._queue_av_chunk(pcm_chunk, buffered_frames)

                log.info("Consumer done")

            try:
                # Run producer and consumer concurrently
                await asyncio.gather(_producer(), _consumer())
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

            await self._await_audio_playout()
            stored_response = _merge_spoken_reply(spoken_prefix, full_response)
            if stored_response:
                self.conversation.add_assistant(stored_response)
                self._has_completed_speech = True

            await self._publish_speech_ended()
            if not self._closed:
                await set_session_state(self.redis, self.session_id, "ready")

    async def _video_put_safe(self, frame) -> None:
        """Put a video frame, dropping oldest if queue is full (no WebRTC peer yet)."""
        if not self.webrtc:
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
        """Put audio samples in small chunks for smooth WebRTC playback."""
        if not self.webrtc:
            return
        arr = np.asarray(pcm, dtype=np.int16)
        # Split into ~20ms chunks (320 samples at 16kHz) for smooth playback
        chunk_size = 320
        for i in range(0, len(arr), chunk_size):
            part = arr[i:i + chunk_size]
            if len(part) == 0:
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
            frames = await self.flashtalk.generate(pcm_chunk)
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

    async def _queue_av_chunk(self, pcm_chunk: np.ndarray, frames: list[Any]) -> None:
        """Queue generated video frames interleaved with matching audio.

        Each video frame is paired with a proportional slice of the audio
        chunk so that the video and audio queues advance at the same pace.
        This prevents lip movement from running ahead of the audio.
        """
        n_frames = len(frames)
        if n_frames == 0:
            await self._audio_put_safe(pcm_chunk)
            return

        arr = np.asarray(pcm_chunk, dtype=np.int16)
        total_samples = len(arr)

        for i, frame in enumerate(frames):
            if self._interrupt.is_set():
                break
            await self._video_put_safe(frame)
            # Pair each frame with its proportional audio slice
            audio_start = i * total_samples // n_frames
            audio_end = (i + 1) * total_samples // n_frames
            audio_slice = arr[audio_start:audio_end]
            if len(audio_slice) > 0:
                await self._audio_put_safe(audio_slice)

        # Cache last frame for idle loop
        if frames:
            self._last_frame = frames[-1].data

    async def interrupt(self) -> None:
        self._interrupt.set()
        tasks = [task for task in self.speech_tasks if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=2.0)
            except asyncio.TimeoutError:
                pass
        self._speaking = False
        self._speech_media_active = False
        await self._publish_speech_ended()
        if not self._closed:
            await set_session_state(self.redis, self.session_id, "ready")

    async def _reset_session_before_turn(self) -> None:
        ref_image_path = self._reference_image_path
        if ref_image_path is None:
            avatar_dir = self.avatar_path()
            for name in ("reference.png", "reference.jpg", "reference.jpeg"):
                candidate = avatar_dir / name
                if candidate.is_file():
                    ref_image_path = candidate.resolve()
                    break
        if ref_image_path is None:
            raise FileNotFoundError(
                f"No reference image found for avatar {self.avatar_id} before speech reset"
            )

        log.info(
            "Resetting FlashTalk backend session before speech: session=%s avatar=%s",
            self.session_id,
            self.avatar_id,
        )
        await self._reset_flashtalk_session(ref_image_path)
        self._idle_frame_idx = 0
        if self._reference_frame is not None:
            self._last_frame = self._reference_frame.copy()
        self._media_clock_started = False
        self._speech_media_active = False

    async def _await_audio_playout(self) -> None:
        if self.webrtc is None:
            return

        audio_queue = getattr(self.webrtc.audio, "_queue", None)
        if not isinstance(audio_queue, asyncio.Queue):
            return

        poll_interval_s = max(
            0.01,
            _env_float("FLASHTALK_AUDIO_DRAIN_POLL_MS", 20.0) / 1000.0,
        )
        timeout_s = max(
            0.5,
            _env_float("FLASHTALK_AUDIO_DRAIN_TIMEOUT_S", 8.0),
        )
        grace_s = max(
            0.0,
            _env_float("FLASHTALK_AUDIO_DRAIN_GRACE_MS", 120.0) / 1000.0,
        )

        drained = await _wait_for_queue_empty(
            audio_queue,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
            interrupted=self._interrupt,
        )
        if drained and grace_s > 0.0 and not self._interrupt.is_set():
            await asyncio.sleep(grace_s)
            log.info(
                "FlashTalk audio drain complete: session=%s grace=%.0fms",
                self.session_id,
                grace_s * 1000.0,
            )
            return

        if not drained:
            log.warning(
                "FlashTalk audio drain timed out: session=%s pending=%d timeout=%.2fs",
                self.session_id,
                audio_queue.qsize(),
                timeout_s,
            )

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
