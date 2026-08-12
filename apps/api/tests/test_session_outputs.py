from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.routes.outputs import router
from opentalking.core.in_memory_redis import InMemoryRedis
from opentalking.core.session_store import session_key


class _Program:
    def __init__(self) -> None:
        self.branches = {}

    def add_branch(self, name, **callbacks) -> None:
        self.branches[name] = callbacks

    def remove_branch(self, name) -> None:
        self.branches.pop(name, None)


class _Publisher:
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


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr("opentalking.streaming.outputs.RTMPSPublisher", _Publisher)
    app = FastAPI()
    app.include_router(router)
    settings = SimpleNamespace(
        streaming_enabled=True,
        streaming_control_token="control-token",
        streaming_internal_control_token="internal-token",
        streaming_allow_local_targets=True,
        streaming_test_auth_bypass=False,
        streaming_rtmps_tls_verify=True,
        streaming_rtmps_ca_file="",
        streaming_whip_tls_verify=True,
        streaming_whip_ca_file="",
        streaming_video_fps=25,
        streaming_audio_sample_rate=48000,
        streaming_audio_tick_ms=20,
        streaming_queue_max_frames=128,
        streaming_queue_max_audio_ms=2000,
        streaming_max_outputs_per_session=4,
        streaming_reconnect_max_attempts=2,
        streaming_reconnect_max_delay_sec=1,
        streaming_whip_ice_servers="",
        streaming_whip_max_redirects=2,
        worker_url="http://127.0.0.1:9",
        streaming_allowed_cidrs="",
    )
    app.state.settings = settings
    app.state.redis = InMemoryRedis()
    app.state.session_runners = {"sess_test": SimpleNamespace(program=_Program())}

    async def seed() -> None:
        await app.state.redis.hset(session_key("sess_test"), mapping={"session_id": "sess_test", "state": "ready"})

    import asyncio

    asyncio.run(seed())
    return TestClient(app)


def test_output_api_requires_control_token_and_does_not_return_secrets(monkeypatch) -> None:
    with _client(monkeypatch) as client:
        body = {
            "type": "rtmps",
            "name": "local",
            "auto_connect": True,
            "transport": {
                "endpoint": "rtmps://localhost:1936/live",
                "stream_key": "secret-key",
                "password": "secret-password",
            },
        }
        assert client.post("/sessions/sess_test/outputs", json=body).status_code == 401
        response = client.post(
            "/sessions/sess_test/outputs",
            headers={"Authorization": "Bearer control-token", "Idempotency-Key": "output-1"},
            json=body,
        )
        assert response.status_code == 201
        output = response.json()
        assert output["secret_configured"] is True
        assert "secret-key" not in response.text
        assert "secret-password" not in response.text

        duplicate = client.post(
            "/sessions/sess_test/outputs",
            headers={"Authorization": "Bearer control-token", "Idempotency-Key": "output-1"},
            json=body,
        )
        assert duplicate.status_code == 201
        assert duplicate.json()["output_id"] == output["output_id"]


def test_output_api_rejects_unknown_transport_fields(monkeypatch) -> None:
    with _client(monkeypatch) as client:
        response = client.post(
            "/sessions/sess_test/outputs",
            headers={"Authorization": "Bearer control-token"},
            json={
                "type": "rtmps",
                "transport": {
                    "endpoint": "rtmps://localhost:1936/live",
                    "stream_key": "key",
                    "ffmpeg_args": ["-vf", "setpts=0"],
                },
            },
        )
        assert response.status_code == 422


def test_output_api_rejects_malformed_stream_key_before_async_connect(monkeypatch) -> None:
    with _client(monkeypatch) as client:
        response = client.post(
            "/sessions/sess_test/outputs",
            headers={"Authorization": "Bearer control-token"},
            json={
                "type": "rtmps",
                "transport": {
                    "endpoint": "rtmps://localhost:1936/live",
                    "stream_key": "bad/key",
                },
            },
        )
        assert response.status_code == 400
        assert "stream_key" in response.json()["detail"]


def test_output_api_mutations_use_async_status_codes_and_delete_204(monkeypatch) -> None:
    with _client(monkeypatch) as client:
        body = {
            "type": "rtmps",
            "transport": {
                "endpoint": "rtmps://localhost:1936/live",
                "stream_key": "key",
            },
        }
        headers = {"Authorization": "Bearer control-token"}
        created = client.post("/sessions/sess_test/outputs", headers=headers, json=body)
        assert created.status_code == 201
        output_id = created.json()["output_id"]
        for action in ("disconnect", "connect", "reconnect"):
            response = client.post(
                f"/sessions/sess_test/outputs/{output_id}/{action}",
                headers=headers,
            )
            assert response.status_code == 202
        delete_headers = {**headers, "Idempotency-Key": "delete-1"}
        deleted = client.delete(f"/sessions/sess_test/outputs/{output_id}", headers=delete_headers)
        assert deleted.status_code == 204
        assert deleted.content == b""
        duplicate = client.delete(f"/sessions/sess_test/outputs/{output_id}", headers=delete_headers)
        assert duplicate.status_code == 204
