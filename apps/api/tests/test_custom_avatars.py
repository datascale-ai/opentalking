from __future__ import annotations

import json
import hashlib
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from apps.cli import prepare_cache
from apps.api.routes import avatars, sessions

REPO_ROOT = Path(__file__).resolve().parents[3]


def _png_bytes(size: tuple[int, int] = (8, 8)) -> bytes:
    out = BytesIO()
    Image.new("RGB", size, (10, 180, 210)).save(out, format="PNG")
    return out.getvalue()


def _transparent_png_bytes(size: tuple[int, int] = (8, 8)) -> bytes:
    image = Image.new("RGBA", size, (10, 180, 210, 255))
    image.putpixel((0, 0), (10, 180, 210, 0))
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _path_has_suffix(path: str, *suffix: str) -> bool:
    return Path(path).parts[-len(suffix):] == suffix


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


def test_create_custom_avatar_persists_selected_person_mode(tmp_path: Path) -> None:
    base = tmp_path / "base-avatar"
    base.mkdir()
    (base / "preview.png").write_bytes(_png_bytes())
    (base / "reference.png").write_bytes(_png_bytes())
    (base / "manifest.json").write_text(
        json.dumps(
            {
                "id": "base-avatar",
                "name": "Base Avatar",
                "model_type": "quicktalk",
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
        data={"base_avatar_id": "base-avatar", "name": "双人上传素材", "model": "quicktalk", "person_mode": "double"},
        files={"image": ("avatar.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    created = response.json()
    assert created["person_mode"] == "double"
    manifest = json.loads((tmp_path / created["id"] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["metadata"]["person_mode"] == "double"
    assert manifest["metadata"]["duo_dialog"]["speaker_faces"] == {"left": "left", "right": "right"}


def test_update_avatar_person_mode_writes_only_person_mode(tmp_path: Path) -> None:
    avatar_dir = tmp_path / "anchor"
    avatar_dir.mkdir()
    (avatar_dir / "preview.png").write_bytes(_png_bytes())
    (avatar_dir / "reference.png").write_bytes(_png_bytes())
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "anchor",
                "name": "Anchor",
                "model_type": "quicktalk",
                "fps": 25,
                "sample_rate": 16000,
                "width": 64,
                "height": 48,
                "version": "1.0",
                "metadata": {"source_image": "source/source.png", "person_mode": "single"},
            }
        ),
        encoding="utf-8",
    )

    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path))
    app.include_router(avatars.router)
    client = TestClient(app)

    response = client.patch("/avatars/anchor/person-mode", json={"person_mode": "double"})

    assert response.status_code == 200
    assert response.json()["person_mode"] == "double"
    manifest = json.loads((avatar_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["metadata"]["source_image"] == "source/source.png"
    assert manifest["metadata"]["person_mode"] == "double"
    assert manifest["metadata"]["duo_dialog"]["speaker_faces"] == {"left": "left", "right": "right"}


def test_avatar_summary_includes_matting_status(tmp_path: Path) -> None:
    root = tmp_path
    avatar_dir = root / "anchor"
    avatar_dir.mkdir()
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "anchor",
                "name": "Anchor",
                "model_type": "flashtalk",
                "fps": 25,
                "sample_rate": 16000,
                "width": 1,
                "height": 1,
                "version": "1.0",
                "metadata": {"matting_status": "transparent_ready"},
            }
        ),
        encoding="utf-8",
    )
    (avatar_dir / "preview.png").write_bytes(_png_bytes())
    (avatar_dir / "reference.png").write_bytes(_png_bytes())

    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(root))
    app.include_router(avatars.router)
    response = TestClient(app).get("/avatars")

    assert response.status_code == 200
    assert response.json()[0]["matting_status"] == "transparent_ready"


def test_avatar_summary_defaults_missing_person_mode_to_single(tmp_path: Path) -> None:
    root = tmp_path
    avatar_dir = root / "anchor"
    avatar_dir.mkdir()
    (avatar_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "anchor",
                "name": "Anchor",
                "model_type": "flashtalk",
                "fps": 25,
                "sample_rate": 16000,
                "width": 1,
                "height": 1,
                "version": "1.0",
            }
        ),
        encoding="utf-8",
    )
    (avatar_dir / "preview.png").write_bytes(_png_bytes())
    (avatar_dir / "reference.png").write_bytes(_png_bytes())

    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(root))
    app.include_router(avatars.router)
    response = TestClient(app).get("/avatars")

    assert response.status_code == 200
    assert response.json()[0]["person_mode"] == "single"


def test_avatar_summary_exposes_duo_dialog_metadata_only_when_declared(tmp_path: Path) -> None:
    duo_dir = tmp_path / "duo-anchor"
    plain_dir = tmp_path / "plain-anchor"
    for avatar_dir, metadata in (
        (
            duo_dir,
            {
                "duo_dialog": {
                    "speaker_faces": {"male": "left", "female": "right"},
                    "default_voices": {
                        "male": "zh-CN-YunxiNeural",
                        "female": "zh-CN-XiaoxiaoNeural",
                    },
                }
            },
        ),
        (plain_dir, {}),
    ):
        avatar_dir.mkdir()
        (avatar_dir / "preview.png").write_bytes(_png_bytes())
        (avatar_dir / "reference.png").write_bytes(_png_bytes())
        (avatar_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "id": avatar_dir.name,
                    "name": avatar_dir.name,
                    "model_type": "quicktalk",
                    "fps": 25,
                    "sample_rate": 16000,
                    "width": 64,
                    "height": 48,
                    "version": "1.0",
                    "metadata": metadata,
                }
            ),
            encoding="utf-8",
        )

    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path))
    app.include_router(avatars.router)
    response = TestClient(app).get("/avatars")

    assert response.status_code == 200
    by_id = {item["id"]: item for item in response.json()}
    assert by_id["duo-anchor"]["person_mode"] == "double"
    assert by_id["plain-anchor"]["person_mode"] == "single"
    assert by_id["duo-anchor"]["duo_dialog"] == {
        "speaker_faces": {"male": "left", "female": "right"},
        "default_voices": {
            "male": "zh-CN-YunxiNeural",
            "female": "zh-CN-XiaoxiaoNeural",
        },
    }
    assert by_id["plain-anchor"]["duo_dialog"] is None


def test_avatar_summary_orders_numbered_duo_dialog_assets_together(tmp_path: Path) -> None:
    def write_avatar(dirname: str, name: str, *, duo: bool) -> None:
        avatar_dir = tmp_path / dirname
        avatar_dir.mkdir()
        (avatar_dir / "preview.png").write_bytes(_png_bytes())
        (avatar_dir / "reference.png").write_bytes(_png_bytes())
        metadata = {}
        if duo:
            metadata["duo_dialog"] = {
                "speaker_faces": {"female": "left", "male": "right"},
                "default_voices": {
                    "female": "zh-CN-XiaoxiaoNeural",
                    "male": "zh-CN-YunxiNeural",
                },
            }
        (avatar_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "id": dirname,
                    "name": name,
                    "model_type": "quicktalk" if duo else "flashtalk",
                    "fps": 25,
                    "sample_rate": 16000,
                    "width": 64,
                    "height": 48,
                    "version": "1.0",
                    "metadata": metadata,
                }
            ),
            encoding="utf-8",
        )

    write_avatar("a-duo-1", "双人对话1", duo=True)
    write_avatar("b-plain", "普通素材", duo=False)
    write_avatar("c-duo-3", "双人对话3", duo=True)
    write_avatar("d-duo-2", "双人对话2", duo=True)

    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path))
    app.include_router(avatars.router)
    response = TestClient(app).get("/avatars")

    assert response.status_code == 200
    assert [item["name"] for item in response.json()] == [
        "双人对话1",
        "双人对话2",
        "双人对话3",
        "普通素材",
    ]


def test_avatar_summary_groups_renamed_duo_dialog_assets_together(tmp_path: Path) -> None:
    def write_avatar(dirname: str, name: str, *, duo: bool) -> None:
        avatar_dir = tmp_path / dirname
        avatar_dir.mkdir()
        (avatar_dir / "preview.png").write_bytes(_png_bytes())
        (avatar_dir / "reference.png").write_bytes(_png_bytes())
        metadata = {"person_mode": "single"}
        if duo:
            metadata = {
                "person_mode": "double",
                "duo_dialog": {
                    "speaker_faces": {"female": "left", "male": "right"},
                    "default_voices": {
                        "female": "zh-CN-XiaoxiaoNeural",
                        "male": "zh-CN-YunxiNeural",
                    },
                },
            }
        (avatar_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "id": dirname,
                    "name": name,
                    "model_type": "quicktalk" if duo else "flashtalk",
                    "fps": 25,
                    "sample_rate": 16000,
                    "width": 64,
                    "height": 48,
                    "version": "1.0",
                    "metadata": metadata,
                }
            ),
            encoding="utf-8",
        )

    write_avatar("a-single", "主播", duo=False)
    write_avatar("b-video-call", "视频通话", duo=True)
    write_avatar("c-news-duo", "新闻双人主播", duo=True)
    write_avatar("d-single", "女主持", duo=False)
    write_avatar("e-hd-news-duo", "访谈双人主播", duo=True)

    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path))
    app.include_router(avatars.router)
    response = TestClient(app).get("/avatars")

    assert response.status_code == 200
    assert [item["name"] for item in response.json()] == [
        "主播",
        "视频通话",
        "新闻双人主播",
        "访谈双人主播",
        "女主持",
    ]


def test_builtin_female_host_transparent_avatar_asset_is_ready() -> None:
    avatar_dir = REPO_ROOT / "examples" / "avatars" / "female-host-transparent"
    manifest = json.loads((avatar_dir / "manifest.json").read_text(encoding="utf-8"))
    reference = avatar_dir / "reference.png"
    preview = avatar_dir / "preview.png"
    source = avatar_dir / "source" / "source.png"

    assert manifest["id"] == "female-host-transparent"
    assert manifest["name"] == "女主持（透明背景）"
    assert manifest["metadata"]["matting_status"] == "transparent_ready"
    assert manifest["metadata"]["source_image"] == "source/source.png"
    assert manifest["metadata"]["source_image_path"] == "reference.png"
    assert reference.is_file()
    assert preview.is_file()
    assert source.is_file()

    image = Image.open(reference)
    assert image.mode == "RGBA"
    assert image.size == (manifest["width"], manifest["height"])
    assert image.getchannel("A").getextrema() == (0, 255)
    assert hashlib.sha256(reference.read_bytes()).hexdigest() == manifest["metadata"]["source_image_hash"]


def test_create_custom_avatar_preserves_uploaded_png_alpha(tmp_path, monkeypatch):
    base = tmp_path / "base-avatar"
    base.mkdir()
    (base / "preview.png").write_bytes(_png_bytes())
    (base / "reference.png").write_bytes(_png_bytes())
    (base / "manifest.json").write_text(
        json.dumps(
            {
                "id": "base-avatar",
                "name": "Base Avatar",
                "model_type": "mock",
                "fps": 25,
                "sample_rate": 16000,
                "width": 8,
                "height": 8,
                "version": "1.0",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(avatars.mouth_metadata, "detect_mouth_landmarks", lambda frame: None)

    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path))
    app.include_router(avatars.router)
    client = TestClient(app)

    response = client.post(
        "/avatars/custom",
        data={"base_avatar_id": "base-avatar", "name": "透明形象"},
        files={"image": ("avatar.png", _transparent_png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    created = response.json()
    assert created["matting_status"] == "transparent_ready"
    custom_dir = tmp_path / created["id"]
    manifest = json.loads((custom_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["metadata"]["matting_status"] == "transparent_ready"
    for rel in ("reference.png", "preview.png", "source/source.png"):
        image = Image.open(custom_dir / rel)
        assert image.mode == "RGBA"
        assert image.getchannel("A").getextrema()[0] == 0


def test_create_custom_avatar_does_not_remove_background_by_default(tmp_path, monkeypatch):
    base = tmp_path / "base-avatar"
    base.mkdir()
    (base / "preview.png").write_bytes(_png_bytes())
    (base / "reference.png").write_bytes(_png_bytes())
    (base / "manifest.json").write_text(
        json.dumps(
            {
                "id": "base-avatar",
                "name": "Base Avatar",
                "model_type": "mock",
                "fps": 25,
                "sample_rate": 16000,
                "width": 8,
                "height": 8,
                "version": "1.0",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(avatars.mouth_metadata, "detect_mouth_landmarks", lambda frame: None)

    def fail_remove_background(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("matting provider should not run unless requested")

    monkeypatch.setattr(avatars, "remove_avatar_background", fail_remove_background)

    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path))
    app.include_router(avatars.router)
    client = TestClient(app)

    response = client.post(
        "/avatars/custom",
        data={"base_avatar_id": "base-avatar", "name": "普通形象"},
        files={"image": ("avatar.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    created = response.json()
    custom_dir = tmp_path / created["id"]
    manifest = json.loads((custom_dir / "manifest.json").read_text(encoding="utf-8"))
    assert created["matting_status"] == "opaque"
    assert manifest["metadata"]["matting_status"] == "opaque"
    assert "matting_provider" not in manifest["metadata"]
    assert not (custom_dir / "source" / "original.png").exists()


def test_create_custom_avatar_removes_background_when_requested(tmp_path, monkeypatch):
    base = tmp_path / "base-avatar"
    base.mkdir()
    (base / "preview.png").write_bytes(_png_bytes())
    (base / "reference.png").write_bytes(_png_bytes())
    (base / "manifest.json").write_text(
        json.dumps(
            {
                "id": "base-avatar",
                "name": "Base Avatar",
                "model_type": "mock",
                "fps": 25,
                "sample_rate": 16000,
                "width": 8,
                "height": 8,
                "version": "1.0",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(avatars.mouth_metadata, "detect_mouth_landmarks", lambda frame: None)

    calls: list[str] = []

    def fake_remove_background(image, *, provider_name, settings):
        calls.append(provider_name)
        result = image.convert("RGBA")
        result.putpixel((0, 0), (*result.getpixel((0, 0))[:3], 0))
        return result, "fake-provider"

    monkeypatch.setattr(avatars, "remove_avatar_background", fake_remove_background)

    app = FastAPI()
    app.state.settings = SimpleNamespace(
        avatars_dir=str(tmp_path),
        avatar_matting_provider="configured-provider",
        avatar_matting_device="cpu",
        avatar_matting_timeout_sec=30,
    )
    app.include_router(avatars.router)
    client = TestClient(app)

    response = client.post(
        "/avatars/custom",
        data={"base_avatar_id": "base-avatar", "name": "抠图形象", "remove_background": "true"},
        files={"image": ("avatar.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    assert calls == ["configured-provider"]
    created = response.json()
    custom_dir = tmp_path / created["id"]
    manifest = json.loads((custom_dir / "manifest.json").read_text(encoding="utf-8"))
    assert created["matting_status"] == "transparent_ready"
    assert manifest["metadata"]["matting_status"] == "transparent_ready"
    assert manifest["metadata"]["matting_provider"] == "fake-provider"
    assert manifest["metadata"]["matting_source"] == "upload_auto"
    assert manifest["metadata"]["original_source_image"] == "source/original.png"
    assert (custom_dir / "source" / "original.png").is_file()
    assert Image.open(custom_dir / "reference.png").getchannel("A").getextrema()[0] == 0


def test_create_custom_avatar_reports_missing_matting_model(tmp_path, monkeypatch):
    base = tmp_path / "base-avatar"
    base.mkdir()
    (base / "preview.png").write_bytes(_png_bytes())
    (base / "reference.png").write_bytes(_png_bytes())
    (base / "manifest.json").write_text(
        json.dumps(
            {
                "id": "base-avatar",
                "name": "Base Avatar",
                "model_type": "mock",
                "fps": 25,
                "sample_rate": 16000,
                "width": 8,
                "height": 8,
                "version": "1.0",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(avatars.mouth_metadata, "detect_mouth_landmarks", lambda frame: None)

    def fail_missing_model(*args, **kwargs):  # noqa: ANN002, ANN003
        raise avatars.MattingError("未找到抠除背景模型 u2net.onnx。\n下载地址：https://example.test/u2net.onnx")

    monkeypatch.setattr(avatars, "remove_avatar_background", fail_missing_model)

    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path))
    app.include_router(avatars.router)

    response = TestClient(app).post(
        "/avatars/custom",
        data={"base_avatar_id": "base-avatar", "name": "缺模型形象", "remove_background": "true"},
        files={"image": ("avatar.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 400
    assert "未找到抠除背景模型" in response.json()["detail"]
    assert not any(path.name.startswith("custom-") for path in tmp_path.iterdir() if path.is_dir())


def test_quicktalk_model_root_falls_back_to_omnirt_model_root(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENTALKING_QUICKTALK_ASSET_ROOT", raising=False)
    monkeypatch.delenv("OPENTALKING_QUICKTALK_MODEL_ROOT", raising=False)
    monkeypatch.delenv("OMNIRT_QUICKTALK_MODEL_ROOT", raising=False)
    monkeypatch.setenv("OMNIRT_MODEL_ROOT", str(tmp_path / "shared-models"))

    settings = SimpleNamespace(models_dir=str(tmp_path / "repo-models"))

    assert avatars._settings_quicktalk_model_root(settings) == (
        tmp_path / "shared-models" / "quicktalk"
    ).resolve()


def test_quicktalk_model_root_prefers_asset_root_setting_and_env(tmp_path, monkeypatch):
    env_asset_root = tmp_path / "env-quicktalk"
    setting_asset_root = tmp_path / "settings-quicktalk"
    monkeypatch.setenv("OPENTALKING_QUICKTALK_ASSET_ROOT", str(env_asset_root))
    monkeypatch.setenv("OPENTALKING_QUICKTALK_MODEL_ROOT", str(tmp_path / "legacy-env-root"))
    monkeypatch.setenv("OMNIRT_QUICKTALK_MODEL_ROOT", str(tmp_path / "omnirt-env-root"))
    monkeypatch.setenv("OMNIRT_MODEL_ROOT", str(tmp_path / "shared-models"))

    settings = SimpleNamespace(
        models_dir=str(tmp_path / "repo-models"),
        quicktalk_asset_root=str(setting_asset_root),
        quicktalk_model_root=str(tmp_path / "legacy-settings-root"),
    )

    assert avatars._settings_quicktalk_model_root(settings) == setting_asset_root.resolve()

    settings.quicktalk_asset_root = ""
    assert avatars._settings_quicktalk_model_root(settings) == env_asset_root.resolve()

    monkeypatch.delenv("OPENTALKING_QUICKTALK_ASSET_ROOT")
    assert avatars._settings_quicktalk_model_root(settings) == (
        tmp_path / "legacy-settings-root"
    ).resolve()
    settings.quicktalk_model_root = ""
    assert avatars._settings_quicktalk_model_root(settings) == (
        tmp_path / "legacy-env-root"
    ).resolve()


def test_quicktalk_avatar_prewarm_uses_full_video_by_default(
    tmp_path,
    monkeypatch,
):
    avatar = tmp_path / "video-singer"
    avatar.mkdir()
    source_dir = avatar / "source"
    source_dir.mkdir()
    (source_dir / "idle.mp4").write_bytes(b"fake-video")
    (avatar / "manifest.json").write_text(
        json.dumps(
            {
                "id": "video-singer",
                "name": "Video Singer",
                "model_type": "quicktalk",
                "fps": 25,
                "sample_rate": 16000,
                "width": 16,
                "height": 24,
                "version": "1.0",
                "metadata": {"source_video": "source/idle.mp4"},
            }
        ),
        encoding="utf-8",
    )

    max_seconds_seen: list[float | None] = []

    class FakeRebuild:
        def read_frames(self, template_video, max_seconds=None):
            del template_video
            max_seconds_seen.append(max_seconds)
            return [object() for _ in range(75)], 25

        def face_detect_frames(self, frames):
            return list(frames)

        def save_face_cache(self, cache_path, face_det_results):
            import numpy as np

            frame_count = len(face_det_results)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            np.savez(
                cache_path,
                faces=np.zeros((frame_count, 256, 256, 3), dtype=np.uint8),
                boxes=np.zeros((frame_count, 4), dtype=np.float32),
                affines=np.zeros((frame_count, 2, 3), dtype=np.float32),
            )

    writes: list[dict[str, object]] = []

    def fake_write_video_template(**kwargs):
        writes.append(kwargs)
        output_path = Path(kwargs["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"template")
        return 75

    monkeypatch.delenv("OPENTALKING_QUICKTALK_MAX_TEMPLATE_SECONDS", raising=False)
    monkeypatch.setattr(avatars, "_quicktalk_cache_builder", lambda settings: FakeRebuild())
    monkeypatch.setattr(prepare_cache, "_read_video_fps", lambda path: 25.0)
    monkeypatch.setattr(prepare_cache, "_write_video_template", fake_write_video_template)

    calls: list[tuple[str, dict]] = []

    async def fake_post_omnirt(settings, path, payload):
        del settings
        calls.append((path, payload))
        return {"type": "preload_ok", "warmed": True, "cache_hit": False}

    monkeypatch.setattr(avatars, "_post_omnirt_json", fake_post_omnirt)
    monkeypatch.setattr(
        avatars,
        "resolve_model_backend",
        lambda model, settings: SimpleNamespace(backend="omnirt"),
    )

    app = FastAPI()
    app.state.settings = SimpleNamespace(
        avatars_dir=str(tmp_path),
        omnirt_endpoint="http://127.0.0.1:9000",
        omnirt_audio2video_path_template="/v1/audio2video/{model}",
        omnirt_api_key="",
        quicktalk_model_root=str(tmp_path / "models" / "quicktalk"),
        quicktalk_device="cuda:0",
        quicktalk_hubert_device="cuda:0",
        quicktalk_model_backend="pth",
        quicktalk_max_long_edge=900,
    )
    app.include_router(avatars.router)
    client = TestClient(app)

    response = client.post("/avatars/video-singer/prewarm", json={"model": "quicktalk"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["cache"]["status"] == "generated"
    assert payload["cache"]["frames"] == 75
    assert writes[0]["max_seconds"] is None
    assert max_seconds_seen == [None]
    assert calls

def test_quicktalk_avatar_prewarm_generates_cache_and_calls_omnirt(
    tmp_path,
    monkeypatch,
):
    avatar = tmp_path / "singer"
    avatar.mkdir()
    (avatar / "reference.png").write_bytes(_png_bytes((16, 24)))
    (avatar / "manifest.json").write_text(
        json.dumps(
            {
                "id": "singer",
                "name": "Singer",
                "model_type": "quicktalk",
                "fps": 25,
                "sample_rate": 16000,
                "width": 16,
                "height": 24,
                "version": "1.0",
            }
        ),
        encoding="utf-8",
    )

    class FakeRebuild:
        def read_frames(self, template_video, max_seconds=None):
            del template_video, max_seconds
            return [object(), object()], 25

        def face_detect_frames(self, frames):
            del frames
            return object()

        def save_face_cache(self, cache_path, face_det_results):
            del face_det_results
            import numpy as np

            cache_path.parent.mkdir(parents=True, exist_ok=True)
            np.savez(
                cache_path,
                faces=np.zeros((2, 256, 256, 3), dtype=np.uint8),
                boxes=np.zeros((2, 4), dtype=np.float32),
                affines=np.zeros((2, 2, 3), dtype=np.float32),
            )

    def fail_full_rebuild(settings):
        del settings
        raise AssertionError("omnirt quicktalk prewarm must not load full QuickTalk runtime")

    monkeypatch.setattr(avatars, "_quicktalk_rebuild", fail_full_rebuild)
    monkeypatch.setattr(avatars, "_quicktalk_cache_builder", lambda settings: FakeRebuild())

    calls: list[tuple[str, dict]] = []

    async def fake_post_omnirt(settings, path, payload):
        del settings
        calls.append((path, payload))
        return {"type": "preload_ok", "warmed": True, "cache_hit": False}

    monkeypatch.setattr(avatars, "_post_omnirt_json", fake_post_omnirt)
    monkeypatch.setattr(avatars, "resolve_model_backend", lambda model, settings: SimpleNamespace(backend="omnirt"))

    app = FastAPI()
    app.state.settings = SimpleNamespace(
        avatars_dir=str(tmp_path),
        omnirt_endpoint="http://127.0.0.1:9000",
        omnirt_audio2video_path_template="/v1/audio2video/{model}",
        omnirt_api_key="",
        quicktalk_model_root=str(tmp_path / "models" / "quicktalk"),
        quicktalk_device="cuda:0",
        quicktalk_hubert_device="cuda:0",
        quicktalk_model_backend="pth",
        quicktalk_max_long_edge=900,
        quicktalk_max_template_seconds=1.0,
    )
    app.include_router(avatars.router)
    client = TestClient(app)

    response = client.post("/avatars/singer/prewarm", json={"model": "quicktalk"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["cache"]["status"] == "generated"
    assert payload["runtime"]["type"] == "preload_ok"
    assert calls
    path, sent = calls[0]
    assert path == "/v1/audio2video/quicktalk/preload"
    assert sent["template_mode"] == "video"
    assert _path_has_suffix(sent["template_video"], "singer", "quicktalk", "template_16x24.mp4")
    assert _path_has_suffix(sent["quicktalk_face_cache"], "singer", "quicktalk", "face_cache_v3_16x24.npz")
    assert (avatar / "quicktalk" / "template_16x24.mp4").is_file()
    assert (avatar / "quicktalk" / "face_cache_v3_16x24.npz").is_file()


def test_avatar_prewarm_rejects_unsupported_model_without_cache_work(
    tmp_path,
    monkeypatch,
):
    avatar = tmp_path / "singer"
    avatar.mkdir()
    (avatar / "reference.png").write_bytes(_png_bytes((16, 24)))
    (avatar / "manifest.json").write_text(
        json.dumps(
            {
                "id": "singer",
                "name": "Singer",
                "model_type": "quicktalk",
                "fps": 25,
                "sample_rate": 16000,
                "width": 16,
                "height": 24,
                "version": "1.0",
            }
        ),
        encoding="utf-8",
    )

    def fail_rebuild(settings):
        del settings
        raise AssertionError("unsupported models must not prepare quicktalk cache")

    async def fail_omnirt(settings, path, payload):
        del settings, path, payload
        raise AssertionError("unsupported models must not call omnirt")

    monkeypatch.setattr(avatars, "_quicktalk_rebuild", fail_rebuild)
    monkeypatch.setattr(avatars, "_post_omnirt_json", fail_omnirt)

    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path))
    app.include_router(avatars.router)
    client = TestClient(app)

    response = client.post("/avatars/singer/prewarm", json={"model": "musetalk"})

    assert response.status_code == 400
    assert "not supported" in response.json()["detail"]
    assert not (avatar / "quicktalk").exists()


def test_quicktalk_avatar_prewarm_cache_hit_skips_rebuild(
    tmp_path,
    monkeypatch,
):
    import numpy as np

    avatar = tmp_path / "singer"
    avatar.mkdir()
    (avatar / "reference.png").write_bytes(_png_bytes((16, 24)))
    quicktalk_dir = avatar / "quicktalk"
    quicktalk_dir.mkdir()
    (quicktalk_dir / "template_16x24.mp4").write_bytes(b"fake-template")
    np.savez(
        quicktalk_dir / "face_cache_v3_16x24.npz",
        faces=np.zeros((2, 256, 256, 3), dtype=np.uint8),
        boxes=np.zeros((2, 4), dtype=np.float32),
        affines=np.zeros((2, 2, 3), dtype=np.float32),
    )
    (avatar / "manifest.json").write_text(
        json.dumps(
            {
                "id": "singer",
                "name": "Singer",
                "model_type": "quicktalk",
                "fps": 25,
                "sample_rate": 16000,
                "width": 16,
                "height": 24,
                "version": "1.0",
            }
        ),
        encoding="utf-8",
    )

    def fail_rebuild(settings):
        del settings
        raise AssertionError("cache hit must not instantiate quicktalk rebuild")

    calls: list[tuple[str, dict]] = []

    async def fake_post_omnirt(settings, path, payload):
        del settings
        calls.append((path, payload))
        return {"type": "preload_ok", "warmed": True, "cache_hit": True}

    monkeypatch.setattr(avatars, "_quicktalk_rebuild", fail_rebuild)
    monkeypatch.setattr(avatars, "_post_omnirt_json", fake_post_omnirt)
    monkeypatch.setattr(avatars, "resolve_model_backend", lambda model, settings: SimpleNamespace(backend="omnirt"))

    app = FastAPI()
    app.state.settings = SimpleNamespace(
        avatars_dir=str(tmp_path),
        omnirt_endpoint="http://127.0.0.1:9000",
        omnirt_audio2video_path_template="/v1/audio2video/{model}",
        omnirt_api_key="",
        quicktalk_max_long_edge=900,
    )
    app.include_router(avatars.router)
    client = TestClient(app)

    response = client.post("/avatars/singer/prewarm", json={"model": "quicktalk"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["cache"]["model"] == "quicktalk"
    assert payload["cache"]["status"] == "hit"
    assert "cache_path" not in payload["cache"]
    assert "template_path" not in payload["cache"]
    assert calls


def test_quicktalk_avatar_prewarm_keeps_asset_ready_when_runtime_preload_fails(
    tmp_path,
    monkeypatch,
):
    import asyncio
    import httpx
    import numpy as np

    avatar = tmp_path / "singer"
    avatar.mkdir()
    (avatar / "reference.png").write_bytes(_png_bytes((16, 24)))
    quicktalk_dir = avatar / "quicktalk"
    quicktalk_dir.mkdir()
    (quicktalk_dir / "template_16x24.mp4").write_bytes(b"fake-template")
    np.savez(
        quicktalk_dir / "face_cache_v3_16x24.npz",
        faces=np.zeros((2, 256, 256, 3), dtype=np.uint8),
        boxes=np.zeros((2, 4), dtype=np.float32),
        affines=np.zeros((2, 2, 3), dtype=np.float32),
    )
    (avatar / "manifest.json").write_text(
        json.dumps(
            {
                "id": "singer",
                "name": "Singer",
                "model_type": "quicktalk",
                "fps": 25,
                "sample_rate": 16000,
                "width": 16,
                "height": 24,
                "version": "1.0",
            }
        ),
        encoding="utf-8",
    )

    def fail_rebuild(settings):
        del settings
        raise AssertionError("cache hit must not instantiate quicktalk rebuild")

    async def fake_post_omnirt(settings, path, payload):
        del settings, path, payload
        return {"type": "error", "code": "runtime_error", "message": "CUDA warmup failed"}

    monkeypatch.setattr(avatars, "_quicktalk_rebuild", fail_rebuild)
    monkeypatch.setattr(avatars, "_post_omnirt_json", fake_post_omnirt)
    monkeypatch.setattr(avatars, "resolve_model_backend", lambda model, settings: SimpleNamespace(backend="omnirt"))

    app = FastAPI()
    app.state.settings = SimpleNamespace(
        avatars_dir=str(tmp_path),
        omnirt_endpoint="http://127.0.0.1:9000",
        omnirt_audio2video_path_template="/v1/audio2video/{model}",
        omnirt_api_key="",
        quicktalk_max_long_edge=900,
    )
    app.include_router(avatars.router)

    async def post_prewarm() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post("/avatars/singer/prewarm", json={"model": "quicktalk"})

    response = asyncio.run(post_prewarm())

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["runtime_status"] == "failed"
    assert payload["cache"]["status"] == "hit"
    assert payload["runtime"]["message"] == "CUDA warmup failed"


def test_wav2lip_avatar_prewarm_uses_avatar_cache_dir_and_omnirt(
    tmp_path,
    monkeypatch,
):
    avatar = tmp_path / "singer"
    frames = avatar / "frames"
    frames.mkdir(parents=True)
    (frames / "frame_00000.png").write_bytes(_png_bytes((16, 24)))
    (frames / "mouth_metadata.json").write_text(
        json.dumps({"frames": {"frame_00000.png": {"source_frame_hash": "unused"}}}),
        encoding="utf-8",
    )
    (avatar / "manifest.json").write_text(
        json.dumps(
            {
                "id": "singer",
                "name": "Singer",
                "model_type": "wav2lip",
                "fps": 25,
                "sample_rate": 16000,
                "width": 16,
                "height": 24,
                "version": "1.0",
                "metadata": {
                    "reference_mode": "frames",
                    "preprocessed": True,
                    "frame_dir": "frames",
                    "frame_metadata": "frames/mouth_metadata.json",
                    "preferred_wav2lip_postprocess_mode": "opentalking_improved",
                },
            }
        ),
        encoding="utf-8",
    )

    calls: list[tuple[str, dict]] = []

    async def fake_post_omnirt(settings, path, payload):
        del settings
        calls.append((path, payload))
        cache_dir = Path(payload["prepared_cache_dir"])
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "v3-test.npz").write_bytes(b"fake")
        return {
            "type": "preload_result",
            "frames": 1,
            "cache_hit": False,
            "cache_source": "built",
            "elapsed_ms": 12.3,
        }

    monkeypatch.setattr(avatars, "_post_omnirt_json", fake_post_omnirt)
    monkeypatch.setattr(avatars, "resolve_model_backend", lambda model, settings: SimpleNamespace(backend="omnirt"))

    app = FastAPI()
    app.state.settings = SimpleNamespace(
        avatars_dir=str(tmp_path),
        omnirt_endpoint="http://127.0.0.1:9000",
        omnirt_audio2video_path_template="/v1/audio2video/{model}",
        omnirt_api_key="",
        wav2lip_postprocess_mode="easy_improved",
    )
    app.include_router(avatars.router)
    client = TestClient(app)

    response = client.post("/avatars/singer/prewarm", json={"model": "wav2lip"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["cache"]["model"] == "wav2lip"
    assert payload["cache"]["status"] == "built"
    assert "cache_path" not in payload["cache"]
    assert "template_path" not in payload["cache"]
    assert payload["runtime"]["type"] == "preload_result"
    assert calls
    path, sent = calls[0]
    assert path == "/v1/audio2video/wav2lip/preload"
    assert sent["avatar_id"] == "singer"
    assert _path_has_suffix(sent["prepared_cache_dir"], "singer", "wav2lip")
    assert sent["wav2lip_postprocess_mode"] == "opentalking_improved"


def test_wav2lip_avatar_prewarm_supports_image_avatar_without_npz_cache(tmp_path, monkeypatch):
    avatar = tmp_path / "image-avatar"
    avatar.mkdir()
    (avatar / "reference.png").write_bytes(_png_bytes((16, 24)))
    (avatar / "manifest.json").write_text(
        json.dumps(
            {
                "id": "image-avatar",
                "name": "Image Avatar",
                "model_type": "wav2lip",
                "fps": 25,
                "sample_rate": 16000,
                "width": 16,
                "height": 24,
                "version": "1.0",
                "metadata": {"reference_mode": "image"},
            }
        ),
        encoding="utf-8",
    )

    calls: list[tuple[str, dict]] = []

    async def fake_post_omnirt(settings, path, payload):
        del settings, path, payload
        raise AssertionError("image Wav2Lip prewarm must not call OmniRT frame preload")

    monkeypatch.setattr(avatars, "_post_omnirt_json", fake_post_omnirt)
    monkeypatch.setattr(avatars, "resolve_model_backend", lambda model, settings: SimpleNamespace(backend="omnirt"))

    app = FastAPI()
    app.state.settings = SimpleNamespace(
        avatars_dir=str(tmp_path),
        omnirt_endpoint="http://127.0.0.1:9000",
        omnirt_audio2video_path_template="/v1/audio2video/{model}",
        omnirt_api_key="",
        wav2lip_postprocess_mode="easy_improved",
    )
    app.include_router(avatars.router)
    client = TestClient(app)

    response = client.post("/avatars/image-avatar/prewarm", json={"model": "wav2lip"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["cache"]["model"] == "wav2lip"
    assert payload["cache"]["status"] == "runtime"
    assert payload["cache"]["source_mode"] == "image"
    assert payload["runtime"]["type"] == "preload_skipped"
    assert payload["runtime"]["reason"] == "image_reference_mode"
    assert "cache_path" not in payload["cache"]
    assert "template_path" not in payload["cache"]
    assert calls == []
    assert not (avatar / "wav2lip").exists()


def test_wav2lip_avatar_prewarm_uses_local_adapter_when_backend_is_local(tmp_path, monkeypatch):
    avatar = tmp_path / "local-wav"
    avatar.mkdir()
    (avatar / "reference.png").write_bytes(_png_bytes((16, 24)))
    (avatar / "manifest.json").write_text(
        json.dumps(
            {
                "id": "local-wav",
                "name": "Local Wav",
                "model_type": "wav2lip",
                "fps": 25,
                "sample_rate": 16000,
                "width": 16,
                "height": 24,
                "version": "1.0",
                "metadata": {"reference_mode": "image"},
            }
        ),
        encoding="utf-8",
    )

    calls: list[tuple[str, object | None]] = []

    class FakeAdapter:
        def load_model(self, device="cuda"):
            calls.append(("load_model", device))

        def load_avatar(self, avatar_path):
            calls.append(("load_avatar", avatar_path))
            return {"avatar_path": avatar_path}

        def warmup(self, avatar_state):
            calls.append(("warmup", avatar_state))

    async def fail_omnirt(settings, path, payload):
        del settings, path, payload
        raise AssertionError("local prewarm must not call OmniRT")

    monkeypatch.setattr(avatars, "_post_omnirt_json", fail_omnirt)
    monkeypatch.setattr(avatars, "resolve_model_backend", lambda model, settings: SimpleNamespace(backend="local"))
    monkeypatch.setattr(avatars, "get_adapter", lambda model: FakeAdapter())

    app = FastAPI()
    app.state.settings = SimpleNamespace(
        avatars_dir=str(tmp_path),
        omnirt_endpoint="http://127.0.0.1:9000",
        device="cuda:0",
    )
    app.include_router(avatars.router)
    client = TestClient(app)

    response = client.post("/avatars/local-wav/prewarm", json={"model": "wav2lip"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["cache"]["model"] == "wav2lip"
    assert payload["cache"]["status"] == "warmed"
    assert payload["runtime"]["type"] == "local_prewarm_result"
    assert payload["runtime"]["warmed"] is True
    assert [name for name, _ in calls] == ["load_model", "load_avatar", "warmup"]
    assert calls[0][1] == "cuda:0"
    assert calls[1][1] == str(avatar)


def test_avatar_prewarm_offloads_local_adapter_work(tmp_path, monkeypatch):
    avatar = tmp_path / "local-wav"
    avatar.mkdir()
    (avatar / "reference.png").write_bytes(_png_bytes((16, 24)))
    (avatar / "manifest.json").write_text(
        json.dumps(
            {
                "id": "local-wav",
                "name": "Local Wav",
                "model_type": "wav2lip",
                "fps": 25,
                "sample_rate": 16000,
                "width": 16,
                "height": 24,
                "version": "1.0",
                "metadata": {"reference_mode": "image"},
            }
        ),
        encoding="utf-8",
    )

    offloaded: list[str] = []

    async def fake_to_thread(func, *args, **kwargs):
        offloaded.append(func.__name__)
        return func(*args, **kwargs)

    def fake_local_backend(*args, **kwargs):
        del args, kwargs
        return (
            {"model": "wav2lip", "status": "warmed", "source_mode": "local", "frames": 1},
            {"type": "local_prewarm_result", "backend": "local", "model": "wav2lip"},
        )

    monkeypatch.setattr(avatars.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(avatars, "_prewarm_local_backend", fake_local_backend)
    monkeypatch.setattr(avatars, "resolve_model_backend", lambda model, settings: SimpleNamespace(backend="local"))

    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path), device="cuda:0")
    app.include_router(avatars.router)
    client = TestClient(app)

    response = client.post("/avatars/local-wav/prewarm", json={"model": "wav2lip"})

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert offloaded == ["fake_local_backend"]


def test_wav2lip_local_frames_prewarm_reports_avatar_npz_cache(tmp_path, monkeypatch):
    avatar = tmp_path / "local-wav-frames"
    frames = avatar / "frames"
    frames.mkdir(parents=True)
    (frames / "frame_00000.png").write_bytes(_png_bytes((16, 24)))
    (frames / "mouth_metadata.json").write_text(
        json.dumps({"frames": {"frame_00000.png": {"source_frame_hash": "unused"}}}),
        encoding="utf-8",
    )
    (avatar / "reference.png").write_bytes(_png_bytes((16, 24)))
    (avatar / "manifest.json").write_text(
        json.dumps(
            {
                "id": "local-wav-frames",
                "name": "Local Wav Frames",
                "model_type": "wav2lip",
                "fps": 25,
                "sample_rate": 16000,
                "width": 16,
                "height": 24,
                "version": "1.0",
                "metadata": {
                    "reference_mode": "frames",
                    "preprocessed": True,
                    "frame_dir": "frames",
                    "frame_metadata": "frames/mouth_metadata.json",
                },
            }
        ),
        encoding="utf-8",
    )

    class FakeAdapter:
        def load_model(self, device="cuda"):
            del device

        def load_avatar(self, avatar_path):
            cache_dir = Path(avatar_path) / "wav2lip"
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / "v3-local-test.npz").write_bytes(b"fake")
            worker = SimpleNamespace(restore_contexts=[object()])
            return SimpleNamespace(worker=worker)

        def warmup(self, avatar_state):
            del avatar_state

    async def fail_omnirt(settings, path, payload):
        del settings, path, payload
        raise AssertionError("local prewarm must not call OmniRT")

    monkeypatch.setattr(avatars, "_post_omnirt_json", fail_omnirt)
    monkeypatch.setattr(avatars, "resolve_model_backend", lambda model, settings: SimpleNamespace(backend="local"))
    monkeypatch.setattr(avatars, "get_adapter", lambda model: FakeAdapter())

    app = FastAPI()
    app.state.settings = SimpleNamespace(
        avatars_dir=str(tmp_path),
        omnirt_endpoint="http://127.0.0.1:9000",
        device="cuda:0",
        wav2lip_postprocess_mode="easy_improved",
    )
    app.include_router(avatars.router)
    client = TestClient(app)

    response = client.post("/avatars/local-wav-frames/prewarm", json={"model": "wav2lip"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["cache"]["model"] == "wav2lip"
    assert payload["cache"]["source_mode"] == "frames"
    assert payload["cache"]["status"] in {"built", "hit", "memory"}
    assert payload["cache"]["frames"] == 1
    assert payload["runtime"]["type"] == "local_prewarm_result"
    assert (avatar / "wav2lip" / "v3-local-test.npz").is_file()


def test_quicktalk_avatar_prewarm_uses_local_adapter_when_backend_is_local(tmp_path, monkeypatch):
    avatar = tmp_path / "local-quick"
    avatar.mkdir()
    (avatar / "reference.png").write_bytes(_png_bytes((16, 24)))
    (avatar / "manifest.json").write_text(
        json.dumps(
            {
                "id": "local-quick",
                "name": "Local Quick",
                "model_type": "quicktalk",
                "fps": 25,
                "sample_rate": 16000,
                "width": 16,
                "height": 24,
                "version": "1.0",
            }
        ),
        encoding="utf-8",
    )

    calls: list[tuple[str, object | None]] = []

    class FakeAdapter:
        def load_model(self, device="cuda"):
            calls.append(("load_model", device))

        def load_avatar(self, avatar_path):
            calls.append(("load_avatar", avatar_path))
            return {"avatar_path": avatar_path}

        def warmup(self, avatar_state):
            calls.append(("warmup", avatar_state))

    async def fail_omnirt(settings, path, payload):
        del settings, path, payload
        raise AssertionError("local prewarm must not call OmniRT")

    prepared_calls: list[dict[str, object]] = []

    def fake_quicktalk_prepare(**kwargs):
        prepared_calls.append(kwargs)
        return (
            avatars.PreparedAssetResult(
                avatar_id="local-quick",
                status="generated",
                source_mode="image",
                template_path=avatar / "quicktalk" / "template_16x24.mp4",
                cache_path=avatar / "quicktalk" / "face_cache_v3_16x24.npz",
                frames=1,
            ),
            {"template_video": str(avatar / "quicktalk" / "template_16x24.mp4")},
        )

    monkeypatch.setattr(avatars, "_prepare_quicktalk_prewarm", fake_quicktalk_prepare)
    monkeypatch.setattr(avatars, "_post_omnirt_json", fail_omnirt)
    monkeypatch.setattr(avatars, "resolve_model_backend", lambda model, settings: SimpleNamespace(backend="local"))
    monkeypatch.setattr(avatars, "get_adapter", lambda model: FakeAdapter())

    app = FastAPI()
    app.state.settings = SimpleNamespace(
        avatars_dir=str(tmp_path),
        omnirt_endpoint="http://127.0.0.1:9000",
        device="cuda:0",
        quicktalk_device="cuda:1",
    )
    app.include_router(avatars.router)
    client = TestClient(app)

    response = client.post("/avatars/local-quick/prewarm", json={"model": "quicktalk"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["cache"]["model"] == "quicktalk"
    assert payload["cache"]["status"] == "warmed"
    assert payload["cache"]["prepared_status"] == "generated"
    assert payload["runtime"]["type"] == "local_prewarm_result"
    assert payload["runtime"]["warmed"] is True
    assert len(prepared_calls) == 1
    assert prepared_calls[0]["avatar_dir"] == avatar
    assert prepared_calls[0]["overwrite"] is False
    assert [name for name, _ in calls] == ["load_model", "load_avatar", "warmup"]
    assert calls[0][1] == "cuda:1"
    assert calls[1][1] == str(avatar)


def test_wav2lip_avatar_can_prewarm_quicktalk_with_asset_root_setting(tmp_path, monkeypatch):
    quicktalk_asset_root = tmp_path / "quicktalk-assets"
    avatar = tmp_path / "wav-avatar"
    avatar.mkdir()
    (avatar / "reference.png").write_bytes(_png_bytes((16, 24)))
    (avatar / "manifest.json").write_text(
        json.dumps(
            {
                "id": "wav-avatar",
                "name": "Wav Avatar",
                "model_type": "wav2lip",
                "fps": 25,
                "sample_rate": 16000,
                "width": 16,
                "height": 24,
                "version": "1.0",
            }
        ),
        encoding="utf-8",
    )

    prepared_asset_roots: list[Path] = []

    def fake_prepare_quicktalk_asset(**kwargs):
        rebuild = kwargs["rebuild"]
        prepared_asset_roots.append(rebuild.asset_root)
        return avatars.PreparedAssetResult(
            avatar_id="wav-avatar",
            status="generated",
            source_mode="image",
            template_path=avatar / "quicktalk" / "template_16x24.mp4",
            cache_path=avatar / "quicktalk" / "face_cache_v3_16x24.npz",
            frames=1,
        )

    class FakeAdapter:
        def load_model(self, device="cuda"):
            del device

        def load_avatar(self, avatar_path):
            return {"avatar_path": avatar_path}

        def warmup(self, avatar_state):
            del avatar_state

    async def fail_omnirt(settings, path, payload):
        del settings, path, payload
        raise AssertionError("local prewarm must not call OmniRT")

    monkeypatch.setattr(avatars, "_prepare_quicktalk_asset", fake_prepare_quicktalk_asset)
    monkeypatch.setattr(
        avatars,
        "_quicktalk_cache_builder",
        lambda settings: SimpleNamespace(
            asset_root=avatars._settings_quicktalk_model_root(settings)
        ),
    )
    monkeypatch.setattr(avatars, "_quicktalk_cache_hit_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(avatars, "_post_omnirt_json", fail_omnirt)
    monkeypatch.setattr(avatars, "resolve_model_backend", lambda model, settings: SimpleNamespace(backend="local"))
    monkeypatch.setattr(avatars, "get_adapter", lambda model: FakeAdapter())
    monkeypatch.setenv("OPENTALKING_QUICKTALK_MODEL_ROOT", str(tmp_path / "wrong-legacy-root"))

    app = FastAPI()
    app.state.settings = SimpleNamespace(
        avatars_dir=str(tmp_path),
        models_dir=str(tmp_path / "wrong-models-dir"),
        quicktalk_asset_root=str(quicktalk_asset_root),
        quicktalk_model_root="",
        quicktalk_device="cpu",
        device="cpu",
    )
    app.include_router(avatars.router)
    client = TestClient(app)

    response = client.post("/avatars/wav-avatar/prewarm", json={"model": "quicktalk"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["cache"]["model"] == "quicktalk"
    assert payload["runtime"]["type"] == "local_prewarm_result"
    assert prepared_asset_roots == [quicktalk_asset_root.resolve()]


def test_video_avatar_exposes_preview_video(tmp_path):
    base = tmp_path / "video-avatar"
    base.mkdir()
    (base / "preview.png").write_bytes(_png_bytes())
    source_dir = base / "source"
    source_dir.mkdir()
    (source_dir / "idle.mp4").write_bytes(b"fake-mp4")
    (base / "manifest.json").write_text(
        json.dumps(
            {
                "id": "video-avatar",
                "name": "Video Avatar",
                "model_type": "wav2lip",
                "fps": 25,
                "sample_rate": 16000,
                "width": 416,
                "height": 704,
                "version": "1.0",
                "metadata": {
                    "idle_mode": "loop",
                    "source_video": "source/idle.mp4",
                },
            }
        ),
        encoding="utf-8",
    )

    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path))
    app.include_router(avatars.router)
    client = TestClient(app)

    listed = client.get("/avatars").json()
    video_avatar = next(item for item in listed if item["id"] == "video-avatar")
    assert video_avatar["has_preview_video"] is True

    preview_video = client.get("/avatars/video-avatar/preview-video")
    assert preview_video.status_code == 200
    assert preview_video.headers["content-type"] == "video/mp4"
    assert preview_video.content == b"fake-mp4"


def test_image_avatar_does_not_expose_preview_video(tmp_path):
    base = tmp_path / "image-avatar"
    base.mkdir()
    (base / "preview.png").write_bytes(_png_bytes())
    (base / "manifest.json").write_text(
        json.dumps(
            {
                "id": "image-avatar",
                "name": "Image Avatar",
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

    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path))
    app.include_router(avatars.router)
    client = TestClient(app)

    listed = client.get("/avatars").json()
    image_avatar = next(item for item in listed if item["id"] == "image-avatar")
    assert image_avatar["has_preview_video"] is False
    assert client.get("/avatars/image-avatar/preview-video").status_code == 404


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


def test_create_custom_avatar_generates_quicktalk_template_from_upload(tmp_path, monkeypatch):
    base = tmp_path / "base-quicktalk"
    base.mkdir()
    (base / "preview.png").write_bytes(_png_bytes((416, 704)))
    (base / "reference.png").write_bytes(_png_bytes((416, 704)))
    source_dir = base / "source"
    source_dir.mkdir()
    (source_dir / "source.png").write_bytes(_png_bytes((416, 704)))
    (source_dir / "idle.mp4").write_bytes(b"old-idle")
    (base / "idle.mp4").write_bytes(b"old-root-idle")
    quicktalk_dir = base / "quicktalk"
    quicktalk_dir.mkdir()
    (quicktalk_dir / "template_900.mp4").write_bytes(b"old-template")
    (quicktalk_dir / "face_cache_v3_900.npz").write_bytes(b"stale-cache")
    (quicktalk_dir / "template_720x900.mp4").write_bytes(b"old-sized-template")
    (quicktalk_dir / "face_cache_v3_720x900.npz").write_bytes(b"stale-sized-cache")
    (base / "manifest.json").write_text(
        json.dumps(
            {
                "id": "base-quicktalk",
                "name": "Base QuickTalk",
                "model_type": "flashhead",
                "fps": 25,
                "sample_rate": 16000,
                "width": 416,
                "height": 704,
                "version": "1.0",
                "metadata": {
                    "source_video": "source/idle.mp4",
                    "source_image": "source/source.png",
                    "quicktalk": {
                        "template_video": "quicktalk/template_900.mp4",
                        "face_cache": "quicktalk/face_cache_v3_900.npz",
                    },
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
        data={"base_avatar_id": "base-quicktalk", "name": "QuickTalk 新形象", "model": "quicktalk"},
        files={"image": ("avatar.png", _png_bytes((640, 900)), "image/png")},
    )

    assert response.status_code == 200
    created = response.json()
    custom_dir = tmp_path / created["id"]
    manifest = json.loads((custom_dir / "manifest.json").read_text(encoding="utf-8"))
    assert created["model_type"] == "quicktalk"
    assert manifest["model_type"] == "quicktalk"
    assert "quicktalk" not in manifest["metadata"]
    assert "source_video" not in manifest["metadata"]
    assert manifest["metadata"]["source_image"] == "source/source.png"
    assert manifest["metadata"]["source_image_path"] == "reference.png"
    assert (custom_dir / "quicktalk" / "template_900.mp4").is_file()
    assert (custom_dir / "quicktalk" / "template_900.mp4").read_bytes() != b"old-template"
    assert not (custom_dir / "quicktalk" / "face_cache_v3_900.npz").exists()
    assert not (custom_dir / "quicktalk" / "template_720x900.mp4").exists()
    assert not (custom_dir / "quicktalk" / "face_cache_v3_720x900.npz").exists()
    assert not (custom_dir / "idle.mp4").exists()
    assert not (custom_dir / "source" / "idle.mp4").exists()
    assert Image.open(custom_dir / "source" / "source.png").size == (640, 900)
    assert client.get(f"/avatars/{created['id']}/preview-video").status_code == 404


def test_create_custom_avatar_accepts_uploaded_source_video(tmp_path, monkeypatch):
    base = tmp_path / "base-quicktalk"
    base.mkdir()
    (base / "preview.png").write_bytes(_png_bytes((416, 704)))
    (base / "reference.png").write_bytes(_png_bytes((416, 704)))
    source_dir = base / "source"
    source_dir.mkdir()
    (source_dir / "source.png").write_bytes(_png_bytes((416, 704)))
    (base / "manifest.json").write_text(
        json.dumps(
            {
                "id": "base-quicktalk",
                "name": "Base QuickTalk",
                "model_type": "quicktalk",
                "fps": 25,
                "sample_rate": 16000,
                "width": 416,
                "height": 704,
                "version": "1.0",
                "metadata": {"source_image": "source/source.png"},
            }
        ),
        encoding="utf-8",
    )

    async def fake_read_upload_video(upload):
        return Image.open(BytesIO(_png_bytes((640, 900)))).convert("RGB"), b"fake-video", ".mp4"

    monkeypatch.setattr(avatars, "_read_upload_video", fake_read_upload_video)
    monkeypatch.setattr(avatars.mouth_metadata, "detect_mouth_landmarks", lambda frame: None)

    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path))
    app.include_router(avatars.router)
    client = TestClient(app)

    response = client.post(
        "/avatars/custom",
        data={"base_avatar_id": "base-quicktalk", "name": "视频源形象", "model": "quicktalk"},
        files={"video": ("source.mp4", b"fake-video", "video/mp4")},
    )

    assert response.status_code == 200
    created = response.json()
    assert created["has_preview_video"] is True
    custom_dir = tmp_path / created["id"]
    manifest = json.loads((custom_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["metadata"]["reference_mode"] == "video"
    assert manifest["metadata"]["idle_mode"] == "loop"
    assert manifest["metadata"]["source_video"] == "source/source_video.mp4"
    assert manifest["metadata"]["source_image"] == "source/source.png"
    assert (custom_dir / "source" / "source_video.mp4").read_bytes() == b"fake-video"
    assert Image.open(custom_dir / "preview.png").size == (640, 900)
    preview_video = client.get(f"/avatars/{created['id']}/preview-video")
    assert preview_video.status_code == 200
    assert preview_video.headers["content-type"] == "video/mp4"
    assert preview_video.content == b"fake-video"


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
    base = tmp_path / "base-wav2lip-avatar"
    base.mkdir()
    (base / "preview.png").write_bytes(_png_bytes())
    (base / "reference.png").write_bytes(_png_bytes())
    (base / "manifest.json").write_text(
        json.dumps(
            {
                "id": "base-wav2lip-avatar",
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
        data={"avatar_id": "base-wav2lip-avatar"},
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
    base = tmp_path / "base-wav2lip-avatar"
    base.mkdir()
    (base / "preview.png").write_bytes(_png_bytes())
    (base / "reference.png").write_bytes(_png_bytes())
    (base / "manifest.json").write_text(
        json.dumps(
            {
                "id": "base-wav2lip-avatar",
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
        data={"avatar_id": "base-wav2lip-avatar"},
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
    base = tmp_path / "base-wav2lip-avatar"
    base.mkdir()
    (base / "preview.png").write_bytes(_png_bytes())
    (base / "reference.png").write_bytes(_png_bytes())
    (base / "manifest.json").write_text(
        json.dumps(
            {
                "id": "base-wav2lip-avatar",
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

    response = client.delete("/avatars/base-wav2lip-avatar")
    assert response.status_code == 403
    assert "built-in" in response.json()["detail"]
    assert (tmp_path / "base-wav2lip-avatar").exists()


def test_delete_unknown_avatar_404(tmp_path):
    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path))
    app.include_router(avatars.router)
    client = TestClient(app)

    assert client.delete("/avatars/does-not-exist").status_code == 404
