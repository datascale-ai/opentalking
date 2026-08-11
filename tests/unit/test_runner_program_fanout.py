from __future__ import annotations

import numpy as np
import pytest

from opentalking.core.types.frames import VideoFrameData
from opentalking.pipeline.session.runner import SessionRunner


class _Program:
    def __init__(self) -> None:
        self.video = []
        self.audio = []

    async def offer_video(self, item, **kwargs) -> None:
        self.video.append((item, kwargs))

    async def offer_audio(self, item, rate, **kwargs) -> None:
        self.audio.append((item, rate, kwargs))


@pytest.mark.asyncio
async def test_session_runner_uses_program_without_touching_webrtc() -> None:
    runner = object.__new__(SessionRunner)
    runner.program = _Program()
    runner.webrtc = None
    runner._last_speech_frame = None
    runner._speech_started = False
    runner._speech_media_started = False
    runner._closed = False
    runner.redis = None
    runner.session_id = "sess"

    frame = VideoFrameData(np.zeros((2, 2, 3), dtype=np.uint8), 2, 2, 0)
    await runner._video_sink(frame)
    await runner._audio_sink(np.zeros(4, dtype=np.int16), 16_000)

    assert runner.program.video[0][0] is frame
    assert runner.program.video[0][1]["source"] == "speech"
    assert runner.program.audio[0][1] == 16_000
