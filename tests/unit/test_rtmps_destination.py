from __future__ import annotations

import pytest

from opentalking.streaming.destinations.rtmps import RTMPSPublisher, RTMPSSettings, normalize_rtmps_endpoint
from opentalking.streaming.types import ProgramVideo
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
