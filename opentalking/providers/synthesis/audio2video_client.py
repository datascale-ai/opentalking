from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import inspect
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import numpy as np

from opentalking.core.interfaces.model_adapter import ModelAdapter
from opentalking.core.types.frames import AudioChunk, VideoFrameData
from opentalking.pipeline.speak.render_pipeline import render_audio_chunk_sync


def make_audio_chunk(audio_pcm: np.ndarray, *, sample_rate: int = 16000) -> AudioChunk:
    """Build an AudioChunk from int16 PCM and derive duration from sample count."""
    pcm = np.asarray(audio_pcm, dtype=np.int16).reshape(-1)
    duration_ms = 0.0
    if sample_rate > 0:
        duration_ms = 1000.0 * float(pcm.size) / float(sample_rate)
    return AudioChunk(data=pcm, sample_rate=int(sample_rate), duration_ms=duration_ms)


@runtime_checkable
class Audio2VideoClient(Protocol):
    """Common realtime audio-to-video client contract for local and OmniRT backends."""

    frame_num: int
    motion_frames_num: int
    slice_len: int
    fps: int
    height: int
    width: int
    sample_rate: int
    audio_chunk_samples: int

    async def connect(self) -> None:
        """Connect to the remote runtime when the backend needs a socket."""

    async def init_session(self, **kwargs: Any) -> dict[str, Any]:
        """Initialize one avatar/model session and populate runtime attributes."""

    async def prewarm(self) -> dict[str, Any]:
        """Prepare runtime/avatar state before first user utterance."""

    async def generate(self, audio_pcm: np.ndarray) -> list[VideoFrameData]:
        """Generate video frames from one int16 PCM chunk."""

    async def close(self, send_close_msg: bool = True) -> None:
        """Release any session resources held by the client."""


class OmniRTAudio2VideoClient:
    """Audio2VideoClient wrapper for OmniRT's FlashTalk-compatible WS client."""

    def __init__(self, ws_client: Any) -> None:
        self._ws_client = ws_client
        self._sync_attrs()

    def _sync_attrs(self) -> None:
        self.frame_num = int(getattr(self._ws_client, "frame_num", 0) or 0)
        self.motion_frames_num = int(getattr(self._ws_client, "motion_frames_num", 0) or 0)
        self.slice_len = int(getattr(self._ws_client, "slice_len", 0) or 0)
        self.fps = int(getattr(self._ws_client, "fps", 25) or 25)
        self.height = int(getattr(self._ws_client, "height", 0) or 0)
        self.width = int(getattr(self._ws_client, "width", 0) or 0)
        self.sample_rate = int(getattr(self._ws_client, "sample_rate", 16000) or 16000)
        self.audio_chunk_samples = int(getattr(self._ws_client, "audio_chunk_samples", 0) or 0)

    async def init_session(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("avatar_path", None)
        init_session = getattr(self._ws_client, "init_session")
        response = await init_session(**kwargs)
        self._sync_attrs()
        return dict(response or {})

    async def connect(self) -> None:
        connect = getattr(self._ws_client, "connect", None)
        if not callable(connect):
            return
        response = connect()
        if inspect.isawaitable(response):
            await response
        self._sync_attrs()

    async def prewarm(self) -> dict[str, Any]:
        prewarm = getattr(self._ws_client, "prewarm", None)
        if not callable(prewarm):
            return {"type": "prewarm_skipped", "reason": "unsupported"}
        response = prewarm()
        if inspect.isawaitable(response):
            response = await response
        self._sync_attrs()
        return dict(response or {})

    async def generate(self, audio_pcm: np.ndarray) -> list[VideoFrameData]:
        frames = await self._ws_client.generate(audio_pcm)
        return list(frames or [])

    async def close(self, send_close_msg: bool = True) -> None:
        close = getattr(self._ws_client, "close", None)
        if not callable(close):
            return
        response = close(send_close_msg=send_close_msg)
        if inspect.isawaitable(response):
            await response
        self._sync_attrs()


class LocalAudio2VideoClient:
    """Audio2VideoClient wrapper around an in-process ModelAdapter."""

    def __init__(
        self,
        adapter: ModelAdapter,
        *,
        device: str = "cuda",
        sample_rate: int = 16000,
    ) -> None:
        self.adapter = adapter
        self.device = device
        self.sample_rate = int(sample_rate)
        self.avatar_state: Any | None = None
        self.frame_index = 0
        self.speech_frame_index = 0
        self.closed = False
        self.frame_num = 0
        self.motion_frames_num = 0
        self.slice_len = 0
        self.fps = 25
        self.height = 0
        self.width = 0
        self.audio_chunk_samples = 0
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=f"local-audio2video-{adapter.__class__.__name__.lower()}",
        )

    async def _run_sync(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            lambda: func(*args, **kwargs),
        )

    async def init_session(
        self,
        *,
        avatar_path: str | Path,
        wav2lip_postprocess_mode: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        if wav2lip_postprocess_mode is not None:
            setter = getattr(self.adapter, "set_wav2lip_postprocess_mode", None)
            if callable(setter):
                await self._run_sync(setter, wav2lip_postprocess_mode)

        await self._run_sync(self.adapter.load_model, self.device)
        self.avatar_state = await self._run_sync(self.adapter.load_avatar, str(avatar_path))
        self.frame_index = 0
        self.speech_frame_index = 0
        self.closed = False
        self._sync_attrs_from_state()
        return {
            "type": "init_ok",
            "frame_num": self.frame_num,
            "motion_frames_num": self.motion_frames_num,
            "slice_len": self.slice_len,
            "fps": self.fps,
            "height": self.height,
            "width": self.width,
            "chunk_samples": self.audio_chunk_samples,
        }

    def _sync_attrs_from_state(self) -> None:
        state = self.avatar_state
        manifest = getattr(state, "manifest", None)
        self.fps = int(getattr(manifest, "fps", self.fps) or self.fps)
        self.height = int(getattr(manifest, "height", self.height) or self.height)
        self.width = int(getattr(manifest, "width", self.width) or self.width)
        self.sample_rate = int(getattr(manifest, "sample_rate", self.sample_rate) or self.sample_rate)
        self.audio_chunk_samples = max(1, int(round(float(self.sample_rate) / max(1, self.fps))))

        session = getattr(state, "session", None)
        video = getattr(session, "video", None)
        audio = getattr(session, "audio", None)
        if video is not None:
            self.frame_num = int(getattr(video, "frame_count", self.frame_num) or self.frame_num)
            self.motion_frames_num = int(
                getattr(video, "motion_frames_num", self.motion_frames_num) or self.motion_frames_num
            )
            self.slice_len = int(getattr(video, "slice_len", self.slice_len) or self.slice_len)
            self.fps = int(getattr(video, "fps", self.fps) or self.fps)
            self.height = int(getattr(video, "height", self.height) or self.height)
            self.width = int(getattr(video, "width", self.width) or self.width)
        if audio is not None:
            self.sample_rate = int(getattr(audio, "sample_rate", self.sample_rate) or self.sample_rate)
            self.audio_chunk_samples = int(
                getattr(audio, "chunk_samples", self.audio_chunk_samples) or self.audio_chunk_samples
            )
        if self.frame_num <= 0:
            frames = getattr(state, "frames", None)
            self.frame_num = len(frames) if frames is not None else 1
        if self._is_quicktalk_adapter():
            self.fps = 25
            if self.slice_len <= 0:
                self.slice_len = 28
            self.audio_chunk_samples = max(
                1,
                int(round(float(self.sample_rate) * float(self.slice_len) / max(1, self.fps))),
            )
        if self.slice_len <= 0:
            self.slice_len = max(1, int(round(self.audio_chunk_samples * self.fps / self.sample_rate)))

    def _is_quicktalk_adapter(self) -> bool:
        adapter_model_type = str(getattr(self.adapter, "model_type", "") or "").strip().lower()
        if adapter_model_type == "quicktalk":
            return True
        state = self.avatar_state
        manifest = getattr(state, "manifest", None)
        manifest_model_type = str(getattr(manifest, "model_type", "") or "").strip().lower()
        if manifest_model_type == "quicktalk":
            return True
        return self.adapter.__class__.__name__.lower().startswith("quicktalk")

    async def prewarm(self) -> dict[str, Any]:
        if self.avatar_state is None:
            raise RuntimeError("init_session() must be called before prewarm()")
        warmup = getattr(self.adapter, "warmup", None)
        if callable(warmup):
            await self._run_sync(warmup, self.avatar_state)
        return {"type": "prewarm_ok"}

    async def connect(self) -> None:
        return None

    async def generate(self, audio_pcm: np.ndarray) -> list[VideoFrameData]:
        if self.avatar_state is None:
            raise RuntimeError("init_session() must be called before generate()")
        chunk = make_audio_chunk(audio_pcm, sample_rate=self.sample_rate)
        next_frame_index, frames = await self._run_sync(
            render_audio_chunk_sync,
            self.adapter,
            self.avatar_state,
            chunk,
            frame_index_start=self.frame_index,
            speech_frame_index_start=self.speech_frame_index,
        )
        self.frame_index = next_frame_index
        self.speech_frame_index += len(frames)
        return frames

    async def close(self, send_close_msg: bool = True) -> None:
        del send_close_msg
        close = getattr(self.adapter, "close", None)
        if callable(close):
            response = await self._run_sync(close)
            if inspect.isawaitable(response):
                await response
        self._executor.shutdown(wait=False, cancel_futures=True)
        self.closed = True
