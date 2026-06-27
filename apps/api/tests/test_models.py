from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.routes import models as models_routes
from opentalking.core.config import Settings
from opentalking.core.model_config import clear_model_config_cache
from opentalking.providers.synthesis.omnirt import resolve_synthesis_ws_url
from opentalking.providers.synthesis.availability import (
    _fetch_omnirt_audio2video_models,
    resolve_model_statuses,
)


def _write_quicktalk_local_assets(asset_root) -> None:
    checkpoints = asset_root / "checkpoints"
    (checkpoints / "chinese-hubert-large").mkdir(parents=True)
    (checkpoints / "auxiliary" / "models" / "buffalo_l").mkdir(parents=True)
    (checkpoints / "quicktalk.pth").write_bytes(b"pth")
    (checkpoints / "repair.npy").write_bytes(b"repair")
    (checkpoints / "chinese-hubert-large" / "pytorch_model.bin").write_bytes(b"hubert")
    (checkpoints / "auxiliary" / "models" / "buffalo_l" / "det_10g.onnx").write_bytes(b"onnx")


def test_models_route_lists_all_models_with_connection_status_without_omnirt(monkeypatch) -> None:
    monkeypatch.delenv("OPENTALKING_QUICKTALK_BACKEND", raising=False)
    monkeypatch.delenv("OPENTALKING_CONFIG_FILE", raising=False)
    monkeypatch.delenv("CONFIG_FILE", raising=False)
    clear_model_config_cache()
    monkeypatch.setattr(
        "opentalking.models.wav2lip.adapter.Wav2LipAdapter.runtime_available",
        staticmethod(lambda: False),
    )
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
    assert payload["models"] == [
        "mock",
        "flashtalk",
        "musetalk",
        "wav2lip",
        "fasterliveportrait",
        "flashhead",
        "quicktalk",
    ]
    statuses = {item["id"]: item for item in payload["statuses"]}
    assert statuses["mock"]["backend"] == "mock"
    assert statuses["mock"]["connected"] is True
    assert statuses["mock"]["reason"] == "local_self_test"
    assert statuses["flashtalk"]["backend"] == "omnirt"
    assert statuses["flashtalk"]["connected"] is False
    assert statuses["musetalk"]["backend"] == "omnirt"
    assert statuses["musetalk"]["connected"] is False
    assert statuses["wav2lip"]["backend"] == "local"
    assert statuses["wav2lip"]["connected"] is False
    assert statuses["wav2lip"]["reason"] == "local_adapter_missing"
    assert statuses["fasterliveportrait"]["backend"] == "omnirt"
    assert statuses["fasterliveportrait"]["connected"] is False
    assert statuses["flashhead"]["backend"] == "direct_ws"
    assert statuses["flashhead"]["connected"] is False
    assert statuses["quicktalk"]["backend"] == "omnirt"
    assert statuses["quicktalk"]["connected"] is False
    assert statuses["quicktalk"]["reason"] == "not_configured"


def test_models_route_exposes_valid_default_model_from_settings(monkeypatch) -> None:
    monkeypatch.setattr(
        "opentalking.models.wav2lip.adapter.Wav2LipAdapter.runtime_available",
        staticmethod(lambda: False),
    )
    app = FastAPI()
    app.state.settings = SimpleNamespace(
        default_model="quicktalk",
        omnirt_endpoint="",
        flashtalk_ws_url="",
        flashhead_ws_url="",
    )
    app.include_router(models_routes.router)

    with TestClient(app) as client:
        response = client.get("/models")

    assert response.status_code == 200
    assert response.json()["default_model"] == "quicktalk"


def test_settings_loads_default_model_from_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENTALKING_DEFAULT_MODEL", "quicktalk")
    monkeypatch.delenv("OPENTALKING_CONFIG_FILE", raising=False)
    monkeypatch.delenv("CONFIG_FILE", raising=False)
    monkeypatch.chdir(tmp_path)

    settings = Settings(_env_file=None)

    assert settings.default_model == "quicktalk"


def test_settings_loads_quicktalk_local_fields_from_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENTALKING_QUICKTALK_ASSET_ROOT", str(tmp_path / "models" / "quicktalk"))
    monkeypatch.setenv("OPENTALKING_QUICKTALK_BACKEND", "local")
    monkeypatch.setenv("OPENTALKING_QUICKTALK_MODEL_BACKEND", "auto")
    monkeypatch.setenv("OPENTALKING_QUICKTALK_DEVICE", "mps")
    monkeypatch.setenv("OPENTALKING_QUICKTALK_SLICE_LEN", "12")
    monkeypatch.delenv("OPENTALKING_CONFIG_FILE", raising=False)
    monkeypatch.delenv("CONFIG_FILE", raising=False)
    monkeypatch.chdir(tmp_path)

    settings = Settings(_env_file=None)

    assert settings.quicktalk_asset_root == str(tmp_path / "models" / "quicktalk")
    assert settings.quicktalk_backend == "local"
    assert settings.quicktalk_model_backend == "auto"
    assert settings.quicktalk_device == "mps"
    assert settings.quicktalk_slice_len == 12


def test_settings_loads_default_model_from_yaml_model_section(monkeypatch, tmp_path) -> None:
    config_file = tmp_path / "opentalking.yaml"
    config_file.write_text(
        "model:\n  default_model: quicktalk\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENTALKING_CONFIG_FILE", str(config_file))
    monkeypatch.delenv("OPENTALKING_DEFAULT_MODEL", raising=False)
    monkeypatch.chdir(tmp_path)

    settings = Settings(_env_file=None)

    assert settings.default_model == "quicktalk"


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


def test_default_settings_do_not_enable_legacy_flashtalk(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("OPENTALKING_FLASHTALK_WS_URL", raising=False)
    monkeypatch.delenv("FLASHTALK_WS_URL", raising=False)
    monkeypatch.delenv("OMNIRT_ENDPOINT", raising=False)
    monkeypatch.delenv("OPENTALKING_OMNIRT_ENDPOINT", raising=False)
    monkeypatch.delenv("OPENTALKING_CONFIG_FILE", raising=False)
    monkeypatch.delenv("CONFIG_FILE", raising=False)
    monkeypatch.chdir(tmp_path)

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
    assert resolve_synthesis_ws_url("quicktalk", settings) == "ws://127.0.0.1:9000/v1/audio2video/quicktalk"


def test_omnirt_endpoint_defaults_to_audio2video_routes() -> None:
    settings = SimpleNamespace(
        omnirt_endpoint="http://127.0.0.1:9000",
        flashtalk_ws_url="",
        flashhead_ws_url="",
    )

    assert resolve_synthesis_ws_url("flashtalk", settings) == "ws://127.0.0.1:9000/v1/audio2video/flashtalk"


async def test_omnirt_status_keeps_local_backend_local(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENTALKING_CONFIG_FILE", raising=False)
    monkeypatch.delenv("CONFIG_FILE", raising=False)
    monkeypatch.setenv("OPENTALKING_QUICKTALK_BACKEND", "omnirt")
    clear_model_config_cache()
    monkeypatch.setattr(
        "opentalking.models.wav2lip.adapter.Wav2LipAdapter.runtime_available",
        staticmethod(lambda: True),
    )

    async def fake_fetch(_settings) -> set[str]:
        return {"flashtalk", "wav2lip", "fasterliveportrait", "quicktalk"}

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
    assert statuses["wav2lip"].backend == "local"
    assert statuses["wav2lip"].connected is True
    assert statuses["wav2lip"].reason == "local_runtime"
    assert statuses["fasterliveportrait"].connected is True
    assert statuses["fasterliveportrait"].reason == "omnirt"
    assert statuses["quicktalk"].backend == "omnirt"
    assert statuses["quicktalk"].connected is True
    assert statuses["quicktalk"].reason == "omnirt"
    clear_model_config_cache()


async def test_models_status_uses_settings_for_local_quicktalk_assets(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENTALKING_QUICKTALK_ASSET_ROOT", raising=False)
    monkeypatch.delenv("OPENTALKING_QUICKTALK_MODEL_ROOT", raising=False)
    monkeypatch.setenv("OPENTALKING_QUICKTALK_BACKEND", "local")
    asset_root = tmp_path / "models" / "quicktalk"
    _write_quicktalk_local_assets(asset_root)

    settings = SimpleNamespace(
        omnirt_endpoint="",
        flashtalk_ws_url="",
        flashhead_ws_url="",
        quicktalk_asset_root=str(asset_root),
        quicktalk_model_root="",
        quicktalk_device="mps",
        quicktalk_hubert_device="",
        torch_device="auto",
        device="",
    )

    statuses = {status.id: status for status in await resolve_model_statuses(settings)}

    assert statuses["quicktalk"].backend == "local"
    assert statuses["quicktalk"].connected is True
    assert statuses["quicktalk"].reason == "local_runtime"


async def test_omnirt_endpoint_only_affects_omnirt_backend(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "opentalking.models.wav2lip.adapter.Wav2LipAdapter.runtime_available",
        staticmethod(lambda: True),
    )

    config_file = tmp_path / "opentalking.yaml"
    config_file.write_text(
        """
models:
  wav2lip:
    backend: local
  musetalk:
    backend: direct_ws
    ws_url: ws://musetalk.example/ws
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENTALKING_CONFIG_FILE", str(config_file))
    clear_model_config_cache()

    async def fake_fetch(_settings) -> set[str]:
        return {"flashtalk", "wav2lip", "musetalk"}

    monkeypatch.setattr(
        "opentalking.providers.synthesis.availability._fetch_omnirt_audio2video_models",
        fake_fetch,
    )
    async def fake_reachable(_url: str) -> bool:
        return True

    monkeypatch.setattr(
        "opentalking.providers.synthesis.availability._is_direct_ws_reachable",
        fake_reachable,
    )
    settings = SimpleNamespace(
        omnirt_endpoint="http://127.0.0.1:9000",
        flashtalk_ws_url="",
        flashhead_ws_url="",
    )

    statuses = {status.id: status for status in await resolve_model_statuses(settings)}

    assert statuses["flashtalk"].backend == "omnirt"
    assert statuses["flashtalk"].connected is True
    assert statuses["wav2lip"].backend == "local"
    assert statuses["wav2lip"].connected is True
    assert statuses["wav2lip"].reason == "local_runtime"
    assert statuses["musetalk"].backend == "direct_ws"
    assert statuses["musetalk"].connected is True
    assert statuses["musetalk"].reason == "direct_ws"

    clear_model_config_cache()


async def test_direct_ws_status_requires_reachable_url(monkeypatch) -> None:
    async def fake_reachable(_url: str) -> bool:
        return False

    monkeypatch.setattr(
        "opentalking.providers.synthesis.availability._is_direct_ws_reachable",
        fake_reachable,
    )

    settings = SimpleNamespace(
        omnirt_endpoint="",
        flashtalk_ws_url="",
        flashhead_ws_url="ws://127.0.0.1:8766/v1/avatar/realtime",
    )

    statuses = {status.id: status for status in await resolve_model_statuses(settings)}

    assert statuses["flashhead"].backend == "direct_ws"
    assert statuses["flashhead"].connected is False
    assert statuses["flashhead"].reason == "direct_ws_unavailable"


async def test_direct_ws_status_reports_reachable_url(monkeypatch) -> None:
    async def fake_reachable(_url: str) -> bool:
        return True

    monkeypatch.setattr(
        "opentalking.providers.synthesis.availability._is_direct_ws_reachable",
        fake_reachable,
    )

    settings = SimpleNamespace(
        omnirt_endpoint="",
        flashtalk_ws_url="",
        flashhead_ws_url="ws://127.0.0.1:8766/v1/avatar/realtime",
    )

    statuses = {status.id: status for status in await resolve_model_statuses(settings)}

    assert statuses["flashhead"].backend == "direct_ws"
    assert statuses["flashhead"].connected is True
    assert statuses["flashhead"].reason == "direct_ws"


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
