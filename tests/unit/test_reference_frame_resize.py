from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace

import numpy as np
from PIL import Image
import pytest

from opentalking.core.model_config import clear_model_config_cache
from opentalking.media.frame_avatar import resize_reference_image_to_video
from opentalking.pipeline.speak.synthesis_runner import FlashTalkRunner


def test_reference_resize_matches_video_dimensions_without_letterbox() -> None:
    image = Image.new("RGB", (100, 50), (255, 255, 255))
    resized = resize_reference_image_to_video(image, width=80, height=80)

    assert resized.size == (80, 80)
    arr = np.asarray(resized)
    assert arr[0, 0].tolist() == [255, 255, 255]


def test_reference_resize_cover_crops_without_distorting_aspect_ratio() -> None:
    image = Image.new("RGB", (200, 100), (255, 0, 0))
    pixels = image.load()
    for x in range(50, 150):
        for y in range(25, 75):
            pixels[x, y] = (0, 255, 0)

    resized = resize_reference_image_to_video(image, width=100, height=100)

    assert resized.size == (100, 100)
    arr = np.asarray(resized)
    green_mask = (arr[:, :, 1] > 200) & (arr[:, :, 0] < 40) & (arr[:, :, 2] < 40)
    ys, xs = np.where(green_mask)
    assert xs.max() - xs.min() >= 90
    assert ys.max() - ys.min() >= 45


def test_fasterliveportrait_idle_frames_keep_reference_still() -> None:
    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "fasterliveportrait"
    base = np.zeros((64, 64, 3), dtype=np.uint8)
    base[20:44, 24:40] = 255

    frames = runner._build_fasterliveportrait_idle_frames(base)

    assert len(frames) == 1
    assert np.array_equal(frames[0], base)


@pytest.mark.asyncio
async def test_fasterliveportrait_queues_reference_rest_frame_after_speech() -> None:
    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "fasterliveportrait"
    runner.session_id = "sess_rest_frame"
    runner._reference_frame = np.full((4, 5, 3), 7, dtype=np.uint8)
    runner._last_frame = np.full((4, 5, 3), 200, dtype=np.uint8)
    runner._av_ts_ms = 1234.0
    runner._speech_media_active = True
    runner._webrtc_started = SimpleNamespace(is_set=lambda: True)
    runner.webrtc = SimpleNamespace(
        video=SimpleNamespace(_queue=asyncio.Queue(maxsize=4)),
        draining=False,
    )

    await runner._queue_fasterliveportrait_rest_frame()

    queued = await runner.webrtc.video._queue.get()
    assert queued.timestamp_ms == 1234.0
    assert queued.width == 5
    assert queued.height == 4
    assert np.array_equal(queued.data, runner._reference_frame)
    assert queued.data is not runner._reference_frame
    assert np.array_equal(runner._last_frame, runner._reference_frame)
    assert runner._last_frame is not runner._reference_frame


def test_fasterliveportrait_uses_single_chunk_prebuffer_even_for_long_text(
    monkeypatch,
) -> None:
    monkeypatch.delenv("FLASHTALK_PREBUFFER_CHUNKS", raising=False)
    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "fasterliveportrait"
    runner.flashtalk = SimpleNamespace(audio_chunk_samples=16000)

    chunks = runner._prebuffer_chunks(
        speech_text="请连续说一段比较长的中文，用来测试实时数字人的首帧和播放队列稳定性。",
    )

    assert chunks == 1


def test_fasterliveportrait_playback_backpressure_defaults(monkeypatch) -> None:
    monkeypatch.delenv("FLP_PLAYBACK_TARGET_QUEUE_FRAMES", raising=False)
    monkeypatch.delenv("FLP_PLAYBACK_MAX_QUEUE_FRAMES", raising=False)
    monkeypatch.delenv("FLP_PLAYBACK_MAX_WAIT_MS", raising=False)
    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "fasterliveportrait"

    assert runner._playback_backpressure_config() == (8, 24, 900.0)


def test_wav2lip_and_quicktalk_playback_backpressure_defaults(monkeypatch) -> None:
    monkeypatch.delenv("AUDIO2VIDEO_PLAYBACK_TARGET_QUEUE_FRAMES", raising=False)
    monkeypatch.delenv("AUDIO2VIDEO_PLAYBACK_MAX_QUEUE_FRAMES", raising=False)
    monkeypatch.delenv("AUDIO2VIDEO_PLAYBACK_MAX_WAIT_MS", raising=False)

    for model_type in ("wav2lip", "quicktalk"):
        runner = FlashTalkRunner.__new__(FlashTalkRunner)
        runner.model_type = model_type

        assert runner._playback_backpressure_config() == (8, 32, 1200.0)


def test_wav2lip_and_quicktalk_playback_backpressure_accept_env(monkeypatch) -> None:
    monkeypatch.setenv("AUDIO2VIDEO_PLAYBACK_TARGET_QUEUE_FRAMES", "3")
    monkeypatch.setenv("AUDIO2VIDEO_PLAYBACK_MAX_QUEUE_FRAMES", "7")
    monkeypatch.setenv("AUDIO2VIDEO_PLAYBACK_MAX_WAIT_MS", "80")

    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "quicktalk"

    assert runner._playback_backpressure_config() == (3, 7, 80.0)


@pytest.mark.asyncio
async def test_fasterliveportrait_waits_when_playback_queue_is_high(monkeypatch) -> None:
    monkeypatch.setenv("FLP_PLAYBACK_TARGET_QUEUE_FRAMES", "1")
    monkeypatch.setenv("FLP_PLAYBACK_MAX_QUEUE_FRAMES", "4")
    monkeypatch.setenv("FLP_PLAYBACK_MAX_WAIT_MS", "60")
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    queue = asyncio.Queue()
    for item in range(6):
        queue.put_nowait(item)

    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "fasterliveportrait"
    runner.webrtc = SimpleNamespace(
        video=SimpleNamespace(_queue=queue),
        draining=False,
    )
    runner._speech_media_active = True
    runner._webrtc_started = SimpleNamespace(is_set=lambda: True)
    runner._interrupt = SimpleNamespace(is_set=lambda: False)

    waited_ms = await runner._wait_for_playback_capacity(
        n_frames=25,
        first_media_this_speak=False,
    )

    assert waited_ms >= 60.0
    assert len(sleeps) >= 3


def test_fasterliveportrait_enables_tts_opener_by_default(
    monkeypatch,
) -> None:
    monkeypatch.delenv("FLASHTALK_TTS_OPENER_ENABLE", raising=False)
    monkeypatch.delenv("OPENTALKING_FLASHTALK_TTS_OPENER_ENABLE", raising=False)
    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "fasterliveportrait"

    assert runner._tts_opener_enabled_for_model() is True


def test_flashtalk_keeps_tts_opener_disabled_by_default(
    monkeypatch,
) -> None:
    monkeypatch.delenv("FLASHTALK_TTS_OPENER_ENABLE", raising=False)
    monkeypatch.delenv("OPENTALKING_FLASHTALK_TTS_OPENER_ENABLE", raising=False)
    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "flashtalk"

    assert runner._tts_opener_enabled_for_model() is False


def test_fasterliveportrait_preloads_tts_openers_for_default_voice(
    monkeypatch,
) -> None:
    monkeypatch.delenv("FLASHTALK_TTS_OPENER_PRELOAD", raising=False)
    monkeypatch.delenv("OPENTALKING_FLASHTALK_TTS_OPENER_PRELOAD", raising=False)
    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "fasterliveportrait"

    assert runner._tts_opener_preload_voice() == "zh-CN-XiaoxiaoNeural"


def test_fasterliveportrait_video_config_preserves_reference_aspect_ratio(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENTALKING_CONFIG_FILE", str(tmp_path / "missing.yaml"))
    clear_model_config_cache()
    ref_image = tmp_path / "reference.png"
    Image.new("RGB", (830, 1108), (255, 255, 255)).save(ref_image)

    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "fasterliveportrait"

    config = runner._fasterliveportrait_video_config(ref_image)

    assert config is not None
    assert config["width"] == 448
    assert config["height"] == 598

    clear_model_config_cache()


def test_fasterliveportrait_reference_payload_uses_live_video_dimensions(tmp_path) -> None:
    ref_image = tmp_path / "reference.png"
    Image.new("RGB", (830, 1108), (255, 255, 255)).save(ref_image)

    runner = FlashTalkRunner.__new__(FlashTalkRunner)
    runner.model_type = "fasterliveportrait"

    payload = runner._fasterliveportrait_ref_image_payload(
        ref_image,
        {"width": 448, "height": 598},
    )

    assert Image.open(io.BytesIO(payload)).size == (448, 598)
