"""IdleVideoGenerator — builds a looping idle video clip for an avatar
using the FlashTalk WebSocket inference server (remote mode compatible).
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

_IDLE_GEN_VERSION = 3  # bump when cache key semantics change

# Keep in sync with FlashTalkWSClient.init_session default when env is unset.
_DEFAULT_INIT_PROMPT = (
    "A person is talking. Only the foreground characters are moving, "
    "the background remains static."
)


def _env_first(*keys: str) -> str | None:
    for k in keys:
        v = os.environ.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return None


def _settings_idle_prompt() -> str | None:
    """Prompt from pydantic Settings (.env); not mirrored to os.environ."""
    try:
        from opentalking.core.config import get_settings
        p = get_settings().flashtalk_idle_prompt
        if p is not None and str(p).strip():
            return str(p).strip()
    except Exception as exc:
        log.warning("Could not read flashtalk_idle_prompt from settings: %s", exc)
    return None


def _settings_idle_seed() -> int | None:
    try:
        from opentalking.core.config import get_settings
        return int(get_settings().flashtalk_idle_seed)
    except Exception:
        return None


def _resolve_idle_init_prompt(explicit: str | None) -> str:
    if explicit is not None and explicit.strip():
        return explicit.strip()
    s = _settings_idle_prompt()
    if s:
        return s
    return _env_first(
        "OPENTALKING_FLASHTALK_IDLE_PROMPT",
        "FLASHTALK_IDLE_PROMPT",
    ) or _DEFAULT_INIT_PROMPT


def _resolve_idle_init_seed(explicit: int | None) -> int:
    if explicit is not None:
        return int(explicit)
    s = _settings_idle_seed()
    if s is not None:
        return s
    raw = _env_first("OPENTALKING_FLASHTALK_IDLE_SEED", "FLASHTALK_IDLE_SEED")
    if raw is None:
        return 9999
    try:
        return int(raw)
    except ValueError:
        log.warning("Invalid FLASHTALK_IDLE_SEED=%r, using 9999", raw)
        return 9999


def _prompt_fingerprint(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def _build_driver_pcm(total_samples: int, level: float = 480.0) -> np.ndarray:
    """Low-energy periodic audio driver so the idle clip loops cleanly."""
    if total_samples <= 0:
        return np.zeros(0, dtype=np.int16)
    phase = np.linspace(0.0, 2.0 * np.pi, total_samples, endpoint=False, dtype=np.float32)
    envelope = 0.35 + 0.65 * (0.5 - 0.5 * np.cos(phase))
    harmonic = (
        0.58 * np.sin(phase)
        + 0.27 * np.sin(2.0 * phase + 0.65)
        + 0.15 * np.sin(3.0 * phase + 1.35)
    )
    signal = envelope * (harmonic + 0.08 * np.sin(5.0 * phase + 0.2))
    peak = float(np.max(np.abs(signal))) if signal.size else 1e-6
    peak = max(peak, 1e-6)
    return np.clip(signal / peak * level, -32767.0, 32767.0).astype(np.int16)


def _blend_frames(a: np.ndarray, b: np.ndarray, alpha: float) -> np.ndarray:
    out = np.asarray(a, dtype=np.float32) * (1.0 - alpha)
    out += np.asarray(b, dtype=np.float32) * alpha
    return np.clip(out, 0.0, 255.0).astype(np.uint8)


def _optimize_loop(frames: list[np.ndarray], crossfade: int = 6) -> list[np.ndarray]:
    """Trim to the smoothest loop segment and crossfade the boundary."""
    if len(frames) < 12:
        return [np.ascontiguousarray(f) for f in frames]

    def _sig(f: np.ndarray) -> np.ndarray:
        g = f[:, :, 0] * 0.114 + f[:, :, 1] * 0.587 + f[:, :, 2] * 0.299
        h, w = g.shape
        return g[::max(1, h // 24), ::max(1, w // 24)][:24, :24].astype(np.float32)

    sigs = [_sig(f) for f in frames]
    n = len(sigs)
    span = max(3, min(8, crossfade))
    min_len = max(span * 3, n // 2)
    best_score: float | None = None
    best_s, best_e = 0, n - 1

    for s in range(max(1, n // 3)):
        for e in range(s + min_len - 1, n):
            score = sum(
                float(np.mean(np.abs(sigs[s + k] - sigs[e - span + 1 + k])))
                for k in range(span)
            )
            if best_score is None or score < best_score:
                best_score, best_s, best_e = score, s, e

    seg = [np.ascontiguousarray(f) for f in frames[best_s:best_e + 1]]
    ov = max(2, min(crossfade, len(seg) // 4))
    if len(seg) <= ov + 2:
        return seg

    out = list(seg[:-ov])
    for i in range(ov):
        out.append(_blend_frames(seg[-ov + i], seg[i], (i + 1) / (ov + 1)))
    out.append(seg[0])
    return out


def _stabilize_mouth(
    frames: list[np.ndarray],
    reference_frame: np.ndarray | None,
    *,
    strength: float = 0.97,
    temporal_strength: float = 0.85,
) -> list[np.ndarray]:
    """Blend the mouth/lower-face region back toward the reference frame.

    Suppresses the open-mouth and jaw-jitter artifacts that appear when
    FlashTalk is driven by low-energy synthetic audio.
    """
    if not frames or reference_frame is None or strength <= 0.0:
        return [np.ascontiguousarray(f) for f in frames]

    h, w = frames[0].shape[:2]
    ref = np.asarray(reference_frame, dtype=np.float32)
    if ref.shape[:2] != (h, w):
        try:
            import cv2
            ref = cv2.resize(ref, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32)
        except Exception:
            yi = np.linspace(0, ref.shape[0] - 1, h).astype(np.int32)
            xi = np.linspace(0, ref.shape[1] - 1, w).astype(np.int32)
            ref = ref[yi][:, xi].astype(np.float32)

    # Soft ellipse covering mouth + chin (lower 35% of face, centred horizontally)
    cy = h * 0.78
    cx = w * 0.50
    ry = h * 0.18
    rx = w * 0.30
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dist = np.sqrt(((xx - cx) / max(rx, 1.0)) ** 2 + ((yy - cy) / max(ry, 1.0)) ** 2)
    feather = 0.35
    outer = 1.0 + feather
    mask = np.clip((outer - dist) / max(outer - 1.0, 1e-6), 0.0, 1.0)
    mask3 = mask[:, :, np.newaxis] * strength

    stabilized: list[np.ndarray] = []
    prev: np.ndarray | None = None
    for frame in frames:
        cur = np.asarray(frame, dtype=np.float32)
        blended = cur * (1.0 - mask3) + ref * mask3
        if prev is not None and temporal_strength > 0.0:
            blended = blended * (1.0 - mask3 * temporal_strength) + prev * (mask3 * temporal_strength)
        prev = blended
        stabilized.append(np.clip(blended, 0.0, 255.0).astype(np.uint8))
    return stabilized


class IdleVideoGenerator:
    """Generates and caches a looping idle video clip for one avatar.

    Opens its own FlashTalk WS connection so it never evicts the live session.
    """

    def __init__(
        self,
        *,
        ws_url: str,
        avatar_id: str,
        ref_image_path: Path,
        cache_dir: Path,
        chunks: int = 4,
        level: float = 80.0,
        crossfade: int = 6,
        init_prompt: str | None = None,
        init_seed: int | None = None,
        mouth_lock: float = 0.97,
        mouth_temporal: float = 0.85,
        reference_frame: np.ndarray | None = None,
    ) -> None:
        self._ws_url = ws_url
        self._avatar_id = avatar_id
        self._ref_image_path = ref_image_path
        self._cache_dir = cache_dir
        self._chunks = chunks
        self._level = level
        self._crossfade = crossfade
        self._init_prompt = _resolve_idle_init_prompt(init_prompt)
        self._init_seed = _resolve_idle_init_seed(init_seed)
        self._mouth_lock = max(0.0, min(1.0, mouth_lock))
        self._mouth_temporal = max(0.0, min(1.0, mouth_temporal))
        self._reference_frame = reference_frame

    def _cache_key(self, width: int, height: int, fps: int, chunk_samples: int) -> str:
        stat = self._ref_image_path.stat()
        prompt_fp = hashlib.sha256(self._init_prompt.encode("utf-8")).hexdigest()[:16]
        payload = "|".join([
            str(_IDLE_GEN_VERSION),
            str(stat.st_mtime_ns),
            str(stat.st_size),
            str(width), str(height), str(fps), str(chunk_samples),
            str(self._chunks), str(self._crossfade),
            prompt_fp,
            str(self._init_seed),
        ])
        return hashlib.sha256(payload.encode()).hexdigest()[:32]

    def _cache_path(self, key: str) -> Path:
        return self._cache_dir / f"idle_{self._avatar_id}_{key}.npz"

    def load_from_disk(self, key: str) -> list[np.ndarray] | None:
        p = self._cache_path(key)
        if not p.exists():
            return None
        try:
            with np.load(p, allow_pickle=False) as d:
                frames = np.asarray(d["frames"], dtype=np.uint8)
            if frames.ndim != 4 or frames.shape[0] == 0:
                return None
            log.info("Loaded idle cache: avatar=%s frames=%d", self._avatar_id, len(frames))
            return [np.ascontiguousarray(f) for f in frames]
        except Exception:
            log.exception("Failed to load idle cache %s", p)
            p.unlink(missing_ok=True)
            return None

    def save_to_disk(self, key: str, frames: list[np.ndarray]) -> None:
        if not frames:
            return
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        p = self._cache_path(key)
        tmp = p.with_suffix(".tmp.npz")
        arr = np.stack(frames, axis=0).astype(np.uint8, copy=False)
        np.savez_compressed(tmp, frames=arr)
        os.replace(tmp, p)
        log.info("Saved idle cache: avatar=%s frames=%d path=%s", self._avatar_id, len(frames), p)

    async def generate(self) -> list[np.ndarray]:
        """Connect to FlashTalk WS, generate idle frames, return optimized loop."""
        from opentalking.models.flashtalk.ws_client import FlashTalkWSClient
        client = FlashTalkWSClient(self._ws_url)
        try:
            await client.connect()
            fp = _prompt_fingerprint(self._init_prompt)
            log.info(
                "Idle init_session: avatar=%s seed=%d prompt_len=%d prompt_fp=%s preview=%r",
                self._avatar_id,
                self._init_seed,
                len(self._init_prompt),
                fp,
                self._init_prompt[:160] + ("…" if len(self._init_prompt) > 160 else ""),
            )
            await client.init_session(
                ref_image=self._ref_image_path,
                prompt=self._init_prompt,
                seed=self._init_seed,
            )
            chunk_samples = int(client.audio_chunk_samples)
            if chunk_samples <= 0:
                return []

            driver = _build_driver_pcm(chunk_samples * self._chunks, self._level)
            frames: list[np.ndarray] = []
            for i in range(self._chunks):
                chunk = driver[i * chunk_samples:(i + 1) * chunk_samples]
                result = await client.generate(chunk)
                frames.extend(np.ascontiguousarray(f.data) for f in result)

            frames = _optimize_loop(frames, self._crossfade)
            frames = _stabilize_mouth(
                frames,
                self._reference_frame,
                strength=self._mouth_lock,
                temporal_strength=self._mouth_temporal,
            )
            log.info(
                "Idle generated: avatar=%s frames=%d level=%.0f mouth_lock=%.2f",
                self._avatar_id, len(frames), self._level, self._mouth_lock,
            )
            return frames
        finally:
            await client.close(send_close_msg=False)

    async def get_or_build(
        self,
        width: int,
        height: int,
        fps: int,
        chunk_samples: int,
    ) -> list[np.ndarray]:
        """Return cached frames if valid, otherwise generate and cache."""
        key = self._cache_key(width, height, fps, chunk_samples)
        cached = self.load_from_disk(key)
        fp = _prompt_fingerprint(self._init_prompt)
        if cached:
            log.info(
                "Idle cache hit (disk): avatar=%s frames=%d cache_key=%s prompt_fp=%s seed=%d prompt_len=%d",
                self._avatar_id,
                len(cached),
                key[:16],
                fp,
                self._init_seed,
                len(self._init_prompt),
            )
            return cached
        log.info(
            "Building idle cache: avatar=%s cache_key=%s prompt_fp=%s seed=%d prompt_len=%d",
            self._avatar_id,
            key[:16],
            fp,
            self._init_seed,
            len(self._init_prompt),
        )
        frames = await self.generate()
        if frames:
            self.save_to_disk(key, frames)
        return frames
