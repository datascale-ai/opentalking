from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.routes import models as models_routes
from opentalking.core.config import Settings
from opentalking.providers.synthesis.omnirt import resolve_synthesis_ws_url
from opentalking.providers.synthesis.availability import (
    _fetch_omnirt_audio2video_models,
    resolve_model_statuses,
)


def test_models_route_lists_all_models_with_connection_status_without_omnirt() -> None:
    app = FastAPI()
    app.state.settings = SimpleNamespace(
        omnirt_endpoint="",
        flashtalk_ws_url="",
        flashhead_ws_url="",
    )
    app.include_router(models_routes.router)

    with TestClient(app) as client:
        response = client.get("/models")

    assert response.status_code == 200
    payload = response.json()
    assert payload["models"] == ["mock", "flashtalk", "musetalk", "wav2lip", "flashhead", "quicktalk"]
    statuses = {item["id"]: item for item in payload["statuses"]}
    assert statuses["mock"]["connected"] is True
    assert statuses["mock"]["reason"] == "local_self_test"
    assert statuses["flashtalk"]["connected"] is False
    assert statuses["musetalk"]["connected"] is False
    assert statuses["wav2lip"]["connected"] is False
    assert statuses["flashhead"]["connected"] is False
    assert statuses["quicktalk"]["connected"] is True
    assert statuses["quicktalk"]["reason"] == "local_runtime"


def test_models_route_marks_legacy_flashtalk_connected_when_explicitly_configured() -> None:
    app = FastAPI()
    app.state.settings = SimpleNamespace(
        omnirt_endpoint="",
        flashtalk_ws_url="ws://127.0.0.1:8765",
        flashhead_ws_url="",
    )
    app.include_router(models_routes.router)

    with TestClient(app) as client:
        response = client.get("/models")

    assert response.status_code == 200
    statuses = {item["id"]: item for item in response.json()["statuses"]}
    assert statuses["flashtalk"]["connected"] is True
    assert statuses["flashtalk"]["reason"] == "legacy_ws"


def test_default_settings_do_not_enable_legacy_flashtalk(monkeypatch) -> None:
    monkeypatch.delenv("OPENTALKING_FLASHTALK_WS_URL", raising=False)
    monkeypatch.delenv("FLASHTALK_WS_URL", raising=False)
    monkeypatch.delenv("OMNIRT_ENDPOINT", raising=False)
    monkeypatch.delenv("OPENTALKING_OMNIRT_ENDPOINT", raising=False)

    settings = Settings(_env_file=None)

    assert settings.omnirt_endpoint == ""
    assert settings.flashtalk_ws_url == ""


def test_omnirt_endpoint_takes_precedence_over_legacy_flashtalk_url() -> None:
    settings = SimpleNamespace(
        omnirt_endpoint="http://127.0.0.1:9000",
        omnirt_audio2video_path_template="/v1/audio2video/{model}",
        flashtalk_ws_url="ws://127.0.0.1:8765",
        flashhead_ws_url="",
    )

    assert resolve_synthesis_ws_url("flashtalk", settings) == "ws://127.0.0.1:9000/v1/audio2video/flashtalk"
    assert resolve_synthesis_ws_url("wav2lip", settings) == "ws://127.0.0.1:9000/v1/audio2video/wav2lip"


def test_omnirt_endpoint_defaults_to_audio2video_routes() -> None:
    settings = SimpleNamespace(
        omnirt_endpoint="http://127.0.0.1:9000",
        flashtalk_ws_url="",
        flashhead_ws_url="",
    )

    assert resolve_synthesis_ws_url("flashtalk", settings) == "ws://127.0.0.1:9000/v1/audio2video/flashtalk"


async def test_omnirt_status_takes_precedence_over_legacy_flashtalk_url(monkeypatch) -> None:
    async def fake_fetch(_settings) -> set[str]:
        return {"flashtalk", "wav2lip"}

    monkeypatch.setattr(
        "opentalking.providers.synthesis.availability._fetch_omnirt_audio2video_models",
        fake_fetch,
    )
    settings = SimpleNamespace(
        omnirt_endpoint="http://127.0.0.1:9000",
        flashtalk_ws_url="ws://127.0.0.1:8765",
        flashhead_ws_url="",
    )

    statuses = {status.id: status for status in await resolve_model_statuses(settings)}

    assert statuses["flashtalk"].connected is True
    assert statuses["flashtalk"].reason == "omnirt"
    assert statuses["wav2lip"].connected is True
    assert statuses["wav2lip"].reason == "omnirt"


async def test_omnirt_status_falls_back_to_legacy_avatar_models_path(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_fetch(_settings, _endpoint: str, path: str) -> set[str]:
        calls.append(path)
        return {"flashtalk"} if path == "/v1/avatar/models" else set()

    monkeypatch.setattr(
        "opentalking.providers.synthesis.availability._fetch_omnirt_models_at_path",
        fake_fetch,
    )
    settings = SimpleNamespace(
        omnirt_endpoint="http://127.0.0.1:9000",
    )

    assert await _fetch_omnirt_audio2video_models(settings) == {"flashtalk"}
    assert calls == ["/v1/audio2video/models", "/v1/avatar/models"]
