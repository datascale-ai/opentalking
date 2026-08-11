from __future__ import annotations

import pytest

from opentalking.streaming.destinations.whip import WHIPPublisher, WHIPSettings


@pytest.mark.asyncio
async def test_whip_requires_bearer_and_https() -> None:
    publisher = WHIPPublisher(
        WHIPSettings(
            endpoint="http://localhost:8889/whip",
            bearer_token="token",
            allow_local=True,
        )
    )
    with pytest.raises(ValueError, match="unsupported target scheme"):
        await publisher.start()

    missing_token = WHIPPublisher(
        WHIPSettings(
            endpoint="https://localhost:8889/whip",
            bearer_token="",
            allow_local=True,
        )
    )
    with pytest.raises(ValueError, match="bearer_token"):
        await missing_token.start()


def test_whip_track_uses_independent_tracks() -> None:
    publisher = WHIPPublisher(
        WHIPSettings(
            endpoint="https://localhost:8889/whip",
            bearer_token="token",
            allow_local=True,
        )
    )
    assert publisher.video_track is not publisher.audio_track
    assert publisher.video_track.kind == "video"
    assert publisher.audio_track.kind == "audio"
