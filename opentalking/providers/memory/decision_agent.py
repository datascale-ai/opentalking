from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from opentalking.providers.memory.schemas import MemoryItem, utc_now_iso

_NOISE_RE = re.compile(r"^[\s\W_]+$", re.UNICODE)
_USER_OWNED_RECALL_RE = re.compile(
    r"(我的|我现在|我之前|我上次|我刚才).*(是什么|是啥|叫啥|哪个|哪些|什么|多少|目标|项目|偏好|习惯|名字)"
)
_USER_NAME_RECALL_RE = re.compile(
    r"(我\s*(叫|是)\s*(什么|啥|谁)|我的\s*(名字|称呼)\s*(是)?\s*(什么|啥|多少|哪个))"
)
_FACT_ENTITY_RE = re.compile(
    r"(\b\d{1,3}(?:\.\d{1,3}){3}\b|[\w.-]+\.[A-Za-z]{2,}|"
    r"(?<![A-Za-z0-9_])\d{2,4}\s*服务器|\b\w+[-_/]\w+\b)",
    re.IGNORECASE,
)
_HIGH_RISK_RE = re.compile(
    r"(部署|上线|迁移|删除|清空|重置|覆盖|回滚|发布|合并|"
    r"\bpush\b|\bmerge\b|\brm\s+-rf\b|\bdrop\s+table\b)",
    re.IGNORECASE,
)
_PREFERENCE_MARKERS = (
    "i like",
    "i love",
    "i prefer",
    "my favorite",
    "remember",
    "call me",
    "my name is",
    "from now on",
    "next time",
    "don't forget",
    "我是",
    "我叫",
    "我喜欢",
    "我不喜欢",
    "我偏好",
    "我的习惯",
    "我的名字",
    "记住",
    "记一下",
    "以后叫我",
    "下次",
    "之后",
    "以后",
)
_EXPLICIT_RECALL_MARKERS = (
    "remember",
    "what did i",
    "last time",
    "previous",
    "continue",
    "as before",
    "my preference",
    "my favorite",
    "上次",
    "之前",
    "以前",
    "刚才",
    "继续",
    "还记得",
    "记得",
    "按我的",
    "我的偏好",
    "我的习惯",
    "我喜欢",
    "我不喜欢",
    "怎么称呼",
)
_LOW_VALUE_INPUTS = {
    "hi",
    "hello",
    "hey",
    "你好",
    "您好",
    "开始",
    "停一下",
    "继续",
    "换一个",
}


@dataclass(frozen=True)
class RecallDecision:
    should_recall: bool
    query: str = ""
    reason: str = ""


class MemoryDecisionAgent:
    """Rule-based first-stage memory extraction.

    This intentionally avoids Mem0 infer/LLM features. It stores compact user
    facts/preferences and skips empty, interrupted, or assistant-only turns.
    """

    def decide_recall(self, user_text: str) -> RecallDecision:
        text = (user_text or "").strip()
        if not text:
            return RecallDecision(False, reason="empty")
        if text.lower() in _LOW_VALUE_INPUTS:
            return RecallDecision(False, reason="low_value")
        lower = text.lower()

        if _USER_OWNED_RECALL_RE.search(text) or _USER_NAME_RECALL_RE.search(text):
            return RecallDecision(True, query=text, reason="user_owned")
        if _HIGH_RISK_RE.search(text) and _FACT_ENTITY_RE.search(text):
            return RecallDecision(False, reason="high_risk_ignored")
        if _FACT_ENTITY_RE.search(text):
            return RecallDecision(True, query=text, reason="fact_entity")
        if any(marker in lower for marker in _EXPLICIT_RECALL_MARKERS):
            return RecallDecision(True, query=text, reason="explicit_recall")
        return RecallDecision(False, reason="no_marker")

    def decide_import(
        self,
        turns: Sequence[dict[str, str]],
        *,
        source: str | None = None,
    ) -> list[MemoryItem]:
        items: list[MemoryItem] = []
        for turn in turns:
            role = (turn.get("role") or "").strip().lower()
            content = (turn.get("content") or "").strip()
            if role != "user" or not self._should_store_import(content):
                continue
            kind = self._classify(content)
            metadata = {"role": role}
            if source:
                metadata["source"] = source
            items.append(
                MemoryItem(
                    id="",
                    text=content,
                    type=kind,  # type: ignore[arg-type]
                    metadata=metadata,
                    created_at=utc_now_iso(),
                )
            )
        return items

    def decide_conversation_write(
        self,
        *,
        user_text: str,
        assistant_text: str,
        interrupted: bool,
    ) -> list[MemoryItem]:
        if interrupted or not assistant_text.strip():
            return []
        text = user_text.strip()
        if not self._should_store_realtime(text):
            return []
        kind = self._classify(text)
        return [
            MemoryItem(
                id="",
                text=text,
                type=kind,
                metadata={"role": "user", "source": "session"},
                created_at=utc_now_iso(),
            )
        ]

    def _base_valid(self, text: str) -> bool:
        stripped = text.strip()
        if len(stripped) < 4 or _NOISE_RE.match(stripped):
            return False
        if len(stripped) > 1200:
            return False
        return True

    def _should_store_import(self, text: str) -> bool:
        stripped = text.strip()
        if not self._base_valid(stripped):
            return False
        return self._looks_like_preference(stripped) or len(stripped) >= 8

    def _should_store_realtime(self, text: str) -> bool:
        stripped = text.strip()
        if not self._base_valid(stripped):
            return False
        return self._looks_like_preference(stripped)

    def _classify(self, text: str):
        if self._looks_like_preference(text):
            return "preference"
        return "fact"

    def _looks_like_preference(self, text: str) -> bool:
        lower = text.lower()
        return any(marker in lower for marker in _PREFERENCE_MARKERS)
