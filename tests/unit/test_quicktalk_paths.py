from __future__ import annotations

from types import SimpleNamespace

import pytest

from opentalking.models.quicktalk.paths import resolve_quicktalk_asset_root


def test_resolve_quicktalk_asset_root_uses_one_public_root_before_legacy(
    tmp_path,
    monkeypatch,
) -> None:
    settings_asset_root = tmp_path / "settings-assets"
    env_asset_root = tmp_path / "env-assets"
    legacy_settings_root = tmp_path / "settings-legacy"
    legacy_env_root = tmp_path / "env-legacy"
    omnirt_root = tmp_path / "omnirt-legacy"
    shared_omnirt_root = tmp_path / "shared-omnirt"

    monkeypatch.setenv("OPENTALKING_QUICKTALK_ASSET_ROOT", str(env_asset_root))
    monkeypatch.setenv("OPENTALKING_QUICKTALK_MODEL_ROOT", str(legacy_env_root))
    monkeypatch.setenv("OMNIRT_QUICKTALK_MODEL_ROOT", str(omnirt_root))
    monkeypatch.setenv("OMNIRT_MODEL_ROOT", str(shared_omnirt_root))
    settings = SimpleNamespace(
        quicktalk_asset_root=str(settings_asset_root),
        quicktalk_model_root=str(legacy_settings_root),
        models_dir=str(tmp_path / "repo-models"),
    )

    assert resolve_quicktalk_asset_root(settings) == settings_asset_root.resolve()

    settings.quicktalk_asset_root = ""
    assert resolve_quicktalk_asset_root(settings) == env_asset_root.resolve()

    monkeypatch.delenv("OPENTALKING_QUICKTALK_ASSET_ROOT")
    assert resolve_quicktalk_asset_root(settings) == legacy_settings_root.resolve()

    settings.quicktalk_model_root = ""
    assert resolve_quicktalk_asset_root(settings) == legacy_env_root.resolve()

    monkeypatch.delenv("OPENTALKING_QUICKTALK_MODEL_ROOT")
    assert resolve_quicktalk_asset_root(settings) == omnirt_root.resolve()

    monkeypatch.delenv("OMNIRT_QUICKTALK_MODEL_ROOT")
    assert resolve_quicktalk_asset_root(settings) == (
        shared_omnirt_root / "quicktalk"
    ).resolve()

    monkeypatch.delenv("OMNIRT_MODEL_ROOT")
    assert resolve_quicktalk_asset_root(settings) == (
        tmp_path / "repo-models" / "quicktalk"
    ).resolve()


def test_resolve_quicktalk_asset_root_can_skip_default_fallback(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OPENTALKING_QUICKTALK_ASSET_ROOT", raising=False)
    monkeypatch.delenv("OPENTALKING_QUICKTALK_MODEL_ROOT", raising=False)
    monkeypatch.delenv("OMNIRT_QUICKTALK_MODEL_ROOT", raising=False)
    monkeypatch.delenv("OMNIRT_MODEL_ROOT", raising=False)

    settings = SimpleNamespace(models_dir=str(tmp_path / "repo-models"))

    assert resolve_quicktalk_asset_root(settings, include_default=False) is None


def test_resolve_quicktalk_asset_root_warns_on_conflicting_explicit_roots(
    tmp_path,
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("OPENTALKING_QUICKTALK_ASSET_ROOT", str(tmp_path / "env-assets"))
    monkeypatch.setenv("OPENTALKING_QUICKTALK_MODEL_ROOT", str(tmp_path / "legacy-env"))
    settings = SimpleNamespace(
        quicktalk_asset_root=str(tmp_path / "settings-assets"),
        quicktalk_model_root="",
        models_dir=str(tmp_path / "repo-models"),
    )

    assert resolve_quicktalk_asset_root(settings) == (tmp_path / "settings-assets").resolve()
    assert "conflicting QuickTalk asset roots" in caplog.text
