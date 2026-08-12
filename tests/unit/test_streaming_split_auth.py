from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

import opentalking.runtime.server as worker_server
from opentalking.core.in_memory_redis import InMemoryRedis


class _Program:
    def add_branch(self, name: str, **callbacks: object) -> None:
        del name, callbacks

    def remove_branch(self, name: str) -> None:
        del name


class _Publisher:
    def __init__(self, settings: object) -> None:
        self.settings = settings
        self.state = "created"
        self.health = "unknown"
        self.last_error = None

    async def start(self) -> None:
        self.state = "connected"

    async def stop(self) -> None:
        self.state = "disconnected"

    async def video(self, item: object) -> None:
        del item

    async def audio(self, item: object) -> None:
        del item


@pytest.mark.asyncio
async def test_split_worker_uses_internal_token_not_public_control_token(monkeypatch) -> None:
    settings = SimpleNamespace(
        streaming_internal_control_token="worker-only",
        streaming_test_auth_bypass=False,
        streaming_allow_local_targets=True,
        streaming_rtmps_tls_verify=True,
        streaming_rtmps_ca_file="",
        streaming_video_fps=25,
        streaming_max_outputs_per_session=4,
        streaming_snapshot_ttl_sec=3600,
    )
    monkeypatch.setattr(worker_server, "get_settings", lambda: settings)
    monkeypatch.setattr("opentalking.streaming.outputs.RTMPSPublisher", _Publisher)
    worker_server.runners.clear()
    worker_server.output_controllers.clear()
    worker_server.runners["sess_split"] = SimpleNamespace(program=_Program())
    app = worker_server.create_app()
    app.state.redis = InMemoryRedis()
    app.state.worker_boot_id = "boot-test"
    body = {
        "body": {
            "type": "rtmps",
            "transport": {
                "endpoint": "rtmps://localhost:1936/live",
                "stream_key": "not-returned",
            },
        }
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://worker.test",
    ) as client:
        assert (await client.post("/sessions/sess_split/outputs", json=body)).status_code == 401
        assert (
            await client.post(
                "/sessions/sess_split/outputs",
                headers={"Authorization": "Bearer public-control-token"},
                json=body,
            )
        ).status_code == 401
        response = await client.post(
            "/sessions/sess_split/outputs",
            headers={"Authorization": "Bearer worker-only"},
            json=body,
        )
    assert response.status_code == 201
    assert "not-returned" not in response.text
    worker_server.runners.clear()
    worker_server.output_controllers.clear()
