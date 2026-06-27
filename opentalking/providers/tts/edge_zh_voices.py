"""Edge TTS voice ID 校验。

Edge TTS 实际有几百个 ShortName（多语言 / 多地区 / 多角色），写死白名单会把
非中文用户挡在外面。这里改为**格式校验**：只防注入，不限语言。

`EDGE_ZH_VOICES` 仍然导出，保留前端 UI 下拉列表的"精选 zh-CN 选项"语义。
任何符合 ShortName 形态的字符串（含 zh-HK / en-US / ja-JP 等）都允许通过 API。
"""

from __future__ import annotations

import re

# 前端 UI 下拉框使用的精选 zh-CN voice 列表（仅用于推荐，不再充当 API 白名单）。
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

# Edge TTS ShortName 格式，例如 zh-CN-XiaoxiaoNeural / en-US-AriaNeural /
# zh-HK-HiuMaanNeural / ja-JP-NanamiNeural / *-MultilingualNeural。
# 只允许字母 + 连字符，限定 Neural 结尾，足以防注入。
_EDGE_VOICE_PATTERN = re.compile(r"^[a-z]{2,3}-[A-Za-z]{2,4}-[A-Za-z0-9]+Neural$")
_MAX_VOICE_LEN = 100


def normalize_optional_edge_voice(raw: str | None) -> str | None:
    """返回合法 ShortName；未传或空字符串返回 None。

    校验：仅做形态匹配（防注入），不再限定具体语言。
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if len(s) > _MAX_VOICE_LEN:
        raise ValueError(f"Edge TTS voice id too long: {s[:60]}…")
    if not _EDGE_VOICE_PATTERN.match(s):
        raise ValueError(
            f"invalid Edge TTS voice id: {s!r} "
            f"(expected ShortName like 'zh-CN-XiaoxiaoNeural' or 'en-US-AriaNeural')"
        )
    return s
