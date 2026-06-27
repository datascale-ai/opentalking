"""TTS opener rules + pure helpers for selecting an opener phrase.

Extracted from synthesis_runner.py. Stateless — no async or runner coupling.
The rules drive the "speak before LLM finishes" UX trick: while the LLM is
still composing, we play a short canned phrase whose intent matches the user
input keywords.
"""
from __future__ import annotations

import re

# Opener rules — improvement backlog (not implemented here):
# - Taxonomy: only greeting/task/explain/confirm; no thanks/apology/small-talk,
#   English, typos, or multi-intent utterances.
# - Keywords: hard-coded substrings; no segmentation, negation, or weighting.
# - Text: fixed short lines; not per-avatar / locale / brand / configurable via env.
# - Selection: keyword first match + PCM length + recent-id rotation; no LLM-based
#   intent, confidence, or A/B testing.
TTS_OPENER_RULES: tuple[tuple[str, tuple[str, ...], tuple[tuple[str, str], ...]], ...] = (
    (
        "greeting",
        ("你好", "您好", "哈喽", "嗨", "在吗", "早安", "晚安", "喂"),
        (
            ("greeting_1", "我在，请讲。"),
            ("greeting_2", "听到啦，你说。"),
            ("greeting_3", "随时在。"),
        ),
    ),
    (
        "task",
        ("帮我", "处理", "看下", "看看", "怎么弄", "怎么办", "查一下", "帮忙", "执行", "设置", "找一下"),
        (
            ("task_1", "好的，我来看看。"),
            ("task_2", "明白，马上处理。"),
            ("task_3", "收到，这就去办。"),
        ),
    ),
    (
        "explain",
        ("为什么", "怎么", "是什么", "原理", "区别", "原因", "介绍", "详细", "意思"),
        (
            ("explain_1", "这个我来解释。"),
            ("explain_2", "好，我给你说明。"),
            ("explain_3", "马上为你解答。"),
        ),
    ),
    (
        "confirm",
        ("能不能", "可以吗", "是否", "有没有", "行不行", "对不对", "对吗", "真的"),
        (
            ("confirm_1", "可以，我告诉你。"),
            ("confirm_2", "这个我来确认。"),
            ("confirm_3", "稍等，我核实下。"),
        ),
    ),
    (
        "create",
        ("写一个", "写一篇", "生成", "画", "起名", "设计", "草拟", "大纲"),
        (
            ("create_1", "好的，这就生成。"),
            ("create_2", "收到，我来构思。"),
        ),
    ),
    (
        "calculate",
        ("算一下", "多少", "统计", "计算", "汇总"),
        (
            ("calc_1", "我来算一下。"),
            ("calc_2", "好，这就看数据。"),
        ),
    ),
    (
        "opinion",
        ("觉得", "看法", "建议", "推荐", "评价", "哪个好"),
        (
            ("opinion_1", "我的看法是这样。"),
            ("opinion_2", "好，给你几个建议。"),
        ),
    ),
    (
        "identity",
        ("你叫什么名字", "你的名字", "你是谁", "怎么称呼", "你叫啥"),
        (
            ("identity_1", "嗯，很高兴认识你。"),
        ),
    ),
)

TTS_OPENER_FALLBACKS: tuple[tuple[str, str], ...] = (
    ("fallback_1", "明白，马上处理。"),
    ("fallback_2", "好的，我来看看。"),
    ("fallback_3", "马上为你解答。"),
    ("fallback_4", "收到，请稍等。"),
)


def join_tts_fragments(left: str, right: str) -> str:
    left = left.strip()
    right = right.strip()
    if not left:
        return right
    if not right:
        return left
    if left[-1].isascii() and left[-1].isalnum() and right[0].isascii() and right[0].isalnum():
        return f"{left} {right}"
    return f"{left}{right}"


def speech_char_count(text: str) -> int:
    return sum(1 for ch in text if not ch.isspace())


def normalize_tts_lookup_text(text: str) -> str:
    return "".join(ch.lower() for ch in text.strip() if not ch.isspace())


def contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def iter_tts_opener_variants() -> list[tuple[str, str]]:
    variants: list[tuple[str, str]] = []
    seen: set[str] = set()
    for _, _, choices in TTS_OPENER_RULES:
        for opener_id, opener_text in choices:
            if opener_id in seen:
                continue
            variants.append((opener_id, opener_text))
            seen.add(opener_id)
    for opener_id, opener_text in TTS_OPENER_FALLBACKS:
        if opener_id in seen:
            continue
        variants.append((opener_id, opener_text))
        seen.add(opener_id)
    return variants


def build_tts_opener_candidates(user_text: str) -> list[tuple[str, str]]:
    normalized = normalize_tts_lookup_text(user_text)
    for _, keywords, choices in TTS_OPENER_RULES:
        if contains_any(normalized, keywords):
            return list(choices) + list(TTS_OPENER_FALLBACKS)
    return list(TTS_OPENER_FALLBACKS)


def strip_redundant_greeting_lead(text: str) -> str:
    """Remove one leading greeting clause (after TTS opener already greeted)."""
    t = text.strip()
    if not t:
        return t
    for pat in (
        r"^你好啊[，,\s]*",
        r"^你好[，,\s]*",
        r"^您好[，,\s]*",
        r"^哈喽[，,\s]*",
        r"^嗨[，,\s]*",
    ):
        nt = re.sub(pat, "", t, count=1)
        if nt != t:
            return nt.strip()
    return t


def merge_spoken_reply(prefix: str, body: str) -> str:
    prefix = prefix.strip()
    body = body.strip()
    if not prefix:
        return body
    if not body:
        return prefix
    if body.startswith(prefix):
        return body
    return join_tts_fragments(prefix, body)
