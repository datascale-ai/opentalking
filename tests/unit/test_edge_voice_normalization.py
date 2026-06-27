"""Edge TTS voice id 校验：格式校验，不再硬白名单。"""
from __future__ import annotations

import pytest

from opentalking.providers.tts.edge_zh_voices import normalize_optional_edge_voice


def test_none_returns_none():
    assert normalize_optional_edge_voice(None) is None
    assert normalize_optional_edge_voice("") is None
    assert normalize_optional_edge_voice("   ") is None


def test_curated_zh_cn_voices_pass():
    for v in [
        "zh-CN-XiaoxiaoNeural",
        "zh-CN-XiaoyiNeural",
        "zh-CN-YunxiNeural",
        "zh-CN-YunjianNeural",
        "zh-CN-YunyangNeural",
        "zh-CN-YunxiaNeural",
    ]:
        assert normalize_optional_edge_voice(v) == v


def test_other_locales_pass():
    """Non-zh-CN voices must work too — that's the whole point of dropping the whitelist."""
    for v in [
        "zh-HK-HiuMaanNeural",
        "zh-TW-HsiaoChenNeural",
        "en-US-AriaNeural",
        "en-GB-RyanNeural",
        "ja-JP-NanamiNeural",
        "ko-KR-SunHiNeural",
        "fr-FR-DeniseNeural",
    ]:
        assert normalize_optional_edge_voice(v) == v


def test_garbage_rejected():
    for bad in ["random; rm -rf /", "<script>", "no-region", "zh-CN-Xiaoxiao"]:  # last one missing Neural suffix
        with pytest.raises(ValueError):
            normalize_optional_edge_voice(bad)


def test_overlong_rejected():
    with pytest.raises(ValueError):
        normalize_optional_edge_voice("zh-CN-" + ("X" * 200) + "Neural")
