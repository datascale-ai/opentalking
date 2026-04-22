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
from opentalking.models.registry import get_adapter
from opentalking.rtc.aiortc_adapter import WebRTCSession
from opentalking.tts import build_tts_adapter
from opentalking.models.wav2lip.official_runtime import (
    load_video_frames,
    official_runtime_available,
    run_official_inference,
)
from opentalking.worker.bus import publish_event
from opentalking.worker.pipeline.render_pipeline import (
    render_audio_chunk_sync,
    reset_avatar_speech_state,
)
from opentalking.worker.text_sanitize import strip_emoji
from opentalking.worker.timing import SpeechTiming

log = logging.getLogger(__name__)
_SETTINGS = get_settings()


@dataclass(frozen=True)
class _SpeechChunkEnvelope:
    idx: int
    chunk: AudioChunk
    lookahead_chunk: AudioChunk | None = None
    is_final: bool = False


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
            writer = cv2.VideoWriter(
                str(silent_path),
                cv2.VideoWriter_fourcc(*"mp4v"),
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
        self._frame_idx = 0
        self._speech_frame_idx = 0
        self._speak_lock = asyncio.Lock()
        self._interrupt = asyncio.Event()
        self._speech_video_ready = asyncio.Event()
        self._render_chunk_events: dict[int, asyncio.Event] = {}
        self._speaking = False
        self._speech_started = False
        self._closed = False
        self._idle_task: asyncio.Task[None] | None = None
        self._rtc_sample_rate = int(os.environ.get("OPENTALKING_RTC_SAMPLE_RATE") or "0")
        self._render_chunk_ms = float(os.environ.get("OPENTALKING_RENDER_CHUNK_MS", "320.0"))
        self._audio_preroll_timeout_ms = float(
            os.environ.get("OPENTALKING_AV_SYNC_AUDIO_PREROLL_TIMEOUT_MS", "1200.0")
        )
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

    def _resolve_audio_preroll_chunks(self) -> int:
        generic = self._read_int_env("OPENTALKING_AV_SYNC_PREROLL_CHUNKS", 0)
        if generic > 0:
            return max(1, generic)
        if self.model_type == "musetalk":
            return max(1, self._read_int_env("OPENTALKING_MUSETALK_PREBUFFER_CHUNKS", 3))
        if self.model_type == "wav2lip":
            return max(1, self._read_int_env("OPENTALKING_WAV2LIP_PREBUFFER_CHUNKS", 2))
        return 1

    async def prepare(self) -> None:
        self.adapter.load_model(self.device)
        self.avatar_state = self.adapter.load_avatar(str(self.avatar_path()))
        self.adapter.warmup()
        fps = float(self.avatar_state.manifest.fps)
        if self._rtc_sample_rate <= 0:
            self._rtc_sample_rate = int(self.avatar_state.manifest.sample_rate)
        self.webrtc = WebRTCSession(
            fps=fps,
            sample_rate=self._rtc_sample_rate,
            mode="buffered",
        )
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
        if not self.ready_event.is_set() or not self.webrtc:
            await self.prepare()
        else:
            await self.ready_event.wait()
        assert self.webrtc is not None
        ans = await self.webrtc.handle_offer(sdp, type_)
        return {"sdp": ans.sdp, "type": ans.type}

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

    async def _video_sink(self, frame: VideoFrameData) -> None:
        if self.webrtc:
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

    def _ensure_render_chunk_event(self, chunk_idx: int) -> asyncio.Event:
        event = self._render_chunk_events.get(chunk_idx)
        if event is None:
            event = asyncio.Event()
            self._render_chunk_events[chunk_idx] = event
        return event

    def _mark_render_chunk_ready(self, chunk_idx: int) -> None:
        self._ensure_render_chunk_event(chunk_idx).set()

    async def _wait_for_render_chunk(self, chunk_idx: int) -> None:
        await self._ensure_render_chunk_event(chunk_idx).wait()

    def _release_render_chunk_events(self) -> None:
        for event in self._render_chunk_events.values():
            event.set()

    async def _render_chunk_worker(
        self,
        queue: asyncio.Queue[_SpeechChunkEnvelope | None],
        debug_capture: _SpeechDebugCapture | None = None,
    ) -> None:
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

    async def _audio_chunk_worker(
        self,
        queue: asyncio.Queue[_SpeechChunkEnvelope | None],
    ) -> None:
        audio_started = False
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
            await self._wait_for_render_chunk(item.idx)
            audio_started_at = _time.perf_counter()
            await self._audio_sink(item.chunk.data, item.chunk.sample_rate)
            if timing is not None:
                timing.mark_once("first_audio_chunk_enqueued")
                timing.add_duration("audio_enqueue_total_s", _time.perf_counter() - audio_started_at)
                timing.add_count("audio_chunks", 1)
                timing.add_count("audio_samples", int(np.asarray(item.chunk.data).size))
            self._render_chunk_events.pop(item.idx, None)

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
        if self.model_type == "wav2lip" and self._wav2lip_live_mode not in {"official", "auto"}:
            return float(os.environ.get("OPENTALKING_WAV2LIP_RENDER_CHUNK_MS", "200.0"))
        return self._render_chunk_ms

    async def _speak_wav2lip_official(
        self,
        speech_text: str,
        debug_capture: _SpeechDebugCapture,
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

    async def speak(self, text: str) -> None:
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
                self._interrupt.clear()
                self._speech_video_ready.clear()
                self._render_chunk_events = {}
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
                try:
                    official_done = await self._speak_wav2lip_official(speech_text, debug_capture)
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
                    self._speech_video_ready.set()
                    self._release_render_chunk_events()
                    await asyncio.gather(
                        asyncio.shield(self._put_queue_sentinel(render_queue)),
                        asyncio.shield(self._put_queue_sentinel(audio_queue)),
                    )
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
            self._render_executor.shutdown(wait=False, cancel_futures=True)
            self._render_executor = None
        if self.webrtc:
            await self.webrtc.close()
        await set_session_state(self.redis, self.session_id, "closed")
