from __future__ import annotations

import io
import sys
import wave
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import numpy as np
import pytest

import apps.api.routes.voices as voices_routes


def test_dedupe_display_label_keeps_unique_label(monkeypatch):
    monkeypatch.setattr(voices_routes, "list_voices", lambda provider: [])

    assert (
        voices_routes._dedupe_display_label(
            "我的复刻音色",
            provider="dashscope",
            target_model="qwen3-tts-vc-realtime-2026-01-15",
        )
        == "我的复刻音色"
    )


def test_dedupe_display_label_adds_timestamp_for_duplicate(monkeypatch):
    monkeypatch.setattr(
        voices_routes,
        "list_voices",
        lambda provider: [
            SimpleNamespace(
                source="clone",
                target_model="qwen3-tts-vc-realtime-2026-01-15",
                display_label="我的复刻音色",
            )
        ],
    )

    label = voices_routes._dedupe_display_label(
        "我的复刻音色",
        provider="dashscope",
        target_model="qwen3-tts-vc-realtime-2026-01-15",
    )

    assert label.startswith("我的复刻音色-")
    assert label != "我的复刻音色"


def _wav_bytes(*, seconds: float = 4.0, amplitude: int = 1200) -> bytes:
    sr = 16000
    samples = max(1, int(sr * seconds))
    if amplitude > 0:
        t = np.arange(samples, dtype=np.float32) / sr
        pcm = (np.sin(2 * np.pi * 220 * t) * amplitude).astype("<i2")
    else:
        pcm = np.zeros(samples, dtype="<i2")
    out = io.BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return out.getvalue()


def test_local_cosyvoice_clone_stores_prompt_locally(tmp_path, monkeypatch):
    inserted: dict[str, object] = {}

    monkeypatch.setenv("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", str(tmp_path / "models"))
    monkeypatch.setattr(voices_routes, "init_voice_store", lambda: None)
    monkeypatch.setattr(
        voices_routes.bailian_clone,
        "convert_audio_to_wav_24k_mono",
        lambda raw, suffix: _wav_bytes(),
    )

    async def fake_validate(wav, prompt_text):
        return {"recognized_text": prompt_text, "duration_sec": 4.0, "active_sec": 3.5}

    monkeypatch.setattr(voices_routes, "_validate_local_cosyvoice_prompt", fake_validate)

    def fake_insert_clone(**kwargs):
        inserted.update(kwargs)
        return 42

    monkeypatch.setattr(voices_routes, "insert_clone", fake_insert_clone)

    app = FastAPI()
    app.include_router(voices_routes.router)
    response = TestClient(app).post(
        "/voices/clone",
        data={
            "provider": "local_cosyvoice",
            "target_model": "FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
            "display_label": "本地客服女声",
            "prompt_text": "开饭时间早上9点至下午5点。",
        },
        files={"audio": ("sample.wav", _wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    voice_id = body["voice_id"]
    voice_dir = tmp_path / "models" / "voices" / "clones" / voice_id
    assert body["provider"] == "local_cosyvoice"
    assert body["entry_id"] == 42
    assert (voice_dir / "prompt.wav").is_file()
    assert (voice_dir / "prompt.txt").read_text(encoding="utf-8") == "开饭时间早上9点至下午5点。"
    assert '"recognized_text": "开饭时间早上9点至下午5点。"' in (voice_dir / "meta.json").read_text(
        encoding="utf-8"
    )
    assert inserted["provider"] == "local_cosyvoice"
    assert inserted["voice_id"] == voice_id
    assert inserted["display_label"] == "本地客服女声"


def test_local_cosyvoice_clone_rejects_silent_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", str(tmp_path / "models"))
    monkeypatch.setattr(voices_routes, "init_voice_store", lambda: None)
    monkeypatch.setattr(voices_routes, "list_voices", lambda provider=None: [])
    monkeypatch.setattr(
        voices_routes.bailian_clone,
        "convert_audio_to_wav_24k_mono",
        lambda raw, suffix: _wav_bytes(amplitude=0),
    )

    app = FastAPI()
    app.include_router(voices_routes.router)
    response = TestClient(app).post(
        "/voices/clone",
        data={
            "provider": "local_cosyvoice",
            "target_model": "FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
            "display_label": "坏样本",
        },
        files={"audio": ("sample.wav", _wav_bytes(amplitude=0), "audio/wav")},
    )

    assert response.status_code == 400
    assert "声音太小" in response.json()["detail"]


def test_local_cosyvoice_prompt_validation_rejects_mismatched_asr(monkeypatch):
    def fake_transcribe(_path):
        return "开饭时间早上9点至下午5点。", 12.3

    monkeypatch.setitem(
        sys.modules,
        "opentalking.providers.stt.factory",
        SimpleNamespace(transcribe_wav_path_sync=fake_transcribe),
    )

    with pytest.raises(HTTPException) as exc:
        import asyncio

        asyncio.run(voices_routes._validate_local_cosyvoice_prompt(_wav_bytes(), "你好，今天阳光很好，我正在用自然清晰的声音，记录这一段音色。"))

    assert exc.value.status_code == 400
    assert "参考文本不一致" in exc.value.detail


def test_delete_local_cosyvoice_clone_removes_prompt_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", str(tmp_path / "models"))
    voice_id = "local-delete-test"
    voice_dir = tmp_path / "models" / "voices" / "clones" / voice_id
    voice_dir.mkdir(parents=True)
    (voice_dir / "prompt.wav").write_bytes(b"RIFFtest")
    (voice_dir / "prompt.txt").write_text("测试文本", encoding="utf-8")
    monkeypatch.setattr(voices_routes, "init_voice_store", lambda: None)
    monkeypatch.setattr(
        voices_routes,
        "get_entry",
        lambda entry_id: {
            "id": entry_id,
            "source": "clone",
            "provider": "local_cosyvoice",
            "voice_id": voice_id,
        },
    )
    monkeypatch.setattr(voices_routes, "delete_entry", lambda entry_id: True)

    app = FastAPI()
    app.include_router(voices_routes.router)
    response = TestClient(app).delete("/voices/123")

    assert response.status_code == 200
    assert not voice_dir.exists()


def test_get_voices_includes_local_cosyvoice_system_voice_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", str(tmp_path / "models"))
    voice_dir = tmp_path / "models" / "voices" / "system" / "local-female-standard"
    voice_dir.mkdir(parents=True)
    (voice_dir / "prompt.wav").write_bytes(b"RIFFtest")
    (voice_dir / "prompt.txt").write_text("标准女声音色。", encoding="utf-8")
    (voice_dir / "meta.json").write_text('{"display_label":"标准女声"}', encoding="utf-8")
    monkeypatch.setattr(voices_routes, "init_voice_store", lambda: None)
    monkeypatch.setattr(voices_routes, "list_voices", lambda provider=None: [])

    app = FastAPI()
    app.include_router(voices_routes.router)
    response = TestClient(app).get("/voices?provider=local_cosyvoice")

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "id": -1,
            "user_id": 1,
            "provider": "local_cosyvoice",
            "voice_id": "local-female-standard",
            "display_label": "标准女声",
            "target_model": None,
            "source": "system",
        }
    ]
