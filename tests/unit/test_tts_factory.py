from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from opentalking.tts.factory import build_tts_adapter


def _settings(**overrides):
    defaults = {
        "normalized_tts_provider": "edge",
        "tts_voice": "zh-CN-XiaoxiaoNeural",
        "tts_language": "zh-cn",
        "tts_clone_reference_audio": "",
        "tts_clone_model_name": "tts_models/multilingual/multi-dataset/xtts_v2",
        "tts_clone_device": "auto",
        "tts_clone_cache_dir": "./temp/tts_cache",
        "tts_cosyvoice_mode": "zero_shot",
        "tts_cosyvoice_model_dir": "./models/cosyvoice",
        "tts_cosyvoice_repo_dir": "./third_party/CosyVoice",
        "tts_cosyvoice_prompt_source": "asr",
        "tts_cosyvoice_prompt_prefix": "You are a helpful assistant.<|endofprompt|>",
        "tts_cosyvoice_prompt_text": "You are a helpful assistant.<|endofprompt|>",
        "tts_cosyvoice_prompt_max_seconds": 14.0,
        "tts_cosyvoice_speed": 1.0,
        "tts_asr_model_path": "./models/Whisper-large-v3/large-v3.pt",
        "tts_asr_language": "zh",
        "ffmpeg_bin": "ffmpeg",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_build_tts_adapter_uses_edge_provider():
    adapter = build_tts_adapter(
        sample_rate=16000,
        chunk_ms=20.0,
        settings=_settings(normalized_tts_provider="edge"),
    )
    assert adapter.__class__.__name__ == "EdgeTTSAdapter"


def test_build_tts_adapter_auto_falls_back_without_reference():
    adapter = build_tts_adapter(
        sample_rate=16000,
        chunk_ms=20.0,
        settings=_settings(normalized_tts_provider="auto"),
    )
    assert adapter.__class__.__name__ == "EdgeTTSAdapter"


def test_build_tts_adapter_auto_uses_xtts(monkeypatch, tmp_path: Path):
    ref_audio = tmp_path / "voice.wav"
    ref_audio.write_bytes(b"fake")

    captured: dict[str, object] = {}

    class DummyXTTSAdapter:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("opentalking.tts.factory.xtts_runtime_available", lambda: (True, None))
    monkeypatch.setattr("opentalking.tts.factory.CoquiXTTSAdapter", DummyXTTSAdapter)

    adapter = build_tts_adapter(
        sample_rate=24000,
        chunk_ms=40.0,
        settings=_settings(
            normalized_tts_provider="auto",
            tts_clone_reference_audio=str(ref_audio),
            tts_clone_cache_dir=str(tmp_path / "cache"),
        ),
    )

    assert adapter.__class__.__name__ == "DummyXTTSAdapter"
    assert captured["reference_audio"] == ref_audio
    assert captured["sample_rate"] == 24000
    assert captured["chunk_ms"] == 40.0


def test_build_tts_adapter_uses_cosyvoice(monkeypatch, tmp_path: Path):
    ref_audio = tmp_path / "voice.wav"
    ref_audio.write_bytes(b"fake")
    repo_dir = tmp_path / "CosyVoice"
    repo_dir.mkdir()
    model_dir = tmp_path / "models"
    model_dir.mkdir()

    captured: dict[str, object] = {}

    class DummyCosyVoiceAdapter:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("opentalking.tts.factory.cosyvoice_runtime_available", lambda _: (True, None))
    monkeypatch.setattr("opentalking.tts.factory.CosyVoiceAdapter", DummyCosyVoiceAdapter)

    adapter = build_tts_adapter(
        sample_rate=16000,
        chunk_ms=30.0,
        settings=_settings(
            normalized_tts_provider="cosyvoice",
            tts_clone_reference_audio=str(ref_audio),
            tts_clone_cache_dir=str(tmp_path / "cache"),
            tts_cosyvoice_repo_dir=str(repo_dir),
            tts_cosyvoice_model_dir=str(model_dir),
            tts_cosyvoice_prompt_text="You are a helpful assistant.<|endofprompt|>",
            tts_cosyvoice_prompt_max_seconds=20.0,
            tts_cosyvoice_speed=1.0,
        ),
    )

    assert adapter.__class__.__name__ == "DummyCosyVoiceAdapter"
    assert captured["reference_audio"] == ref_audio
    assert captured["repo_dir"] == repo_dir
    assert captured["model_dir"] == model_dir
    assert captured["mode"] == "zero_shot"
    assert captured["prompt_source"] == "asr"
