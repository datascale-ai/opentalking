from __future__ import annotations

import base64
import json
from io import BytesIO
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from apps.api.routes import video_clone
from opentalking.providers.synthesis.video_clone.ws_client import MAGIC_FRAME


def _png_bytes(size: tuple[int, int] = (32, 32)) -> bytes:
    out = BytesIO()
    Image.new("RGB", size, (40, 120, 180)).save(out, format="PNG")
    return out.getvalue()


def test_collect_avatar_source_image_prefers_reference_png(tmp_path) -> None:
    avatar = tmp_path / "avatar"
    avatar.mkdir()
    (avatar / "reference.png").write_bytes(_png_bytes())
    (avatar / "manifest.json").write_text(
        json.dumps({"id": "avatar", "name": "Avatar", "model_type": "fasterliveportrait", "width": 32, "height": 32}),
        encoding="utf-8",
    )

    payload = video_clone.collect_avatar_source_payload(tmp_path, "avatar")

    assert payload["avatar_id"] == "avatar"
    assert base64.b64decode(payload["ref_image"]) == (avatar / "reference.png").read_bytes()
    assert payload["width"] == 32
    assert payload["height"] == 32


def test_video_clone_status_aggregates_omnirt_status(monkeypatch) -> None:
    async def fake_fetch(settings):
        del settings
        return {"fasterliveportrait", "fasterliveportrait_video_clone"}

    monkeypatch.setattr(video_clone, "_fetch_omnirt_audio2video_models", fake_fetch)
    app = FastAPI()
    app.state.settings = SimpleNamespace(omnirt_endpoint="http://127.0.0.1:9000")
    app.include_router(video_clone.router)

    with TestClient(app) as client:
        response = client.get("/video-clone/status")

    assert response.status_code == 200
    assert response.json() == {
        "model": "fasterliveportrait",
        "connected": True,
        "reason": "omnirt",
    }


def test_video_clone_ws_rejects_missing_avatar(tmp_path) -> None:
    app = FastAPI()
    app.state.settings = SimpleNamespace(avatars_dir=str(tmp_path), omnirt_endpoint="http://127.0.0.1:9000", omnirt_api_key="")
    app.include_router(video_clone.router)

    with TestClient(app) as client:
        with client.websocket_connect("/video-clone/fasterliveportrait/ws") as ws:
            ws.send_json({"type": "init", "avatar_id": "missing"})
            error = ws.receive_json()

    assert error["type"] == "error"
    assert error["code"] == "avatar_not_found"


def test_frame_payload_magic_is_fram() -> None:
    assert MAGIC_FRAME == b"FRAM"
