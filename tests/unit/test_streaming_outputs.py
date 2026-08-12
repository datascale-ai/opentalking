from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from opentalking.core.in_memory_redis import InMemoryRedis
from opentalking.streaming.outputs import SessionOutputController
from opentalking.streaming.destinations.rtmps import RTMPSSettings, build_rtmps_url, validate_stream_key
from opentalking.streaming.security import validate_target_url


class _FakeProgram:
    def __init__(self) -> None:
        self.added: dict[str, object] = {}
        self.removed: list[str] = []

    def add_branch(self, name: str, **callbacks) -> None:
        self.added[name] = callbacks

    def remove_branch(self, name: str) -> None:
        self.removed.append(name)
        self.added.pop(name, None)


@pytest.mark.asyncio
async def test_output_controller_does_not_expose_secrets_and_enforces_idempotency(monkeypatch) -> None:
    class Publisher:
        def __init__(self, settings) -> None:
            self.settings = settings
            self.state = "created"
            self.health = "unknown"
            self.last_error = None

        async def start(self) -> None:
            self.state = "connected"

        async def stop(self) -> None:
            self.state = "disconnected"

        async def video(self, item) -> None:
            del item

        async def audio(self, item) -> None:
            del item

    monkeypatch.setattr("opentalking.streaming.outputs.RTMPSPublisher", Publisher)
    settings = SimpleNamespace(
        streaming_allow_local_targets=True,
        streaming_test_auth_bypass=True,
        streaming_rtmps_ca_file="",
        streaming_video_fps=25,
        streaming_max_outputs_per_session=4,
        streaming_audio_sample_rate=48000,
        streaming_audio_tick_ms=20,
    )
    controller = SessionOutputController(session_id="sess", program=_FakeProgram(), settings=settings)
    body = {
        "type": "rtmps",
        "name": "local",
        "auto_connect": True,
        "transport": {
            "endpoint": "rtmps://localhost:1936/live",
            "stream_key": "secret-key",
            "password": "do-not-return",
        },
    }
    record = await controller.create(body, idempotency_key="k1")
    again = await controller.create(body, idempotency_key="k1")
    assert record.output_id == again.output_id
    public = record.public()
    assert public["secret_configured"] is True
    assert "secret-key" not in str(public)
    assert "do-not-return" not in str(public)

    with pytest.raises(ValueError, match="different payload"):
        await controller.create({**body, "name": "changed"}, idempotency_key="k1")
    await controller.close()


@pytest.mark.asyncio
async def test_output_profile_cannot_silently_change_program_fps(monkeypatch) -> None:
    class Publisher:
        def __init__(self, settings) -> None:
            self.state = "created"
            self.health = "unknown"
            self.last_error = None

        async def start(self) -> None:
            self.state = "connected"

        async def stop(self) -> None:
            self.state = "disconnected"

        async def video(self, item) -> None:
            del item

        async def audio(self, item) -> None:
            del item

    monkeypatch.setattr("opentalking.streaming.outputs.RTMPSPublisher", Publisher)
    settings = SimpleNamespace(
        streaming_allow_local_targets=True,
        streaming_test_auth_bypass=True,
        streaming_rtmps_ca_file="",
        streaming_video_fps=25,
        streaming_max_outputs_per_session=4,
        streaming_audio_sample_rate=48000,
        streaming_audio_tick_ms=20,
    )
    program = _FakeProgram()
    program.clock = SimpleNamespace(fps=25)
    controller = SessionOutputController(session_id="sess", program=program, settings=settings)
    with pytest.raises(ValueError, match="ProgramClock"):
        await controller.create(
            {
                "type": "rtmps",
                "transport": {"endpoint": "rtmps://localhost:1936/live", "stream_key": "key"},
                "profile": {"fps": 30},
            }
        )


def test_rtmps_structured_url_and_target_validation() -> None:
    settings = RTMPSSettings(
        endpoint="rtmps://localhost:1936/live",
        stream_key="demo-key",
        username="publisher",
        password="secret",
        allow_local=True,
    )
    assert build_rtmps_url(settings) == "rtmps://localhost:1936/live/demo-key?user=publisher&pass=secret"
    with pytest.raises(ValueError):
        validate_stream_key("bad/key")
    with pytest.raises(ValueError):
        validate_target_url("http://127.0.0.1:1/x", schemes={"https"}, allow_local=True)


@pytest.mark.asyncio
async def test_output_lifecycle_detaches_branch_and_reconnects(monkeypatch) -> None:
    class Publisher:
        def __init__(self, settings) -> None:
            self.settings = settings
            self.state = "created"
            self.health = "unknown"
            self.last_error = None
            self.starts = 0

        async def start(self) -> None:
            self.starts += 1
            self.state = "connected"

        async def stop(self) -> None:
            self.state = "disconnected"

        async def video(self, item) -> None:
            del item

        async def audio(self, item) -> None:
            del item

    monkeypatch.setattr("opentalking.streaming.outputs.RTMPSPublisher", Publisher)
    settings = SimpleNamespace(
        streaming_allow_local_targets=True,
        streaming_test_auth_bypass=True,
        streaming_rtmps_ca_file="",
        streaming_video_fps=25,
        streaming_max_outputs_per_session=4,
        streaming_audio_sample_rate=48000,
        streaming_audio_tick_ms=20,
    )
    program = _FakeProgram()
    program.clock = SimpleNamespace(fps=25)
    controller = SessionOutputController(session_id="sess", program=program, settings=settings)
    record = await controller.create(
        {
            "type": "rtmps",
            "transport": {"endpoint": "rtmps://localhost:1936/live", "stream_key": "key"},
            "auto_connect": True,
        }
    )
    await asyncio.sleep(0.01)
    assert record.output_id in program.added
    assert record.connection_state.value == "connected"
    await controller.disconnect(record.output_id)
    assert record.output_id not in program.added
    assert record.connection_state.value == "disconnected"
    await controller.reconnect(record.output_id)
    await asyncio.sleep(0.01)
    assert record.output_id in program.added
    assert record.attempts == 2
    await controller.delete(record.output_id)
    assert record.output_id not in controller.outputs


@pytest.mark.asyncio
async def test_output_snapshot_is_failed_closed_after_worker_boot_changes(monkeypatch) -> None:
    class Publisher:
        def __init__(self, settings) -> None:
            self.settings = settings
            self.state = "created"
            self.health = "unknown"
            self.last_error = None

        async def start(self) -> None:
            self.state = "connected"

        async def stop(self) -> None:
            self.state = "disconnected"

        async def video(self, item) -> None:
            del item

        async def audio(self, item) -> None:
            del item

    monkeypatch.setattr("opentalking.streaming.outputs.RTMPSPublisher", Publisher)
    settings = SimpleNamespace(
        streaming_allow_local_targets=True,
        streaming_test_auth_bypass=True,
        streaming_rtmps_ca_file="",
        streaming_video_fps=25,
        streaming_max_outputs_per_session=4,
        streaming_snapshot_ttl_sec=3600,
    )
    redis = InMemoryRedis()
    body = {
        "type": "rtmps",
        "name": "persisted",
        "transport": {"endpoint": "rtmps://localhost:1936/live", "stream_key": "key"},
    }
    first = SessionOutputController(
        session_id="sess",
        program=_FakeProgram(),
        settings=settings,
        redis=redis,
        worker_boot_id="boot-a",
    )
    record = await first.create(body, idempotency_key="create-1")
    second = SessionOutputController(
        session_id="sess",
        program=_FakeProgram(),
        settings=settings,
        redis=redis,
        worker_boot_id="boot-b",
    )
    await second.load_stale_state()
    snapshot = second.get(record.output_id)
    assert snapshot is not None
    assert snapshot.public()["connection_state"] == "failed"
    assert snapshot.public()["health"] == "failed"
    assert snapshot.public()["secret_configured"] is False
    assert snapshot.public()["last_error"] == "stale_worker_state"
    with pytest.raises(ValueError, match="stale_worker_state"):
        await second.create(body, idempotency_key="create-1")
    await second.delete(record.output_id)
    assert second.get(record.output_id) is None


@pytest.mark.asyncio
async def test_lifecycle_action_receipt_deduplicates_connect(monkeypatch) -> None:
    class Publisher:
        def __init__(self, settings) -> None:
            self.settings = settings
            self.state = "created"
            self.health = "unknown"
            self.last_error = None
            self.starts = 0

        async def start(self) -> None:
            self.starts += 1
            self.state = "connected"

        async def stop(self) -> None:
            self.state = "disconnected"

        async def video(self, item) -> None:
            del item

        async def audio(self, item) -> None:
            del item

    monkeypatch.setattr("opentalking.streaming.outputs.RTMPSPublisher", Publisher)
    settings = SimpleNamespace(
        streaming_allow_local_targets=True,
        streaming_test_auth_bypass=True,
        streaming_rtmps_ca_file="",
        streaming_video_fps=25,
        streaming_max_outputs_per_session=4,
        streaming_snapshot_ttl_sec=3600,
    )
    controller = SessionOutputController(
        session_id="sess-action",
        program=_FakeProgram(),
        settings=settings,
        redis=InMemoryRedis(),
    )
    record = await controller.create(
        {
            "type": "rtmps",
            "transport": {"endpoint": "rtmps://localhost:1936/live", "stream_key": "key"},
        }
    )
    assert await controller.reserve_action_idempotency(record.output_id, "connect", "connect-1") is False
    controller.request_connect(record.output_id)
    await asyncio.sleep(0.02)
    assert await controller.reserve_action_idempotency(record.output_id, "connect", "connect-1") is True
    assert record.publisher.starts == 1
    await controller.delete(record.output_id)
