"""百炼 Qwen 实时 TTS：音色名校验。完整列表以[阿里云百炼控制台](https://bailian.console.aliyun.com)文档为准。"""

from __future__ import annotations

QWEN_VOICE_ALIASES = {
    "kiki": "Kiki",
    "kiki（粤语女声）": "Kiki",
    "kiki(粤语女声)": "Kiki",
    "rocky": "Rocky",
    "rocky（粤语男声）": "Rocky",
    "rocky(粤语男声)": "Rocky",
}

QWEN_CANTONESE_VOICES = frozenset({"Kiki", "Rocky"})


def normalize_optional_qwen_voice(raw: str | None) -> str | None:
    """校验百炼系 TTS 的 voice 参数（CosyVoice 等含空格、括号亦可）。"""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if len(s) > 160:
        raise ValueError("TTS voice string too long")
    for c in s:
        if ord(c) < 32:
            raise ValueError(f"unsupported control character in TTS voice: {s!r}")
    return QWEN_VOICE_ALIASES.get(s.lower(), s)


def sanitize_qwen_model(raw: str | None) -> str | None:
    """合成模型 ID 校验（允许字母数字与 ``-_. /`` 等控制台常见字符）。"""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if len(s) > 128:
        raise ValueError("TTS model id too long")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_./")
    if not all(c in allowed for c in s):
        raise ValueError(f"invalid TTS model id: {s!r}")
    return s
