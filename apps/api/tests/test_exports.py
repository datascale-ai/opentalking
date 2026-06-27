from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.routes import exports


def _client(tmp_path):
    app = FastAPI()
    app.state.settings = SimpleNamespace(exports_dir=str(tmp_path), export_max_bytes=1024)
    app.include_router(exports.router)
    return TestClient(app)


def test_upload_list_detail_download_and_delete_export_video(tmp_path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/exports/videos",
            data={
                "kind": "realtime_dialogue",
                "title": "Dialog clip",
                "duration_sec": "4.25",
                "session_id": "sess_1",
                "avatar_id": "anchor",
                "model": "fasterliveportrait",
            },
            files={"file": ("evil.mp4", b"video-bytes", "video/webm")},
        )

        assert response.status_code == 200
        item = response.json()
        assert item["kind"] == "realtime_dialogue"
        assert item["title"] == "Dialog clip"
        assert item["duration_sec"] == 4.25
        assert item["size_bytes"] == len(b"video-bytes")
        assert item["mime_type"] == "video/webm"
        assert item["download_url"] == f"/exports/videos/{item['id']}/download"
        assert item["path"].endswith("recording.webm")

        list_response = client.get("/exports/videos")
        assert list_response.status_code == 200
        assert list_response.json()["items"][0]["id"] == item["id"]

        detail_response = client.get(f"/exports/videos/{item['id']}")
        assert detail_response.status_code == 200
        assert detail_response.json()["id"] == item["id"]

        download_response = client.get(f"/exports/videos/{item['id']}/download")
        assert download_response.status_code == 200
        assert download_response.headers["content-type"].startswith("video/webm")
        assert download_response.content == b"video-bytes"

        delete_response = client.delete(f"/exports/videos/{item['id']}")
        assert delete_response.status_code == 200
        assert delete_response.json() == {"id": item["id"], "deleted": True}
        assert client.get(f"/exports/videos/{item['id']}").status_code == 404


def test_upload_export_video_uses_mp4_extension_for_mp4_mime_type(tmp_path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/exports/videos",
            data={"kind": "video_clone", "title": "MP4 clip"},
            files={"file": ("clip.webm", b"mp4-bytes", "video/mp4")},
        )

        assert response.status_code == 200
        item = response.json()
        assert item["mime_type"] == "video/mp4"
        assert item["path"].endswith("recording.mp4")

        download_response = client.get(f"/exports/videos/{item['id']}/download")
        assert download_response.status_code == 200
        assert download_response.headers["content-type"].startswith("video/mp4")
        assert download_response.content == b"mp4-bytes"


def test_export_video_upload_rejects_bad_kind_and_oversized_file(tmp_path) -> None:
    with _client(tmp_path) as client:
        bad_kind = client.post(
            "/exports/videos",
            data={"kind": "../bad", "title": "bad"},
            files={"file": ("clip.webm", b"video", "video/webm")},
        )
        assert bad_kind.status_code == 400

        too_large = client.post(
            "/exports/videos",
            data={"kind": "video_clone", "title": "big"},
            files={"file": ("clip.webm", b"x" * 2048, "video/webm")},
        )
        assert too_large.status_code == 413


def test_export_video_routes_reject_path_traversal(tmp_path) -> None:
    with _client(tmp_path) as client:
        assert client.get("/exports/videos/../secret").status_code in {400, 404}
        assert client.get("/exports/videos/../secret/download").status_code in {400, 404}
        assert client.delete("/exports/videos/../secret").status_code in {400, 404}
