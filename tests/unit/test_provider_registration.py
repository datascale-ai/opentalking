"""Verify provider sub-packages register themselves on import."""
from __future__ import annotations

from opentalking.core.registry import list_keys, resolve
from opentalking.providers import bootstrap


def test_bootstrap_registers_all_capability_keys() -> None:
    bootstrap()
    assert {"edge", "dashscope_qwen", "dashscope_sambert", "cosyvoice_ws", "elevenlabs"} <= set(
        list_keys("tts")
    )
    assert "openai_compatible" in list_keys("llm")
    assert {"flashtalk", "musetalk", "wav2lip", "quicktalk", "flashhead"} <= set(list_keys("synthesis"))


def test_resolve_returns_class() -> None:
    bootstrap()
    cls = resolve("tts", "edge")
    assert cls.__name__ == "EdgeTTSAdapter"

    syn = resolve("synthesis", "musetalk")
    # All audio2video models behind OmniRT speak the FlashTalk-compatible WS protocol.
    assert syn.__name__ == "FlashTalkWSClient"

    quicktalk = resolve("synthesis", "quicktalk")
    assert quicktalk.__name__ == "FlashTalkWSClient"
