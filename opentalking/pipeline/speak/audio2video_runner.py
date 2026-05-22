from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from opentalking.core.types.frames import VideoFrameData
from opentalking.providers.synthesis.audio2video_client import Audio2VideoClient


class Audio2VideoRunner:
    """Small shared runner facade around local and OmniRT audio2video clients.

    The full conversation runner still owns LLM, TTS, WebRTC, idle playback, and
    interruption. This class centralizes the model-client lifecycle so Phase 2
    can route both local and OmniRT through one client surface without changing
    user-visible behavior yet.
    """

    def __init__(
        self,
        *,
        session_id: str,
        avatar_id: str,
        model_type: str,
        avatars_root: Path,
        audio2video_client: Audio2VideoClient,
    ) -> None:
        self.session_id = session_id
        self.avatar_id = avatar_id
        self.model_type = model_type
        self.avatars_root = avatars_root
        self.audio2video = audio2video_client
        self._sync_audio2video_attrs()

    def _sync_audio2video_attrs(self) -> None:
        self.frame_num = int(getattr(self.audio2video, "frame_num", 0) or 0)
        self.motion_frames_num = int(getattr(self.audio2video, "motion_frames_num", 0) or 0)
        self.slice_len = int(getattr(self.audio2video, "slice_len", 0) or 0)
        self.fps = int(getattr(self.audio2video, "fps", 25) or 25)
        self.height = int(getattr(self.audio2video, "height", 0) or 0)
        self.width = int(getattr(self.audio2video, "width", 0) or 0)
        self.sample_rate = int(getattr(self.audio2video, "sample_rate", 16000) or 16000)
        self.audio_chunk_samples = int(getattr(self.audio2video, "audio_chunk_samples", 0) or 0)

    async def init_audio2video_session(self, **kwargs: Any) -> dict[str, Any]:
        response = await self.audio2video.init_session(**kwargs)
        self._sync_audio2video_attrs()
        return response

    async def prewarm_audio2video(self) -> dict[str, Any]:
        response = await self.audio2video.prewarm()
        self._sync_audio2video_attrs()
        return response

    async def generate_audio2video(self, audio_pcm: np.ndarray) -> list[VideoFrameData]:
        frames = await self.audio2video.generate(audio_pcm)
        self._sync_audio2video_attrs()
        return frames

    async def close_audio2video(self, send_close_msg: bool = True) -> None:
        try:
            await self.audio2video.close(send_close_msg=send_close_msg)
        except TypeError:
            await self.audio2video.close()
        self._sync_audio2video_attrs()
