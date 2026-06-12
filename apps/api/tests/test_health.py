from __future__ import annotations

from types import SimpleNamespace

from apps.api.routes.health import _runtime_status_payload


def test_health_reports_resolved_quicktalk_asset_root(tmp_path, monkeypatch) -> None:
    settings_asset_root = tmp_path / "settings-assets"
    env_asset_root = tmp_path / "env-assets"
    monkeypatch.setenv("OPENTALKING_QUICKTALK_ASSET_ROOT", str(env_asset_root))
    monkeypatch.setenv("OPENTALKING_QUICKTALK_MODEL_ROOT", str(tmp_path / "legacy-root"))

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(
                    quicktalk_asset_root=str(settings_asset_root),
                    quicktalk_model_root="",
                    models_dir=str(tmp_path / "models"),
                    llm_api_key="",
                    llm_provider="openai_compatible",
                    llm_model="",
                    default_model="quicktalk",
                    quicktalk_backend="local",
                    quicktalk_device="mps",
                )
            )
        )
    )

    payload = _runtime_status_payload(request)

    assert payload["quicktalk_asset_root"] == str(settings_asset_root.resolve())
