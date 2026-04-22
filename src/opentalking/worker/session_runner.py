from __future__ import annotations

import asyncio
import logging
import time as _time
from pathlib import Path
from typing import Any

import numpy as np

from opentalking.core.session_store import set_session_state
from opentalking.models.registry import get_adapter
from opentalking.rtc.aiortc_adapter import WebRTCSession
from opentalking.tts.factory import create_tts_adapter
from opentalking.worker.bus import publish_event
from opentalking.worker.pipeline.render_pipeline import render_audio_chunk
from opentalking.worker.text_sanitize import strip_emoji

log = logging.getLogger(__name__)


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
    ) -> None:
        self.session_id = session_id
        self.avatar_id = avatar_id
        self.model_type = model_type
        self.avatars_root = avatars_root
        self.redis = redis
        self.device = device
        self.adapter = get_adapter(model_type)
        self.avatar_state: Any = None
        self.webrtc: WebRTCSession | None = None
        self.ready_event = asyncio.Event()
        self.speech_tasks: set[asyncio.Task[None]] = set()
        self._frame_idx = 0
        self._speak_lock = asyncio.Lock()
        self._interrupt = asyncio.Event()
        self._speaking = False
        self._speech_started = False
        self._closed = False
        self._idle_task: asyncio.Task[None] | None = None

    def avatar_path(self) -> Path:
        return (self.avatars_root / self.avatar_id).resolve()

    async def prepare(self) -> None:
        self.adapter.load_model(self.device)
        self.avatar_state = self.adapter.load_avatar(str(self.avatar_path()))
        fps = float(self.avatar_state.manifest.fps)
        sr = int(self.avatar_state.manifest.sample_rate)
        self.webrtc = WebRTCSession(fps=fps, sample_rate=sr)
        if self._idle_task is None:
            self._idle_task = asyncio.create_task(self._idle_loop())
        self.ready_event.set()

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
        await self.ready_event.wait()
        if not self.webrtc:
            await self.prepare()
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
            self._run_speak_task(text, tts_voice, tts_provider, tts_model, enqueue_unix)
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
        log = logging.getLogger(__name__)
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

    async def _video_sink(self, frame: Any) -> None:
        if self.webrtc:
            await self.webrtc.video.put(frame)

    async def _audio_sink(self, pcm: Any) -> None:
        if self.webrtc:
            arr = np.asarray(pcm)
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

            self._interrupt.clear()
            self._speaking = True
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
            log = logging.getLogger(__name__)
            tts = create_tts_adapter(
                sample_rate=int(self.avatar_state.manifest.sample_rate),
                chunk_ms=400.0,
                default_voice=tts_voice,
                tts_provider=tts_provider,
                tts_model=tts_model,
            )
            try:
                pipeline_t0 = _time.perf_counter()
                tts_started_at = _time.perf_counter()
                chunk_idx = 0
                media_started_sent = False
                async for chunk in tts.synthesize_stream(speech_text):
                    if chunk_idx == 0:
                        log.info(
                            "TTS first chunk in %.0fms",
                            (_time.perf_counter() - tts_started_at) * 1000,
                        )
                    chunk_idx += 1
                    if self._interrupt.is_set():
                        break
                    self._frame_idx = await render_audio_chunk(
                        self.adapter,
                        self.avatar_state,
                        chunk,
                        frame_index_start=self._frame_idx,
                        video_sink=self._video_sink,
                    )
                    if not media_started_sent:
                        media_started_sent = True
                        await publish_event(
                            self.redis,
                            self.session_id,
                            "speech.media_started",
                            {"session_id": self.session_id},
                        )
                    await self._audio_sink(chunk.data)
                log.info(
                    "Speak timing (render path): session=%s wall_ms=%.0f "
                    "tts_chunks=%d text_chars=%d",
                    self.session_id,
                    (_time.perf_counter() - pipeline_t0) * 1000,
                    chunk_idx,
                    len(speech_text),
                )
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
                if hasattr(tts, "aclose"):
                    try:
                        await tts.aclose()
                    except Exception:
                        log.exception("TTS adapter aclose failed")
                self._speaking = False
            await self._publish_speech_ended()
            if not self._closed:
                await set_session_state(self.redis, self.session_id, "ready")

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
        if self.webrtc:
            await self.webrtc.close()
        await set_session_state(self.redis, self.session_id, "closed")
