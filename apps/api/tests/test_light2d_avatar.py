from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from apps.api.routes import avatars
from opentalking.avatar.light2d import (
    Light2DContractError,
    open_referenced_asset,
    load_canonical_dogo_renderer,
    load_light2d_renderer,
    resolve_referenced_asset,
)


def _renderer_config() -> dict:
    return {
        "version": 1,
        "canvas": {"width": 64, "height": 96},
        "layers": {
            "base": {"source": "layers/base.png", "rect": [0, 0, 64, 96]},
            "blink": {"source": "layers/eyes-closed.png", "rect": [16, 20, 32, 12]},
            "mouth": {
                "closed": {"source": "layers/mouth-closed.png", "rect": [20, 44, 24, 12]},
                "small": {"source": "layers/mouth-small.png", "rect": [20, 44, 24, 12]},
                "medium": {"source": "layers/mouth-medium.png", "rect": [20, 44, 24, 12]},
                "large": {"source": "layers/mouth-large.png", "rect": [20, 44, 24, 12]},
            },
        },
        "audio": {
            "silence_gate": 0.03,
            "small_threshold": 0.08,
            "medium_threshold": 0.18,
            "attack_ms": 45,
            "release_ms": 120,
            "crossfade_ms": 80,
        },
        "animation": {
            "breath_period_ms": 2600,
            "breath_scale": 0.006,
            "sway_degrees": 0.7,
            "blink_period_ms": 4800,
            "blink_duration_ms": 130,
        },
    }


def _make_avatar(root: Path, *, config: dict | None = None) -> Path:
    avatar_dir = root / "dogo-light2d"
    layer_dir = avatar_dir / "light2d" / "layers"
    layer_dir.mkdir(parents=True)
    renderer = {
        "type": "light2d",
        "config": "light2d/avatar.json",
        "recommended_for": ["mock"],
    }
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "dogo-light2d",
                "name": "DOGO",
                "model_type": "mock",
                "fps": 25,
                "sample_rate": 16000,
                "width": 64,
                "height": 96,
                "version": "1.0",
                "metadata": {"client_renderer": renderer},
            }
        ),
        encoding="utf-8",
    )
    for name in ("preview.png", "reference.png"):
        Image.new("RGB", (64, 96), "white").save(avatar_dir / name)
    for name in (
        "base.png",
        "eyes-closed.png",
        "mouth-closed.png",
        "mouth-small.png",
        "mouth-medium.png",
        "mouth-large.png",
    ):
        Image.new("RGBA", (64, 96), (255, 255, 255, 0)).save(layer_dir / name)
    (avatar_dir / "light2d" / "avatar.json").write_text(
        json.dumps(config or _renderer_config()), encoding="utf-8"
    )
    return avatar_dir


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    _make_avatar(tmp_path)
    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path))
    app.include_router(avatars.router)
    return TestClient(app)


def test_avatar_summary_exposes_public_client_renderer(client: TestClient) -> None:
    response = client.get("/avatars")

    assert response.status_code == 200
    assert response.json()[0]["client_renderer"] == {
        "type": "light2d",
        "config_url": "/avatars/dogo-light2d/client-renderer",
        "asset_base_url": "/avatars/dogo-light2d/client-assets/",
        "recommended_for": ["mock"],
    }


def test_client_renderer_returns_validated_config_and_referenced_asset(client: TestClient) -> None:
    config_response = client.get("/avatars/dogo-light2d/client-renderer")
    asset_response = client.get("/avatars/dogo-light2d/client-assets/layers/base.png")

    assert config_response.status_code == 200
    assert config_response.json() == _renderer_config()
    assert asset_response.status_code == 200
    assert asset_response.headers["content-type"] == "image/png"


def test_unreferenced_client_asset_preserves_api_error_detail(client: TestClient) -> None:
    response = client.get("/avatars/dogo-light2d/client-assets/layers/unreferenced.png")

    assert response.status_code == 404
    assert response.json() == {"detail": "asset not referenced"}


def test_avatar_api_keeps_supporting_noncanonical_light2d_assets(tmp_path: Path) -> None:
    avatar_dir = _make_avatar(tmp_path)
    generic_dir = tmp_path / "generic-light2d"
    avatar_dir.rename(generic_dir)
    manifest_path = generic_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["id"] = "generic-light2d"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path))
    app.include_router(avatars.router)
    client = TestClient(app)

    assert client.get("/avatars").json()[0]["client_renderer"]["type"] == "light2d"
    assert client.get("/avatars/generic-light2d/client-renderer").status_code == 200


@pytest.mark.parametrize("manifest", [[], None])
def test_non_object_manifest_hides_renderer_instead_of_raising_500(
    tmp_path: Path,
    manifest: object,
) -> None:
    avatar_dir = _make_avatar(tmp_path)
    (avatar_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path))
    app.include_router(avatars.router)

    response = TestClient(app).get("/avatars/dogo-light2d/client-renderer")

    assert response.status_code == 404


def test_open_referenced_asset_reads_opened_inode_after_path_replacement(tmp_path: Path) -> None:
    context = load_light2d_renderer(_make_avatar(tmp_path))
    asset_path = context.renderer_root / "layers/base.png"

    with open_referenced_asset(context, "layers/base.png") as asset:
        original = asset.read()
        replacement = asset_path.with_suffix(".replacement.png")
        Image.new("RGBA", (64, 96), (255, 0, 0, 255)).save(replacement)
        replacement.replace(asset_path)
        asset.seek(0)
        reopened = asset.read()

    assert reopened == original


def test_client_asset_response_does_not_reopen_validated_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    avatar_dir = _make_avatar(tmp_path)
    original = (avatar_dir / "light2d/layers/base.png").read_bytes()
    real_open = avatars.open_referenced_asset

    @contextmanager
    def replace_after_open(context: object, asset_path: object):
        with real_open(context, asset_path) as asset:
            replacement = avatar_dir / "light2d/layers/replacement.png"
            Image.new("RGBA", (64, 96), (255, 0, 0, 255)).save(replacement)
            replacement.replace(avatar_dir / "light2d/layers/base.png")
            yield asset

    monkeypatch.setattr(avatars, "open_referenced_asset", replace_after_open)
    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path))
    app.include_router(avatars.router)

    response = TestClient(app).get("/avatars/dogo-light2d/client-assets/layers/base.png")

    assert response.status_code == 200
    assert response.content == original


@pytest.mark.parametrize(
    "path",
    [
        "../manifest.json",
        "%2e%2e/manifest.json",
        "layers%2fbase.png",
        "layers%5cbase.png",
        "layers\\base.png",
        "/etc/passwd",
        "layers/base.png%00.txt",
        "layers/unreferenced.png",
    ],
)
def test_client_asset_rejects_unsafe_or_unreferenced_paths(client: TestClient, path: str) -> None:
    response = client.get(f"/avatars/dogo-light2d/client-assets/{path}")

    assert response.status_code in {400, 404}


def test_client_asset_rejects_symlink_component(tmp_path: Path) -> None:
    avatar_dir = _make_avatar(tmp_path)
    target = tmp_path / "outside"
    target.mkdir()
    Image.new("RGBA", (4, 4), "white").save(target / "base.png")
    layer_dir = avatar_dir / "light2d" / "layers"
    for path in layer_dir.iterdir():
        path.unlink()
    layer_dir.rmdir()
    try:
        os.symlink(target, layer_dir, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable")

    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path))
    app.include_router(avatars.router)
    response = TestClient(app).get("/avatars/dogo-light2d/client-assets/layers/base.png")

    assert response.status_code in {400, 404}


def test_invalid_renderer_config_is_not_exposed(tmp_path: Path) -> None:
    invalid = _renderer_config()
    invalid["audio"]["small_threshold"] = 0.01
    _make_avatar(tmp_path, config=invalid)
    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path))
    app.include_router(avatars.router)
    client = TestClient(app)

    assert client.get("/avatars").json()[0]["client_renderer"] is None
    assert client.get("/avatars/dogo-light2d/client-renderer").status_code == 404


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_renderer_numbers_are_rejected(tmp_path: Path, value: float) -> None:
    invalid = _renderer_config()
    invalid["animation"]["breath_period_ms"] = value
    _make_avatar(tmp_path, config=invalid)
    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path))
    app.include_router(avatars.router)
    client = TestClient(app)

    assert client.get("/avatars/dogo-light2d/client-renderer").status_code == 404


def test_shared_contract_loads_valid_canonical_dogo(tmp_path: Path) -> None:
    avatar_dir = _make_avatar(tmp_path)

    context = load_canonical_dogo_renderer(avatar_dir)

    assert context.avatar_id == "dogo-light2d"
    assert context.model_type == "mock"
    assert context.config == _renderer_config()
    assert context.recommended_for == ("mock",)
    assert resolve_referenced_asset(context, "layers/base.png").is_file()


@pytest.mark.parametrize("asset_path", ["../base.png", "layers/unreferenced.png"])
def test_shared_contract_rejects_unsafe_or_unreferenced_asset(
    tmp_path: Path,
    asset_path: str,
) -> None:
    context = load_light2d_renderer(_make_avatar(tmp_path))

    with pytest.raises(Light2DContractError):
        resolve_referenced_asset(context, asset_path)


def test_shared_contract_rejects_symlink_asset_component(tmp_path: Path) -> None:
    avatar_dir = _make_avatar(tmp_path)
    target = tmp_path / "outside"
    target.mkdir()
    Image.new("RGBA", (4, 4), "white").save(target / "base.png")
    layer_dir = avatar_dir / "light2d" / "layers"
    for path in layer_dir.iterdir():
        path.unlink()
    layer_dir.rmdir()
    try:
        os.symlink(target, layer_dir, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable")

    with pytest.raises(Light2DContractError):
        load_canonical_dogo_renderer(avatar_dir)


def test_shared_contract_rejects_missing_referenced_layer(tmp_path: Path) -> None:
    avatar_dir = _make_avatar(tmp_path)
    (avatar_dir / "light2d/layers/mouth-large.png").unlink()

    with pytest.raises(Light2DContractError):
        load_light2d_renderer(avatar_dir)


def test_shared_contract_rejects_invalid_layer_rectangle(tmp_path: Path) -> None:
    invalid = _renderer_config()
    invalid["layers"]["base"]["rect"] = [0, 0, 65, 96]

    with pytest.raises(Light2DContractError):
        load_canonical_dogo_renderer(_make_avatar(tmp_path, config=invalid))


def test_shared_contract_rejects_fractional_layer_rectangle(tmp_path: Path) -> None:
    invalid = _renderer_config()
    invalid["layers"]["base"]["rect"] = [0.5, 0, 63, 96]

    with pytest.raises(Light2DContractError):
        load_canonical_dogo_renderer(_make_avatar(tmp_path, config=invalid))


@pytest.mark.parametrize(
    ("manifest_field", "value"),
    [("id", "other-avatar"), ("model_type", "wav2lip")],
)
def test_shared_contract_rejects_noncanonical_dogo_manifest(
    tmp_path: Path,
    manifest_field: str,
    value: str,
) -> None:
    avatar_dir = _make_avatar(tmp_path)
    manifest_path = avatar_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[manifest_field] = value
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(Light2DContractError):
        load_canonical_dogo_renderer(avatar_dir)
