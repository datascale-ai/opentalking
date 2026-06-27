from __future__ import annotations

import numpy as np
import pytest

from opentalking.core.types.frames import VideoFrameData
from opentalking.pipeline.speak.audio2video_runner import Audio2VideoRunner


class FakeAudio2VideoClient:
    def __init__(self) -> None:
        self.frame_num = 29
        self.motion_frames_num = 1
        self.slice_len = 28
        self.fps = 25
        self.height = 704
        self.width = 416
        self.sample_rate = 16000
        self.audio_chunk_samples = 17920
        self.init_kwargs = None
        self.prewarmed = False
        self.generated = []
        self.closed = False

    async def init_session(self, **kwargs):
        self.init_kwargs = kwargs
        return {"type": "init_ok"}

    async def prewarm(self):
        self.prewarmed = True
        return {"type": "prewarm_ok"}

    async def generate(self, audio_pcm):
        self.generated.append(np.asarray(audio_pcm, dtype=np.int16).copy())
        return [
            VideoFrameData(
                data=np.zeros((self.height, self.width, 3), dtype=np.uint8),
                width=self.width,
                height=self.height,
                timestamp_ms=0.0,
            )
        ]

    async def close(self, send_close_msg=True):
        self.send_close_msg = send_close_msg
        self.closed = True


@pytest.mark.asyncio
async def test_audio2video_runner_prepares_generates_and_closes(tmp_path):
    client = FakeAudio2VideoClient()
    runner = Audio2VideoRunner(
        session_id="sess_a2v",
        avatar_id="singer",
        model_type="wav2lip",
        avatars_root=tmp_path,
        audio2video_client=client,
    )
    ref = tmp_path / "reference.png"
    ref.write_bytes(b"image")
    pcm = np.arange(8, dtype=np.int16)

    await runner.init_audio2video_session(ref_image=ref, video_config={"fps": 25})
    await runner.prewarm_audio2video()
    frames = await runner.generate_audio2video(pcm)
    await runner.close_audio2video()

    assert client.init_kwargs == {"ref_image": ref, "video_config": {"fps": 25}}
    assert client.prewarmed is True
    assert np.array_equal(client.generated[0], pcm)
    assert frames[0].width == 416
    assert runner.fps == 25
    assert runner.width == 416
    assert runner.audio_chunk_samples == 17920
    assert client.closed is True
