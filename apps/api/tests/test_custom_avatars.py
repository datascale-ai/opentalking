from __future__ import annotations

import json
from io import BytesIO
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from apps.api.routes import avatars, sessions


def _png_bytes(size: tuple[int, int] = (8, 8)) -> bytes:
    out = BytesIO()
    Image.new("RGB", size, (10, 180, 210)).save(out, format="PNG")
    return out.getvalue()


def test_create_custom_avatar_adds_listed_asset_with_preview(tmp_path):
    base = tmp_path / "base-avatar"
    base.mkdir()
    (base / "preview.png").write_bytes(_png_bytes())
    (base / "reference.png").write_bytes(_png_bytes())
    (base / "manifest.json").write_text(
        json.dumps(
            {
                "id": "base-avatar",
                "name": "Base Avatar",
                "model_type": "flashtalk",
                "fps": 25,
                "sample_rate": 16000,
                "width": 416,
                "height": 704,
                "version": "1.0",
            }
        ),
        encoding="utf-8",
    )

    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path))
    app.include_router(avatars.router)
    client = TestClient(app)

    response = client.post(
        "/avatars/custom",
        data={"base_avatar_id": "base-avatar", "name": "我的形象"},
        files={"image": ("avatar.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    created = response.json()
    assert created["id"].startswith("custom-")
    assert created["name"] == "我的形象"
    assert created["model_type"] == "flashtalk"

    custom_dir = tmp_path / created["id"]
    assert (custom_dir / "manifest.json").is_file()
    assert (custom_dir / "preview.png").is_file()
    assert (custom_dir / "reference.png").is_file()

    listed = client.get("/avatars").json()
    assert any(item["id"] == created["id"] and item["name"] == "我的形象" for item in listed)

    preview = client.get(f"/avatars/{created['id']}/preview")
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"


def test_create_custom_wav2lip_avatar_writes_frame_and_mouth_metadata(tmp_path, monkeypatch):
    base = tmp_path / "base-wav2lip"
    base.mkdir()
    (base / "preview.png").write_bytes(_png_bytes())
    (base / "reference.png").write_bytes(_png_bytes())
    (base / "frames").mkdir()
    (base / "frames" / "frame_00000.png").write_bytes(_png_bytes())
    (base / "manifest.json").write_text(
        json.dumps(
            {
                "id": "base-wav2lip",
                "name": "Base Wav2Lip",
                "model_type": "wav2lip",
                "fps": 25,
                "sample_rate": 16000,
                "width": 416,
                "height": 704,
                "version": "1.0",
            }
        ),
        encoding="utf-8",
    )

    def fake_detect(frame):
        from opentalking.avatar.mouth_metadata import AvatarMouthLandmarks

        height, width = frame.shape[:2]
        return AvatarMouthLandmarks(
            mouth_center=(width // 2, height * 5 // 8),
            mouth_rx=width // 4,
            mouth_ry=height // 8,
            outer_lip=((width // 4, height * 5 // 8), (width // 2, height // 2), (width * 3 // 4, height * 5 // 8), (width // 2, height * 3 // 4)),
            inner_mouth=((width * 3 // 8, height * 5 // 8), (width * 5 // 8, height * 5 // 8), (width // 2, height * 3 // 4)),
        )

    monkeypatch.setattr(avatars.mouth_metadata, "detect_mouth_landmarks", fake_detect)

    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path))
    app.include_router(avatars.router)
    client = TestClient(app)

    response = client.post(
        "/avatars/custom",
        data={"base_avatar_id": "base-wav2lip", "name": "我的Wav2Lip形象"},
        files={"image": ("avatar.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    created = response.json()
    custom_dir = tmp_path / created["id"]
    assert (custom_dir / "frames" / "frame_00000.png").is_file()
    manifest = json.loads((custom_dir / "manifest.json").read_text(encoding="utf-8"))
    metadata = manifest["metadata"]
    assert metadata["custom_avatar"] is True
    assert len(metadata["source_image_hash"]) == 64
    assert metadata["animation"]["outer_lip"] == [[0.25, 0.625], [0.5, 0.5], [0.75, 0.625], [0.5, 0.75]]


def test_create_custom_avatar_from_non_wav2lip_base_writes_mouth_metadata(tmp_path, monkeypatch):
    base = tmp_path / "base-musetalk"
    base.mkdir()
    (base / "preview.png").write_bytes(_png_bytes())
    (base / "reference.png").write_bytes(_png_bytes())
    (base / "manifest.json").write_text(
        json.dumps(
            {
                "id": "base-musetalk",
                "name": "Base MuseTalk",
                "model_type": "musetalk",
                "fps": 25,
                "sample_rate": 16000,
                "width": 416,
                "height": 704,
                "version": "1.0",
                "metadata": {
                    "source_image_hash": "old",
                    "animation": {"outer_lip": [[0.1, 0.1], [0.2, 0.1], [0.15, 0.2]]},
                },
            }
        ),
        encoding="utf-8",
    )

    def fake_detect(frame):
        from opentalking.avatar.mouth_metadata import AvatarMouthLandmarks

        height, width = frame.shape[:2]
        return AvatarMouthLandmarks(
            mouth_center=(width // 2, height * 5 // 8),
            mouth_rx=width // 4,
            mouth_ry=height // 8,
            outer_lip=((width // 4, height * 5 // 8), (width // 2, height // 2), (width * 3 // 4, height * 5 // 8), (width // 2, height * 3 // 4)),
        )

    monkeypatch.setattr(avatars.mouth_metadata, "detect_mouth_landmarks", fake_detect)

    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path))
    app.include_router(avatars.router)
    client = TestClient(app)

    response = client.post(
        "/avatars/custom",
        data={"base_avatar_id": "base-musetalk", "name": "可用于Wav2Lip的形象"},
        files={"image": ("avatar.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    created = response.json()
    manifest = json.loads((tmp_path / created["id"] / "manifest.json").read_text(encoding="utf-8"))
    metadata = manifest["metadata"]
    assert metadata["custom_avatar"] is True
    assert metadata["source_image_hash"] != "old"
    assert metadata["source_image_path"] == "reference.png"
    assert metadata["mouth_polygon_source"] == "mediapipe"
    assert metadata["animation"]["outer_lip"] == [[0.25, 0.625], [0.5, 0.5], [0.75, 0.625], [0.5, 0.75]]


def test_create_custom_avatar_resizes_large_upload_to_realtime_max(tmp_path, monkeypatch):
    base = tmp_path / "base-wav2lip"
    base.mkdir()
    (base / "preview.png").write_bytes(_png_bytes((416, 704)))
    (base / "reference.png").write_bytes(_png_bytes((416, 704)))
    (base / "frames").mkdir()
    (base / "frames" / "frame_00000.png").write_bytes(_png_bytes((416, 704)))
    (base / "manifest.json").write_text(
        json.dumps(
            {
                "id": "base-wav2lip",
                "name": "Base Wav2Lip",
                "model_type": "wav2lip",
                "fps": 25,
                "sample_rate": 16000,
                "width": 416,
                "height": 704,
                "version": "1.0",
            }
        ),
        encoding="utf-8",
    )

    def fake_detect(frame):
        from opentalking.avatar.mouth_metadata import AvatarMouthLandmarks

        height, width = frame.shape[:2]
        return AvatarMouthLandmarks(
            mouth_center=(width // 2, height // 2),
            mouth_rx=width // 8,
            mouth_ry=height // 32,
            outer_lip=((width // 4, height // 2), (width // 2, height // 2 - 10), (width * 3 // 4, height // 2)),
        )

    monkeypatch.setattr(avatars.mouth_metadata, "detect_mouth_landmarks", fake_detect)

    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path))
    app.include_router(avatars.router)
    client = TestClient(app)

    response = client.post(
        "/avatars/custom",
        data={"base_avatar_id": "base-wav2lip", "name": "大图上传"},
        files={"image": ("avatar.png", _png_bytes((2203, 1633)), "image/png")},
    )

    assert response.status_code == 200
    created = response.json()
    custom_dir = tmp_path / created["id"]
    manifest = json.loads((custom_dir / "manifest.json").read_text(encoding="utf-8"))
    assert (manifest["width"], manifest["height"]) == (720, 534)
    assert Image.open(custom_dir / "reference.png").size == (720, 534)
    assert Image.open(custom_dir / "preview.png").size == (720, 534)
    assert Image.open(custom_dir / "frames" / "frame_00000.png").size == (720, 534)


def test_customize_reference_updates_mouth_metadata_for_uploaded_image(tmp_path, monkeypatch):
    base = tmp_path / "demo-avatar"
    base.mkdir()
    (base / "preview.png").write_bytes(_png_bytes())
    (base / "reference.png").write_bytes(_png_bytes())
    (base / "manifest.json").write_text(
        json.dumps(
            {
                "id": "demo-avatar",
                "name": "Demo",
                "model_type": "musetalk",
                "fps": 25,
                "sample_rate": 16000,
                "width": 416,
                "height": 704,
                "version": "1.0",
                "metadata": {
                    "source_image_hash": "old",
                    "animation": {"outer_lip": [[0.1, 0.1], [0.2, 0.1], [0.15, 0.2]]},
                },
            }
        ),
        encoding="utf-8",
    )

    def fake_detect(frame):
        from opentalking.avatar.mouth_metadata import AvatarMouthLandmarks

        return AvatarMouthLandmarks(
            mouth_center=(4, 5),
            mouth_rx=2,
            mouth_ry=1,
            outer_lip=((2, 5), (4, 4), (6, 5), (4, 6)),
        )

    monkeypatch.setattr(avatars.mouth_metadata, "detect_mouth_landmarks", fake_detect)

    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path))
    app.include_router(sessions.router)
    client = TestClient(app)

    response = client.post(
        "/sessions/customize/reference",
        data={"avatar_id": "demo-avatar"},
        files={"reference_image": ("avatar.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    metadata = manifest["metadata"]
    assert metadata["source_image_hash"] != "old"
    assert metadata["source_image_path"] == "reference_custom.png"
    assert metadata["mouth_polygon_source"] == "mediapipe"
    assert metadata["animation"]["outer_lip"] == [[0.25, 0.625], [0.5, 0.5], [0.75, 0.625], [0.5, 0.75]]


def test_customize_reference_clears_stale_mouth_metadata_when_detection_fails(tmp_path, monkeypatch):
    base = tmp_path / "demo-avatar"
    base.mkdir()
    (base / "preview.png").write_bytes(_png_bytes())
    (base / "reference.png").write_bytes(_png_bytes())
    (base / "manifest.json").write_text(
        json.dumps(
            {
                "id": "demo-avatar",
                "name": "Demo",
                "model_type": "wav2lip",
                "fps": 25,
                "sample_rate": 16000,
                "width": 416,
                "height": 704,
                "version": "1.0",
                "metadata": {
                    "source_image_hash": "old",
                    "source_image_path": "old.png",
                    "mouth_polygon_source": "mediapipe",
                    "face_box": [0.1, 0.2, 0.8, 0.9],
                    "animation": {"outer_lip": [[0.1, 0.1], [0.2, 0.1], [0.15, 0.2]]},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(avatars.mouth_metadata, "detect_mouth_landmarks", lambda frame: None)

    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path))
    app.include_router(sessions.router)
    client = TestClient(app)

    response = client.post(
        "/sessions/customize/reference",
        data={"avatar_id": "demo-avatar"},
        files={"reference_image": ("avatar.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    metadata = manifest["metadata"]
    assert metadata["source_image_hash"] != "old"
    assert metadata["source_image_path"] == "reference_custom.png"
    assert metadata["mouth_polygon_source"] == "unavailable"
    assert "animation" not in metadata
    assert "face_box" not in metadata


def test_delete_custom_avatar_removes_directory(tmp_path):
    base = tmp_path / "base-avatar"
    base.mkdir()
    (base / "preview.png").write_bytes(_png_bytes())
    (base / "reference.png").write_bytes(_png_bytes())
    (base / "manifest.json").write_text(
        json.dumps(
            {
                "id": "base-avatar",
                "name": "Base",
                "model_type": "flashtalk",
                "fps": 25,
                "sample_rate": 16000,
                "width": 416,
                "height": 704,
                "version": "1.0",
            }
        ),
        encoding="utf-8",
    )

    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path))
    app.include_router(avatars.router)
    client = TestClient(app)

    created = client.post(
        "/avatars/custom",
        data={"base_avatar_id": "base-avatar", "name": "tmp"},
        files={"image": ("a.png", _png_bytes(), "image/png")},
    ).json()

    response = client.delete(f"/avatars/{created['id']}")
    assert response.status_code == 200
    assert response.json()["status"] == "deleted"
    assert not (tmp_path / created["id"]).exists()
    assert not any(item["id"] == created["id"] for item in client.get("/avatars").json())


def test_delete_builtin_avatar_forbidden(tmp_path):
    """Built-in demos lack metadata.custom_avatar, so DELETE → 403."""
    base = tmp_path / "demo-avatar"
    base.mkdir()
    (base / "preview.png").write_bytes(_png_bytes())
    (base / "reference.png").write_bytes(_png_bytes())
    (base / "manifest.json").write_text(
        json.dumps(
            {
                "id": "demo-avatar",
                "name": "Demo",
                "model_type": "flashtalk",
                "fps": 25,
                "sample_rate": 16000,
                "width": 416,
                "height": 704,
                "version": "1.0",
            }
        ),
        encoding="utf-8",
    )

    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path))
    app.include_router(avatars.router)
    client = TestClient(app)

    response = client.delete("/avatars/demo-avatar")
    assert response.status_code == 403
    assert "built-in" in response.json()["detail"]
    assert (tmp_path / "demo-avatar").exists()


def test_delete_unknown_avatar_404(tmp_path):
    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path))
    app.include_router(avatars.router)
    client = TestClient(app)

    assert client.delete("/avatars/does-not-exist").status_code == 404
