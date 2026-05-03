"""
FlashTalkSessionRunner – drives the full conversation pipeline:

    user text → LLM → TTS (Edge 或 OPENTALKING_TTS_PROVIDER) → FlashTalk backend → WebRTC
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import numpy as np

from opentalking.core.config import get_settings
from opentalking.models.flashtalk.idle_generator import IdleVideoGenerator
from opentalking.core.session_store import set_session_state
from opentalking.llm.openai_compatible import OpenAICompatibleLLMClient
from opentalking.llm.sentence_splitter import SentenceSplitter
from opentalking.llm.conversation import ConversationHistory
from opentalking.models.flashtalk.ws_client import FlashTalkWSClient
from opentalking.rtc.aiortc_adapter import WebRTCSession
from opentalking.tts.factory import create_tts_adapter, tts_log_profile
from opentalking.worker.bus import publish_event
from opentalking.worker.text_sanitize import sanitize_tts_text, strip_emoji

log = logging.getLogger(__name__)

_IDLE_CACHE_VERSION = 6
_IDLE_FRAME_CACHE: dict[str, list[np.ndarray]] = {}
_IDLE_CACHE_LOCKS: dict[str, asyncio.Lock] = {}
_TTS_OPENER_PCM_CACHE: dict[str, np.ndarray] = {}
_TTS_OPENER_CACHE_LOCKS: dict[str, asyncio.Lock] = {}
_TTS_OPENER_PRELOAD_TASK: asyncio.Task[None] | None = None
_SENTINEL = object()  # unique marker for "not yet set"

# Opener rules — improvement backlog (not implemented here):
# - Taxonomy: only greeting/task/explain/confirm; no thanks/apology/small-talk,
#   English, typos, or multi-intent utterances.
# - Keywords: hard-coded substrings; no segmentation, negation, or weighting.
# - Text: fixed short lines; not per-avatar / locale / brand / configurable via env.
# - Selection: keyword first match + PCM length + recent-id rotation; no LLM-based
#   intent, confidence, or A/B testing.
# - Timing: opener is fully enqueued before LLM+TTS runs; if FlashTalk drains opener
#   faster than the first LLM sentence is synthesized, the audio queue can go dry
#   briefly (heard as pause/stutter) — see speak() pipeline ordering.
# - Coherence with reply: mitigated by system nudge + lead trim, still model-dependent.
_TTS_OPENER_RULES: tuple[tuple[str, tuple[str, ...], tuple[tuple[str, str], ...]], ...] = (
    (
        "greeting",
        ("你好", "您好", "哈喽", "嗨", "在吗", "早安", "晚安", "喂"),
        (
            ("greeting_1", "我在，请讲。"),
            ("greeting_2", "听到啦，你说。"),
            ("greeting_3", "随时在。"),
        ),
    ),
    (
        "task",
        ("帮我", "处理", "看下", "看看", "怎么弄", "怎么办", "查一下", "帮忙", "执行", "设置", "找一下"),
        (
            ("task_1", "好的，我来看看。"),
            ("task_2", "明白，马上处理。"),
            ("task_3", "收到，这就去办。"),
        ),
    ),
    (
        "explain",
        ("为什么", "怎么", "是什么", "原理", "区别", "原因", "介绍", "详细", "意思"),
        (
            ("explain_1", "这个我来解释。"),
            ("explain_2", "好，我给你说明。"),
            ("explain_3", "马上为你解答。"),
        ),
    ),
    (
        "confirm",
        ("能不能", "可以吗", "是否", "有没有", "行不行", "对不对", "对吗", "真的"),
        (
            ("confirm_1", "可以，我告诉你。"),
            ("confirm_2", "这个我来确认。"),
            ("confirm_3", "稍等，我核实下。"),
        ),
    ),
    (
        "create",
        ("写一个", "写一篇", "生成", "画", "起名", "设计", "草拟", "大纲"),
        (
            ("create_1", "好的，这就生成。"),
            ("create_2", "收到，我来构思。"),
        ),
    ),
    (
        "calculate",
        ("算一下", "多少", "统计", "计算", "汇总"),
        (
            ("calc_1", "我来算一下。"),
            ("calc_2", "好，这就看数据。"),
        ),
    ),
    (
        "opinion",
        ("觉得", "看法", "建议", "推荐", "评价", "哪个好"),
        (
            ("opinion_1", "我的看法是这样。"),
            ("opinion_2", "好，给你几个建议。"),
        ),
    ),
    (
        "identity",
        ("你叫什么名字", "你的名字", "你是谁", "怎么称呼", "你叫啥"),
        (
            ("identity_1", "嗯，很高兴认识你。"),
        ),
    ),
)

_TTS_OPENER_FALLBACKS: tuple[tuple[str, str], ...] = (
    ("fallback_1", "明白，马上处理。"),
    ("fallback_2", "好的，我来看看。"),
    ("fallback_3", "马上为你解答。"),
    ("fallback_4", "收到，请稍等。"),
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


def _idle_cache_dir() -> Path:
    s = get_settings()
    if s.flashtalk_idle_cache_dir:
        return Path(s.flashtalk_idle_cache_dir)
    return Path(s.models_dir) / ".idle_cache"


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


def _trim_trailing_silence_i16(
    pcm: np.ndarray,
    sample_rate: int,
    *,
    threshold: int = 300,
    min_tail_ms: float = 60.0,
) -> np.ndarray:
    """Remove trailing near-silence from PCM, keeping at least *min_tail_ms* ms."""
    if pcm.size == 0:
        return pcm
    min_keep = max(1, int(sample_rate * min_tail_ms / 1000.0))
    abs_pcm = np.abs(pcm)
    indices = np.nonzero(abs_pcm > threshold)[0]
    if indices.size == 0:
        return pcm[:min_keep]
    last_loud = int(indices[-1])
    end = max(last_loud + 1 + min_keep, min_keep)
    return pcm[: min(end, pcm.size)]


def _strip_redundant_greeting_lead(text: str) -> str:
    """Remove one leading greeting clause (after TTS opener already greeted the user)."""
    t = text.strip()
    if not t:
        return t
    for pat in (
        r"^你好啊[，,\s]*",
        r"^你好[，,\s]*",
        r"^您好[，,\s]*",
        r"^哈喽[，,\s]*",
        r"^嗨[，,\s]*",
    ):
        nt = re.sub(pat, "", t, count=1)
        if nt != t:
            return nt.strip()
    return t


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


async def _preload_tts_openers(sample_rate: int) -> None:
    for _, opener_text in _iter_tts_opener_variants():
        try:
            await _synthesize_tts_opener_pcm(opener_text, sample_rate=sample_rate)
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
    ) -> None:
        self.session_id = session_id
        self.avatar_id = avatar_id
        self.avatars_root = avatars_root
        self.redis = redis
        self._flashtalk_ws_url = flashtalk_ws_url or _default_flashtalk_ws_url()
        self._custom_ref_image_path = custom_ref_image_path.strip()

        self.flashtalk = flashtalk_client or FlashTalkWSClient(
            self._flashtalk_ws_url
        )
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
        self._speech_media_active = False
        self._av_ts_ms = 0.0
        #: Background dynamic idle cache (closes main WS briefly); speak() must await this.
        self._dynamic_idle_prepare_task: asyncio.Task[None] | None = None

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
        await self.flashtalk.init_session(ref_image=ref_image_path)

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

        # Start idle loop after init; it replays local cached frames when WebRTC is live.
        if self._idle_task is None:
            self._idle_task = asyncio.create_task(self._idle_loop())

        self.ready_event.set()
        log.info("FlashTalkRunner prepared: session=%s, avatar=%s", self.session_id, self.avatar_id)

        # Build idle cache in background for all modes (local and remote).
        # IdleVideoGenerator opens its own WS connection so it never evicts
        # the live session.
        if get_settings().flashtalk_idle_enable:
            self._dynamic_idle_prepare_task = asyncio.create_task(
                self._prepare_dynamic_idle_cache(ref_image_path)
            )
        elif self._allow_background_idle_cache:
            asyncio.create_task(self._prepare_idle_cache_background(ref_image_path))

        global _TTS_OPENER_PRELOAD_TASK
        s = get_settings()
        if s.flashtalk_tts_opener_enable and s.flashtalk_tts_opener_preload:
            task = _TTS_OPENER_PRELOAD_TASK
            if task is None or task.done():
                _TTS_OPENER_PRELOAD_TASK = asyncio.create_task(
                    _preload_tts_openers(sample_rate=16000)
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
            )

            # Try disk cache first — no need to touch the main WS connection.
            w = self.flashtalk.width
            h = self.flashtalk.height
            fps = self.flashtalk.fps
            cs = self.flashtalk.audio_chunk_samples
            key = gen._cache_key(w, h, fps, cs)
            cached = gen.load_from_disk(key)
            if cached:
                from opentalking.models.flashtalk.idle_generator import _prompt_fingerprint
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
            # Close the main session first so the server (single-session
            # architecture) doesn't deadlock on a concurrent HCCL broadcast.
            await self.flashtalk.close()
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

    async def _select_tts_opener(
        self,
        user_text: str,
        *,
        sample_rate: int,
        chunk_samples: int,
        default_voice: str | None = None,
    ) -> tuple[str, str, np.ndarray, bool, bool] | None:
        s = get_settings()
        if not s.flashtalk_tts_opener_enable:
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
        return {"sdp": ans.sdp, "type": ans.type}

    def _ensure_media_clock_started(self) -> None:
        if self.webrtc is None or self._media_clock_started:
            return
        self.webrtc.reset_clocks()
        self._media_clock_started = True

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
            prebuffer_chunks = max(1, _env_int("FLASHTALK_PREBUFFER_CHUNKS", 1))
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

            producer_error: list[BaseException] = []

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
                except Exception as exc:
                    producer_error.append(exc)
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

                    log.info("Pre-buffer done (%d chunks), starting pacing", generated)
                    _start_pacing()
                    for pc, bf, st in pending:
                        if st:
                            await _publish_subtitle_chunk(st)
                        await self._queue_av_chunk(pc, bf)
                    pending.clear()

                if pending and not self._interrupt.is_set():
                    log.info("Flushing short pre-buffer (%d chunks), starting pacing", len(pending))
                    _start_pacing()
                    for pc, buffered_frames, st in pending:
                        if st:
                            await _publish_subtitle_chunk(st)
                        await self._queue_av_chunk(pc, buffered_frames)

                timing["flashtalk_generate_sum_ms"] = flashtalk_gen_sum_s * 1000.0
                timing["flashtalk_chunks"] = float(flashtalk_chunks)
                timing["consumer_wall_ms"] = (time.perf_counter() - t_consumer0) * 1000.0
                log.info("Consumer done")

                if producer_error and flashtalk_chunks == 0:
                    raise producer_error[0]

            try:
                # Run producer and consumer concurrently
                t_parallel0 = time.perf_counter()
                await asyncio.gather(_producer(), _consumer())
                timing["parallel_total_ms"] = (time.perf_counter() - t_parallel0) * 1000.0
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
            prebuffer_chunks = max(1, _env_int("FLASHTALK_PREBUFFER_CHUNKS", 1))
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

                    log.info("Pre-buffer done (%d chunks), starting pacing", generated)
                    _start_pacing()
                    for pc, bf, st in pending:
                        if st:
                            await _publish_subtitle_chunk(st)
                        await self._queue_av_chunk(pc, bf)
                    pending.clear()

                if pending and not self._interrupt.is_set():
                    log.info("Flushing short pre-buffer (%d chunks), starting pacing", len(pending))
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

        n_frames = len(frames)
        if n_frames == 0:
            await self._audio_put_safe(pcm_chunk)
            return

        arr = np.asarray(pcm_chunk, dtype=np.int16)
        total_samples = len(arr)
        sample_rate = max(1, int(getattr(self.flashtalk, "sample_rate", 16000) or 16000))
        fallback_frame_ms = 1000.0 / max(1.0, float(getattr(self.flashtalk, "fps", 25) or 25))

        for i, frame in enumerate(frames):
            if self._interrupt.is_set():
                break
            # Pair each frame with its proportional audio slice.
            # Use _audio_put_safe (20ms sub-chunks) for clean opus encoding,
            # but feed them right after the matching video frame so A/V stay
            # in lockstep within the queue.
            audio_start = i * total_samples // n_frames
            audio_end = (i + 1) * total_samples // n_frames
            audio_slice = arr[audio_start:audio_end]
            frame.timestamp_ms = self._av_ts_ms
            await self._video_put_safe(frame)
            if len(audio_slice) > 0:
                await self._audio_put_safe(audio_slice)
                self._av_ts_ms += (len(audio_slice) * 1000.0) / sample_rate
            else:
                self._av_ts_ms += fallback_frame_ms

        # Cache last frame for idle loop
        if frames:
            self._last_frame = frames[-1].data

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
