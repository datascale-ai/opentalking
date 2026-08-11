from __future__ import annotations

import pytest

from opentalking.streaming.destinations.rtmps import RTMPSPublisher, RTMPSSettings, normalize_rtmps_endpoint


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

