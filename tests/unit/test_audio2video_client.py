from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import threading
import time
from typing import Any

import numpy as np
import pytest

from opentalking.core.interfaces.avatar_asset import AvatarManifest
from opentalking.core.types.frames import VideoFrameData
from opentalking.providers.synthesis.audio2video_client import (
    LocalAudio2VideoClient,
    OmniRTAudio2VideoClient,
    make_audio_chunk,
)


class FakeOmniRTWSClient:
    def __init__(self) -> None:
        self.init_kwargs: dict[str, Any] | None = None
        self.generated: list[np.ndarray] = []
        self.closed_with: bool | None = None
        self.frame_num = 0
        self.motion_frames_num = 0
        self.slice_len = 0
        self.fps = 25
        self.height = 0
        self.width = 0
        self.sample_rate = 16000
        self.audio_chunk_samples = 0

    async def init_session(self, **kwargs: Any) -> dict[str, Any]:
        self.init_kwargs = kwargs
        self.frame_num = 29
        self.motion_frames_num = 1
        self.slice_len = 28
        self.fps = 25
        self.height = 704
        self.width = 416
        self.audio_chunk_samples = 17920
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

    async def generate(self, audio_pcm: np.ndarray) -> list[VideoFrameData]:
        self.generated.append(np.asarray(audio_pcm, dtype=np.int16).copy())
        return [
            VideoFrameData(
                data=np.zeros((2, 4, 3), dtype=np.uint8),
                width=4,
                height=2,
                timestamp_ms=0.0,
            )
        ]

    async def close(self, send_close_msg: bool = True) -> None:
        self.closed_with = send_close_msg


@pytest.mark.asyncio
async def test_omnirt_audio2video_client_delegates_session_generate_and_close(
    tmp_path: Path,
) -> None:
    ws_client = FakeOmniRTWSClient()
    client = OmniRTAudio2VideoClient(ws_client)
    ref = tmp_path / "reference.png"
    ref.write_bytes(b"image")
    audio = np.arange(8, dtype=np.int16)

    init = await client.init_session(
        ref_image=ref,
        wav2lip_postprocess_mode="easy_improved",
        mouth_metadata={"animation": {"mouth_center": [0.5, 0.6]}},
        video_config={"width": 416, "height": 704, "fps": 25},
    )
    frames = await client.generate(audio)
    await client.close()

    assert init["type"] == "init_ok"
    assert ws_client.init_kwargs == {
        "ref_image": ref,
        "wav2lip_postprocess_mode": "easy_improved",
        "mouth_metadata": {"animation": {"mouth_center": [0.5, 0.6]}},
        "video_config": {"width": 416, "height": 704, "fps": 25},
    }
    assert np.array_equal(ws_client.generated[0], audio)
    assert frames[0].width == 4
    assert client.slice_len == 28
    assert client.width == 416
    assert client.height == 704
    assert client.audio_chunk_samples == 17920
    assert ws_client.closed_with is True


@dataclass
class FakeState:
    manifest: AvatarManifest
    extra: dict[str, Any]


class FakeLocalAdapter:
    model_type = "fake"

    def __init__(self) -> None:
        self.loaded_device: str | None = None
        self.loaded_avatar: str | None = None
        self.warmed_state: FakeState | None = None
        self.features_calls: list[tuple[int, int]] = []
        self.infer_calls = 0
        self.composed: list[int] = []

    def load_model(self, device: str = "cuda") -> None:
        self.loaded_device = device

    def load_avatar(self, avatar_path: str) -> FakeState:
        self.loaded_avatar = avatar_path
        return FakeState(
            manifest=AvatarManifest(
                id="fake-avatar",
                model_type="fake",
                fps=25,
                sample_rate=16000,
                width=64,
                height=48,
                version="1.0",
            ),
            extra={},
        )

    def warmup(self, avatar_state: FakeState | None = None) -> None:
        self.warmed_state = avatar_state

    def extract_features_for_stream(self, audio_chunk: Any, avatar_state: FakeState) -> Any:
        self.features_calls.append((int(audio_chunk.sample_rate), int(audio_chunk.data.size)))
        return type("Features", (), {"frame_count": 3})()

    def infer(self, features: Any, avatar_state: FakeState) -> list[str]:
        self.infer_calls += 1
        return ["a", "b", "c"]

    def compose_frame(
        self,
        avatar_state: FakeState,
        frame_idx: int,
        prediction: Any,
    ) -> VideoFrameData:
        self.composed.append(frame_idx)
        data = np.full((48, 64, 3), frame_idx, dtype=np.uint8)
        return VideoFrameData(data=data, width=64, height=48, timestamp_ms=frame_idx * 40.0)


@pytest.mark.asyncio
async def test_local_audio2video_client_wraps_adapter_lifecycle_and_rendering(
    tmp_path: Path,
) -> None:
    adapter = FakeLocalAdapter()
    client = LocalAudio2VideoClient(adapter, device="cuda:2")
    avatar = tmp_path / "avatar"
    avatar.mkdir()
    audio = np.arange(1600, dtype=np.int16)

    init = await client.init_session(avatar_path=avatar)
    await client.prewarm()
    frames = await client.generate(audio)
    await client.close()

    assert adapter.loaded_device == "cuda:2"
    assert adapter.loaded_avatar == str(avatar)
    assert adapter.warmed_state is client.avatar_state
    assert init == {
        "type": "init_ok",
        "frame_num": 1,
        "motion_frames_num": 0,
        "slice_len": 1,
        "fps": 25,
        "height": 48,
        "width": 64,
        "chunk_samples": 640,
    }
    assert adapter.features_calls == [(16000, 1600)]
    assert adapter.infer_calls == 1
    assert adapter.composed == [0, 1, 2]
    assert [frame.timestamp_ms for frame in frames] == [0.0, 40.0, 80.0]
    assert client.frame_index == 3
    assert client.closed is True


@pytest.mark.asyncio
async def test_local_audio2video_client_generate_does_not_block_event_loop(
    tmp_path: Path,
) -> None:
    class SlowLocalAdapter(FakeLocalAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.infer_thread_names: list[str] = []

        def infer(self, features: Any, avatar_state: FakeState) -> list[str]:
            self.infer_thread_names.append(threading.current_thread().name)
            time.sleep(0.08)
            return super().infer(features, avatar_state)

    adapter = SlowLocalAdapter()
    client = LocalAudio2VideoClient(adapter, device="cuda:0")
    avatar = tmp_path / "avatar"
    avatar.mkdir()
    await client.init_session(avatar_path=avatar)

    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        deadline = time.perf_counter() + 0.06
        while time.perf_counter() < deadline:
            await asyncio.sleep(0.01)
            ticks += 1

    await asyncio.gather(
        client.generate(np.arange(1600, dtype=np.int16)),
        ticker(),
    )

    assert ticks >= 3
    assert adapter.infer_thread_names
    assert all(name != threading.current_thread().name for name in adapter.infer_thread_names)


def test_make_audio_chunk_uses_pcm_length_for_duration() -> None:
    chunk = make_audio_chunk(np.zeros(8000, dtype=np.int16), sample_rate=16000)

    assert chunk.sample_rate == 16000
    assert chunk.duration_ms == 500.0


@pytest.mark.asyncio
async def test_local_audio2video_client_accepts_wav2lip_postprocess_mode(
    tmp_path: Path,
) -> None:
    class Wav2LipLikeAdapter(FakeLocalAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.mode: str | None = None

        def set_wav2lip_postprocess_mode(self, mode: str | None) -> None:
            self.mode = mode

    adapter = Wav2LipLikeAdapter()
    client = LocalAudio2VideoClient(adapter, device="cuda:0")
    avatar = tmp_path / "avatar"
    avatar.mkdir()

    await client.init_session(
        avatar_path=avatar,
        wav2lip_postprocess_mode="opentalking_improved",
    )

    assert adapter.mode == "opentalking_improved"
    assert adapter.loaded_avatar == str(avatar)


class FakeQuickTalkLocalAdapter(FakeLocalAdapter):
    model_type = "quicktalk"

    def load_avatar(self, avatar_path: str) -> FakeState:
        self.loaded_avatar = avatar_path
        return FakeState(
            manifest=AvatarManifest(
                id="quicktalk-avatar",
                model_type="quicktalk",
                fps=24,
                sample_rate=16000,
                width=506,
                height=900,
                version="1.0",
            ),
            extra={},
        )


@pytest.mark.asyncio
async def test_local_quicktalk_uses_omnirt_chunk_defaults(tmp_path: Path) -> None:
    adapter = FakeQuickTalkLocalAdapter()
    client = LocalAudio2VideoClient(adapter, device="cuda:0")
    avatar = tmp_path / "avatar"
    avatar.mkdir()

    init = await client.init_session(avatar_path=avatar)

    assert init["fps"] == 25
    assert init["slice_len"] == 28
    assert init["chunk_samples"] == 17920
    assert client.audio_chunk_samples == 17920
