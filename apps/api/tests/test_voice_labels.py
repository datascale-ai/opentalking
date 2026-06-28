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
    monkeypatch.setattr(voices_routes, "list_voices", lambda provider=None: [])
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



def test_local_f5_tts_clone_stores_prompt_audio_and_text(tmp_path, monkeypatch):
    inserted: dict[str, object] = {}

    monkeypatch.setenv("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", str(tmp_path / "models"))
    monkeypatch.setattr(voices_routes, "init_voice_store", lambda: None)
    monkeypatch.setattr(voices_routes, "list_voices", lambda provider=None: [])
    monkeypatch.setattr(
        voices_routes.bailian_clone,
        "convert_audio_to_wav_24k_mono",
        lambda raw, suffix: _wav_bytes(),
    )

    def fake_insert_clone(**kwargs):
        inserted.update(kwargs)
        return 77

    monkeypatch.setattr(voices_routes, "insert_clone", fake_insert_clone)

    app = FastAPI()
    app.include_router(voices_routes.router)
    response = TestClient(app).post(
        "/voices/clone",
        data={
            "provider": "local_f5_tts",
            "target_model": "SWivid/F5-TTS/F5TTS_v1_Base",
            "display_label": "F5 客服女声",
            "prompt_text": "您好，欢迎使用实时数字人。",
        },
        files={"audio": ("sample.wav", _wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    voice_id = body["voice_id"]
    voice_dir = tmp_path / "models" / "voices" / "clones" / voice_id
    assert body["provider"] == "local_f5_tts"
    assert body["entry_id"] == 77
    assert body["target_model"] == "SWivid/F5-TTS/F5TTS_v1_Base"
    assert (voice_dir / "prompt.wav").is_file()
    assert (voice_dir / "prompt.txt").read_text(encoding="utf-8") == "您好，欢迎使用实时数字人。"
    meta = (voice_dir / "meta.json").read_text(encoding="utf-8")
    assert '"provider": "local_f5_tts"' in meta
    assert inserted["provider"] == "local_f5_tts"
    assert inserted["voice_id"] == voice_id
    assert inserted["display_label"] == "F5 客服女声"


def test_get_voices_includes_local_f5_tts_system_voice_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", str(tmp_path / "models"))
    voice_dir = tmp_path / "models" / "voices" / "system" / "f5-clear-cn"
    voice_dir.mkdir(parents=True)
    (voice_dir / "prompt.wav").write_bytes(b"RIFFtest")
    (voice_dir / "prompt.txt").write_text("这是一段 F5 参考音色。", encoding="utf-8")
    (voice_dir / "meta.json").write_text(
        '{"provider":"local_f5_tts","display_label":"F5 清晰中文","target_model":"SWivid/F5-TTS/F5TTS_v1_Base"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(voices_routes, "init_voice_store", lambda: None)
    monkeypatch.setattr(voices_routes, "list_voices", lambda provider=None: [])

    app = FastAPI()
    app.include_router(voices_routes.router)
    response = TestClient(app).get("/voices?provider=local_f5_tts")

    assert response.status_code == 200
    assert {
        "id": -1,
        "user_id": 1,
        "provider": "local_f5_tts",
        "voice_id": "f5-clear-cn",
        "display_label": "F5 清晰中文",
        "target_model": "SWivid/F5-TTS/F5TTS_v1_Base",
        "source": "system",
    } in response.json()["items"]


def test_get_voices_shares_bundled_zero_shot_system_voices_with_local_f5_tts(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", str(tmp_path / "models"))
    monkeypatch.setattr(voices_routes, "init_voice_store", lambda: None)
    monkeypatch.setattr(voices_routes, "list_voices", lambda provider=None: [])

    app = FastAPI()
    app.include_router(voices_routes.router)
    response = TestClient(app).get("/voices?provider=local_f5_tts")

    assert response.status_code == 200
    items = response.json()["items"]
    assert {
        "id": -1,
        "user_id": 1,
        "provider": "local_f5_tts",
        "voice_id": "cosyvoice-official-zero-shot",
        "display_label": "官方示例女声",
        "target_model": "FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
        "source": "system",
    } in items
    assert any(item["voice_id"] == "local-office-serena" for item in items)


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
    item = next(item for item in response.json()["items"] if item["voice_id"] == "local-female-standard")
    assert item == {
        "id": -1,
        "user_id": 1,
        "provider": "local_cosyvoice",
        "voice_id": "local-female-standard",
        "display_label": "标准女声",
        "target_model": None,
        "source": "system",
    }


@pytest.mark.parametrize("provider", ["indextts", "local_indextts", "omnirt_indextts"])
def test_get_voices_includes_indextts_system_voice_dirs(provider: str, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", str(tmp_path / "models"))
    voice_dir = tmp_path / "models" / "voices" / "system" / "indextts-clear-cn"
    voice_dir.mkdir(parents=True)
    (voice_dir / "prompt.wav").write_bytes(b"RIFFtest")
    (voice_dir / "prompt.txt").write_text("这是一段清晰自然的中文参考音色。", encoding="utf-8")
    (voice_dir / "meta.json").write_text(
        '{"display_label":"IndexTTS 清晰中文","target_model":"IndexTeam/IndexTTS-2"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(voices_routes, "init_voice_store", lambda: None)
    monkeypatch.setattr(voices_routes, "list_voices", lambda provider=None: [])

    app = FastAPI()
    app.include_router(voices_routes.router)
    response = TestClient(app).get(f"/voices?provider={provider}")

    assert response.status_code == 200
    assert {
        "id": -1,
        "user_id": 1,
        "provider": "indextts",
        "voice_id": "indextts-clear-cn",
        "display_label": "清晰中文",
        "target_model": "IndexTeam/IndexTTS-2",
        "source": "system",
    } in response.json()["items"]


def test_get_voices_all_includes_single_indextts_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", str(tmp_path / "models"))
    voice_dir = tmp_path / "models" / "voices" / "system" / "indextts-warm-cn"
    voice_dir.mkdir(parents=True)
    (voice_dir / "prompt.wav").write_bytes(b"RIFFtest")
    (voice_dir / "meta.json").write_text('{"display_label":"IndexTTS 温和中文"}', encoding="utf-8")
    monkeypatch.setattr(voices_routes, "init_voice_store", lambda: None)
    monkeypatch.setattr(voices_routes, "list_voices", lambda provider=None: [])

    app = FastAPI()
    app.include_router(voices_routes.router)
    response = TestClient(app).get("/voices")

    providers = [(item["provider"], item["voice_id"]) for item in response.json()["items"]]
    assert providers.count(("indextts", "indextts-warm-cn")) == 1


def test_get_voices_includes_xiaomi_mimo_system_voices(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENTALKING_SQLITE_PATH", str(tmp_path / "voices.sqlite3"))

    app = FastAPI()
    app.include_router(voices_routes.router)

    response = TestClient(app).get("/voices?provider=xiaomi_mimo")

    assert response.status_code == 200
    items = response.json()["items"]
    assert {
        "id": 301,
        "user_id": 1,
        "provider": "xiaomi_mimo",
        "voice_id": "mimo_default",
        "display_label": "MiMo 默认",
        "target_model": "mimo-v2.5-tts",
        "source": "system",
        "profile": "xiaomi_mimo",
    } in items
    assert any(
        item["voice_id"] == "冰糖" and item["display_label"] == "冰糖（中文女声）"
        for item in items
    )
    assert any(
        item["voice_id"] == "Dean" and item["display_label"] == "Dean（English male）"
        for item in items
    )


def test_xiaomi_mimo_clone_stores_reference_audio_data_uri(tmp_path, monkeypatch):
    inserted: dict[str, object] = {}

    monkeypatch.setenv("OPENTALKING_SQLITE_PATH", str(tmp_path / "voices.sqlite3"))
    monkeypatch.setattr(
        voices_routes.bailian_clone,
        "convert_audio_to_wav_24k_mono",
        lambda raw, suffix: _wav_bytes(),
    )

    def fake_insert_clone(**kwargs):
        inserted.update(kwargs)
        return 456

    monkeypatch.setattr(voices_routes, "insert_clone", fake_insert_clone)
    app = FastAPI()
    app.include_router(voices_routes.router)

    response = TestClient(app).post(
        "/voices/clone",
        data={
            "provider": "xiaomi_mimo",
            "target_model": "mimo-v2.5-tts-voiceclone",
            "display_label": "小米复刻",
            "prompt_text": "你好，今天阳光很好，我正在用自然清晰的声音，记录这一段音色。",
        },
        files={"audio": ("sample.wav", _wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "xiaomi_mimo"
    assert body["target_model"] == "mimo-v2.5-tts-voiceclone"
    assert body["display_label"] == "小米复刻"
    assert body["voice_id"].startswith("data:audio/wav;base64,")
    assert inserted == {
        "provider": "xiaomi_mimo",
        "voice_id": body["voice_id"],
        "display_label": "小米复刻",
        "target_model": "mimo-v2.5-tts-voiceclone",
    }


def test_indextts_clone_stores_prompt_locally(tmp_path, monkeypatch):
    inserted: dict[str, object] = {}

    monkeypatch.setenv("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", str(tmp_path / "models"))
    monkeypatch.setattr(
        voices_routes.bailian_clone,
        "convert_audio_to_wav_24k_mono",
        lambda raw, suffix: _wav_bytes(),
    )

    def fake_insert_clone(**kwargs):
        inserted.update(kwargs)
        return 789

    monkeypatch.setattr(voices_routes, "insert_clone", fake_insert_clone)
    app = FastAPI()
    app.include_router(voices_routes.router)

    response = TestClient(app).post(
        "/voices/clone",
        data={
            "provider": "indextts",
            "target_model": "IndexTeam/IndexTTS-2",
            "display_label": "IndexTTS 复刻",
            "prompt_text": "你好，今天阳光很好，我正在用自然清晰的声音，记录这一段音色。",
        },
        files={"audio": ("sample.wav", _wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    voice_id = body["voice_id"]
    voice_dir = tmp_path / "models" / "voices" / "clones" / voice_id
    assert body["provider"] == "indextts"
    assert body["target_model"] == "IndexTeam/IndexTTS-2"
    assert body["display_label"] == "IndexTTS 复刻"
    assert body["entry_id"] == 789
    assert (voice_dir / "prompt.wav").is_file()
    meta = (voice_dir / "meta.json").read_text(encoding="utf-8")
    assert '"provider": "indextts"' in meta
    assert '"providers"' not in meta
    assert '"local_indextts"' not in meta
    assert '"omnirt_indextts"' not in meta
    assert inserted == {
        "provider": "indextts",
        "voice_id": voice_id,
        "display_label": "IndexTTS 复刻",
        "target_model": "IndexTeam/IndexTTS-2",
    }


def test_get_voices_includes_bundled_indextts_system_voices(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", str(tmp_path / "models"))
    monkeypatch.setattr(voices_routes, "init_voice_store", lambda: None)
    monkeypatch.setattr(voices_routes, "list_voices", lambda provider=None: [])

    app = FastAPI()
    app.include_router(voices_routes.router)
    response = TestClient(app).get("/voices?provider=indextts")

    assert response.status_code == 200
    items = response.json()["items"]
    assert any(
        item["provider"] == "indextts"
        and item["voice_id"] == "indextts-xiaoxiao-cn"
        and item["source"] == "system"
        for item in items
    )


@pytest.mark.parametrize("provider", ["indextts", "local_indextts", "omnirt_indextts"])
def test_get_voices_includes_indextts_clone_voice_dirs(provider: str, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENTALKING_LOCAL_AUDIO_MODEL_ROOT", str(tmp_path / "models"))
    voice_dir = tmp_path / "models" / "voices" / "clones" / "indextts-cloned-cn"
    voice_dir.mkdir(parents=True)
    (voice_dir / "prompt.wav").write_bytes(b"RIFFtest")
    (voice_dir / "meta.json").write_text(
        '{"display_label":"IndexTTS 复刻中文","target_model":"IndexTeam/IndexTTS-2","providers":["local_indextts","omnirt_indextts"]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(voices_routes, "init_voice_store", lambda: None)
    monkeypatch.setattr(voices_routes, "list_voices", lambda provider=None: [])

    app = FastAPI()
    app.include_router(voices_routes.router)
    response = TestClient(app).get(f"/voices?provider={provider}")

    assert response.status_code == 200
    item = next(item for item in response.json()["items"] if item["voice_id"] == "indextts-cloned-cn")
    assert item == {
        "id": item["id"],
        "user_id": 1,
        "provider": "indextts",
        "voice_id": "indextts-cloned-cn",
        "display_label": "复刻中文",
        "target_model": "IndexTeam/IndexTTS-2",
        "source": "clone",
    }
