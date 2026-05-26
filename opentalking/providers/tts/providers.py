from __future__ import annotations

CORE_TTS_PROVIDERS = frozenset({"auto", "edge", "elevenlabs"})
QWEN_TTS_PROVIDERS = frozenset({"dashscope", "bailian", "qwen", "qwen_tts"})
COSYVOICE_TTS_PROVIDERS = frozenset({"cosyvoice", "cosyvoice_http"})
SAMBERT_TTS_PROVIDERS = frozenset({"sambert", "dashscope_sambert"})
LOCAL_TTS_PROVIDERS = frozenset({"local_cosyvoice", "local_qwen3_tts"})
BAILIAN_TTS_PROVIDERS = (
    QWEN_TTS_PROVIDERS
    | COSYVOICE_TTS_PROVIDERS
    | SAMBERT_TTS_PROVIDERS
)
SUPPORTED_TTS_PROVIDERS = CORE_TTS_PROVIDERS | BAILIAN_TTS_PROVIDERS | LOCAL_TTS_PROVIDERS


def normalize_tts_provider(value: str | None, *, default: str | None = None) -> str | None:
    provider = (value or "").strip().lower()
    if not provider:
        return default
    if provider not in SUPPORTED_TTS_PROVIDERS:
        raise ValueError(f"unsupported tts provider: {value}")
    return provider
