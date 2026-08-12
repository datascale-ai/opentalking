from __future__ import annotations

import pytest

from opentalking.streaming.destinations.rtmps import (
    RTMPSPublisher,
    RTMPSSettings,
    _pin_rtmps_url,
    normalize_rtmps_endpoint,
)
from opentalking.streaming.types import ProgramAudio, ProgramVideo
import numpy as np


def test_rtmps_endpoint_rejects_secret_url_components() -> None:
    with pytest.raises(ValueError):
        normalize_rtmps_endpoint("rtmps://user:pass@example.com/live", allow_local=True)
    with pytest.raises(ValueError):
        normalize_rtmps_endpoint("rtmps://example.com/live?stream_key=secret", allow_local=True)
    with pytest.raises(ValueError):
        normalize_rtmps_endpoint("rtmps://example.com/live/%2F", allow_local=True)


@pytest.mark.asyncio
async def test_rtmps_start_validates_before_creating_task() -> None:
    publisher = RTMPSPublisher(
        RTMPSSettings(endpoint="rtmps://example.com/live", stream_key="bad/key", allow_local=True)
    )
    with pytest.raises(ValueError):
        await publisher.start()
    assert publisher._task is None


@pytest.mark.asyncio
async def test_rtmps_rejects_local_dns_without_test_allowlist() -> None:
    publisher = RTMPSPublisher(
        RTMPSSettings(endpoint="rtmps://localhost:1936/live", stream_key="key", allow_local=False)
    )
    with pytest.raises(ValueError, match="private/local"):
        await publisher.start()


@pytest.mark.asyncio
async def test_rtmps_runtime_error_has_bounded_reconnect() -> None:
    publisher = RTMPSPublisher(
        RTMPSSettings(
            endpoint="rtmps://localhost:1936/live",
            stream_key="key",
            allow_local=True,
            reconnect_max_attempts=1,
            reconnect_max_delay_sec=0,
        )
    )
    calls = 0

    async def fake_write(item) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("downstream unavailable")

    publisher._write_video = fake_write  # type: ignore[method-assign]
    await publisher._queue.put(("video", ProgramVideo(np.zeros((2, 2, 3), dtype=np.uint8), 2, 2, 0)))
    await publisher._queue.put(None)
    await publisher._run()

    assert calls == 1
    assert publisher.state == "disconnected"


@pytest.mark.asyncio
async def test_rtmps_pyav_path_emits_h264_and_aac(tmp_path, monkeypatch) -> None:
    import av

    output = tmp_path / "capture.flv"
    original_open = av.open
    monkeypatch.setattr(
        "opentalking.streaming.destinations.rtmps._verify_tls_peer",
        lambda *args: None,
    )
    monkeypatch.setattr(
        av,
        "open",
        lambda *args, **kwargs: original_open(output, mode="w", format="flv"),
    )
    publisher = RTMPSPublisher(
        RTMPSSettings(endpoint="rtmps://localhost:1936/live", stream_key="key", allow_local=True)
    )
    await publisher.start()
    await publisher.video(ProgramVideo(np.zeros((64, 64, 3), dtype=np.uint8), 64, 64, 0))
    await publisher.audio(ProgramAudio(np.zeros(960, dtype=np.int16), 48_000, 0))
    await publisher._queue.put(None)
    await publisher._task

    probe = original_open(output, mode="r")
    try:
        codecs = {stream.codec.name for stream in probe.streams}
    finally:
        probe.close()
    assert {"h264", "aac"}.issubset(codecs)


def test_rtmps_pinned_url_keeps_structured_credentials_and_path() -> None:
    settings = RTMPSSettings(
        endpoint="rtmps://stream.example/live",
        stream_key="demo",
        username="publisher",
        password="secret",
        allow_local=True,
    )
    assert _pin_rtmps_url(settings, "203.0.113.10") == (
        "rtmps://203.0.113.10/live/demo?user=publisher&pass=secret"
    )
