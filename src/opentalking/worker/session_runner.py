from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from functools import partial
import json
import logging
import os
from pathlib import Path
import subprocess
import time as _time
from typing import Any
import wave

import cv2
import numpy as np
from av import AudioFrame
from av.audio.resampler import AudioResampler

from opentalking.core.session_store import set_session_state
from opentalking.core.config import Settings, get_settings
from opentalking.core.types.frames import AudioChunk, VideoFrameData
from opentalking.llm.conversation import ConversationHistory
from opentalking.llm.openai_compatible import OpenAICompatibleLLMClient
from opentalking.llm.sentence_splitter import SentenceSplitter
from opentalking.models.registry import get_adapter
from opentalking.rtc.aiortc_adapter import WebRTCSession
from opentalking.tts import build_tts_adapter
try:
    from opentalking.models.wav2lip.official_runtime import (
        load_video_frames,
        official_runtime_available,
        run_official_inference,
    )
except Exception:
    # official wav2lip runtime is optional; keep unified startup resilient
    # when the module is absent in lightweight or customized deployments.
    def official_runtime_available() -> bool:
        return False

    def run_official_inference(
        *,
        avatar_path: Path,
        face_image: Path | None = None,
        pcm: np.ndarray,
        sample_rate: int,
        fps: int,
        ffmpeg_bin: str,
        checkpoint_path: Path | None = None,
        pads: tuple[int, int, int, int] = (0, 10, 0, 0),
        box: tuple[int, int, int, int] | None = None,
        resize_factor: int = 1,
        face_det_batch_size: int = 8,
        wav2lip_batch_size: int = 64,
        nosmooth: bool = False,
    ) -> tuple[Path, Path, Path]:
        raise RuntimeError("wav2lip official runtime is unavailable")

    def load_video_frames(video_path: Path) -> list[np.ndarray]:
        raise RuntimeError("wav2lip official runtime is unavailable")
from opentalking.worker.bus import publish_event
from opentalking.worker.pipeline.render_pipeline import (
    iter_rendered_frames_sync,
    render_audio_chunk_sync,
    reset_avatar_speech_state,
)
from opentalking.worker.text_sanitize import sanitize_tts_text, strip_emoji
from opentalking.worker.timing import SpeechTiming

log = logging.getLogger(__name__)
_SETTINGS = get_settings()


def _next_iter_item(iterator: Any) -> tuple[bool, Any]:
    try:
        return True, next(iterator)
    except StopIteration:
        return False, None


@dataclass(frozen=True)
class _SpeechChunkEnvelope:
    idx: int
    chunk: AudioChunk
    lookahead_chunk: AudioChunk | None = None
    is_final: bool = False


@dataclass(frozen=True)
class _IdleFrameCacheEntry:
    data: np.ndarray
    width: int
    height: int


class _StreamingPCMResampler:
    def __init__(self) -> None:
        self._src_rate: int | None = None
        self._dst_rate: int | None = None
        self._resampler: AudioResampler | None = None

    def convert(
        self,
        samples: np.ndarray,
        *,
        src_rate: int,
        dst_rate: int,
    ) -> np.ndarray:
        arr = np.asarray(samples, dtype=np.int16).reshape(-1)
        if arr.size == 0 or src_rate == dst_rate:
            return arr
        if (
            self._resampler is None
            or self._src_rate != int(src_rate)
            or self._dst_rate != int(dst_rate)
        ):
            self._src_rate = int(src_rate)
            self._dst_rate = int(dst_rate)
            self._resampler = AudioResampler(format="s16", layout="mono", rate=self._dst_rate)

        frame = AudioFrame(format="s16", layout="mono", samples=arr.shape[0])
        frame.planes[0].update(arr.astype("<i2", copy=False).tobytes())
        frame.sample_rate = self._src_rate

        out_parts: list[np.ndarray] = []
        for out_frame in self._resampler.resample(frame):
            out_parts.append(out_frame.to_ndarray().reshape(-1).astype(np.int16, copy=False))
        if not out_parts:
            return np.zeros(0, dtype=np.int16)
        return np.concatenate(out_parts).astype(np.int16, copy=False)


class _SpeechDebugCapture:
    def __init__(
        self,
        *,
        enabled: bool,
        root_dir: Path | None,
        session_id: str,
        avatar_id: str,
        model_type: str,
        fps: int,
        sample_rate: int,
        ffmpeg_bin: str,
        text: str,
    ) -> None:
        self.enabled = enabled and root_dir is not None
        self.root_dir = root_dir
        self.session_id = session_id
        self.avatar_id = avatar_id
        self.model_type = model_type
        self.fps = fps
        self.sample_rate = sample_rate
        self.ffmpeg_bin = ffmpeg_bin
        self.text = text
        self._pcm_parts: list[np.ndarray] = []
        self._frames: list[np.ndarray] = []

    def add_audio_chunk(self, chunk: AudioChunk) -> None:
        if not self.enabled:
            return
        self._pcm_parts.append(np.asarray(chunk.data, dtype=np.int16).reshape(-1).copy())

    def add_frame(self, frame: VideoFrameData) -> None:
        if not self.enabled:
            return
        self._frames.append(np.asarray(frame.data, dtype=np.uint8).copy())

    def finalize(self) -> Path | None:
        if not self.enabled or self.root_dir is None:
            return None
        self.root_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        out_dir = self.root_dir / f"{self.model_type}-live-{stamp}-{self.session_id}"
        out_dir.mkdir(parents=True, exist_ok=True)

        wav_path = out_dir / "tts.wav"
        silent_path = out_dir / "rendered_silent.mp4"
        muxed_path = out_dir / "rendered_with_audio.mp4"
        meta_path = out_dir / "meta.json"

        pcm = (
            np.concatenate(self._pcm_parts).astype(np.int16, copy=False)
            if self._pcm_parts
            else np.zeros(0, dtype=np.int16)
        )
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm.tobytes())

        if self._frames:
            h, w = self._frames[0].shape[:2]
            video_writer_fourcc = getattr(cv2, "VideoWriter_fourcc")
            writer = cv2.VideoWriter(
                str(silent_path),
                video_writer_fourcc(*"mp4v"),
                float(self.fps),
                (w, h),
            )
            if not writer.isOpened():
                raise RuntimeError(f"Failed to open debug video writer for {silent_path}")
            try:
                for frame in self._frames:
                    writer.write(frame)
            finally:
                writer.release()
            subprocess.run(
                [
                    self.ffmpeg_bin,
                    "-y",
                    "-i",
                    str(silent_path),
                    "-i",
                    str(wav_path),
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-shortest",
                    str(muxed_path),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        meta = {
            "session_id": self.session_id,
            "avatar_id": self.avatar_id,
            "model_type": self.model_type,
            "text": self.text,
            "fps": self.fps,
            "sample_rate": self.sample_rate,
            "frames": len(self._frames),
            "audio_wav": str(wav_path),
            "silent_video": str(silent_path),
            "muxed_video": str(muxed_path),
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return out_dir


class SessionRunner:
    def __init__(
        self,
        *,
        session_id: str,
        avatar_id: str,
        model_type: str,
        avatars_root: Path,
        redis: Any,
        device: str = "cuda",
        tts_settings: Settings | None = None,
        llm_base_url: str = "",
        llm_api_key: str = "",
        llm_model: str = "qwen-turbo",
        llm_system_prompt: str = "",
    ) -> None:
        self.session_id = session_id
        self.avatar_id = avatar_id
        self.model_type = model_type
        self.avatars_root = avatars_root
        self.redis = redis
        self.device = device
        self._tts_settings = tts_settings or _SETTINGS
        self.adapter = get_adapter(model_type)
        self.avatar_state: Any = None
        self.webrtc: WebRTCSession | None = None
        self.ready_event = asyncio.Event()
        self.speech_tasks: set[asyncio.Task[None]] = set()
        self._llm_base_url = llm_base_url
        self._llm_api_key = llm_api_key
        self._llm_model = llm_model
        self._llm_system_prompt = llm_system_prompt or _SETTINGS.llm_system_prompt
        self._llm_client: Any = None
        self._conversation: Any = None
        self._frame_idx = 0
        self._speech_frame_idx = 0
        self._speak_lock = asyncio.Lock()
        self._interrupt = asyncio.Event()
        self._speech_video_ready = asyncio.Event()
        self._render_chunk_events: dict[int, asyncio.Event] = {}
        self._render_chunk_audio_events: dict[int, asyncio.Event] = {}
        self._speaking = False
        self._speech_started = False
        self._closed = False
        self._idle_task: asyncio.Task[None] | None = None
        self._rtc_sample_rate = int(os.environ.get("OPENTALKING_RTC_SAMPLE_RATE") or "0")
        self._render_chunk_ms = float(os.environ.get("OPENTALKING_RENDER_CHUNK_MS", "320.0"))
        self._audio_preroll_timeout_ms = float(
            os.environ.get("OPENTALKING_AV_SYNC_AUDIO_PREROLL_TIMEOUT_MS", "1200.0")
        )
        self._quicktalk_audio_delay_ms = self._read_quicktalk_float_env("AUDIO_DELAY_MS", 0.0)
        self._reset_frame_idx_on_speak = (
            os.environ.get("OPENTALKING_RESET_FRAME_IDX_ON_SPEAK", "1") != "0"
        )
        debug_dump_dir = os.environ.get("OPENTALKING_DEBUG_DUMP_SPEECH_DIR", "").strip()
        self._debug_dump_speech_dir = Path(debug_dump_dir).expanduser().resolve() if debug_dump_dir else None
        self._ffmpeg_bin = os.environ.get("OPENTALKING_FFMPEG_BIN", "ffmpeg")
        self._wav2lip_live_mode = os.environ.get("OPENTALKING_WAV2LIP_LIVE_MODE", "streaming").strip().lower()
        self._render_in_executor = os.environ.get("OPENTALKING_RENDER_IN_EXECUTOR", "1") == "1"
        self._tts_prewarm_on_prepare = os.environ.get("OPENTALKING_TTS_PREWARM_ON_PREPARE", "1") != "0"
        self._tts_prewarm_text = os.environ.get("OPENTALKING_TTS_PREWARM_TEXT", "你好")
        self._render_executor: ThreadPoolExecutor | None = None
        self._audio_resampler = _StreamingPCMResampler()
        self._active_timing: SpeechTiming | None = None
        self._rendered_chunk_count = 0
        self._audio_preroll_chunks = self._resolve_audio_preroll_chunks()
        self._idle_frame_cache: list[_IdleFrameCacheEntry] = []
        self._idle_frame_cache_cursor = 0
        self._idle_frame_cache_direction = 1
        self._idle_frame_cache_playback = os.environ.get(
            "OPENTALKING_IDLE_CACHE_PLAYBACK",
            self._quicktalk_env("IDLE_CACHE_PLAYBACK", "loop"),
        ).strip().lower()
        # Cache the most recent speech frame so that, in the gap between two
        # sentences (句间) when the next chunk's audio/video is still being
        # rendered, the idle loop can repeat this frame instead of falling back
        # to a stale idle template that visibly snaps the mouth closed.
        self._last_speech_frame: VideoFrameData | None = None

    def avatar_path(self) -> Path:
        return (self.avatars_root / self.avatar_id).resolve()

    @staticmethod
    async def _put_queue_sentinel(queue: asyncio.Queue[_SpeechChunkEnvelope | None]) -> None:
        await queue.put(None)

    @staticmethod
    def _read_int_env(name: str, default: int) -> int:
        raw = os.environ.get(name, "").strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    @staticmethod
    def _read_float_env(name: str, default: float) -> float:
        raw = os.environ.get(name, "").strip()
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    @staticmethod
    def _quicktalk_env(suffix: str, default: str = "") -> str:
        raw = os.environ.get(f"OPENTALKING_QUICKTALK_{suffix}", "").strip()
        if raw:
            return raw
        return default

    def _read_quicktalk_int_env(self, suffix: str, default: int) -> int:
        raw = self._quicktalk_env(suffix)
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    def _read_quicktalk_float_env(self, suffix: str, default: float) -> float:
        raw = self._quicktalk_env(suffix)
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    def _resolve_audio_preroll_chunks(self) -> int:
        generic = self._read_int_env("OPENTALKING_AV_SYNC_PREROLL_CHUNKS", 0)
        if generic > 0:
            return max(1, generic)
        if self.model_type == "musetalk":
            return max(1, self._read_int_env("OPENTALKING_MUSETALK_PREBUFFER_CHUNKS", 3))
        if self.model_type == "wav2lip":
            return max(1, self._read_int_env("OPENTALKING_WAV2LIP_PREBUFFER_CHUNKS", 2))
        return 1

    def _resolve_idle_cache_frames(self) -> int:
        generic = self._read_int_env("OPENTALKING_IDLE_CACHE_FRAMES", -1)
        if generic >= 0:
            return generic
        if self.model_type == "quicktalk":
            return max(1, self._read_quicktalk_int_env("IDLE_CACHE_FRAMES", 1))
        return 0

    def _build_idle_frame_cache(self) -> None:
        self._idle_frame_cache = []
        self._idle_frame_cache_cursor = 0
        self._idle_frame_cache_direction = 1
        if self.avatar_state is None:
            return
        cache_frames = self._resolve_idle_cache_frames()
        if cache_frames <= 0:
            return
        idle_frame = getattr(self.adapter, "idle_frame", None)
        if not callable(idle_frame):
            return
        try:
            for idx in range(cache_frames):
                frame = idle_frame(self.avatar_state, idx)
                data = np.asarray(frame.data, dtype=np.uint8)
                self._idle_frame_cache.append(
                    _IdleFrameCacheEntry(
                        data=data.copy(),
                        width=int(frame.width),
                        height=int(frame.height),
                    )
                )
        except Exception:  # noqa: BLE001
            log.warning("failed to build idle frame cache for session %s", self.session_id, exc_info=True)
            self._idle_frame_cache = []
            self._idle_frame_cache_cursor = 0
            return
        if self._idle_frame_cache:
            log.info(
                "idle frame cache ready: session=%s model=%s frames=%d playback=%s",
                self.session_id,
                self.model_type,
                len(self._idle_frame_cache),
                self._idle_frame_cache_playback,
            )

    def _next_idle_cache_entry(self) -> _IdleFrameCacheEntry:
        if not self._idle_frame_cache:
            raise RuntimeError("idle frame cache is empty")
        if len(self._idle_frame_cache) == 1:
            return self._idle_frame_cache[0]
        if self._idle_frame_cache_playback in {"pingpong", "ping-pong", "bounce"}:
            idx = max(0, min(self._idle_frame_cache_cursor, len(self._idle_frame_cache) - 1))
            entry = self._idle_frame_cache[idx]
            if idx >= len(self._idle_frame_cache) - 1:
                self._idle_frame_cache_direction = -1
            elif idx <= 0:
                self._idle_frame_cache_direction = 1
            self._idle_frame_cache_cursor = idx + self._idle_frame_cache_direction
            return entry
        entry = self._idle_frame_cache[self._idle_frame_cache_cursor % len(self._idle_frame_cache)]
        self._idle_frame_cache_cursor += 1
        return entry

    def _prepare_avatar_sync(self) -> Any:
        self.adapter.load_model(self.device)
        avatar_state = self.adapter.load_avatar(str(self.avatar_path()))
        self.adapter.warmup()
        return avatar_state

    async def prepare(self) -> None:
        if self.ready_event.is_set():
            return
        if self.model_type == "quicktalk":
            loop = asyncio.get_running_loop()
            self.avatar_state = await loop.run_in_executor(None, self._prepare_avatar_sync)
        else:
            self.avatar_state = self._prepare_avatar_sync()
        fps = float(self.avatar_state.manifest.fps)
        if self._rtc_sample_rate <= 0:
            self._rtc_sample_rate = int(self.avatar_state.manifest.sample_rate)
        self.webrtc = WebRTCSession(
            fps=fps,
            sample_rate=self._rtc_sample_rate,
            mode="buffered",
        )
        self._build_idle_frame_cache()
        if self._render_in_executor and self._render_executor is None:
            self._render_executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix=f"opentalking-render-{self.session_id}",
            )
        if self._idle_task is None:
            self._idle_task = asyncio.create_task(self._idle_loop())
        if self._tts_prewarm_on_prepare:
            await self._prewarm_tts()
        self.ready_event.set()

    async def wait_ready(self, timeout: float | None = None) -> None:
        if timeout is None:
            await self.ready_event.wait()
            return
        await asyncio.wait_for(self.ready_event.wait(), timeout=timeout)

    async def _prewarm_tts(self) -> None:
        return

    async def _idle_loop(self) -> None:
        fps = max(1.0, float(self.avatar_state.manifest.fps)) if self.avatar_state else 25.0
        interval = 1.0 / fps
        while not self._closed:
            await asyncio.sleep(interval)
            if self._closed:
                break
            if self._speaking or not self.webrtc or not self.avatar_state:
                continue
            try:
                await self.idle_tick()
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001
                continue

    async def handle_webrtc_offer(self, sdp: str, type_: str) -> dict[str, str]:
        await self.wait_ready(timeout=120.0)
        if not self.webrtc:
            raise RuntimeError("Session runner is ready but WebRTC is unavailable")
        assert self.webrtc is not None
        ans = await self.webrtc.handle_offer(sdp, type_)
        return {"sdp": ans.sdp, "type": ans.type}

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
            self._run_speak_task(
                text,
                tts_voice=tts_voice,
                tts_provider=tts_provider,
                tts_model=tts_model,
                enqueue_unix=enqueue_unix,
            )
        )
        self.speech_tasks.add(task)
        task.add_done_callback(self.speech_tasks.discard)
        return task

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

    def create_chat_task(
        self,
        prompt: str,
        tts_voice: str | None = None,
        *,
        tts_provider: str | None = None,
        tts_model: str | None = None,
        enqueue_unix: float | None = None,
    ) -> asyncio.Task[None]:
        task = asyncio.create_task(
            self._run_chat_task(
                prompt,
                tts_voice=tts_voice,
                tts_provider=tts_provider,
                tts_model=tts_model,
                enqueue_unix=enqueue_unix,
            )
        )
        self.speech_tasks.add(task)
        task.add_done_callback(self.speech_tasks.discard)
        return task

    async def _run_chat_task(
        self,
        prompt: str,
        tts_voice: str | None = None,
        tts_provider: str | None = None,
        tts_model: str | None = None,
        enqueue_unix: float | None = None,
    ) -> None:
        log.info("chat start: %s (session=%s)", prompt[:30], self.session_id)
        try:
            await self.chat(
                prompt,
                tts_voice=tts_voice,
                tts_provider=tts_provider,
                tts_model=tts_model,
                enqueue_unix=enqueue_unix,
            )
            log.info("chat done: session=%s", self.session_id)
        except asyncio.CancelledError:
            log.info("chat cancelled: session=%s", self.session_id)
        except Exception:  # noqa: BLE001
            log.exception("chat failed: session=%s", self.session_id)
            if not self._closed:
                await set_session_state(self.redis, self.session_id, "error")

    async def _video_sink(self, frame: VideoFrameData) -> None:
        if self.webrtc:
            self._last_speech_frame = frame
            await self.webrtc.video.put(frame)

    async def _audio_sink(self, pcm: Any, sample_rate: int) -> None:
        if not self.webrtc:
            return
        arr = np.asarray(pcm, dtype=np.int16).reshape(-1)
        if arr.size == 0:
            return
        if sample_rate != self._rtc_sample_rate:
            arr = self._audio_resampler.convert(
                arr,
                src_rate=int(sample_rate),
                dst_rate=int(self._rtc_sample_rate),
            )
        if arr.size > 0:
            await self.webrtc.audio.put_pcm(arr)

    def _maybe_delay_quicktalk_audio(
        self,
        pcm: Any,
        sample_rate: int,
        *,
        already_delayed: bool = False,
    ) -> np.ndarray:
        arr = np.asarray(pcm, dtype=np.int16).reshape(-1)
        if (
            self.model_type != "quicktalk"
            or already_delayed
            or self._quicktalk_audio_delay_ms <= 0.0
            or arr.size == 0
        ):
            return arr
        delay_samples = int(round(float(sample_rate) * self._quicktalk_audio_delay_ms / 1000.0))
        if delay_samples <= 0:
            return arr
        return np.concatenate((np.zeros(delay_samples, dtype=np.int16), arr)).astype(np.int16, copy=False)

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

    async def _render_chunk_frames(
        self,
        chunk: AudioChunk,
        *,
        frame_index_start: int,
        speech_frame_index_start: int,
    ) -> tuple[int, list[VideoFrameData]]:
        render_call = partial(
            render_audio_chunk_sync,
            self.adapter,
            self.avatar_state,
            chunk,
            frame_index_start=frame_index_start,
            speech_frame_index_start=speech_frame_index_start,
        )
        if self._render_in_executor and self._render_executor is not None:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self._render_executor, render_call)
        return render_call()

    async def _iter_render_chunk_frames(
        self,
        chunk: AudioChunk,
        *,
        frame_index_start: int,
        speech_frame_index_start: int,
    ) -> tuple[int, Any, Any]:
        render_call = partial(
            iter_rendered_frames_sync,
            self.adapter,
            self.avatar_state,
            chunk,
            frame_index_start=frame_index_start,
            speech_frame_index_start=speech_frame_index_start,
        )
        if self._render_in_executor and self._render_executor is not None:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self._render_executor, render_call)
        return render_call()

    def _ensure_render_chunk_event(self, chunk_idx: int) -> asyncio.Event:
        event = self._render_chunk_events.get(chunk_idx)
        if event is None:
            event = asyncio.Event()
            self._render_chunk_events[chunk_idx] = event
        return event

    def _ensure_render_chunk_audio_event(self, chunk_idx: int) -> asyncio.Event:
        events = getattr(self, "_render_chunk_audio_events", None)
        if not isinstance(events, dict):
            events = {}
            self._render_chunk_audio_events = events
        event = events.get(chunk_idx)
        if event is None:
            event = asyncio.Event()
            events[chunk_idx] = event
        return event

    def _mark_render_chunk_ready(self, chunk_idx: int) -> None:
        self._ensure_render_chunk_event(chunk_idx).set()

    def _mark_render_chunk_audio_ready(self, chunk_idx: int) -> None:
        self._ensure_render_chunk_audio_event(chunk_idx).set()

    async def _wait_for_render_chunk(self, chunk_idx: int) -> None:
        await self._ensure_render_chunk_event(chunk_idx).wait()

    async def _wait_for_render_chunk_audio(self, chunk_idx: int) -> None:
        await self._ensure_render_chunk_audio_event(chunk_idx).wait()

    def _release_render_chunk_events(self) -> None:
        for event in self._render_chunk_events.values():
            event.set()
        for event in self._render_chunk_audio_events.values():
            event.set()

    async def _render_chunk_worker(
        self,
        queue: asyncio.Queue[_SpeechChunkEnvelope | None],
        debug_capture: _SpeechDebugCapture | None = None,
    ) -> None:
        if self.model_type == "quicktalk":
            await self._render_chunk_worker_streaming(queue, debug_capture)
            return

        pending_video_chunks: list[tuple[int, list[VideoFrameData]]] = []
        media_started = False

        async def _flush_video_chunks(chunks: list[tuple[int, list[VideoFrameData]]]) -> None:
            for chunk_idx, chunk_frames in chunks:
                for frame in chunk_frames:
                    if debug_capture is not None:
                        debug_capture.add_frame(frame)
                    await self._video_sink(frame)
                    if timing is not None:
                        timing.mark_once("first_video_frame_enqueued")
                self._mark_render_chunk_ready(chunk_idx)

        while True:
            item = await queue.get()
            if item is None:
                if pending_video_chunks:
                    if not self._speech_video_ready.is_set():
                        self._speech_video_ready.set()
                    await _flush_video_chunks(pending_video_chunks)
                    pending_video_chunks = []
                return
            timing = self._active_timing
            visual_frame_idx = self._frame_idx
            if self.avatar_state is not None and isinstance(getattr(self.avatar_state, "extra", None), dict):
                self.avatar_state.extra["wav2lip_stream_is_final"] = bool(item.is_final)
                lookahead_pcm = (
                    np.asarray(item.lookahead_chunk.data, dtype=np.int16).reshape(-1)
                    if item.lookahead_chunk is not None
                    else np.zeros(0, dtype=np.int16)
                )
                self.avatar_state.extra["wav2lip_stream_lookahead_pcm"] = lookahead_pcm
            render_started_at = _time.perf_counter()
            self._frame_idx, frames = await self._render_chunk_frames(
                item.chunk,
                frame_index_start=self._frame_idx,
                speech_frame_index_start=self._speech_frame_idx,
            )
            if timing is not None:
                timing.mark_once("first_render_chunk_ready")
                timing.add_duration("render_total_s", _time.perf_counter() - render_started_at)
                timing.add_count("render_chunks", 1)
                timing.add_count("render_frames", len(frames))
            if self.avatar_state is not None and isinstance(getattr(self.avatar_state, "extra", None), dict):
                self.avatar_state.extra["wav2lip_stream_is_final"] = False
                self.avatar_state.extra["wav2lip_stream_lookahead_pcm"] = np.zeros(0, dtype=np.int16)
            self._rendered_chunk_count += 1
            pending_video_chunks.append((item.idx, frames))
            should_release_media = (
                media_started
                or self._rendered_chunk_count >= self._audio_preroll_chunks
                or item.is_final
            )
            if should_release_media:
                if not self._speech_video_ready.is_set():
                    self._speech_video_ready.set()
                media_started = True
                await _flush_video_chunks(pending_video_chunks)
                pending_video_chunks = []
            self._speech_frame_idx += max(0, self._frame_idx - visual_frame_idx)

    async def _render_chunk_worker_streaming(
        self,
        queue: asyncio.Queue[_SpeechChunkEnvelope | None],
        debug_capture: _SpeechDebugCapture | None = None,
    ) -> None:
        media_started = False
        # 多卡 prefetch：当 chunk N 还在渲染（ONNX 在 device GPU 上 yield 帧）时，
        # 把 chunk N+1 的 prepare（HuBERT 在 hubert_device GPU + build_rep_chunks）
        # 放到默认 ThreadPool 异步启动。两块 GPU 物理并行 → 块切换时 chunk N+1
        # 的 prepare 已经完成，直接拿结果，没有"块尾 80ms HuBERT 暂停"。
        # 默认开；OPENTALKING_QUICKTALK_PREFETCH=0 关闭以便 A/B 对比。
        prefetch_enabled = self._quicktalk_env("PREFETCH", "1") != "0"
        prefetch: tuple[_SpeechChunkEnvelope, asyncio.Future] | None = None
        saw_queue_sentinel = False

        while True:
            if prefetch is not None:
                item = prefetch[0]
            elif saw_queue_sentinel:
                return
            else:
                item = await queue.get()
            if item is None:
                if prefetch is not None:
                    # 句末退出：取消 / 等 prefetch（不应留悬挂任务）。
                    try:
                        prefetch[1].cancel()
                    except Exception:  # noqa: BLE001
                        pass
                    prefetch = None
                return

            timing = self._active_timing
            visual_frame_idx = self._frame_idx
            render_started_at = _time.perf_counter()
            render_prepare_started_at = _time.perf_counter()
            try:
                if prefetch is not None and prefetch[0] is item:
                    # 预取已完成 prepare，直接拿结果（多数情况下已经 ready）。
                    next_frame_idx, _features, frames = await prefetch[1]
                    prefetch = None
                else:
                    next_frame_idx, _features, frames = await self._iter_render_chunk_frames(
                        item.chunk,
                        frame_index_start=self._frame_idx,
                        speech_frame_index_start=self._speech_frame_idx,
                    )
            except Exception:  # noqa: BLE001
                # 单块渲染失败（例如 PCM 太短让 HuBERT 抛错）—— 记录后跳过，
                # 不能 raise，否则 audio_chunk_worker 会永远等这个 chunk_event 而死锁。
                log.warning(
                    "render chunk %d failed for session %s; skipping",
                    item.idx,
                    self.session_id,
                    exc_info=True,
                )
                self._mark_render_chunk_audio_ready(item.idx)
                self._mark_render_chunk_ready(item.idx)
                prefetch = None
                continue
            if timing is not None:
                timing.mark_once("first_render_chunk_ready")
                timing.add_duration("render_prepare_s", _time.perf_counter() - render_prepare_started_at)
                feature_seconds = getattr(_features, "audio_feature_seconds", None)
                if feature_seconds is not None:
                    timing.add_duration("render_feature_s", float(feature_seconds))
                timing.add_count("render_chunks", 1)

            should_release_media = (
                media_started
                or self._rendered_chunk_count + 1 >= self._audio_preroll_chunks
                or item.is_final
            )
            if should_release_media and not self._speech_video_ready.is_set():
                self._speech_video_ready.set()
            media_started = media_started or should_release_media

            frame_count = 0
            chunk_audio_ready_marked = False
            iterator = iter(frames)
            loop = asyncio.get_running_loop()

            # 启动 chunk N+1 的 prepare 预取，让它与本块的 ONNX 帧迭代并行。
            # HuBERT 在 hubert_device（多卡时另一张卡），ONNX 在 device 卡，
            # 物理并行不抢 GPU。default ThreadPool 跑 prepare，
            # _render_executor 跑 ONNX 帧迭代，互不干扰。
            if prefetch_enabled and not item.is_final and prefetch is None:
                try:
                    next_item = queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                else:
                    if next_item is None:
                        saw_queue_sentinel = True
                    else:
                        prefetch_render_call = partial(
                            iter_rendered_frames_sync,
                            self.adapter,
                            self.avatar_state,
                            next_item.chunk,
                            frame_index_start=next_frame_idx,
                            speech_frame_index_start=self._speech_frame_idx
                            + max(0, next_frame_idx - visual_frame_idx),
                        )
                        prefetch_future = asyncio.ensure_future(
                            loop.run_in_executor(None, prefetch_render_call)
                        )
                        prefetch = (next_item, prefetch_future)

            try:
                while True:
                    next_started_at = _time.perf_counter()
                    if self._render_in_executor and self._render_executor is not None:
                        ok, frame = await loop.run_in_executor(
                            self._render_executor,
                            _next_iter_item,
                            iterator,
                        )
                    else:
                        ok, frame = _next_iter_item(iterator)
                    next_seconds = _time.perf_counter() - next_started_at
                    if not ok:
                        break
                    if timing is not None:
                        timing.add_duration("render_next_frame_s", next_seconds)
                    if debug_capture is not None:
                        debug_started_at = _time.perf_counter()
                        debug_capture.add_frame(frame)
                        if timing is not None:
                            timing.add_duration("render_debug_capture_s", _time.perf_counter() - debug_started_at)
                    video_enqueue_started_at = _time.perf_counter()
                    await self._video_sink(frame)
                    if timing is not None:
                        timing.add_duration("render_video_enqueue_s", _time.perf_counter() - video_enqueue_started_at)
                    if media_started and not chunk_audio_ready_marked:
                        self._mark_render_chunk_audio_ready(item.idx)
                        chunk_audio_ready_marked = True
                    frame_count += 1
                    if timing is not None:
                        timing.mark_once("first_video_frame_enqueued")
            except Exception:  # noqa: BLE001
                log.warning(
                    "render frame iteration failed for chunk %d session %s; skipping remainder",
                    item.idx,
                    self.session_id,
                    exc_info=True,
                )
            if not chunk_audio_ready_marked:
                self._mark_render_chunk_audio_ready(item.idx)
            self._frame_idx = next_frame_idx
            self._rendered_chunk_count += 1
            if timing is not None:
                timing.add_duration("render_total_s", _time.perf_counter() - render_started_at)
                timing.add_count("render_frames", frame_count)
            self._mark_render_chunk_ready(item.idx)
            self._speech_frame_idx += max(0, self._frame_idx - visual_frame_idx)

    async def _audio_chunk_worker(
        self,
        queue: asyncio.Queue[_SpeechChunkEnvelope | None],
    ) -> None:
        audio_started = False
        audio_delay_applied = False
        while True:
            item = await queue.get()
            if item is None:
                return
            timing = self._active_timing
            if not audio_started:
                audio_started = True
                if not self._speech_video_ready.is_set():
                    preroll_started_at = _time.perf_counter()
                    try:
                        await asyncio.wait_for(
                            self._speech_video_ready.wait(),
                            timeout=max(0.05, self._audio_preroll_timeout_ms / 1000.0),
                        )
                    except asyncio.TimeoutError:
                        log.warning(
                            "audio preroll wait timed out for session %s",
                            self.session_id,
                        )
                    finally:
                        if timing is not None:
                            timing.add_duration(
                                "audio_preroll_wait_s",
                                _time.perf_counter() - preroll_started_at,
                            )
                    if timing is not None:
                        timing.add_count("audio_preroll_chunks", self._audio_preroll_chunks)
            if self.model_type == "quicktalk":
                await self._wait_for_render_chunk_audio(item.idx)
            else:
                await self._wait_for_render_chunk(item.idx)
            audio_started_at = _time.perf_counter()
            pcm = self._maybe_delay_quicktalk_audio(
                item.chunk.data,
                item.chunk.sample_rate,
                already_delayed=audio_delay_applied,
            )
            if self.model_type == "quicktalk" and not audio_delay_applied and pcm.size > 0:
                audio_delay_applied = True
            await self._audio_sink(pcm, item.chunk.sample_rate)
            if timing is not None:
                timing.mark_once("first_audio_chunk_enqueued")
                timing.add_duration("audio_enqueue_total_s", _time.perf_counter() - audio_started_at)
                timing.add_count("audio_chunks", 1)
                timing.add_count("audio_samples", int(np.asarray(item.chunk.data).size))
            self._render_chunk_events.pop(item.idx, None)
            self._render_chunk_audio_events.pop(item.idx, None)

    def _build_debug_capture(self, speech_text: str) -> _SpeechDebugCapture:
        return _SpeechDebugCapture(
            enabled=self._debug_dump_speech_dir is not None,
            root_dir=self._debug_dump_speech_dir,
            session_id=self.session_id,
            avatar_id=self.avatar_id,
            model_type=self.model_type,
            fps=int(self.avatar_state.manifest.fps),
            sample_rate=int(self.avatar_state.manifest.sample_rate),
            ffmpeg_bin=self._ffmpeg_bin,
            text=speech_text,
        )

    def _speech_chunk_ms(self) -> float:
        if self.model_type == "quicktalk":
            return float(self._quicktalk_env("RENDER_CHUNK_MS", "500.0"))
        if self.model_type == "wav2lip" and self._wav2lip_live_mode not in {"official", "auto"}:
            return float(os.environ.get("OPENTALKING_WAV2LIP_RENDER_CHUNK_MS", "200.0"))
        return self._render_chunk_ms

    def _quicktalk_full_audio_enabled_for(self, speech_text: str) -> bool:
        if self.model_type != "quicktalk":
            return False
        mode = self._quicktalk_env("FULL_AUDIO", "stream").strip().lower()
        if mode not in {"1", "true", "on", "full"}:
            return False
        max_chars = self._read_quicktalk_int_env("FULL_AUDIO_MAX_CHARS", 80)
        if max_chars > 0 and len(speech_text) > max_chars:
            log.info(
                "quicktalk full-audio disabled for long text: chars=%d max=%d",
                len(speech_text),
                max_chars,
            )
            return False
        return True

    async def _speak_quicktalk_full_audio(
        self,
        speech_text: str,
        debug_capture: _SpeechDebugCapture,
        *,
        tts_voice: str | None = None,
        tts_provider: str | None = None,
        tts_model: str | None = None,
    ) -> bool:
        if self.model_type != "quicktalk":
            return False
        if self.avatar_state is None or self.webrtc is None:
            return False
        if not self._quicktalk_full_audio_enabled_for(speech_text):
            return False

        tts = build_tts_adapter(
            sample_rate=int(self.avatar_state.manifest.sample_rate),
            chunk_ms=self._speech_chunk_ms(),
            settings=self._tts_settings,
            default_voice=tts_voice,
            tts_provider=tts_provider,
            tts_model=tts_model,
        )
        pcm_parts: list[np.ndarray] = []
        tts_started_at = _time.perf_counter()
        chunk_idx = 0
        timing = self._active_timing
        async for chunk in tts.synthesize_stream(speech_text):
            if chunk_idx == 0:
                if timing is not None:
                    timing.mark_once("tts_first_pcm")
                log.info(
                    "TTS first chunk in %.0fms",
                    (_time.perf_counter() - tts_started_at) * 1000,
                )
            if self._interrupt.is_set():
                return True
            debug_capture.add_audio_chunk(chunk)
            pcm_parts.append(np.asarray(chunk.data, dtype=np.int16).reshape(-1).copy())
            if timing is not None:
                timing.add_count("tts_chunks", 1)
                timing.add_count("tts_samples", int(np.asarray(chunk.data).size))
            chunk_idx += 1
        if timing is not None:
            timing.add_duration("tts_total_s", _time.perf_counter() - tts_started_at)
        if not pcm_parts:
            return True

        pcm = np.concatenate(pcm_parts).astype(np.int16, copy=False)
        sample_rate = int(self.avatar_state.manifest.sample_rate)
        duration_ms = float(pcm.shape[0]) / float(sample_rate) * 1000.0
        chunk = AudioChunk(data=pcm, sample_rate=sample_rate, duration_ms=duration_ms)

        render_started_at = _time.perf_counter()
        prepare_started_at = _time.perf_counter()
        next_frame_idx, features, frames = iter_rendered_frames_sync(
            self.adapter,
            self.avatar_state,
            chunk,
            frame_index_start=self._frame_idx,
            speech_frame_index_start=self._speech_frame_idx,
        )
        if timing is not None:
            timing.mark_once("first_render_chunk_ready")
            timing.add_duration("render_prepare_s", _time.perf_counter() - prepare_started_at)
            feature_seconds = getattr(features, "audio_feature_seconds", None)
            if feature_seconds is not None:
                timing.add_duration("render_feature_s", float(feature_seconds))
            timing.add_count("render_chunks", 1)

        self._speech_video_ready.set()
        iterator = iter(frames)
        frame_count = 0
        audio_enqueued = False
        playback_pcm = self._maybe_delay_quicktalk_audio(pcm, sample_rate)
        media_started_at: float | None = None
        while True:
            next_started_at = _time.perf_counter()
            ok, frame = _next_iter_item(iterator)
            next_seconds = _time.perf_counter() - next_started_at
            if not ok:
                break
            if timing is not None:
                timing.add_duration("render_next_frame_s", next_seconds)
            debug_started_at = _time.perf_counter()
            debug_capture.add_frame(frame)
            if timing is not None:
                timing.add_duration("render_debug_capture_s", _time.perf_counter() - debug_started_at)
            enqueue_started_at = _time.perf_counter()
            await self._video_sink(frame)
            if timing is not None:
                timing.add_duration("render_video_enqueue_s", _time.perf_counter() - enqueue_started_at)
                timing.mark_once("first_video_frame_enqueued")
            frame_count += 1
            if not audio_enqueued:
                audio_started_at = _time.perf_counter()
                await self._audio_sink(playback_pcm, sample_rate)
                media_started_at = _time.perf_counter()
                audio_enqueued = True
                if timing is not None:
                    timing.mark_once("first_audio_chunk_enqueued")
                    timing.add_duration("audio_enqueue_total_s", media_started_at - audio_started_at)
                    timing.add_count("audio_chunks", 1)
                    timing.add_count("audio_samples", int(playback_pcm.size))
                await asyncio.sleep(0)
        if timing is not None:
            timing.add_duration("render_total_s", _time.perf_counter() - render_started_at)
            timing.add_count("render_frames", frame_count)

        if not audio_enqueued:
            audio_started_at = _time.perf_counter()
            await self._audio_sink(playback_pcm, sample_rate)
            media_started_at = _time.perf_counter()
            if timing is not None:
                timing.mark_once("first_audio_chunk_enqueued")
                timing.add_duration("audio_enqueue_total_s", media_started_at - audio_started_at)
                timing.add_count("audio_chunks", 1)
                timing.add_count("audio_samples", int(playback_pcm.size))
        # Buffered WebRTC tracks pace playback themselves (see
        # _BufferedPCM16AudioTrack.recv); we used to ``await asyncio.sleep`` for
        # the audio's remaining duration here, which only kept ``_speak_lock``
        # held and stalled the next user turn without delivering any benefit.
        self._frame_idx = next_frame_idx
        self._speech_frame_idx = next_frame_idx
        self._rendered_chunk_count += 1
        return True

    async def _speak_wav2lip_official(
        self,
        speech_text: str,
        debug_capture: _SpeechDebugCapture,
        *,
        tts_voice: str | None = None,
        tts_provider: str | None = None,
        tts_model: str | None = None,
    ) -> bool:
        if self.model_type != "wav2lip":
            return False
        if self._wav2lip_live_mode not in {"official", "auto"}:
            return False
        if self.avatar_state is None or self.webrtc is None:
            return False
        if not official_runtime_available():
            if self._wav2lip_live_mode == "official":
                log.warning("official wav2lip runtime unavailable; falling back to reactive live mode")
            return False

        tts = build_tts_adapter(
            sample_rate=int(self.avatar_state.manifest.sample_rate),
            chunk_ms=self._speech_chunk_ms(),
            settings=self._tts_settings,
            default_voice=tts_voice,
            tts_provider=tts_provider,
            tts_model=tts_model,
        )
        pcm_parts: list[np.ndarray] = []
        tts_started_at = _time.perf_counter()
        chunk_idx = 0
        timing = self._active_timing
        async for chunk in tts.synthesize_stream(speech_text):
            if chunk_idx == 0:
                if timing is not None:
                    timing.mark_once("tts_first_pcm")
                log.info(
                    "TTS first chunk in %.0fms",
                    (_time.perf_counter() - tts_started_at) * 1000,
                )
            if self._interrupt.is_set():
                return True
            debug_capture.add_audio_chunk(chunk)
            pcm_parts.append(np.asarray(chunk.data, dtype=np.int16).reshape(-1).copy())
            if timing is not None:
                timing.add_count("tts_chunks", 1)
                timing.add_count("tts_samples", int(np.asarray(chunk.data).size))
            chunk_idx += 1
        if timing is not None:
            timing.add_duration("tts_total_s", _time.perf_counter() - tts_started_at)

        if not pcm_parts:
            return True

        pcm = np.concatenate(pcm_parts).astype(np.int16, copy=False)
        avatar_path = self.avatar_path()
        fps = int(self.avatar_state.manifest.fps)
        sample_rate = int(self.avatar_state.manifest.sample_rate)
        log.info("wav2lip official live render: samples=%d fps=%d", pcm.shape[0], fps)

        infer_started_at = _time.perf_counter()
        _, _, video_path = await asyncio.to_thread(
            run_official_inference,
            avatar_path=avatar_path,
            pcm=pcm,
            sample_rate=sample_rate,
            fps=fps,
            ffmpeg_bin=self._ffmpeg_bin,
        )
        if timing is not None:
            timing.add_duration("official_infer_total_s", _time.perf_counter() - infer_started_at)
        load_frames_started_at = _time.perf_counter()
        frames = await asyncio.to_thread(load_video_frames, video_path)
        if timing is not None:
            timing.add_duration("official_load_frames_total_s", _time.perf_counter() - load_frames_started_at)
            timing.add_count("render_frames", len(frames))
        if self._interrupt.is_set():
            return True

        self.webrtc.clear_media_queues()
        self.webrtc.reset_clocks()
        self._speech_video_ready.set()

        timestamp_ms = 0.0
        frame_duration_ms = 1000.0 / max(1, fps)
        for frame in frames:
            frame_data = VideoFrameData(
                data=frame,
                width=frame.shape[1],
                height=frame.shape[0],
                timestamp_ms=timestamp_ms,
            )
            debug_capture.add_frame(frame_data)
            await self._video_sink(frame_data)
            if timing is not None:
                timing.mark_once("first_video_frame_enqueued")
            timestamp_ms += frame_duration_ms
        await self._audio_sink(pcm, sample_rate)
        if timing is not None:
            timing.mark_once("first_audio_chunk_enqueued")
        self._frame_idx = len(frames)
        self._speech_frame_idx = len(frames)
        return True

    async def speak(
        self,
        text: str,
        tts_voice: str | None = None,
        *,
        tts_provider: str | None = None,
        tts_model: str | None = None,
        enqueue_unix: float | None = None,
    ) -> None:
        async with self._speak_lock:
            speech_text = strip_emoji(text).strip()
            if not speech_text or self._closed:
                return

            timing = SpeechTiming(
                session_id=self.session_id,
                model_type=self.model_type,
                text_preview=speech_text,
            )
            self._active_timing = timing

            try:
                await self.wait_ready(timeout=180.0)
                if self.avatar_state is None:
                    raise RuntimeError("Session runner is ready but avatar state is unavailable")
                self._interrupt.clear()
                self._speech_video_ready.clear()
                self._render_chunk_events = {}
                self._render_chunk_audio_events = {}
                self._rendered_chunk_count = 0
                self._audio_preroll_chunks = self._resolve_audio_preroll_chunks()
                self._speaking = True
                if self.avatar_state is not None:
                    reset_avatar_speech_state(self.avatar_state)
                if self._reset_frame_idx_on_speak:
                    self._frame_idx = 0
                self._speech_frame_idx = 0
                if self.webrtc:
                    self.webrtc.clear_media_queues()
                    self.webrtc.reset_clocks()
                log.info(
                    "speech preroll config: session=%s model=%s preroll_chunks=%d",
                    self.session_id,
                    self.model_type,
                    self._audio_preroll_chunks,
                )
                await set_session_state(self.redis, self.session_id, "speaking")
                await publish_event(
                    self.redis,
                    self.session_id,
                    "speech.started",
                    {"session_id": self.session_id, "text": speech_text},
                )
                self._speech_started = True
                await publish_event(
                    self.redis,
                    self.session_id,
                    "subtitle.chunk",
                    {"session_id": self.session_id, "text": speech_text, "is_final": True},
                )
                debug_capture = self._build_debug_capture(speech_text)
                official_done = False
                finish_workers_gracefully = False
                try:
                    official_done = await self._speak_quicktalk_full_audio(
                        speech_text,
                        debug_capture,
                        tts_voice=tts_voice,
                        tts_provider=tts_provider,
                        tts_model=tts_model,
                    )
                    if not official_done:
                        official_done = await self._speak_wav2lip_official(
                            speech_text,
                            debug_capture,
                            tts_voice=tts_voice,
                            tts_provider=tts_provider,
                            tts_model=tts_model,
                        )
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    log.warning("official wav2lip live render failed; falling back", exc_info=True)
                    official_done = False
                if official_done:
                    try:
                        out_dir = debug_capture.finalize()
                        if out_dir is not None:
                            log.info("speech debug dump saved: %s", out_dir)
                    except Exception:  # noqa: BLE001
                        log.warning("failed to finalize speech debug dump", exc_info=True)
                    await self._publish_speech_ended()
                    if not self._closed:
                        await set_session_state(self.redis, self.session_id, "ready")
                    self._speaking = False
                    return
                tts = build_tts_adapter(
                    sample_rate=int(self.avatar_state.manifest.sample_rate),
                    chunk_ms=self._speech_chunk_ms(),
                    settings=self._tts_settings,
                    default_voice=tts_voice,
                    tts_provider=tts_provider,
                    tts_model=tts_model,
                )
                render_queue: asyncio.Queue[_SpeechChunkEnvelope | None] = asyncio.Queue(maxsize=4)
                audio_queue: asyncio.Queue[_SpeechChunkEnvelope | None] = asyncio.Queue(maxsize=4)
                render_task = asyncio.create_task(self._render_chunk_worker(render_queue, debug_capture))
                audio_task = asyncio.create_task(self._audio_chunk_worker(audio_queue))
                try:
                    tts_started_at = _time.perf_counter()
                    chunk_idx = 0
                    delayed_envelope: _SpeechChunkEnvelope | None = None
                    use_wav2lip_lookahead = (
                        self.model_type == "wav2lip"
                        and self._wav2lip_live_mode not in {"official", "auto"}
                    )
                    async for chunk in tts.synthesize_stream(speech_text):
                        if chunk_idx == 0:
                            timing.mark_once("tts_first_pcm")
                            log.info(
                                "TTS first chunk in %.0fms",
                                (_time.perf_counter() - tts_started_at) * 1000,
                            )
                        if self._interrupt.is_set():
                            break
                        debug_capture.add_audio_chunk(chunk)
                        timing.add_count("tts_chunks", 1)
                        timing.add_count("tts_samples", int(np.asarray(chunk.data).size))
                        envelope = _SpeechChunkEnvelope(idx=chunk_idx, chunk=chunk)
                        if use_wav2lip_lookahead:
                            if delayed_envelope is not None:
                                delayed_envelope = _SpeechChunkEnvelope(
                                    idx=delayed_envelope.idx,
                                    chunk=delayed_envelope.chunk,
                                    lookahead_chunk=envelope.chunk,
                                )
                                self._ensure_render_chunk_event(delayed_envelope.idx)
                                await render_queue.put(delayed_envelope)
                                await audio_queue.put(delayed_envelope)
                            delayed_envelope = envelope
                        else:
                            self._ensure_render_chunk_event(chunk_idx)
                            await render_queue.put(envelope)
                            await audio_queue.put(envelope)
                        chunk_idx += 1
                    timing.add_duration("tts_total_s", _time.perf_counter() - tts_started_at)
                    if use_wav2lip_lookahead and delayed_envelope is not None and not self._interrupt.is_set():
                        delayed_envelope = _SpeechChunkEnvelope(
                            idx=delayed_envelope.idx,
                            chunk=delayed_envelope.chunk,
                            is_final=True,
                        )
                        self._ensure_render_chunk_event(delayed_envelope.idx)
                        await render_queue.put(delayed_envelope)
                        await audio_queue.put(delayed_envelope)
                    finish_workers_gracefully = not self._interrupt.is_set()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    await publish_event(
                        self.redis,
                        self.session_id,
                        "error",
                        {
                            "session_id": self.session_id,
                            "code": "SPEAK_FAILED",
                            "message": str(exc),
                        },
                    )
                    raise
                finally:
                    if not finish_workers_gracefully:
                        self._speech_video_ready.set()
                        self._release_render_chunk_events()
                    await asyncio.gather(
                        asyncio.shield(self._put_queue_sentinel(render_queue)),
                        asyncio.shield(self._put_queue_sentinel(audio_queue)),
                    )
                    if finish_workers_gracefully:
                        worker_results = await asyncio.gather(render_task, audio_task, return_exceptions=True)
                    else:
                        try:
                            worker_results = await asyncio.wait_for(
                                asyncio.gather(render_task, audio_task, return_exceptions=True),
                                timeout=5.0,
                            )
                        except asyncio.TimeoutError:
                            render_task.cancel()
                            audio_task.cancel()
                            worker_results = await asyncio.gather(
                                render_task,
                                audio_task,
                                return_exceptions=True,
                            )
                    for result in worker_results:
                        if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                            log.warning(
                                "speech worker ended with error for session %s: %r",
                                self.session_id,
                                result,
                            )
                    try:
                        out_dir = debug_capture.finalize()
                        if out_dir is not None:
                            log.info("speech debug dump saved: %s", out_dir)
                    except Exception:  # noqa: BLE001
                        log.warning("failed to finalize speech debug dump", exc_info=True)
                    self._render_chunk_events.clear()
                    self._render_chunk_audio_events.clear()
                    self._speaking = False
                await self._publish_speech_ended()
                if not self._closed:
                    await set_session_state(self.redis, self.session_id, "ready")
            finally:
                log.info(
                    "speech timing summary: %s",
                    timing.to_json(
                        mark_order=[
                            "tts_first_pcm",
                            "first_render_chunk_ready",
                            "first_video_frame_enqueued",
                            "first_audio_chunk_enqueued",
                        ],
                        counter_order=[
                            "tts_total_s",
                            "tts_chunks",
                            "tts_samples",
                            "official_infer_total_s",
                            "official_load_frames_total_s",
                            "render_total_s",
                            "render_prepare_s",
                            "render_feature_s",
                            "render_next_frame_s",
                            "render_debug_capture_s",
                            "render_video_enqueue_s",
                            "render_chunks",
                            "render_frames",
                            "audio_preroll_wait_s",
                            "audio_preroll_chunks",
                            "audio_enqueue_total_s",
                            "audio_chunks",
                            "audio_samples",
                        ],
                    ),
                )
                self._active_timing = None

    def _ensure_llm_client(self) -> OpenAICompatibleLLMClient:
        if self._llm_client is None:
            if not self._llm_base_url:
                raise RuntimeError(
                    "LLM 未配置：请设置 OPENTALKING_LLM_BASE_URL（OpenAI-compatible /v1）。"
                )
            self._llm_client = OpenAICompatibleLLMClient(
                base_url=self._llm_base_url,
                api_key=self._llm_api_key,
                model=self._llm_model,
            )
        return self._llm_client

    def _ensure_conversation(self) -> ConversationHistory:
        if self._conversation is None:
            base_prompt = (
                self._llm_system_prompt
                or "你是一个友好的数字人助手，请用自然、完整的中文回答问题。"
            )
            format_guard = os.environ.get(
                "OPENTALKING_LLM_FORMAT_GUARD",
                "请只输出纯文本，不要使用 Markdown 标记（例如 **、#、列表符号、代码块），"
                "不要使用表情符号；回答需要完整，不要故意省略结尾。",
            ).strip()
            system_prompt = f"{base_prompt}\n{format_guard}" if format_guard else base_prompt
            self._conversation = ConversationHistory(
                system_prompt=system_prompt,
                max_turns=20,
            )
        return self._conversation

    async def chat(
        self,
        prompt: str,
        tts_voice: str | None = None,
        *,
        tts_provider: str | None = None,
        tts_model: str | None = None,
        enqueue_unix: float | None = None,
    ) -> None:
        prompt_text = strip_emoji(prompt or "").strip()
        if not prompt_text or self._closed:
            return

        async with self._speak_lock:
            timing = SpeechTiming(
                session_id=self.session_id,
                model_type=self.model_type,
                text_preview=prompt_text,
            )
            self._active_timing = timing
            chat_started_at = _time.perf_counter()

            try:
                await self.wait_ready(timeout=180.0)
                if self.avatar_state is None:
                    raise RuntimeError("Session runner is ready but avatar state is unavailable")

                llm = self._ensure_llm_client()
                conversation = self._ensure_conversation()
                conversation.add_user(prompt_text)

                self._interrupt.clear()
                self._speech_video_ready.clear()
                self._render_chunk_events = {}
                self._render_chunk_audio_events = {}
                self._rendered_chunk_count = 0
                self._audio_preroll_chunks = self._resolve_audio_preroll_chunks()
                self._speaking = True
                if self.avatar_state is not None:
                    reset_avatar_speech_state(self.avatar_state)
                if self._reset_frame_idx_on_speak:
                    self._frame_idx = 0
                self._speech_frame_idx = 0
                if self.webrtc:
                    self.webrtc.clear_media_queues()
                    self.webrtc.reset_clocks()

                await set_session_state(self.redis, self.session_id, "speaking")
                await publish_event(
                    self.redis,
                    self.session_id,
                    "speech.started",
                    {"session_id": self.session_id, "text": prompt_text},
                )
                self._speech_started = True

                debug_capture = self._build_debug_capture(prompt_text)
                tts = build_tts_adapter(
                    sample_rate=int(self.avatar_state.manifest.sample_rate),
                    chunk_ms=self._speech_chunk_ms(),
                    settings=self._tts_settings,
                    default_voice=tts_voice,
                    tts_provider=tts_provider,
                    tts_model=tts_model,
                )
                render_queue: asyncio.Queue[_SpeechChunkEnvelope | None] = asyncio.Queue(maxsize=4)
                audio_queue: asyncio.Queue[_SpeechChunkEnvelope | None] = asyncio.Queue(maxsize=4)
                render_task = asyncio.create_task(self._render_chunk_worker(render_queue, debug_capture))
                audio_task = asyncio.create_task(self._audio_chunk_worker(audio_queue))

                splitter = SentenceSplitter()
                full_response_parts: list[str] = []
                chunk_idx = 0
                finish_workers_gracefully = False

                async def _enqueue_sentence(sentence: str) -> int:
                    nonlocal chunk_idx
                    text = sanitize_tts_text(sentence)
                    if not text:
                        return 0
                    await publish_event(
                        self.redis,
                        self.session_id,
                        "subtitle.chunk",
                        {
                            "session_id": self.session_id,
                            "text": text,
                            "is_final": False,
                        },
                    )

                    sentence_enqueued = 0

                    async def _enqueue_from_tts(tts_adapter: Any) -> int:
                        nonlocal chunk_idx
                        nonlocal sentence_enqueued
                        enqueued = 0
                        async for tts_chunk in tts_adapter.synthesize_stream(text):
                            if self._interrupt.is_set():
                                break
                            if chunk_idx == 0:
                                timing.mark_once("tts_first_pcm")
                                timing.mark_once(
                                    "chat_first_audio_ms",
                                )
                            debug_capture.add_audio_chunk(tts_chunk)
                            timing.add_count("tts_chunks", 1)
                            timing.add_count(
                                "tts_samples",
                                int(np.asarray(tts_chunk.data).size),
                            )
                            envelope = _SpeechChunkEnvelope(idx=chunk_idx, chunk=tts_chunk)
                            self._ensure_render_chunk_event(chunk_idx)
                            await render_queue.put(envelope)
                            await audio_queue.put(envelope)
                            chunk_idx += 1
                            enqueued += 1
                            sentence_enqueued += 1
                        return enqueued

                    try:
                        return await _enqueue_from_tts(tts)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        if (
                            self._read_int_env("OPENTALKING_TTS_EDGE_FALLBACK_ON_EMPTY_ERROR", 1) <= 0
                            or self._interrupt.is_set()
                            or sentence_enqueued > 0
                        ):
                            raise
                        log.warning(
                            "primary TTS failed before sentence audio completed; "
                            "falling back to Edge voice for session %s",
                            self.session_id,
                            exc_info=True,
                        )
                        fallback_voice = os.environ.get(
                            "OPENTALKING_TTS_EDGE_FALLBACK_VOICE",
                            "zh-CN-XiaoxiaoNeural",
                        ).strip() or "zh-CN-XiaoxiaoNeural"
                        fallback_tts = build_tts_adapter(
                            sample_rate=int(self.avatar_state.manifest.sample_rate),
                            chunk_ms=self._speech_chunk_ms(),
                            settings=self._tts_settings,
                            default_voice=fallback_voice,
                            tts_provider="edge",
                            tts_model=None,
                        )
                        timing.add_count("tts_edge_fallbacks", 1)
                        return await _enqueue_from_tts(fallback_tts)

                # 首句尽早送 TTS：拿到 N 个字或软标点（，；：、）就提交
                first_sentence_min_chars = self._read_int_env(
                    "OPENTALKING_CHAT_FIRST_SENT_MIN_CHARS", 6
                )
                first_sentence_max_chars = self._read_int_env(
                    "OPENTALKING_CHAT_FIRST_SENT_MAX_CHARS", 20
                )
                soft_punct = "，；：、,;:"
                first_sentence_committed = False

                def _try_commit_first_sentence() -> str | None:
                    """在没有硬标点的情况下，从 splitter 内部 buffer 里抢一段当首句。"""
                    if first_sentence_committed:
                        return None
                    buf = splitter._buffer  # noqa: SLF001 — 只读访问
                    if not buf:
                        return None
                    buf_len = len(buf)
                    # 优先在软标点处切
                    if buf_len >= first_sentence_min_chars:
                        for i, ch in enumerate(buf):
                            if i + 1 >= first_sentence_min_chars and ch in soft_punct:
                                head = buf[: i + 1].strip()
                                splitter._buffer = buf[i + 1 :]
                                return head or None
                    # 没软标点但已积累很多 → 强切
                    if buf_len >= first_sentence_max_chars:
                        head = buf[:first_sentence_max_chars].strip()
                        splitter._buffer = buf[first_sentence_max_chars:]
                        return head or None
                    return None

                try:
                    llm_started_at = _time.perf_counter()
                    first_token_marked = False
                    async for delta in llm.chat_stream(conversation.get_messages()):
                        if self._interrupt.is_set():
                            break
                        if not first_token_marked:
                            timing.mark_once("llm_first_token")
                            timing.add_duration(
                                "llm_first_token_s",
                                _time.perf_counter() - llm_started_at,
                            )
                            first_token_marked = True
                        full_response_parts.append(delta)
                        for sentence in splitter.feed(delta):
                            first_sentence_committed = True
                            await _enqueue_sentence(sentence)
                            if self._interrupt.is_set():
                                break
                        if not first_sentence_committed:
                            early = _try_commit_first_sentence()
                            if early:
                                first_sentence_committed = True
                                await _enqueue_sentence(early)
                    if not self._interrupt.is_set():
                        tail = splitter.flush()
                        if tail:
                            await _enqueue_sentence(tail)
                    timing.add_duration(
                        "llm_total_s",
                        _time.perf_counter() - llm_started_at,
                    )
                    finish_workers_gracefully = not self._interrupt.is_set()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    await publish_event(
                        self.redis,
                        self.session_id,
                        "error",
                        {
                            "session_id": self.session_id,
                            "code": "CHAT_FAILED",
                            "message": str(exc),
                        },
                    )
                    raise
                finally:
                    if not finish_workers_gracefully:
                        self._speech_video_ready.set()
                        self._release_render_chunk_events()
                    await asyncio.gather(
                        asyncio.shield(self._put_queue_sentinel(render_queue)),
                        asyncio.shield(self._put_queue_sentinel(audio_queue)),
                    )
                    # 即便正常路径也加超时，防止 worker 内部出意外时无限等下去。
                    graceful_timeout = 30.0 if finish_workers_gracefully else 5.0
                    try:
                        worker_results = await asyncio.wait_for(
                            asyncio.gather(render_task, audio_task, return_exceptions=True),
                            timeout=graceful_timeout,
                        )
                    except asyncio.TimeoutError:
                        log.warning(
                            "chat worker drain timeout (%.1fs) session=%s; cancelling",
                            graceful_timeout,
                            self.session_id,
                        )
                        render_task.cancel()
                        audio_task.cancel()
                        worker_results = await asyncio.gather(
                            render_task, audio_task, return_exceptions=True
                        )
                    for result in worker_results:
                        if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                            log.warning(
                                "chat worker ended with error for session %s: %r",
                                self.session_id,
                                result,
                            )
                    try:
                        out_dir = debug_capture.finalize()
                        if out_dir is not None:
                            log.info("chat debug dump saved: %s", out_dir)
                    except Exception:  # noqa: BLE001
                        log.warning("failed to finalize chat debug dump", exc_info=True)
                    self._render_chunk_events.clear()
                    self._render_chunk_audio_events.clear()
                    self._speaking = False

                full_response_raw = "".join(full_response_parts).strip()
                full_response = sanitize_tts_text(full_response_raw)
                if full_response:
                    conversation.add_assistant(full_response)
                    await publish_event(
                        self.redis,
                        self.session_id,
                        "assistant.message",
                        {"session_id": self.session_id, "text": full_response},
                    )

                await self._publish_speech_ended()
                if not self._closed:
                    await set_session_state(self.redis, self.session_id, "ready")
            finally:
                if enqueue_unix is not None:
                    timing.add_duration(
                        "chat_first_audio_e2e_s",
                        _time.perf_counter() - chat_started_at,
                    )
                log.info(
                    "chat timing summary: %s",
                    timing.to_json(
                        mark_order=[
                            "llm_first_token",
                            "tts_first_pcm",
                            "first_render_chunk_ready",
                            "first_video_frame_enqueued",
                            "first_audio_chunk_enqueued",
                        ],
                        counter_order=[
                            "llm_first_token_s",
                            "llm_total_s",
                            "tts_chunks",
                            "tts_samples",
                            "render_total_s",
                            "render_prepare_s",
                            "render_feature_s",
                            "render_chunks",
                            "render_frames",
                            "audio_preroll_wait_s",
                            "audio_preroll_chunks",
                            "audio_chunks",
                            "audio_samples",
                        ],
                    ),
                )
                self._active_timing = None

    async def interrupt(self) -> None:
        self._interrupt.set()
        tasks = [task for task in self.speech_tasks if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=3.0)
            except asyncio.TimeoutError:
                log.warning("interrupt wait timed out for session %s", self.session_id)
        self._speaking = False
        self._speech_video_ready.set()
        self._release_render_chunk_events()
        await self._publish_speech_ended()
        if not self._closed:
            await set_session_state(self.redis, self.session_id, "ready")

    async def idle_tick(self) -> None:
        if not self.webrtc or not self.avatar_state:
            return
        if self._idle_frame_cache:
            entry = self._next_idle_cache_entry()
            frame = VideoFrameData(
                data=entry.data,
                width=entry.width,
                height=entry.height,
                timestamp_ms=self._frame_idx * (1000.0 / max(1.0, float(self.avatar_state.manifest.fps))),
            )
        else:
            frame = self.adapter.idle_frame(self.avatar_state, self._frame_idx)
        self._frame_idx += 1
        await self.webrtc.video.put(frame)

    async def close(self) -> None:
        self._closed = True
        await self.interrupt()
        if self._idle_task:
            self._idle_task.cancel()
            try:
                await self._idle_task
            except asyncio.CancelledError:
                pass
        if self._render_executor is not None:
            try:
                self._render_executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                self._render_executor.shutdown(wait=False)
            self._render_executor = None
        if self.webrtc:
            await self.webrtc.close()
        await set_session_state(self.redis, self.session_id, "closed")
