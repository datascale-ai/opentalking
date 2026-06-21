from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import apps.unified.main as unified_main
from apps.api.routes import scene_assets
from opentalking.scene_assets import SceneAssetStore


PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\xe2!\xbc"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_scene_asset_store_creates_lists_and_deletes_background(tmp_path: Path) -> None:
    store = SceneAssetStore(tmp_path)

    created = store.create_background(
        content=PNG_BYTES,
        filename="studio.png",
        mime_type="image/png",
        name="Studio",
    )

    assert created["id"].startswith("bg-")
    assert created["name"] == "Studio"
    assert created["kind"] == "image"
    assert created["mime_type"] == "image/png"
    assert created["url"] == f"/scene-assets/backgrounds/{created['id']}/file"
    assert store.background_file_path(str(created["id"])).is_file()
    assert store.list_backgrounds()[0]["id"] == created["id"]
    assert store.delete_background(str(created["id"])) is True
    assert store.list_backgrounds() == []


def test_scene_asset_store_rejects_unsupported_background_type(tmp_path: Path) -> None:
    store = SceneAssetStore(tmp_path)

    with pytest.raises(ValueError, match="unsupported background media type"):
        store.create_background(
            content=b"not media",
            filename="notes.txt",
            mime_type="text/plain",
            name="Notes",
        )


def test_scene_asset_store_rejects_spoofed_background_content(tmp_path: Path) -> None:
    store = SceneAssetStore(tmp_path)

    with pytest.raises(ValueError, match="unsupported background media type"):
        store.create_background(
            content=b"plain text pretending to be an image",
            filename="studio.png",
            mime_type="image/png",
            name="Spoof",
        )


def test_scene_asset_store_rejects_zero_avatar_scale(tmp_path: Path) -> None:
    store = SceneAssetStore(tmp_path)

    with pytest.raises(ValueError, match="avatar_scale must be between 0.5 and 2.0"):
        store.create_composition(
            {
                "name": "Zero Scale",
                "avatar_id": "anchor",
                "avatar_scale": 0,
            }
        )


def test_scene_asset_store_rejects_unsafe_background_delete_id(tmp_path: Path) -> None:
    store = SceneAssetStore(tmp_path / "assets")
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / "keep.txt").write_text("keep", encoding="utf-8")

    unsafe_id = f"bg-valid/../../{outside_dir.name}"
    store.backgrounds_dir.mkdir(parents=True)
    store.background_index_path.write_text(
        f'[{{"id": "{unsafe_id}", "mime_type": "image/png"}}]\n',
        encoding="utf-8",
    )

    assert store.delete_background(unsafe_id) is False
    assert (outside_dir / "keep.txt").is_file()


def test_scene_asset_store_creates_and_updates_composition(tmp_path: Path) -> None:
    store = SceneAssetStore(tmp_path)
    background = store.create_background(
        content=PNG_BYTES,
        filename="studio.png",
        mime_type="image/png",
        name="Studio",
    )

    created = store.create_composition(
        {
            "name": "Demo Scene",
            "avatar_id": "anchor",
            "background_id": background["id"],
            "avatar_fit": "contain",
            "avatar_scale": 1.0,
            "avatar_anchor": "center",
            "matting_required": True,
            "subtitle_style": "lower-third",
        }
    )

    assert created["id"].startswith("scene-")
    assert created["background_id"] == background["id"]
    assert created["matting_required"] is True
    assert store.list_compositions()[0]["id"] == created["id"]

    updated = store.update_composition(str(created["id"]), {"name": "Updated", "avatar_scale": 1.25})
    assert updated is not None
    assert updated["name"] == "Updated"
    assert updated["avatar_scale"] == 1.25
    assert updated["avatar_id"] == "anchor"

    assert store.delete_composition(str(created["id"])) is True
    assert store.list_compositions() == []


def test_scene_asset_store_rejects_unknown_background_id(tmp_path: Path) -> None:
    store = SceneAssetStore(tmp_path)

    with pytest.raises(ValueError, match="background_id not found"):
        store.create_composition(
            {
                "name": "Missing Background",
                "avatar_id": "anchor",
                "background_id": "bg-missing",
            }
        )

    background = store.create_background(
        content=PNG_BYTES,
        filename="studio.png",
        mime_type="image/png",
        name="Studio",
    )
    created = store.create_composition(
        {
            "name": "Demo Scene",
            "avatar_id": "anchor",
            "background_id": background["id"],
        }
    )
    with pytest.raises(ValueError, match="background_id not found"):
        store.update_composition(str(created["id"]), {"background_id": "bg-missing"})


def _client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.state.settings = SimpleNamespace(
        scene_assets_dir=str(tmp_path / "scene-assets"),
        scene_asset_max_bytes=len(PNG_BYTES),
    )
    app.include_router(scene_assets.router)
    return TestClient(app)


def test_scene_asset_api_uploads_lists_downloads_and_deletes_background(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        upload = client.post(
            "/scene-assets/backgrounds",
            data={"name": "Studio"},
            files={"file": ("studio.png", PNG_BYTES, "image/png")},
        )
        assert upload.status_code == 200
        item = upload.json()
        assert item["name"] == "Studio"
        assert item["url"] == f"/scene-assets/backgrounds/{item['id']}/file"

        listed = client.get("/scene-assets/backgrounds")
        assert listed.status_code == 200
        assert listed.json()["items"][0]["id"] == item["id"]

        downloaded = client.get(item["url"])
        assert downloaded.status_code == 200
        assert downloaded.headers["content-type"].startswith("image/png")

        deleted = client.delete(f"/scene-assets/backgrounds/{item['id']}")
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True


def test_scene_asset_api_rejects_oversized_background_upload(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        upload = client.post(
            "/scene-assets/backgrounds",
            data={"name": "Too Big"},
            files={"file": ("studio.png", PNG_BYTES + b"x", "image/png")},
        )
        assert upload.status_code == 413
        assert upload.json()["detail"] == "background asset exceeds size limit"


def test_scene_asset_api_rejects_spoofed_content_type(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        upload = client.post(
            "/scene-assets/backgrounds",
            data={"name": "Spoof"},
            files={"file": ("studio.png", b"this is plain text", "image/png")},
        )
        assert upload.status_code == 400
        assert upload.json()["detail"] == "unsupported background media type"


def test_scene_asset_api_manages_compositions(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        bg = client.post(
            "/scene-assets/backgrounds",
            data={"name": "Studio"},
            files={"file": ("studio.png", PNG_BYTES, "image/png")},
        ).json()

        created = client.post(
            "/scene-assets/compositions",
            json={
                "name": "Demo Scene",
                "avatar_id": "anchor",
                "background_id": bg["id"],
                "avatar_fit": "contain",
                "avatar_scale": 1.0,
                "avatar_anchor": "center",
                "matting_required": True,
                "subtitle_style": "lower-third",
            },
        )
        assert created.status_code == 200
        scene = created.json()
        assert scene["background_id"] == bg["id"]

        patched = client.patch(
            f"/scene-assets/compositions/{scene['id']}",
            json={"name": "Updated Scene", "avatar_scale": 1.2},
        )
        assert patched.status_code == 200
        assert patched.json()["name"] == "Updated Scene"
        assert patched.json()["avatar_scale"] == 1.2

        listed = client.get("/scene-assets/compositions")
        assert listed.status_code == 200
        assert listed.json()["items"][0]["id"] == scene["id"]

        deleted = client.delete(f"/scene-assets/compositions/{scene['id']}")
        assert deleted.status_code == 200
        assert deleted.json() == {"id": scene["id"], "deleted": True}

        listed_after_delete = client.get("/scene-assets/compositions")
        assert listed_after_delete.status_code == 200
        assert listed_after_delete.json()["items"] == []

        deleted_again = client.delete(f"/scene-assets/compositions/{scene['id']}")
        assert deleted_again.status_code == 404


def test_scene_asset_api_rejects_unknown_background_id(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        created = client.post(
            "/scene-assets/compositions",
            json={
                "name": "Missing Background",
                "avatar_id": "anchor",
                "background_id": "bg-missing",
            },
        )
        assert created.status_code == 400
        assert created.json()["detail"] == "background_id not found"


def test_unified_app_registers_scene_asset_routes() -> None:
    app = unified_main.create_app()

    paths = set(app.openapi()["paths"])

    assert "/scene-assets/backgrounds" in paths
    assert "/scene-assets/compositions" in paths
