from __future__ import annotations

from types import SimpleNamespace

from opentalking.tts.factory import build_tts_adapter


def _settings(**overrides):
    defaults = {
        "normalized_tts_provider": "edge",
        "tts_voice": "zh-CN-XiaoxiaoNeural",
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
