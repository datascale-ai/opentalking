from __future__ import annotations

import json
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.routes import video_creation
from opentalking.core.types.frames import AudioChunk, VideoFrameData
from opentalking.video_creation import VideoCreationService


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


def _write_duo_avatar(root: Path, avatar_id: str = "duo-anchor") -> Path:
    avatar = _write_avatar(root, avatar_id)
    source_dir = avatar / "source"
    source_dir.mkdir()
    (source_dir / "source_video.mp4").write_bytes(b"template-video")
    manifest = json.loads((avatar / "manifest.json").read_text(encoding="utf-8"))
    manifest["model_type"] = "quicktalk"
    manifest["metadata"] = {
        "reference_mode": "video",
        "source_video": "source/source_video.mp4",
        "quicktalk": {"template_video": "source/source_video.mp4"},
        "duo_dialog": {
            "speaker_faces": {"male": "left", "female": "right"},
            "default_voices": {"male": "zh-CN-YunxiNeural", "female": "zh-CN-XiaoxiaoNeural"},
        },
    }
    (avatar / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
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
        stored_kwargs = dict(kwargs)
        config = stored_kwargs.get("indextts_config")
        if isinstance(config, dict) and config.get("emo_audio_prompt"):
            stored_kwargs["emotion_audio_bytes"] = Path(str(config["emo_audio_prompt"])).read_bytes()
        self.calls.append(("tts", stored_kwargs))
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

    async def create_from_duo_dialog(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("duo_dialog", kwargs))
        return {
            "job_id": "job-duo",
            "status": "done",
            "source": "duo_dialog",
            "export_video": {
                "id": "export-duo",
                "kind": "video_creation",
                "title": kwargs["title"],
                "duration_sec": 1.0,
                "size_bytes": 9,
                "mime_type": "video/mp4",
                "created_at": "2026-06-03T00:00:00Z",
                "path": str(Path(str(getattr(self.settings, "exports_dir"))) / "duo.mp4"),
                "download_url": "/exports/videos/export-duo/download",
                "session_id": None,
                "avatar_id": kwargs["avatar_id"],
                "model": kwargs["model"],
            },
        }

    async def create_reference_video(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("reference", kwargs))
        return {
            "job_id": "job-reference",
            "status": "done",
            "source": "reference_video",
            "export_video": {
                "id": "export-reference",
                "kind": "video_creation",
                "title": kwargs["title"],
                "duration_sec": float(kwargs["duration_sec"]),
                "size_bytes": 9,
                "mime_type": "video/mp4",
                "created_at": "2026-06-03T00:00:00Z",
                "path": str(Path(str(getattr(self.settings, "exports_dir"))) / "reference.mp4"),
                "download_url": "/exports/videos/export-reference/download",
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


def test_video_creation_route_passes_composition_config(tmp_path: Path, monkeypatch) -> None:
    client, creators = _client(tmp_path, monkeypatch)
    composition = {
        "scene_composition_id": "scene-anchor-news",
        "background_id": "bg-newsroom",
        "background_color": "#ffffff",
        "avatar_fit": "contain",
        "avatar_anchor": "center",
        "avatar_scale": 1.25,
        "avatar_offset_x": 96,
        "avatar_offset_y": -32,
    }
    with client:
        response = client.post(
            "/video-creation/jobs",
            data={
                "model": "wav2lip",
                "avatar_id": "anchor",
                "audio_source": "upload",
                "title": "Composed take",
                "composition_config": json.dumps(composition),
            },
            files={"audio_file": ("speech.wav", b"RIFFaudio", "audio/wav")},
        )

    assert response.status_code == 200, response.text
    assert creators[0].calls[0][1]["composition_config"] == composition


def test_video_creation_route_passes_reference_video_composition_config(tmp_path: Path, monkeypatch) -> None:
    client, creators = _client(tmp_path, monkeypatch)
    composition = {
        "scene_composition_id": "scene-anchor-news",
        "background_id": "bg-newsroom",
        "background_color": "#ffffff",
        "avatar_fit": "contain",
        "avatar_anchor": "center",
        "avatar_scale": 1.25,
        "avatar_offset_x": 96,
        "avatar_offset_y": -32,
        "output_width": 1920,
        "output_height": 1080,
    }
    with client:
        response = client.post(
            "/video-creation/jobs",
            data={
                "model": "flashtalk",
                "avatar_id": "duo-anchor",
                "audio_source": "reference_video",
                "title": "Reference take",
                "duration_sec": 30,
                "composition_config": json.dumps(composition),
            },
        )

    assert response.status_code == 200, response.text
    assert creators[0].calls[0][1]["composition_config"] == composition
    assert creators[0].calls[0][1]["duration_sec"] == 30


def test_video_creation_route_rejects_invalid_composition_config(tmp_path: Path, monkeypatch) -> None:
    client, _creators = _client(tmp_path, monkeypatch)
    with client:
        response = client.post(
            "/video-creation/jobs",
            data={
                "model": "wav2lip",
                "avatar_id": "anchor",
                "audio_source": "upload",
                "title": "Broken composition",
                "composition_config": "{",
            },
            files={"audio_file": ("speech.wav", b"RIFFaudio", "audio/wav")},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "composition_config must be valid JSON"


def test_write_video_only_preserves_bgr_frames_for_opencv_writer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from opentalking import video_creation as video_creation_module

    captured: list[np.ndarray] = []

    class FakeWriter:
        def isOpened(self) -> bool:
            return True

        def write(self, frame: np.ndarray) -> None:
            captured.append(np.asarray(frame).copy())

        def release(self) -> None:
            return None

    monkeypatch.setattr(video_creation_module.cv2, "VideoWriter_fourcc", lambda *_args: 0)
    monkeypatch.setattr(video_creation_module.cv2, "VideoWriter", lambda *_args, **_kwargs: FakeWriter())

    bgr = np.zeros((2, 2, 3), dtype=np.uint8)
    bgr[:, :] = [200, 20, 10]

    video_creation_module._write_video_only(tmp_path / "out.mp4", [bgr], 25)

    assert captured
    assert captured[0][0, 0].tolist() == [200, 20, 10]


def test_video_creation_quicktalk_default_backend_is_omnirt(monkeypatch: pytest.MonkeyPatch) -> None:
    from opentalking.core.model_config import clear_model_config_cache
    from opentalking.providers.synthesis.backends import resolve_model_backend

    monkeypatch.delenv("OPENTALKING_QUICKTALK_BACKEND", raising=False)
    clear_model_config_cache()
    try:
        backend = resolve_model_backend("quicktalk", SimpleNamespace())
        assert backend.backend == "omnirt"
    finally:
        clear_model_config_cache()


@pytest.mark.parametrize(
    "model",
    ["flashtalk", "flashhead", "fasterliveportrait", "musetalk", "quicktalk", "wav2lip"],
)
def test_video_creation_accepts_audio_renderer_models(model: str) -> None:
    from opentalking import video_creation as video_creation_module

    assert video_creation_module._normalize_model(model) == model


def test_video_creation_uses_flashhead_client_for_flashhead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opentalking import video_creation as video_creation_module
    import opentalking.providers.synthesis.flashhead as flashhead_module

    captured: dict[str, object] = {}

    class FakeFlashHeadClient:
        def __init__(self, ws_url: str, *, model: str, config: dict[str, object]) -> None:
            captured["ws_url"] = ws_url
            captured["model"] = model
            captured["config"] = config

    class FakeOmniRTClient:
        def __init__(self, ws_client: object) -> None:
            captured["ws_client"] = ws_client

    monkeypatch.setattr(flashhead_module, "FlashHeadWSClient", FakeFlashHeadClient)
    monkeypatch.setattr(video_creation_module, "OmniRTAudio2VideoClient", FakeOmniRTClient)

    client = video_creation_module._audio2video_client(
        SimpleNamespace(
            flashhead_ws_url="ws://settings-flashhead/ws",
            flashhead_model="soulx-flashhead-test",
            flashhead_fps=25,
            flashhead_sample_rate=16000,
            flashhead_width=416,
            flashhead_height=704,
            flashhead_frame_num=25,
            flashhead_chunk_samples=16000,
        ),
        "flashhead",
        16000,
        backend=SimpleNamespace(model="flashhead", backend="direct_ws", ws_url="ws://backend-flashhead/ws"),
    )

    assert isinstance(client, FakeOmniRTClient)
    assert isinstance(captured["ws_client"], FakeFlashHeadClient)
    assert captured["ws_url"] == "ws://backend-flashhead/ws"
    assert captured["model"] == "soulx-flashhead-test"
    assert captured["config"] == {
        "fps": 25,
        "sample_rate": 16000,
        "width": 416,
        "height": 704,
        "frame_num": 25,
        "chunk_samples": 16000,
    }


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


def test_video_creation_route_passes_duo_dialog_payload(tmp_path: Path, monkeypatch) -> None:
    client, creators = _client(tmp_path, monkeypatch)
    payload = {
        "lines": [
            {"id": "line-1", "role": "male", "text": "大家好，我是男主持。"},
            {"id": "line-2", "role": "female", "text": "我是女主持，欢迎收看。"},
        ],
        "voices": {"male": "zh-CN-YunxiNeural", "female": "zh-CN-XiaoxiaoNeural"},
        "gap_ms": 120,
    }
    composition = {"background_id": "bg-news", "avatar_scale": 1.1}
    with client:
        response = client.post(
            "/video-creation/jobs",
            data={
                "model": "quicktalk",
                "avatar_id": "anchor",
                "audio_source": "duo_dialog",
                "title": "双人对话",
                "tts_provider": "edge",
                "tts_model": "edge-tts",
                "duo_dialog": json.dumps(payload),
                "composition_config": json.dumps(composition),
            },
        )

    assert response.status_code == 200, response.text
    call_type, kwargs = creators[0].calls[0]
    assert call_type == "duo_dialog"
    assert kwargs["duo_dialog"] == payload
    assert kwargs["tts_provider"] == "edge"
    assert kwargs["tts_model"] == "edge-tts"
    assert kwargs["composition_config"] == composition
    assert response.json()["source"] == "duo_dialog"


def test_video_creation_route_rejects_invalid_duo_dialog_json(tmp_path: Path, monkeypatch) -> None:
    client, _creators = _client(tmp_path, monkeypatch)
    with client:
        response = client.post(
            "/video-creation/jobs",
            data={
                "model": "quicktalk",
                "avatar_id": "anchor",
                "audio_source": "duo_dialog",
                "title": "Broken duo",
                "duo_dialog": "{",
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "duo_dialog must be valid JSON"


def test_video_creation_reference_video_passes_duration(tmp_path: Path, monkeypatch) -> None:
    client, creators = _client(tmp_path, monkeypatch)
    with client:
        response = client.post(
            "/video-creation/jobs",
            data={
                "model": "flashtalk",
                "avatar_id": "anchor",
                "audio_source": "reference_video",
                "title": "Reference take",
                "duration_sec": "30",
            },
        )

    assert response.status_code == 200, response.text
    call_type, kwargs = creators[0].calls[0]
    assert call_type == "reference"
    assert kwargs["model"] == "flashtalk"
    assert kwargs["avatar_id"] == "anchor"
    assert kwargs["title"] == "Reference take"
    assert kwargs["duration_sec"] == 30
    payload = response.json()
    assert payload["source"] == "reference_video"
    assert payload["export_video"]["duration_sec"] == 30.0

def test_video_creation_tts_text_passes_indextts_config(tmp_path: Path, monkeypatch) -> None:
    client, creators = _client(tmp_path, monkeypatch)
    with client:
        response = client.post(
            "/video-creation/jobs",
            data={
                "model": "quicktalk",
                "avatar_id": "anchor",
                "audio_source": "tts_text",
                "title": "IndexTTS emotion take",
                "text": "你好，欢迎来到 OpenTalking。",
                "tts_provider": "indextts",
                "tts_model": "IndexTeam/IndexTTS-2",
                "voice": "indextts-default",
                "indextts_config": json.dumps(
                    {
                        "emotion_mode": "text",
                        "emo_alpha": 0.6,
                        "emo_text": "开心、自然、像直播介绍一样。",
                        "use_random": False,
                        "interval_silence_ms": 80,
                        "streaming_mode": "segment",
                        "max_text_tokens_per_segment": 80,
                        "quick_streaming_tokens": 4,
                    }
                ),
            },
        )

    assert response.status_code == 200, response.text
    call_type, kwargs = creators[0].calls[0]
    assert call_type == "tts"
    assert kwargs["indextts_config"] == {
        "emo_alpha": 0.6,
        "use_emo_text": True,
        "emo_text": "开心、自然、像直播介绍一样。",
        "use_random": False,
        "interval_silence_ms": 80,
        "streaming_mode": "segment",
        "max_text_tokens_per_segment": 80,
        "quick_streaming_tokens": 4,
    }


@pytest.mark.parametrize("provider", ["indextts", "local_indextts", "omnirt_indextts"])
@pytest.mark.parametrize("audio_source", ["tts_text", "voice_clone"])
def test_video_creation_indextts_config_supports_local_and_omnirt_sources(
    tmp_path: Path,
    monkeypatch,
    provider: str,
    audio_source: str,
) -> None:
    client, creators = _client(tmp_path, monkeypatch)
    with client:
        response = client.post(
            "/video-creation/jobs",
            data={
                "model": "quicktalk",
                "avatar_id": "anchor",
                "audio_source": audio_source,
                "title": "IndexTTS dual backend take",
                "text": "这是 IndexTTS 双后端的视频创作测试。",
                "tts_provider": provider,
                "tts_model": "IndexTeam/IndexTTS-2",
                "voice": "indextts-default",
                "indextts_config": json.dumps(
                    {
                        "emotion_mode": "vector",
                        "emo_alpha": 0.8,
                        "emo_vector": [0, 1, 0, 0, 0, 0, 0, 0],
                        "use_random": True,
                        "interval_silence_ms": 40,
                        "streaming_mode": "segment",
                        "max_text_tokens_per_segment": 80,
                        "quick_streaming_tokens": 4,
                    }
                ),
            },
        )

    assert response.status_code == 200, response.text
    call_type, kwargs = creators[0].calls[0]
    assert call_type == "tts"
    assert kwargs["source"] == audio_source
    assert kwargs["tts_provider"] == provider
    assert kwargs["indextts_config"] == {
        "emo_alpha": 0.8,
        "use_random": True,
        "emo_vector": [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "interval_silence_ms": 40,
        "streaming_mode": "segment",
        "max_text_tokens_per_segment": 80,
        "quick_streaming_tokens": 4,
    }


def test_video_creation_tts_text_passes_indextts_emotion_audio_file(tmp_path: Path, monkeypatch) -> None:
    client, creators = _client(tmp_path, monkeypatch)
    with client:
        response = client.post(
            "/video-creation/jobs",
            data={
                "model": "quicktalk",
                "avatar_id": "anchor",
                "audio_source": "tts_text",
                "title": "IndexTTS emotion reference take",
                "text": "你好，欢迎来到 OpenTalking。",
                "tts_provider": "indextts",
                "tts_model": "IndexTeam/IndexTTS-2",
                "voice": "indextts-default",
                "indextts_config": json.dumps({"emotion_mode": "audio", "emo_alpha": 0.85}),
            },
            files={"indextts_emotion_audio_file": ("emotion.wav", b"RIFFemotion", "audio/wav")},
        )

    assert response.status_code == 200, response.text
    call_type, kwargs = creators[0].calls[0]
    assert call_type == "tts"
    assert kwargs["indextts_config"]["emo_alpha"] == 0.85
    assert kwargs["emotion_audio_bytes"] == b"RIFFemotion"


def test_video_creation_audio_upload_passes_fasterliveportrait_config(tmp_path: Path, monkeypatch) -> None:
    client, creators = _client(tmp_path, monkeypatch)
    with client:
        response = client.post(
            "/video-creation/jobs",
            data={
                "model": "fasterliveportrait",
                "avatar_id": "anchor",
                "audio_source": "upload",
                "title": "Upload take",
                "fasterliveportrait_config": json.dumps(
                    {
                        "mouth_open_multiplier": 2.2,
                        "animation_region": "all",
                        "flag_pasteback": False,
                    }
                ),
            },
            files={"audio_file": ("speech.wav", b"RIFFaudio", "audio/wav")},
        )

    assert response.status_code == 200, response.text
    call_type, kwargs = creators[0].calls[0]
    assert call_type == "audio"
    assert kwargs["fasterliveportrait_config"] == {
        "mouth_open_multiplier": 2.2,
        "animation_region": "all",
        "flag_pasteback": False,
    }
    assert response.json()["export_video"]["model"] == "fasterliveportrait"


@pytest.mark.parametrize("audio_source", ["tts_text", "voice_clone"])
def test_video_creation_tts_sources_pass_fasterliveportrait_config(
    tmp_path: Path,
    monkeypatch,
    audio_source: str,
) -> None:
    client, creators = _client(tmp_path, monkeypatch)
    with client:
        response = client.post(
            "/video-creation/jobs",
            data={
                "model": "fasterliveportrait",
                "avatar_id": "anchor",
                "audio_source": audio_source,
                "title": "TTS take",
                "text": "这是文本或复刻音色驱动的视频创作。",
                "tts_provider": "dashscope",
                "tts_model": "cosyvoice-v2",
                "voice": "voice-clone-1",
                "fasterliveportrait_config": json.dumps(
                    {
                        "mouth_open_multiplier": 2.2,
                        "animation_region": "all",
                        "flag_pasteback": False,
                    }
                ),
            },
        )

    assert response.status_code == 200, response.text
    call_type, kwargs = creators[0].calls[0]
    assert call_type == "tts"
    assert kwargs["source"] == audio_source
    assert kwargs["fasterliveportrait_config"] == {
        "mouth_open_multiplier": 2.2,
        "animation_region": "all",
        "flag_pasteback": False,
    }
    assert response.json()["export_video"]["model"] == "fasterliveportrait"



@pytest.mark.asyncio
@pytest.mark.parametrize("audio_source", ["upload", "tts_text", "voice_clone"])
async def test_video_creation_driving_sources_use_uploaded_source_video_template(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    audio_source: str,
) -> None:
    from opentalking import video_creation as video_creation_module
    from opentalking.core.types.frames import AudioChunk

    avatars = tmp_path / "avatars"
    exports = tmp_path / "exports"
    avatar = _write_avatar(avatars)
    manifest = json.loads((avatar / "manifest.json").read_text(encoding="utf-8"))
    manifest["model_type"] = "quicktalk"
    source_dir = avatar / "source"
    source_dir.mkdir()
    source_video = source_dir / "source_video.mp4"
    source_video.write_bytes(b"uploaded-video")
    manifest["metadata"] = {"reference_mode": "video", "source_video": "source/source_video.mp4"}
    (avatar / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    uploaded = tmp_path / "speech.wav"
    uploaded.write_bytes(b"RIFFaudio")

    class FakeTTS:
        async def synthesize_stream(self, text: str, *, voice: str | None = None):
            del text, voice
            yield AudioChunk(data=np.arange(8, dtype=np.int16), sample_rate=16000, duration_ms=0.5)

        async def aclose(self) -> None:
            pass

    class FakeWSClient:
        def __init__(self, ws_url: str, *, extra_headers: dict[str, str] | None = None) -> None:
            self.ws_url = ws_url
            self.extra_headers = extra_headers or {}

    class FakeOmniRTClient:
        instances: list["FakeOmniRTClient"] = []

        def __init__(self, ws_client: FakeWSClient) -> None:
            self.ws_client = ws_client
            self.init_kwargs: dict[str, object] | None = None
            self.fps = 4
            self.audio_chunk_samples = 4
            FakeOmniRTClient.instances.append(self)

        async def init_session(self, **kwargs: object) -> dict[str, object]:
            self.init_kwargs = kwargs
            return {"type": "init_ok"}

        async def prewarm(self) -> dict[str, object]:
            return {"type": "prewarm_skipped"}

        async def generate(self, audio_pcm: np.ndarray) -> list[VideoFrameData]:
            del audio_pcm
            return [
                VideoFrameData(
                    data=np.zeros((48, 64, 3), dtype=np.uint8),
                    width=64,
                    height=48,
                    timestamp_ms=0.0,
                )
            ]

        async def close(self, send_close_msg: bool = True) -> None:
            del send_close_msg

    async def fake_mux(_ffmpeg_bin: str, _video_in: Path, _audio_in: Path, out_mp4: Path) -> None:
        out_mp4.write_bytes(b"mp4")

    async def fake_decode(_path: Path) -> np.ndarray:
        return np.arange(8, dtype=np.int16)

    def fake_create_video_export(root: Path, **kwargs: object) -> dict[str, object]:
        return {
            "id": f"export-{audio_source}",
            "kind": "video_creation",
            "title": kwargs["title"],
            "duration_sec": kwargs["duration_sec"],
            "size_bytes": len(kwargs["content"]),
            "mime_type": "video/mp4",
            "created_at": "2026-06-04T00:00:00Z",
            "path": str(root / f"export-{audio_source}.mp4"),
            "session_id": kwargs["session_id"],
            "avatar_id": kwargs["avatar_id"],
            "model": kwargs["model"],
        }

    monkeypatch.setattr(video_creation_module, "FlashTalkWSClient", FakeWSClient, raising=False)
    monkeypatch.setattr(video_creation_module, "OmniRTAudio2VideoClient", FakeOmniRTClient, raising=False)
    monkeypatch.setattr(video_creation_module, "build_tts_adapter", lambda **_kwargs: FakeTTS())
    monkeypatch.setattr(video_creation_module, "decode_audio_file_to_pcm_i16", fake_decode)
    monkeypatch.setattr(video_creation_module, "_write_video_only", lambda path, _frames, _fps: path.write_bytes(b"video"))
    monkeypatch.setattr(video_creation_module, "_ffmpeg_mux", fake_mux)
    monkeypatch.setattr(
        video_creation_module,
        "resolve_model_backend",
        lambda model, _settings: SimpleNamespace(model=model, backend="omnirt", ws_url=""),
    )
    monkeypatch.setattr(video_creation_module, "create_video_export", fake_create_video_export)

    service = VideoCreationService(
        SimpleNamespace(
            avatars_dir=str(avatars),
            exports_dir=str(exports),
            export_max_bytes=1024 * 1024,
            ffmpeg_bin="ffmpeg",
            omnirt_endpoint="http://127.0.0.1:9000",
            omnirt_audio2video_path_template="/v1/audio2video/{model}",
            omnirt_api_key="",
            tts_sample_rate=16000,
        )
    )

    if audio_source == "upload":
        result = await service.create_from_audio_file(
            model="quicktalk",
            avatar_id="anchor",
            upload_path=uploaded,
            title="upload source video take",
        )
    else:
        result = await service.create_from_tts_text(
            model="quicktalk",
            avatar_id="anchor",
            text="这是用文本或复刻音色驱动上传视频源的测试。",
            title=f"{audio_source} source video take",
            tts_provider="edge",
            tts_model=None,
            voice="zh-CN-XiaoxiaoNeural",
            source=audio_source,
        )

    client = FakeOmniRTClient.instances[0]
    assert client.init_kwargs is not None
    assert client.init_kwargs["template_mode"] == "video"
    assert client.init_kwargs["template_video"] == source_video.resolve()
    assert result["source"] == audio_source
    assert result["export_video"]["model"] == "quicktalk"


@pytest.mark.asyncio
async def test_video_creation_service_renders_fasterliveportrait_via_omnirt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opentalking import video_creation as video_creation_module

    avatars = tmp_path / "avatars"
    exports = tmp_path / "exports"
    _write_avatar(avatars)
    uploaded = tmp_path / "speech.wav"
    uploaded.write_bytes(b"RIFFaudio")

    class FakeWSClient:
        def __init__(self, ws_url: str, *, extra_headers: dict[str, str] | None = None) -> None:
            self.ws_url = ws_url
            self.extra_headers = extra_headers or {}

    class FakeOmniRTClient:
        instances: list["FakeOmniRTClient"] = []

        def __init__(self, ws_client: FakeWSClient) -> None:
            self.ws_client = ws_client
            self.init_kwargs: dict[str, object] | None = None
            self.generated_chunks: list[np.ndarray] = []
            self.closed = False
            self.fps = 25
            self.audio_chunk_samples = 4
            FakeOmniRTClient.instances.append(self)

        async def init_session(self, **kwargs: object) -> dict[str, object]:
            self.init_kwargs = kwargs
            return {"type": "init_ok"}

        async def prewarm(self) -> dict[str, object]:
            return {"type": "prewarm_skipped"}

        async def generate(self, audio_pcm: np.ndarray) -> list[VideoFrameData]:
            self.generated_chunks.append(np.asarray(audio_pcm, dtype=np.int16).copy())
            return [
                VideoFrameData(
                    data=np.zeros((2, 2, 3), dtype=np.uint8),
                    width=2,
                    height=2,
                    timestamp_ms=0.0,
                )
            ]

        async def close(self, send_close_msg: bool = True) -> None:
            self.closed = send_close_msg

    async def fake_decode(_path: Path) -> np.ndarray:
        return np.arange(6, dtype=np.int16)

    async def fake_mux(_ffmpeg_bin: str, _video_in: Path, _audio_in: Path, out_mp4: Path) -> None:
        out_mp4.write_bytes(b"mp4")

    def fake_create_video_export(root: Path, **kwargs: object) -> dict[str, object]:
        return {
            "id": "export-flp",
            "kind": "video_creation",
            "title": kwargs["title"],
            "duration_sec": kwargs["duration_sec"],
            "size_bytes": len(kwargs["content"]),
            "mime_type": "video/mp4",
            "created_at": "2026-06-04T00:00:00Z",
            "path": str(root / "export-flp.mp4"),
            "session_id": kwargs["session_id"],
            "avatar_id": kwargs["avatar_id"],
            "model": kwargs["model"],
        }

    monkeypatch.setattr(video_creation_module, "FlashTalkWSClient", FakeWSClient, raising=False)
    monkeypatch.setattr(video_creation_module, "OmniRTAudio2VideoClient", FakeOmniRTClient, raising=False)
    monkeypatch.setattr(video_creation_module, "decode_audio_file_to_pcm_i16", fake_decode)
    monkeypatch.setattr(video_creation_module, "_write_video_only", lambda path, _frames, _fps: path.write_bytes(b"video"))
    monkeypatch.setattr(video_creation_module, "_ffmpeg_mux", fake_mux)
    monkeypatch.setattr(
        video_creation_module,
        "get_model_config",
        lambda _model: {
            "width": 448,
            "height": 900,
            "fps": 25,
            "emit_frames_per_chunk": 25,
            "render_keyframes_per_chunk": 25,
            "disable_frame_interpolation": True,
        },
    )
    monkeypatch.setattr(video_creation_module, "create_video_export", fake_create_video_export)

    settings = SimpleNamespace(
        avatars_dir=str(avatars),
        exports_dir=str(exports),
        export_max_bytes=1024 * 1024,
        ffmpeg_bin="ffmpeg",
        omnirt_endpoint="http://127.0.0.1:9000",
        omnirt_audio2video_path_template="/v1/audio2video/{model}",
        omnirt_api_key="",
        video_creation_fasterliveportrait_preroll_ms=0,
    )
    service = VideoCreationService(settings)

    result = await service.create_from_audio_file(
        model="fasterliveportrait",
        avatar_id="anchor",
        upload_path=uploaded,
        title="FasterLivePortrait take",
        fasterliveportrait_config={
            "mouth_open_multiplier": 2.0,
            "animation_region": "all",
            "flag_pasteback": False,
            "flag_stitching": False,
        },
    )

    client = FakeOmniRTClient.instances[0]
    assert client.ws_client.ws_url == "ws://127.0.0.1:9000/v1/audio2video/fasterliveportrait"
    assert client.init_kwargs is not None
    assert "ref_image" in client.init_kwargs
    assert client.init_kwargs["avatar_path"] == avatars / "anchor"
    assert client.init_kwargs["video_config"] == {
        "width": 448,
        "height": 900,
        "fps": 25,
        "emit_frames_per_chunk": 25,
        "render_keyframes_per_chunk": 25,
        "disable_frame_interpolation": True,
        **video_creation_module.VIDEO_CREATION_FASTLIVEPORTRAIT_DEFAULT_CONFIG,
        "mouth_open_multiplier": 2.0,
        "animation_region": "all",
        "flag_pasteback": False,
        "flag_stitching": False,
    }
    assert [chunk.size for chunk in client.generated_chunks] == [4, 4]
    assert client.closed is True
    assert result["source"] == "upload"
    assert result["export_video"]["model"] == "fasterliveportrait"


@pytest.mark.asyncio
async def test_video_creation_service_renders_quicktalk_via_omnirt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opentalking import video_creation as video_creation_module

    avatars = tmp_path / "avatars"
    exports = tmp_path / "exports"
    avatar = _write_avatar(avatars)
    manifest = json.loads((avatar / "manifest.json").read_text(encoding="utf-8"))
    manifest["model_type"] = "quicktalk"
    manifest["width"] = 64
    manifest["height"] = 48
    manifest["fps"] = 25
    (avatar / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    quicktalk_dir = avatar / "quicktalk"
    quicktalk_dir.mkdir()
    template = quicktalk_dir / "template_64x48.mp4"
    cache = quicktalk_dir / "face_cache_v3_64x48.npz"
    template.write_bytes(b"template")
    cache.write_bytes(b"cache")
    uploaded = tmp_path / "speech.wav"
    uploaded.write_bytes(b"RIFFaudio")

    class FakeWSClient:
        def __init__(self, ws_url: str, *, extra_headers: dict[str, str] | None = None) -> None:
            self.ws_url = ws_url
            self.extra_headers = extra_headers or {}

    class FakeOmniRTClient:
        instances: list["FakeOmniRTClient"] = []

        def __init__(self, ws_client: FakeWSClient) -> None:
            self.ws_client = ws_client
            self.init_kwargs: dict[str, object] | None = None
            self.generated_chunks: list[np.ndarray] = []
            self.closed = False
            self.fps = 25
            self.audio_chunk_samples = 4
            FakeOmniRTClient.instances.append(self)

        async def init_session(self, **kwargs: object) -> dict[str, object]:
            self.init_kwargs = kwargs
            return {"type": "init_ok"}

        async def prewarm(self) -> dict[str, object]:
            return {"type": "prewarm_skipped"}

        async def generate(self, audio_pcm: np.ndarray) -> list[VideoFrameData]:
            self.generated_chunks.append(np.asarray(audio_pcm, dtype=np.int16).copy())
            return [
                VideoFrameData(
                    data=np.zeros((48, 64, 3), dtype=np.uint8),
                    width=64,
                    height=48,
                    timestamp_ms=0.0,
                )
            ]

        async def close(self, send_close_msg: bool = True) -> None:
            self.closed = send_close_msg

    async def fake_decode(_path: Path) -> np.ndarray:
        return np.arange(6, dtype=np.int16)

    async def fake_mux(_ffmpeg_bin: str, _video_in: Path, _audio_in: Path, out_mp4: Path) -> None:
        out_mp4.write_bytes(b"mp4")

    def fail_get_adapter(_model: str) -> object:
        raise AssertionError("quicktalk omnirt video creation must not load local adapter")

    def fake_create_video_export(root: Path, **kwargs: object) -> dict[str, object]:
        return {
            "id": "export-quicktalk",
            "kind": "video_creation",
            "title": kwargs["title"],
            "duration_sec": kwargs["duration_sec"],
            "size_bytes": len(kwargs["content"]),
            "mime_type": "video/mp4",
            "created_at": "2026-06-04T00:00:00Z",
            "path": str(root / "export-quicktalk.mp4"),
            "session_id": kwargs["session_id"],
            "avatar_id": kwargs["avatar_id"],
            "model": kwargs["model"],
        }

    monkeypatch.setattr(video_creation_module, "FlashTalkWSClient", FakeWSClient, raising=False)
    monkeypatch.setattr(video_creation_module, "OmniRTAudio2VideoClient", FakeOmniRTClient, raising=False)
    monkeypatch.setattr(video_creation_module, "decode_audio_file_to_pcm_i16", fake_decode)
    monkeypatch.setattr(video_creation_module, "_write_video_only", lambda path, _frames, _fps: path.write_bytes(b"video"))
    monkeypatch.setattr(video_creation_module, "_ffmpeg_mux", fake_mux)
    monkeypatch.setattr(video_creation_module, "get_adapter", fail_get_adapter)
    monkeypatch.setattr(
        video_creation_module,
        "resolve_model_backend",
        lambda model, _settings: SimpleNamespace(model=model, backend="omnirt", ws_url=""),
    )
    monkeypatch.setattr(video_creation_module, "create_video_export", fake_create_video_export)

    settings = SimpleNamespace(
        avatars_dir=str(avatars),
        exports_dir=str(exports),
        export_max_bytes=1024 * 1024,
        ffmpeg_bin="ffmpeg",
        omnirt_endpoint="http://127.0.0.1:9000",
        omnirt_audio2video_path_template="/v1/audio2video/{model}",
        omnirt_api_key="",
    )
    service = VideoCreationService(settings)

    result = await service.create_from_audio_file(
        model="quicktalk",
        avatar_id="anchor",
        upload_path=uploaded,
        title="QuickTalk take",
    )

    client = FakeOmniRTClient.instances[0]
    assert client.ws_client.ws_url == "ws://127.0.0.1:9000/v1/audio2video/quicktalk"
    assert client.init_kwargs is not None
    assert client.init_kwargs["avatar_path"] == avatars / "anchor"
    assert client.init_kwargs["ref_image"] == (avatars / "anchor" / "reference.png").resolve()
    assert client.init_kwargs["template_mode"] == "video"
    assert client.init_kwargs["template_video"] == template.resolve()
    assert client.init_kwargs["quicktalk_face_cache"] == cache.resolve()
    assert client.init_kwargs["video_config"] == {"width": 64, "height": 48, "fps": 25}
    assert [chunk.size for chunk in client.generated_chunks] == [4, 4]
    assert client.closed is True
    assert result["source"] == "upload"
    assert result["export_video"]["model"] == "quicktalk"


@pytest.mark.asyncio
async def test_video_creation_service_renders_quicktalk_duo_dialog_with_role_voices(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opentalking import video_creation as video_creation_module

    avatars = tmp_path / "avatars"
    exports = tmp_path / "exports"
    quicktalk_root = tmp_path / "quicktalk-model"
    quicktalk_root.mkdir()
    _write_duo_avatar(avatars)
    tts_calls: list[tuple[str, str | None]] = []
    worker_scripts: list[dict[str, object]] = []
    worker_kwargs: list[dict[str, object]] = []
    muxed_audio: dict[str, np.ndarray] = {}

    class FakeTTS:
        async def synthesize_stream(self, text: str, *, voice: str | None = None):
            tts_calls.append((text, voice))
            size = 1600 if voice == "zh-CN-YunxiNeural" else 800
            value = 100 if voice == "zh-CN-YunxiNeural" else 200
            yield AudioChunk(
                data=np.full(size, value, dtype=np.int16),
                sample_rate=16000,
                duration_ms=float(size) / 16.0,
            )

        async def aclose(self) -> None:
            pass

    class FakeMultiFaceWorker:
        def __init__(self, **kwargs: object) -> None:
            self.fps = 25
            worker_kwargs.append(kwargs)

        def generate_frames_from_script(self, script: dict[str, object]):
            worker_scripts.append(script)
            return iter([np.zeros((48, 64, 3), dtype=np.uint8) for _ in range(7)])

    async def fake_mux(_ffmpeg_bin: str, _video_in: Path, audio_in: Path, out_mp4: Path) -> None:
        with wave.open(str(audio_in), "rb") as wf:
            muxed_audio["pcm"] = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").copy()
        out_mp4.write_bytes(b"mp4")

    def fake_create_video_export(root: Path, **kwargs: object) -> dict[str, object]:
        return {
            "id": "export-duo",
            "kind": "video_creation",
            "title": kwargs["title"],
            "duration_sec": kwargs["duration_sec"],
            "size_bytes": len(kwargs["content"]),
            "mime_type": "video/mp4",
            "created_at": "2026-06-04T00:00:00Z",
            "path": str(root / "export-duo.mp4"),
            "session_id": kwargs["session_id"],
            "avatar_id": kwargs["avatar_id"],
            "model": kwargs["model"],
        }

    monkeypatch.setattr(video_creation_module, "build_tts_adapter", lambda **_kwargs: FakeTTS())
    monkeypatch.setattr(video_creation_module, "MultiFaceRealtimeV3Worker", FakeMultiFaceWorker, raising=False)
    monkeypatch.setattr(video_creation_module, "resolve_quicktalk_asset_root", lambda _settings: quicktalk_root, raising=False)
    monkeypatch.setattr(video_creation_module, "_write_video_only", lambda path, _frames, _fps: path.write_bytes(b"video"))
    monkeypatch.setattr(video_creation_module, "_ffmpeg_mux", fake_mux)
    monkeypatch.setattr(video_creation_module, "create_video_export", fake_create_video_export)
    monkeypatch.setattr(
        video_creation_module,
        "resolve_model_backend",
        lambda model, _settings: SimpleNamespace(model=model, backend="local", ws_url=""),
    )

    service = VideoCreationService(
        SimpleNamespace(
            avatars_dir=str(avatars),
            exports_dir=str(exports),
            export_max_bytes=1024 * 1024,
            ffmpeg_bin="ffmpeg",
            tts_sample_rate=16000,
            torch_device="cpu",
            quicktalk_device="cpu",
            quicktalk_hubert_device="cpu",
            quicktalk_model_backend="pth",
        )
    )

    result = await service.create_from_duo_dialog(
        model="quicktalk",
        avatar_id="duo-anchor",
        title="QuickTalk duo take",
        duo_dialog={
            "lines": [
                {"id": "line-1", "role": "male", "text": "男方开场"},
                {"id": "line-2", "role": "female", "text": "女方回应"},
            ],
            "voices": {"male": "zh-CN-YunxiNeural", "female": "zh-CN-XiaoxiaoNeural"},
            "gap_ms": 120,
        },
        tts_provider="edge",
        tts_model=None,
        composition_config=None,
    )

    assert tts_calls == [("男方开场", "zh-CN-YunxiNeural"), ("女方回应", "zh-CN-XiaoxiaoNeural")]
    assert worker_kwargs[0]["asset_root"] == quicktalk_root
    assert worker_kwargs[0]["template_video"].name == "source_video.mp4"
    assert worker_scripts[0]["speaker_faces"] == {"male": "left", "female": "right"}
    segments = worker_scripts[0]["segments"]
    assert segments == [
        {"speaker_id": "male", "start_ms": 0, "end_ms": 100, "audio": segments[0]["audio"]},
        {"speaker_id": "female", "start_ms": 220, "end_ms": 270, "audio": segments[1]["audio"]},
    ]
    assert Path(segments[0]["audio"]).is_file()
    assert Path(segments[1]["audio"]).is_file()
    assert muxed_audio["pcm"].size == 4320
    assert muxed_audio["pcm"][:1600].tolist() == [100] * 1600
    assert np.all(muxed_audio["pcm"][1600:3520] == 0)
    assert muxed_audio["pcm"][3520:].tolist() == [200] * 800
    assert result["source"] == "duo_dialog"
    assert result["export_video"]["model"] == "quicktalk"


@pytest.mark.asyncio
async def test_video_creation_service_accepts_left_right_roles_for_legacy_duo_avatar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opentalking import video_creation as video_creation_module

    avatars = tmp_path / "avatars"
    exports = tmp_path / "exports"
    quicktalk_root = tmp_path / "quicktalk-model"
    quicktalk_root.mkdir()
    _write_duo_avatar(avatars)
    tts_calls: list[tuple[str, str | None]] = []
    worker_scripts: list[dict[str, object]] = []

    class FakeTTS:
        async def synthesize_stream(self, text: str, *, voice: str | None = None):
            tts_calls.append((text, voice))
            yield AudioChunk(
                data=np.full(160, 100, dtype=np.int16),
                sample_rate=16000,
                duration_ms=10.0,
            )

        async def aclose(self) -> None:
            pass

    class FakeMultiFaceWorker:
        def __init__(self, **_kwargs: object) -> None:
            self.fps = 25

        def generate_frames_from_script(self, script: dict[str, object]):
            worker_scripts.append(script)
            return iter([np.zeros((48, 64, 3), dtype=np.uint8)])

    async def fake_mux(_ffmpeg_bin: str, _video_in: Path, _audio_in: Path, out_mp4: Path) -> None:
        out_mp4.write_bytes(b"mp4")

    def fake_create_video_export(root: Path, **kwargs: object) -> dict[str, object]:
        return {
            "id": "export-duo-left-right",
            "kind": "video_creation",
            "title": kwargs["title"],
            "duration_sec": kwargs["duration_sec"],
            "size_bytes": len(kwargs["content"]),
            "mime_type": "video/mp4",
            "created_at": "2026-06-04T00:00:00Z",
            "path": str(root / "export-duo-left-right.mp4"),
            "session_id": kwargs["session_id"],
            "avatar_id": kwargs["avatar_id"],
            "model": kwargs["model"],
        }

    monkeypatch.setattr(video_creation_module, "build_tts_adapter", lambda **_kwargs: FakeTTS())
    monkeypatch.setattr(video_creation_module, "MultiFaceRealtimeV3Worker", FakeMultiFaceWorker, raising=False)
    monkeypatch.setattr(video_creation_module, "resolve_quicktalk_asset_root", lambda _settings: quicktalk_root, raising=False)
    monkeypatch.setattr(video_creation_module, "_write_video_only", lambda path, _frames, _fps: path.write_bytes(b"video"))
    monkeypatch.setattr(video_creation_module, "_ffmpeg_mux", fake_mux)
    monkeypatch.setattr(video_creation_module, "create_video_export", fake_create_video_export)
    monkeypatch.setattr(
        video_creation_module,
        "resolve_model_backend",
        lambda model, _settings: SimpleNamespace(model=model, backend="local", ws_url=""),
    )

    service = VideoCreationService(
        SimpleNamespace(
            avatars_dir=str(avatars),
            exports_dir=str(exports),
            export_max_bytes=1024 * 1024,
            ffmpeg_bin="ffmpeg",
            tts_sample_rate=16000,
            torch_device="cpu",
            quicktalk_device="cpu",
            quicktalk_hubert_device="cpu",
            quicktalk_model_backend="pth",
        )
    )

    await service.create_from_duo_dialog(
        model="quicktalk",
        avatar_id="duo-anchor",
        title="Left right duo take",
        duo_dialog={
            "lines": [
                {"id": "line-1", "role": "left", "text": "左侧开场"},
                {"id": "line-2", "role": "right", "text": "右侧回应"},
            ],
            "speakers": {
                "left": {"tts_provider": "edge", "voice": "zh-CN-XiaoxiaoNeural"},
                "right": {"tts_provider": "edge", "voice": "zh-CN-YunxiNeural"},
            },
        },
        tts_provider="edge",
        tts_model=None,
        composition_config=None,
    )

    assert tts_calls == [("左侧开场", "zh-CN-XiaoxiaoNeural"), ("右侧回应", "zh-CN-YunxiNeural")]
    assert worker_scripts[0]["speaker_faces"] == {"left": "left", "right": "right"}
    assert [segment["speaker_id"] for segment in worker_scripts[0]["segments"]] == ["left", "right"]


@pytest.mark.asyncio
async def test_video_creation_service_renders_duo_dialog_with_per_role_tts_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opentalking import video_creation as video_creation_module

    avatars = tmp_path / "avatars"
    exports = tmp_path / "exports"
    quicktalk_root = tmp_path / "quicktalk-model"
    quicktalk_root.mkdir()
    _write_duo_avatar(avatars)
    tts_build_calls: list[dict[str, object]] = []
    tts_calls: list[tuple[str, str | None, str | None]] = []
    worker_scripts: list[dict[str, object]] = []

    class FakeTTS:
        def __init__(self, provider: str | None) -> None:
            self.provider = provider

        async def synthesize_stream(self, text: str, *, voice: str | None = None):
            tts_calls.append((text, voice, self.provider))
            size = 1600 if self.provider == "edge" else 800
            yield AudioChunk(
                data=np.full(size, 100, dtype=np.int16),
                sample_rate=16000,
                duration_ms=float(size) / 16.0,
            )

        async def aclose(self) -> None:
            pass

    class FakeMultiFaceWorker:
        def __init__(self, **_kwargs: object) -> None:
            self.fps = 25

        def generate_frames_from_script(self, script: dict[str, object]):
            worker_scripts.append(script)
            return iter([np.zeros((48, 64, 3), dtype=np.uint8) for _ in range(7)])

    def fake_build_tts_adapter(**kwargs):
        tts_build_calls.append(kwargs)
        return FakeTTS(kwargs.get("tts_provider"))

    async def fake_mux(_ffmpeg_bin: str, _video_in: Path, _audio_in: Path, out_mp4: Path) -> None:
        out_mp4.write_bytes(b"mp4")

    def fake_create_video_export(root: Path, **kwargs: object) -> dict[str, object]:
        return {
            "id": "export-duo-role-tts",
            "kind": "video_creation",
            "title": kwargs["title"],
            "duration_sec": kwargs["duration_sec"],
            "size_bytes": len(kwargs["content"]),
            "mime_type": "video/mp4",
            "created_at": "2026-06-04T00:00:00Z",
            "path": str(root / "export-duo-role-tts.mp4"),
            "session_id": kwargs["session_id"],
            "avatar_id": kwargs["avatar_id"],
            "model": kwargs["model"],
        }

    monkeypatch.setattr(video_creation_module, "build_tts_adapter", fake_build_tts_adapter)
    monkeypatch.setattr(video_creation_module, "MultiFaceRealtimeV3Worker", FakeMultiFaceWorker, raising=False)
    monkeypatch.setattr(video_creation_module, "resolve_quicktalk_asset_root", lambda _settings: quicktalk_root, raising=False)
    monkeypatch.setattr(video_creation_module, "_write_video_only", lambda path, _frames, _fps: path.write_bytes(b"video"))
    monkeypatch.setattr(video_creation_module, "_ffmpeg_mux", fake_mux)
    monkeypatch.setattr(video_creation_module, "create_video_export", fake_create_video_export)
    monkeypatch.setattr(
        video_creation_module,
        "resolve_model_backend",
        lambda model, _settings: SimpleNamespace(model=model, backend="local", ws_url=""),
    )

    service = VideoCreationService(
        SimpleNamespace(
            avatars_dir=str(avatars),
            exports_dir=str(exports),
            export_max_bytes=1024 * 1024,
            ffmpeg_bin="ffmpeg",
            tts_sample_rate=16000,
            torch_device="cpu",
            quicktalk_device="cpu",
            quicktalk_hubert_device="cpu",
            quicktalk_model_backend="pth",
        )
    )

    await service.create_from_duo_dialog(
        model="quicktalk",
        avatar_id="duo-anchor",
        title="QuickTalk duo per role TTS",
        duo_dialog={
            "lines": [
                {"id": "line-1", "role": "male", "text": "男方开场"},
                {"id": "line-2", "role": "female", "text": "女方回应"},
            ],
            "speakers": {
                "male": {"tts_provider": "edge", "voice": "zh-CN-YunxiNeural"},
                "female": {"tts_provider": "xiaomi_mimo", "tts_model": "mimo-v2.5-tts", "voice": "冰糖"},
            },
        },
        tts_provider="edge",
        tts_model=None,
        composition_config=None,
    )

    assert [(c["tts_provider"], c["tts_model"], c["default_voice"]) for c in tts_build_calls] == [
        ("edge", None, "zh-CN-YunxiNeural"),
        ("xiaomi_mimo", "mimo-v2.5-tts", "冰糖"),
    ]
    assert tts_calls == [("男方开场", "zh-CN-YunxiNeural", "edge"), ("女方回应", "冰糖", "xiaomi_mimo")]
    assert [segment["speaker_id"] for segment in worker_scripts[0]["segments"]] == ["male", "female"]


@pytest.mark.asyncio
async def test_video_creation_service_rejects_duo_dialog_for_non_quicktalk(tmp_path: Path) -> None:
    avatars = tmp_path / "avatars"
    exports = tmp_path / "exports"
    _write_duo_avatar(avatars)
    service = VideoCreationService(SimpleNamespace(avatars_dir=str(avatars), exports_dir=str(exports)))

    with pytest.raises(ValueError, match="duo_dialog only supports quicktalk"):
        await service.create_from_duo_dialog(
            model="wav2lip",
            avatar_id="duo-anchor",
            title="Wrong model",
            duo_dialog={"lines": [{"role": "male", "text": "hello"}]},
            tts_provider="edge",
            tts_model=None,
            composition_config=None,
        )


@pytest.mark.asyncio
async def test_video_creation_service_rejects_duo_dialog_avatar_without_capability(tmp_path: Path) -> None:
    avatars = tmp_path / "avatars"
    exports = tmp_path / "exports"
    avatar = _write_avatar(avatars)
    manifest = json.loads((avatar / "manifest.json").read_text(encoding="utf-8"))
    manifest["model_type"] = "quicktalk"
    (avatar / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    service = VideoCreationService(SimpleNamespace(avatars_dir=str(avatars), exports_dir=str(exports)))

    with pytest.raises(ValueError, match="avatar does not support duo_dialog"):
        await service.create_from_duo_dialog(
            model="quicktalk",
            avatar_id="anchor",
            title="No duo metadata",
            duo_dialog={"lines": [{"role": "male", "text": "hello"}]},
            tts_provider="edge",
            tts_model=None,
            composition_config=None,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"lines": []}, "duo_dialog.lines must be a non-empty list"),
        ({"lines": [{"role": "host", "text": "hello"}]}, "invalid duo_dialog role: host"),
    ],
)
async def test_video_creation_service_rejects_invalid_duo_dialog_payload(
    tmp_path: Path,
    payload: dict[str, object],
    message: str,
) -> None:
    avatars = tmp_path / "avatars"
    exports = tmp_path / "exports"
    _write_duo_avatar(avatars)
    service = VideoCreationService(SimpleNamespace(avatars_dir=str(avatars), exports_dir=str(exports)))

    with pytest.raises(ValueError, match=message):
        await service.create_from_duo_dialog(
            model="quicktalk",
            avatar_id="duo-anchor",
            title="Invalid duo payload",
            duo_dialog=payload,
            tts_provider="edge",
            tts_model=None,
            composition_config=None,
        )


def test_video_creation_composition_keeps_output_size_without_background(tmp_path: Path) -> None:
    from opentalking import video_creation as video_creation_module

    avatars = tmp_path / "avatars"
    avatar = _write_avatar(avatars)

    config = video_creation_module._normalize_video_composition_config(
        SimpleNamespace(scene_assets_dir=str(tmp_path / "scene-assets")),
        avatar,
        {
            "background_id": None,
            "background_color": "#ffffff",
            "avatar_fit": "contain",
            "avatar_anchor": "center",
            "output_width": 1280,
            "output_height": 720,
        },
    )

    assert config is not None
    assert config["output_width"] == 1280
    assert config["output_height"] == 720
    assert config["background_path"] is None


def test_video_creation_composition_resizes_frames_without_background() -> None:
    from opentalking import video_creation as video_creation_module

    frame = np.full((1080, 1920, 3), 128, dtype=np.uint8)

    frames = video_creation_module._apply_video_composition(
        [frame],
        config={
            "background_path": None,
            "background_color": "#ffffff",
            "avatar_fit": "contain",
            "avatar_anchor": "center",
            "avatar_scale": 1.0,
            "avatar_offset_x": 0.0,
            "avatar_offset_y": 0.0,
            "output_width": 1280,
            "output_height": 720,
        },
    )

    assert frames[0].shape[:2] == (720, 1280)


@pytest.mark.asyncio
async def test_video_creation_service_composites_generated_frames_over_scene_background(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opentalking import video_creation as video_creation_module
    from opentalking.scene_assets import SceneAssetStore
    from PIL import Image
    import io

    avatars = tmp_path / "avatars"
    exports = tmp_path / "exports"
    scene_assets = tmp_path / "scene-assets"
    _write_avatar(avatars)
    transparent_reference = Image.new("RGBA", (4, 4), (255, 0, 0, 0))
    transparent_reference.save(avatars / "anchor" / "reference.png")
    uploaded = tmp_path / "speech.wav"
    uploaded.write_bytes(b"RIFFaudio")

    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 200)).save(buffer, format="PNG")
    background = SceneAssetStore(scene_assets).create_background(
        content=buffer.getvalue(),
        filename="blue.png",
        mime_type="image/png",
        name="Blue",
    )

    captured_frames: list[np.ndarray] = []

    class FakeWSClient:
        def __init__(self, ws_url: str, *, extra_headers: dict[str, str] | None = None) -> None:
            self.ws_url = ws_url
            self.extra_headers = extra_headers or {}

    class FakeOmniRTClient:
        def __init__(self, _ws_client: FakeWSClient) -> None:
            self.fps = 25
            self.audio_chunk_samples = 4

        async def init_session(self, **_kwargs: object) -> dict[str, object]:
            return {"type": "init_ok"}

        async def prewarm(self) -> dict[str, object]:
            return {"type": "prewarm_skipped"}

        async def generate(self, _audio_pcm: np.ndarray) -> list[VideoFrameData]:
            red = np.zeros((4, 4, 3), dtype=np.uint8)
            red[:, :, 0] = 255
            return [VideoFrameData(data=red, width=4, height=4, timestamp_ms=0.0)]

        async def close(self, send_close_msg: bool = True) -> None:
            return None

    async def fake_decode(_path: Path) -> np.ndarray:
        return np.arange(4, dtype=np.int16)

    async def fake_mux(_ffmpeg_bin: str, _video_in: Path, _audio_in: Path, out_mp4: Path) -> None:
        out_mp4.write_bytes(b"mp4")

    def fake_write_video_only(path: Path, frames: list[np.ndarray], _fps: float) -> None:
        captured_frames.extend(np.asarray(frame).copy() for frame in frames)
        path.write_bytes(b"video")

    def fake_create_video_export(root: Path, **kwargs: object) -> dict[str, object]:
        return {
            "id": "export-composed",
            "kind": "video_creation",
            "title": kwargs["title"],
            "duration_sec": kwargs["duration_sec"],
            "size_bytes": len(kwargs["content"]),
            "mime_type": "video/mp4",
            "created_at": "2026-06-04T00:00:00Z",
            "path": str(root / "export-composed.mp4"),
            "session_id": kwargs["session_id"],
            "avatar_id": kwargs["avatar_id"],
            "model": kwargs["model"],
        }

    monkeypatch.setattr(video_creation_module, "FlashTalkWSClient", FakeWSClient, raising=False)
    monkeypatch.setattr(video_creation_module, "OmniRTAudio2VideoClient", FakeOmniRTClient, raising=False)
    monkeypatch.setattr(video_creation_module, "decode_audio_file_to_pcm_i16", fake_decode)
    monkeypatch.setattr(video_creation_module, "_write_video_only", fake_write_video_only)
    monkeypatch.setattr(video_creation_module, "_ffmpeg_mux", fake_mux)
    monkeypatch.setattr(
        video_creation_module,
        "resolve_model_backend",
        lambda model, _settings: SimpleNamespace(model=model, backend="omnirt", ws_url=""),
    )
    monkeypatch.setattr(video_creation_module, "create_video_export", fake_create_video_export)

    service = VideoCreationService(
        SimpleNamespace(
            avatars_dir=str(avatars),
            exports_dir=str(exports),
            scene_assets_dir=str(scene_assets),
            export_max_bytes=1024 * 1024,
            ffmpeg_bin="ffmpeg",
            omnirt_endpoint="http://127.0.0.1:9000",
            omnirt_audio2video_path_template="/v1/audio2video/{model}",
            omnirt_api_key="",
        )
    )

    result = await service.create_from_audio_file(
        model="wav2lip",
        avatar_id="anchor",
        upload_path=uploaded,
        title="Composed take",
        composition_config={
            "background_id": background["id"],
            "avatar_fit": "contain",
            "avatar_anchor": "center",
            "avatar_scale": 1.0,
            "avatar_offset_x": 0,
            "avatar_offset_y": 0,
            "output_width": 320,
            "output_height": 180,
        },
    )

    assert result["export_video"]["model"] == "wav2lip"
    assert captured_frames
    assert captured_frames[0].shape == (180, 320, 3)
    assert captured_frames[0][0, 0].tolist() == [200, 20, 10]


@pytest.mark.asyncio
async def test_video_creation_service_renders_musetalk_via_omnirt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opentalking import video_creation as video_creation_module

    avatars = tmp_path / "avatars"
    exports = tmp_path / "exports"
    avatar = _write_avatar(avatars)
    manifest = json.loads((avatar / "manifest.json").read_text(encoding="utf-8"))
    manifest["model_type"] = "musetalk"
    (avatar / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    uploaded = tmp_path / "speech.wav"
    uploaded.write_bytes(b"RIFFaudio")

    class FakeWSClient:
        def __init__(self, ws_url: str, *, extra_headers: dict[str, str] | None = None) -> None:
            self.ws_url = ws_url
            self.extra_headers = extra_headers or {}

    class FakeOmniRTClient:
        instances: list["FakeOmniRTClient"] = []

        def __init__(self, ws_client: FakeWSClient) -> None:
            self.ws_client = ws_client
            self.init_kwargs: dict[str, object] | None = None
            self.generated_chunks: list[np.ndarray] = []
            self.closed = False
            self.fps = 25
            self.audio_chunk_samples = 4
            FakeOmniRTClient.instances.append(self)

        async def init_session(self, **kwargs: object) -> dict[str, object]:
            self.init_kwargs = kwargs
            return {"type": "init_ok"}

        async def prewarm(self) -> dict[str, object]:
            return {"type": "prewarm_skipped"}

        async def generate(self, audio_pcm: np.ndarray) -> list[VideoFrameData]:
            self.generated_chunks.append(np.asarray(audio_pcm, dtype=np.int16).copy())
            return [
                VideoFrameData(
                    data=np.zeros((48, 64, 3), dtype=np.uint8),
                    width=64,
                    height=48,
                    timestamp_ms=0.0,
                )
            ]

        async def close(self, send_close_msg: bool = True) -> None:
            self.closed = send_close_msg

    async def fake_decode(_path: Path) -> np.ndarray:
        return np.arange(6, dtype=np.int16)

    async def fake_mux(_ffmpeg_bin: str, _video_in: Path, _audio_in: Path, out_mp4: Path) -> None:
        out_mp4.write_bytes(b"mp4")

    def fail_get_adapter(_model: str) -> object:
        raise AssertionError("musetalk omnirt video creation must not load local adapter")

    def fake_create_video_export(root: Path, **kwargs: object) -> dict[str, object]:
        return {
            "id": "export-musetalk",
            "kind": "video_creation",
            "title": kwargs["title"],
            "duration_sec": kwargs["duration_sec"],
            "size_bytes": len(kwargs["content"]),
            "mime_type": "video/mp4",
            "created_at": "2026-06-04T00:00:00Z",
            "path": str(root / "export-musetalk.mp4"),
            "session_id": kwargs["session_id"],
            "avatar_id": kwargs["avatar_id"],
            "model": kwargs["model"],
        }

    monkeypatch.setattr(video_creation_module, "FlashTalkWSClient", FakeWSClient, raising=False)
    monkeypatch.setattr(video_creation_module, "OmniRTAudio2VideoClient", FakeOmniRTClient, raising=False)
    monkeypatch.setattr(video_creation_module, "decode_audio_file_to_pcm_i16", fake_decode)
    monkeypatch.setattr(video_creation_module, "_write_video_only", lambda path, _frames, _fps: path.write_bytes(b"video"))
    monkeypatch.setattr(video_creation_module, "_ffmpeg_mux", fake_mux)
    monkeypatch.setattr(video_creation_module, "get_adapter", fail_get_adapter)
    monkeypatch.setattr(
        video_creation_module,
        "resolve_model_backend",
        lambda model, _settings: SimpleNamespace(model=model, backend="omnirt", ws_url=""),
    )
    monkeypatch.setattr(video_creation_module, "create_video_export", fake_create_video_export)

    settings = SimpleNamespace(
        avatars_dir=str(avatars),
        exports_dir=str(exports),
        export_max_bytes=1024 * 1024,
        ffmpeg_bin="ffmpeg",
        omnirt_endpoint="http://127.0.0.1:9000",
        omnirt_audio2video_path_template="/v1/audio2video/{model}",
        omnirt_api_key="",
    )
    service = VideoCreationService(settings)

    result = await service.create_from_audio_file(
        model="musetalk",
        avatar_id="anchor",
        upload_path=uploaded,
        title="MuseTalk take",
    )

    client = FakeOmniRTClient.instances[0]
    assert client.ws_client.ws_url == "ws://127.0.0.1:9000/v1/audio2video/musetalk"
    assert client.init_kwargs is not None
    assert client.init_kwargs["avatar_path"] == avatars / "anchor"
    assert client.init_kwargs["ref_image"] == (avatars / "anchor" / "reference.png").resolve()
    assert "template_mode" not in client.init_kwargs
    assert "quicktalk_face_cache" not in client.init_kwargs
    assert "video_config" not in client.init_kwargs
    assert [chunk.size for chunk in client.generated_chunks] == [4, 4]
    assert client.closed is True
    assert result["source"] == "upload"
    assert result["export_video"]["model"] == "musetalk"


def test_video_creation_fasterliveportrait_preroll_samples() -> None:
    from opentalking import video_creation as video_creation_module

    settings = SimpleNamespace(video_creation_fasterliveportrait_preroll_ms=400)

    assert video_creation_module._fasterliveportrait_preroll_samples(settings, "fasterliveportrait", 16000) == 6400
    assert video_creation_module._fasterliveportrait_preroll_samples(settings, "wav2lip", 16000) == 0
    assert video_creation_module._fasterliveportrait_preroll_samples(
        SimpleNamespace(video_creation_fasterliveportrait_preroll_ms=0),
        "fasterliveportrait",
        16000,
    ) == 0


def test_video_creation_fasterliveportrait_uses_video_creation_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    from opentalking import video_creation as video_creation_module

    monkeypatch.setattr(
        video_creation_module,
        "get_model_config",
        lambda _model: {
            "width": 448,
            "height": 900,
            "fps": 25,
            "render_keyframes_per_chunk": 25,
            "disable_frame_interpolation": True,
            "animation_region": "lip",
            "expression_multiplier": 1.0,
            "mouth_open_multiplier": 1.25,
            "mouth_corner_multiplier": 0.85,
            "cheek_jaw_multiplier": 0.9,
            "driving_multiplier": 1.0,
            "cfg_scale": 4.0,
            "flag_normalize_lip": True,
        },
    )

    config = video_creation_module._fasterliveportrait_video_config(None)

    assert config is not None
    assert config["width"] == 448
    assert config["render_keyframes_per_chunk"] == 25
    assert config["animation_region"] == "lip"
    assert config["expression_multiplier"] == 1.0
    assert config["mouth_open_multiplier"] == 0.9
    assert config["mouth_corner_multiplier"] == 0.85
    assert config["cheek_jaw_multiplier"] == 0.9
    assert config["driving_multiplier"] == 1.0
    assert config["cfg_scale"] == 3.0
    assert config["flag_normalize_lip"] is False


def test_quicktalk_init_session_prefers_uploaded_source_video_over_realtime_cache(
    tmp_path: Path,
) -> None:
    from opentalking import video_creation as video_creation_module

    avatar = _write_avatar(tmp_path, "video-avatar")
    source_dir = avatar / "source"
    source_dir.mkdir()
    source_video = source_dir / "source_video.mp4"
    source_video.write_bytes(b"uploaded-video")
    quicktalk_dir = avatar / "quicktalk"
    quicktalk_dir.mkdir()
    realtime_template = quicktalk_dir / "template_320x242.mp4"
    realtime_cache = quicktalk_dir / "face_cache_v3_320x242.npz"
    realtime_template.write_bytes(b"short-realtime-template")
    realtime_cache.write_bytes(b"realtime-cache")
    manifest = json.loads((avatar / "manifest.json").read_text(encoding="utf-8"))
    manifest["model_type"] = "quicktalk"
    manifest["width"] = 320
    manifest["height"] = 241
    manifest["metadata"] = {
        "custom_avatar": True,
        "reference_mode": "video",
        "source_image": "source/source.png",
        "source_video": "source/source_video.mp4",
    }
    (avatar / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    kwargs = video_creation_module._quicktalk_init_session_kwargs(
        SimpleNamespace(quicktalk_max_long_edge=900),
        avatar,
    )

    assert kwargs["template_mode"] == "video"
    assert kwargs["template_video"] == source_video.resolve()
    assert "quicktalk_face_cache" not in kwargs
    assert kwargs["video_config"] == {"width": 320, "height": 241, "fps": 25}


def test_quicktalk_init_session_uses_uploaded_source_video_without_prepared_cache(
    tmp_path: Path,
) -> None:
    from opentalking import video_creation as video_creation_module

    avatar = _write_avatar(tmp_path, "video-avatar")
    source_dir = avatar / "source"
    source_dir.mkdir()
    source_video = source_dir / "source_video.mp4"
    source_video.write_bytes(b"uploaded-video")
    manifest = json.loads((avatar / "manifest.json").read_text(encoding="utf-8"))
    manifest["model_type"] = "quicktalk"
    manifest["width"] = 320
    manifest["height"] = 241
    manifest["metadata"] = {
        "custom_avatar": True,
        "reference_mode": "video",
        "source_image": "source/source.png",
        "source_video": "source/source_video.mp4",
    }
    (avatar / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    kwargs = video_creation_module._quicktalk_init_session_kwargs(
        SimpleNamespace(quicktalk_max_long_edge=900),
        avatar,
    )

    assert kwargs["template_mode"] == "video"
    assert kwargs["template_video"] == source_video.resolve()
    assert "quicktalk_face_cache" not in kwargs
    assert kwargs["video_config"] == {"width": 320, "height": 241, "fps": 25}


@pytest.mark.asyncio
async def test_video_creation_trims_generated_frames_to_audio_duration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opentalking import video_creation as video_creation_module

    avatars = tmp_path / "avatars"
    exports = tmp_path / "exports"
    avatar = _write_avatar(avatars)
    manifest = json.loads((avatar / "manifest.json").read_text(encoding="utf-8"))
    manifest["model_type"] = "quicktalk"
    manifest["width"] = 64
    manifest["height"] = 48
    source_dir = avatar / "source"
    source_dir.mkdir()
    source_video = source_dir / "source_video.mp4"
    source_video.write_bytes(b"uploaded-video")
    manifest["metadata"] = {"reference_mode": "video", "source_video": "source/source_video.mp4"}
    (avatar / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    uploaded = tmp_path / "speech.wav"
    uploaded.write_bytes(b"RIFFaudio")
    written_frame_counts: list[int] = []

    class FakeWSClient:
        def __init__(self, ws_url: str, *, extra_headers: dict[str, str] | None = None) -> None:
            self.ws_url = ws_url
            self.extra_headers = extra_headers or {}

    class FakeOmniRTClient:
        instances: list["FakeOmniRTClient"] = []

        def __init__(self, ws_client: FakeWSClient) -> None:
            self.ws_client = ws_client
            self.init_kwargs: dict[str, object] | None = None
            self.fps = 4
            self.audio_chunk_samples = 4
            FakeOmniRTClient.instances.append(self)

        async def init_session(self, **kwargs: object) -> dict[str, object]:
            self.init_kwargs = kwargs
            return {"type": "init_ok"}

        async def prewarm(self) -> dict[str, object]:
            return {"type": "prewarm_skipped"}

        async def generate(self, audio_pcm: np.ndarray) -> list[VideoFrameData]:
            del audio_pcm
            return [
                VideoFrameData(
                    data=np.full((48, 64, 3), fill_value=index, dtype=np.uint8),
                    width=64,
                    height=48,
                    timestamp_ms=float(index),
                )
                for index in range(3)
            ]

        async def close(self, send_close_msg: bool = True) -> None:
            del send_close_msg

    async def fake_decode(_path: Path) -> np.ndarray:
        return np.arange(8, dtype=np.int16)

    async def fake_mux(_ffmpeg_bin: str, _video_in: Path, _audio_in: Path, out_mp4: Path) -> None:
        out_mp4.write_bytes(b"mp4")

    def fake_write_video_only(path: Path, frames: list[np.ndarray], fps: float) -> None:
        del fps
        written_frame_counts.append(len(frames))
        path.write_bytes(b"video")

    def fake_create_video_export(root: Path, **kwargs: object) -> dict[str, object]:
        return {
            "id": "export-trimmed",
            "kind": "video_creation",
            "title": kwargs["title"],
            "duration_sec": kwargs["duration_sec"],
            "size_bytes": len(kwargs["content"]),
            "mime_type": "video/mp4",
            "created_at": "2026-06-04T00:00:00Z",
            "path": str(root / "export-trimmed.mp4"),
            "session_id": kwargs["session_id"],
            "avatar_id": kwargs["avatar_id"],
            "model": kwargs["model"],
        }

    monkeypatch.setattr(video_creation_module, "FlashTalkWSClient", FakeWSClient, raising=False)
    monkeypatch.setattr(video_creation_module, "OmniRTAudio2VideoClient", FakeOmniRTClient, raising=False)
    monkeypatch.setattr(video_creation_module, "decode_audio_file_to_pcm_i16", fake_decode)
    monkeypatch.setattr(video_creation_module, "_write_video_only", fake_write_video_only)
    monkeypatch.setattr(video_creation_module, "_ffmpeg_mux", fake_mux)
    monkeypatch.setattr(
        video_creation_module,
        "resolve_model_backend",
        lambda model, _settings: SimpleNamespace(model=model, backend="omnirt", ws_url=""),
    )
    monkeypatch.setattr(video_creation_module, "create_video_export", fake_create_video_export)

    service = VideoCreationService(
        SimpleNamespace(
            avatars_dir=str(avatars),
            exports_dir=str(exports),
            export_max_bytes=1024 * 1024,
            ffmpeg_bin="ffmpeg",
            omnirt_endpoint="http://127.0.0.1:9000",
            omnirt_audio2video_path_template="/v1/audio2video/{model}",
            omnirt_api_key="",
        )
    )

    result = await service.create_from_audio_file(
        model="quicktalk",
        avatar_id="anchor",
        upload_path=uploaded,
        title="Trimmed source video take",
    )

    client = FakeOmniRTClient.instances[0]
    assert client.init_kwargs is not None
    assert client.init_kwargs["template_mode"] == "video"
    assert client.init_kwargs["template_video"] == source_video.resolve()
    assert written_frame_counts == [1]
    assert result["export_video"]["duration_sec"] == 0.0005


def test_video_creation_rejects_oversized_uploaded_audio(tmp_path: Path, monkeypatch) -> None:
    client, _creators = _client(tmp_path, monkeypatch)
    with client:
        response = client.post(
            "/video-creation/jobs",
            data={"model": "wav2lip", "avatar_id": "anchor", "audio_source": "upload"},
            files={"audio_file": ("speech.wav", b"x" * 2048, "audio/wav")},
        )

    assert response.status_code == 413


def test_reference_video_duration_options_default_and_settings() -> None:
    from opentalking import video_creation as video_creation_module

    assert video_creation_module._reference_duration_options(SimpleNamespace()) == {10, 30, 60}
    assert video_creation_module._reference_duration_options(
        SimpleNamespace(video_creation_reference_durations="5, 10, bad, 120")
    ) == {5, 10, 120}


def test_reference_video_driver_pcm_matches_duration_and_is_low_energy() -> None:
    from opentalking import video_creation as video_creation_module

    pcm = video_creation_module._build_reference_driver_pcm(16000 * 10, level=480.0)

    assert pcm.dtype == np.int16
    assert pcm.shape == (16000 * 10,)
    assert int(np.max(np.abs(pcm))) <= 480
    assert int(np.max(np.abs(pcm))) > 0
    assert int(np.count_nonzero(pcm)) > 1000


@pytest.mark.asyncio
async def test_create_reference_video_rejects_non_flashtalk(tmp_path: Path) -> None:
    avatars = tmp_path / "avatars"
    exports = tmp_path / "exports"
    _write_avatar(avatars)
    service = VideoCreationService(
        SimpleNamespace(
            avatars_dir=str(avatars),
            exports_dir=str(exports),
            video_creation_reference_durations="10,30,60",
        )
    )

    with pytest.raises(ValueError, match="reference video generation only supports flashtalk"):
        await service.create_reference_video(
            model="quicktalk",
            avatar_id="anchor",
            duration_sec=10,
            title="Reference take",
        )


@pytest.mark.asyncio
async def test_create_reference_video_uses_synthetic_driver_pcm_when_audio_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    avatars = tmp_path / "avatars"
    exports = tmp_path / "exports"
    _write_avatar(avatars)
    captured: dict[str, object] = {}

    async def fake_create_from_pcm(self, **kwargs: object) -> dict[str, object]:
        del self
        captured.update(kwargs)
        pcm = np.asarray(kwargs["pcm"], dtype=np.int16)
        return {
            "job_id": "job-reference",
            "status": "done",
            "source": kwargs["source"],
            "export_video": {
                "id": "export-reference",
                "kind": "video_creation",
                "title": kwargs["title"],
                "duration_sec": float(pcm.size) / 16000.0,
                "size_bytes": 9,
                "mime_type": "video/mp4",
                "created_at": "2026-06-03T00:00:00Z",
                "path": str(exports / "reference.mp4"),
                "download_url": "/exports/videos/export-reference/download",
                "session_id": None,
                "avatar_id": kwargs["avatar_id"],
                "model": kwargs["model"],
            },
        }

    monkeypatch.setattr(VideoCreationService, "_create_from_pcm", fake_create_from_pcm)
    service = VideoCreationService(
        SimpleNamespace(
            avatars_dir=str(avatars),
            exports_dir=str(exports),
            video_creation_reference_durations="10,30,60",
            video_creation_reference_driver_audio=str(tmp_path / "missing-driver.wav"),
            video_creation_reference_driver_level=240,
        )
    )
    result = await service.create_reference_video(
        model="flashtalk",
        avatar_id="anchor",
        duration_sec=10,
        title="Reference take",
    )

    pcm = np.asarray(captured["pcm"], dtype=np.int16)
    assert captured["model"] == "flashtalk"
    assert captured["avatar_id"] == "anchor"
    assert captured["source"] == "reference_video"
    assert pcm.shape == (16000 * 10,)
    assert int(np.max(np.abs(pcm))) <= 240
    assert result["source"] == "reference_video"
    assert result["export_video"]["duration_sec"] == 10.0


@pytest.mark.asyncio
async def test_create_reference_video_uses_default_driver_audio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    avatars = tmp_path / "avatars"
    exports = tmp_path / "exports"
    _write_avatar(avatars)
    driver_audio = tmp_path / "driver.wav"
    driver_pcm = np.array([100, -100, 200, -200], dtype=np.int16)

    from opentalking import video_creation as video_creation_module

    video_creation_module._write_wav(driver_audio, driver_pcm, sample_rate=16000)
    captured: dict[str, object] = {}

    async def fake_create_from_pcm(self, **kwargs: object) -> dict[str, object]:
        del self
        captured.update(kwargs)
        pcm = np.asarray(kwargs["pcm"], dtype=np.int16)
        return {
            "job_id": "job-reference",
            "status": "done",
            "source": kwargs["source"],
            "export_video": {
                "id": "export-reference",
                "kind": "video_creation",
                "title": kwargs["title"],
                "duration_sec": float(pcm.size) / 16000.0,
                "size_bytes": 9,
                "mime_type": "video/mp4",
                "created_at": "2026-06-03T00:00:00Z",
                "path": str(exports / "reference.mp4"),
                "download_url": "/exports/videos/export-reference/download",
                "session_id": None,
                "avatar_id": kwargs["avatar_id"],
                "model": kwargs["model"],
            },
        }

    monkeypatch.setattr(VideoCreationService, "_create_from_pcm", fake_create_from_pcm)
    service = VideoCreationService(
        SimpleNamespace(
            avatars_dir=str(avatars),
            exports_dir=str(exports),
            video_creation_reference_durations="10,30,60",
            video_creation_reference_driver_audio=str(driver_audio),
        )
    )

    result = await service.create_reference_video(
        model="flashtalk",
        avatar_id="anchor",
        duration_sec=10,
        title="Reference take",
    )

    pcm = np.asarray(captured["pcm"], dtype=np.int16)
    assert pcm.shape == (16000 * 10,)
    assert pcm[:8].tolist() == [100, -100, 200, -200, 100, -100, 200, -200]
    assert result["source"] == "reference_video"
    assert result["export_video"]["duration_sec"] == 10.0


@pytest.mark.asyncio
async def test_create_reference_video_falls_back_when_default_driver_audio_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    avatars = tmp_path / "avatars"
    exports = tmp_path / "exports"
    _write_avatar(avatars)
    captured: dict[str, object] = {}

    async def fake_create_from_pcm(self, **kwargs: object) -> dict[str, object]:
        del self
        captured.update(kwargs)
        pcm = np.asarray(kwargs["pcm"], dtype=np.int16)
        return {
            "job_id": "job-reference",
            "status": "done",
            "source": kwargs["source"],
            "export_video": {
                "id": "export-reference",
                "kind": "video_creation",
                "title": kwargs["title"],
                "duration_sec": float(pcm.size) / 16000.0,
                "size_bytes": 9,
                "mime_type": "video/mp4",
                "created_at": "2026-06-03T00:00:00Z",
                "path": str(exports / "reference.mp4"),
                "download_url": "/exports/videos/export-reference/download",
                "session_id": None,
                "avatar_id": kwargs["avatar_id"],
                "model": kwargs["model"],
            },
        }

    monkeypatch.setattr(VideoCreationService, "_create_from_pcm", fake_create_from_pcm)
    service = VideoCreationService(
        SimpleNamespace(
            avatars_dir=str(avatars),
            exports_dir=str(exports),
            video_creation_reference_durations="10,30,60",
            video_creation_reference_driver_audio=str(tmp_path / "missing.wav"),
            video_creation_reference_driver_level=240,
        )
    )

    result = await service.create_reference_video(
        model="flashtalk",
        avatar_id="anchor",
        duration_sec=10,
        title="Reference take",
    )

    pcm = np.asarray(captured["pcm"], dtype=np.int16)
    assert pcm.shape == (16000 * 10,)
    assert int(np.max(np.abs(pcm))) <= 240
    assert int(np.count_nonzero(pcm)) > 1000
    assert result["source"] == "reference_video"
