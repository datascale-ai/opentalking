from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.routes import video_creation


def _write_avatar(root: Path, avatar_id: str = "anchor") -> Path:
    avatar = root / avatar_id
    avatar.mkdir(parents=True)
    (avatar / "reference.png").write_bytes(b"png")
    (avatar / "manifest.json").write_text(
        json.dumps(
            {
                "id": avatar_id,
                "name": "Anchor",
                "model_type": "wav2lip",
                "fps": 25,
                "sample_rate": 16000,
                "width": 64,
                "height": 48,
                "version": "1.0",
            }
        ),
        encoding="utf-8",
    )
    return avatar


class FakeVideoCreator:
    def __init__(self, settings: object) -> None:
        self.settings = settings
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def create_from_audio_file(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("audio", kwargs))
        return {
            "job_id": "job-audio",
            "status": "done",
            "export_video": {
                "id": "export-audio",
                "kind": "video_creation",
                "title": kwargs["title"],
                "duration_sec": 1.0,
                "size_bytes": 9,
                "mime_type": "video/mp4",
                "created_at": "2026-06-03T00:00:00Z",
                "path": str(Path(str(getattr(self.settings, "exports_dir"))) / "audio.mp4"),
                "download_url": "/exports/videos/export-audio/download",
                "session_id": None,
                "avatar_id": kwargs["avatar_id"],
                "model": kwargs["model"],
            },
        }

    async def create_from_tts_text(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("tts", kwargs))
        return {
            "job_id": "job-tts",
            "status": "done",
            "export_video": {
                "id": "export-tts",
                "kind": "video_creation",
                "title": kwargs["title"],
                "duration_sec": 1.0,
                "size_bytes": 9,
                "mime_type": "video/mp4",
                "created_at": "2026-06-03T00:00:00Z",
                "path": str(Path(str(getattr(self.settings, "exports_dir"))) / "tts.mp4"),
                "download_url": "/exports/videos/export-tts/download",
                "session_id": None,
                "avatar_id": kwargs["avatar_id"],
                "model": kwargs["model"],
            },
        }


def _client(tmp_path: Path, monkeypatch):
    avatars = tmp_path / "avatars"
    exports = tmp_path / "exports"
    _write_avatar(avatars)
    app = FastAPI()
    app.state.settings = SimpleNamespace(
        avatars_dir=str(avatars),
        exports_dir=str(exports),
        export_max_bytes=1024 * 1024,
        video_creation_audio_max_bytes=1024,
    )
    creators: list[FakeVideoCreator] = []

    def fake_creator(settings: object) -> FakeVideoCreator:
        creator = FakeVideoCreator(settings)
        creators.append(creator)
        return creator

    monkeypatch.setattr(video_creation, "VideoCreationService", fake_creator)
    app.include_router(video_creation.router)
    return TestClient(app), creators


def test_video_creation_audio_upload_returns_export_video(tmp_path: Path, monkeypatch) -> None:
    client, _creators = _client(tmp_path, monkeypatch)
    with client:
        response = client.post(
            "/video-creation/jobs",
            data={
                "model": "wav2lip",
                "avatar_id": "anchor",
                "audio_source": "upload",
                "title": "Upload take",
            },
            files={"audio_file": ("speech.wav", b"RIFFaudio", "audio/wav")},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "done"
    assert payload["export_video"]["kind"] == "video_creation"
    assert payload["export_video"]["download_url"].startswith("/exports/videos/")


def test_video_creation_tts_text_passes_voice_model_without_audio_preview(tmp_path: Path, monkeypatch) -> None:
    client, creators = _client(tmp_path, monkeypatch)
    with client:
        response = client.post(
            "/video-creation/jobs",
            data={
                "model": "quicktalk",
                "avatar_id": "anchor",
                "audio_source": "tts_text",
                "title": "TTS take",
                "text": "你好，欢迎来到 OpenTalking。",
                "tts_provider": "local_cosyvoice",
                "tts_model": "FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
                "voice": "local-demo",
            },
        )

    assert response.status_code == 200, response.text
    call_type, kwargs = creators[0].calls[0]
    assert call_type == "tts"
    assert kwargs["text"] == "你好，欢迎来到 OpenTalking。"
    assert kwargs["tts_provider"] == "local_cosyvoice"
    assert kwargs["tts_model"] == "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"
    assert kwargs["voice"] == "local-demo"
    assert response.json()["export_video"]["model"] == "quicktalk"


def test_video_creation_rejects_oversized_uploaded_audio(tmp_path: Path, monkeypatch) -> None:
    client, _creators = _client(tmp_path, monkeypatch)
    with client:
        response = client.post(
            "/video-creation/jobs",
            data={"model": "wav2lip", "avatar_id": "anchor", "audio_source": "upload"},
            files={"audio_file": ("speech.wav", b"x" * 2048, "audio/wav")},
        )

    assert response.status_code == 413
