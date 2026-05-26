from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import apps.unified.main as unified_main
import opentalking.runtime.task_consumer as task_consumer


class FakeRunner:
    def __init__(self, *, session_id: str, redis) -> None:
        self.session_id = session_id
        self.redis = redis

    async def prepare(self) -> None:
        return None

    async def close(self) -> None:
        return None


def _client(monkeypatch, tmp_path: Path) -> TestClient:
    def fake_create_runner(task, redis, avatars_root: Path, device: str) -> FakeRunner:
        del avatars_root, device
        return FakeRunner(session_id=str(task["session_id"]), redis=redis)

    monkeypatch.setattr(task_consumer, "_create_runner", fake_create_runner)
    monkeypatch.delenv("OPENTALKING_CONFIG_FILE", raising=False)
    monkeypatch.delenv("CONFIG_FILE", raising=False)
    monkeypatch.delenv("OMNIRT_ENDPOINT", raising=False)
    monkeypatch.delenv("OPENTALKING_OMNIRT_ENDPOINT", raising=False)
    monkeypatch.chdir(tmp_path)
    avatars_dir = Path(__file__).resolve().parents[3] / "examples" / "avatars"
    monkeypatch.setenv("OPENTALKING_AVATARS_DIR", str(avatars_dir))
    monkeypatch.setenv("OPENTALKING_FLASHTALK_WS_URL", "ws://127.0.0.1:8765")
    unified_main.get_settings.cache_clear()
    return TestClient(unified_main.create_app())


def test_create_session_rejects_api_stt_without_module_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENTALKING_STT_API_KEY", raising=False)
    monkeypatch.delenv("OPENTALKING_STT_DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setenv("OPENTALKING_TTS_PROVIDER", "local_cosyvoice")

    with _client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/sessions",
            json={
                "avatar_id": "singer",
                "model": "flashtalk",
                "stt_provider": "dashscope",
                "tts_provider": "local_cosyvoice",
            },
        )

    assert response.status_code == 400
    assert "OPENTALKING_STT_DASHSCOPE_API_KEY" in response.json()["detail"]


def test_create_session_rejects_api_tts_without_module_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENTALKING_TTS_API_KEY", raising=False)
    monkeypatch.delenv("OPENTALKING_TTS_DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setenv("OPENTALKING_STT_PROVIDER", "sensevoice")

    with _client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/sessions",
            json={"avatar_id": "singer", "model": "flashtalk", "tts_provider": "dashscope"},
        )

    assert response.status_code == 400
    assert "OPENTALKING_TTS_DASHSCOPE_API_KEY" in response.json()["detail"]


def test_unified_startup_prewarms_local_stt(monkeypatch, tmp_path: Path) -> None:
    from opentalking.providers.stt import factory as stt_factory

    calls: list[str | None] = []

    def fake_prewarm(provider: str | None = None) -> bool:
        calls.append(provider)
        return True

    monkeypatch.setenv("OPENTALKING_STT_DEFAULT_PROVIDER", "sensevoice")
    monkeypatch.setattr(stt_factory, "prewarm_stt_adapter", fake_prewarm)

    with _client(monkeypatch, tmp_path) as client:
        assert client.get("/health").status_code == 200

    assert calls == [None]
