"""允许的 Edge zh-CN Neural 音色（与 `edge-tts --list-voices` 一致，按需扩展）。"""

from __future__ import annotations

# 前端与 API 共用：仅允许这些 ShortName，防止注入任意字符串。
EDGE_ZH_VOICES: frozenset[str] = frozenset(
    {
        "zh-CN-XiaoxiaoNeural",
        "zh-CN-XiaoyiNeural",
        "zh-CN-YunxiNeural",
        "zh-CN-YunjianNeural",
        "zh-CN-YunyangNeural",
        "zh-CN-YunxiaNeural",
    }
)


def normalize_optional_edge_voice(raw: str | None) -> str | None:
    """返回合法 ShortName；未传返回 None（由工厂使用环境变量默认）。"""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s not in EDGE_ZH_VOICES:
        raise ValueError(f"unsupported Edge TTS voice: {s}")
    return s
