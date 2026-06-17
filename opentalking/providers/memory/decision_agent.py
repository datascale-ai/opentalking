from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

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
_SENSITIVE_RE = re.compile(
    r"(\bapi[_ -]?key\b|\btoken\b|\bsecret\b|\bpassword\b|密码|口令|私钥|密钥|sk-[A-Za-z0-9_-]{6,})",
    re.IGNORECASE,
)
_FEEDBACK_CORRECTION_RE = re.compile(
    r"(不是.+是|不对|纠正|更正|你刚才太|你刚刚太|别总|不要总|这个称呼我不喜欢|我不是.+)"
)
_MEMORY_CHECK_QUESTION_RE = re.compile(
    r"((你|还|你还).{0,8}(记得|记住).{0,40}(吗|么|\?|？)|"
    r"(记住|记得).{0,20}(了吗|了么|吗|么|\?|？))"
)
_RECALL_WRITE_QUESTION_RE = re.compile(
    r"((按|照|根据).{0,12}(我|我的|之前|以前|上次|刚才).{0,24}"
    r"(方式|风格|偏好|习惯|回答|说法|计划|目标).{0,40}"
    r"(解释|回答|说|讲|怎么|如何|吗|么|\?|？)|"
    r"(我的|我现在|我之前|我上次|我刚才).{0,30}"
    r"(是什么|是啥|叫啥|哪个|哪些|什么|多少|目标|项目|偏好|习惯|名字))"
)
_ASSISTANT_CONTEXT_CONFIRMATION_RE = re.compile(
    r"((好|可以|行|嗯|没问题|同意|接受|就这样).{0,20}"
    r"(以后|之后|下次|就按|按|这样|这么|方式|方案|计划|练|记住)|"
    r"(以后|之后|下次).{0,12}(就按|按).{0,20}"
    r"(你刚才|刚才|这个|这个方式|这个方案|这个计划))"
)
_ENTITY_RELATION_RE = re.compile(
    r"(我(女朋友|男朋友|老婆|老公|前女友|前男友|朋友|同事|妈妈|爸爸|母亲|父亲|老师|孩子|儿子|女儿).{0,12}叫|"
    r"我家(猫|狗|宠物).{0,12}叫|我在.{1,12}(工作|上学|生活)|我最近在(学|准备|练).{1,20})"
)
_RELATION_WORDS = (
    "女朋友",
    "男朋友",
    "老婆",
    "老公",
    "前女友",
    "前男友",
    "朋友",
    "同事",
    "妈妈",
    "爸爸",
    "母亲",
    "父亲",
    "老师",
    "孩子",
    "儿子",
    "女儿",
)
_RELATION_DECLARATION_RE = re.compile(
    rf"我(?P<relation>{'|'.join(_RELATION_WORDS)}).{{0,12}}叫(?P<name>[\u4e00-\u9fffA-Za-z0-9_-]{{1,20}})"
)
_RELATION_CORRECTION_RE = re.compile(
    rf"不是(?P<old>{'|'.join(_RELATION_WORDS)}).{{0,8}}是(?P<new>{'|'.join(_RELATION_WORDS)})"
)
_GOAL_PROGRESS_RE = re.compile(
    r"(完成|背完|跑完|做完|练完|学完|达成|结束了|面试结束|今天.*(背|跑|练|学|复习).*(了|完))"
)
_GOAL_INTENT_RE = re.compile(
    r"(我(在|正在|最近在|这段时间在)?(.{0,10})(准备|备考|学习|复习|练习|练).{0,30}"
    r"(雅思|托福|考试|英语|日语|口语|面试|健身|跑步|背单词)|"
    r"(准备|备考).{0,20}(雅思|托福|考试|英语|日语|口语|面试))"
)
_DECISION_PLAN_RE = re.compile(
    r"((那就|就按|决定|计划|以后|之后|下次|每天|每晚|提醒我|开始).{0,40}"
    r"(提醒|复盘|背|学|练|计划|方式|这样|这么|做|开始)|以后.*(提醒|叫|按|这样|这种))"
)
_MEDIUM_MEMORY_RE = re.compile(
    r"(最近|这段时间|可能|想|打算|准备|希望).{0,40}(学习|英语|日语|健身|运动|睡|焦虑|压力|状态|聊天|陪练)"
)
_SUMMARY_VALUE_RE = re.compile(r"(累|难过|压力|焦虑|随便聊|陪我|今天|最近|感觉|心情|状态|想聊|聊天)")
_COMFORT_CONTEXT_RE = re.compile(r"(压力|难过|焦虑|失眠|累|崩溃|安慰|陪我|陪.*聊|心情)")
_GOAL_CONTEXT_RE = re.compile(r"(背单词|学习|复习|考试|雅思|英语|日语|健身|跑步|提醒我|目标|计划|进度)")
_PREFERENCE_CONTEXT_RE = re.compile(r"(适合我的|我适合|推荐.*(衣服|穿搭|商品|礼物)|预算|尺码|风格|喜欢|不喜欢)")
_NAMED_ENTITY_QUESTION_RE = re.compile(
    r"^[\s\"'“”‘’]*([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9_-]{1,20})"
    r"(是谁|是谁呀|是谁啊|是什么人|跟我什么关系|和我什么关系)[？?]?$"
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
    "更喜欢",
    "希望你",
    "别叫我",
    "别总",
    "不要总",
    "温柔",
    "简洁",
    "说教",
    "官方",
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
    categories: tuple[str, ...] = ()


@dataclass(frozen=True)
class MemoryWriteDecision:
    action: str
    category: str = ""
    confidence: str = ""
    reason: str = ""
    items: list[MemoryItem] = field(default_factory=list)


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
            return RecallDecision(
                True,
                query=text,
                reason="user_owned",
                categories=("user_preference", "entity_relation", "goal_progress", "decision_plan"),
            )
        if _HIGH_RISK_RE.search(text) and _FACT_ENTITY_RE.search(text):
            return RecallDecision(False, reason="high_risk_ignored")
        if _COMFORT_CONTEXT_RE.search(text):
            return RecallDecision(
                True,
                query=text,
                reason="comfort_context",
                categories=("user_preference", "feedback_correction", "entity_relation"),
            )
        if _GOAL_CONTEXT_RE.search(text):
            return RecallDecision(
                True,
                query=text,
                reason="goal_context",
                categories=("goal_progress", "decision_plan", "user_preference"),
            )
        if _PREFERENCE_CONTEXT_RE.search(text):
            return RecallDecision(
                True,
                query=text,
                reason="preference_context",
                categories=("user_preference", "feedback_correction", "decision_plan"),
            )
        if _FACT_ENTITY_RE.search(text):
            return RecallDecision(True, query=text, reason="fact_entity", categories=("entity_relation", "note"))
        if any(marker in lower for marker in _EXPLICIT_RECALL_MARKERS):
            return RecallDecision(
                True,
                query=text,
                reason="explicit_recall",
                categories=(
                    "user_preference",
                    "decision_plan",
                    "goal_progress",
                    "entity_relation",
                    "feedback_correction",
                    "episode_summary",
                ),
            )
        if _NAMED_ENTITY_QUESTION_RE.search(text):
            return RecallDecision(
                True,
                query=text,
                reason="named_entity_question",
                categories=("entity_relation", "feedback_correction", "episode_summary"),
            )
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
            category, confidence, reason = self._classify_write_candidate(content, import_mode=True)
            kind = self._classify(content, category=category)
            metadata = {"role": role}
            if source:
                metadata["source"] = source
            metadata.update(
                {
                    "category": category,
                    "confidence": confidence,
                    "decision_reason": reason,
                    "source_type": "import",
                }
            )
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

    def decide_conversation_write_decision(
        self,
        *,
        user_text: str,
        assistant_text: str,
        interrupted: bool,
    ) -> MemoryWriteDecision:
        if interrupted or not assistant_text.strip():
            return MemoryWriteDecision("reject", reason="interrupted_or_empty_assistant")
        text = user_text.strip()
        if text.lower() in _LOW_VALUE_INPUTS:
            return MemoryWriteDecision("reject", reason="low_value")
        if not self._base_valid(text):
            return MemoryWriteDecision("reject", reason="invalid")
        if _SENSITIVE_RE.search(text):
            return MemoryWriteDecision("reject", reason="sensitive")
        if _MEMORY_CHECK_QUESTION_RE.search(text):
            return MemoryWriteDecision("reject", reason="memory_check_question")
        if _NAMED_ENTITY_QUESTION_RE.search(text) or _RECALL_WRITE_QUESTION_RE.search(text):
            return MemoryWriteDecision("reject", reason="recall_question")

        item = MemoryItem(
            id="",
            text=text,
            type="chat_turn",
            metadata={
                "role": "user",
                "source": "session",
                "source_type": "realtime_turn",
                "category": "mem0_candidate",
                "confidence": "unknown",
                "write_action": "mem0_infer",
                "decision_reason": "needs_smart_judgement",
            },
            created_at=utc_now_iso(),
        )
        return MemoryWriteDecision(
            "mem0_infer",
            category="mem0_candidate",
            confidence="unknown",
            reason="needs_smart_judgement",
            items=[item],
        )

    def decide_conversation_write(
        self,
        *,
        user_text: str,
        assistant_text: str,
        interrupted: bool,
    ) -> list[MemoryItem]:
        return self.decide_conversation_write_decision(
            user_text=user_text,
            assistant_text=assistant_text,
            interrupted=interrupted,
        ).items

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

    def _classify(self, text: str, *, category: str | None = None):
        if category == "user_preference" or self._looks_like_preference(text):
            return "preference"
        return "fact"

    def _looks_like_preference(self, text: str) -> bool:
        lower = text.lower()
        return any(marker in lower for marker in _PREFERENCE_MARKERS)

    def _classify_write_candidate(self, text: str, *, import_mode: bool) -> tuple[str, str, str]:
        stripped = text.strip()
        if _FEEDBACK_CORRECTION_RE.search(stripped):
            return "feedback_correction", "high", "feedback_correction"
        if _ENTITY_RELATION_RE.search(stripped):
            return "entity_relation", "high", "entity_relation"
        if _GOAL_PROGRESS_RE.search(stripped):
            return "goal_progress", "high", "goal_progress"
        if _GOAL_INTENT_RE.search(stripped):
            return "goal_progress", "high", "goal_context"
        if _DECISION_PLAN_RE.search(stripped):
            return "decision_plan", "high", "decision_plan"
        if self._looks_like_preference(stripped):
            return "user_preference", "high", "preference_marker"
        if _MEDIUM_MEMORY_RE.search(stripped):
            return "goal_progress", "medium", "medium_durable_context"
        if _SUMMARY_VALUE_RE.search(stripped):
            return "episode_summary", "low", "summary_context"
        if import_mode and len(stripped) >= 8:
            return "entity_relation", "medium", "import_context"
        return "reject", "", "no_marker"


def canonical_relation_correction_memory(
    *,
    current_text: str,
    context_turns: Sequence[dict[str, str]],
) -> MemoryItem | None:
    correction = _RELATION_CORRECTION_RE.search(current_text.strip())
    if not correction:
        return None
    old_relation = correction.group("old")
    new_relation = correction.group("new")
    for turn in reversed(list(context_turns)):
        if (turn.get("role") or "").strip().lower() != "user":
            continue
        declaration = _RELATION_DECLARATION_RE.search((turn.get("content") or "").strip())
        if not declaration:
            continue
        if declaration.group("relation") != old_relation:
            continue
        name = declaration.group("name").strip("，。！？,.!? ")
        if not name:
            continue
        return MemoryItem(
            id="",
            text=f"{name}是用户的{new_relation}。",
            type="fact",
            metadata={
                "role": "user",
                "source": "session",
                "source_type": "realtime_turn",
                "category": "entity_relation",
                "confidence": "high",
                "write_action": "direct_write",
                "decision_reason": "relation_correction_context",
            },
            created_at=utc_now_iso(),
        )
    return None


def needs_recent_context_for_smart_write(user_text: str) -> bool:
    text = (user_text or "").strip()
    return bool(
        _FEEDBACK_CORRECTION_RE.search(text)
        or _ASSISTANT_CONTEXT_CONFIRMATION_RE.search(text)
    )


def should_include_assistant_context_for_smart_write(user_text: str) -> bool:
    return bool(_ASSISTANT_CONTEXT_CONFIRMATION_RE.search((user_text or "").strip()))


def _extract_json_object(text: str) -> dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        loaded = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


class MemoryLLMRecallJudge:
    """Second-stage recall judge for ambiguous inputs.

    The rule-based agent remains the first gate. This judge is only invoked by
    MemoryRuntime when configuration allows it and the rule result is ambiguous.
    """

    def __init__(self, settings: Any) -> None:
        self.settings = settings

    async def decide_recall(self, user_text: str) -> RecallDecision:
        if not getattr(self.settings, "llm_base_url", ""):
            return RecallDecision(False, reason="llm_unavailable")

        from opentalking.providers.llm.openai_compatible.adapter import OpenAICompatibleLLMClient

        client = OpenAICompatibleLLMClient(
            base_url=self.settings.llm_base_url,
            api_key=self.settings.llm_api_key,
            model=self.settings.llm_model,
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You decide whether a user message needs long-term memory recall. "
                    "Return JSON only with keys: should_recall, query, reason, categories. "
                    "Recall only for references to the user's identity, preferences, "
                    "past decisions, goals, important people/entities, prior context, "
                    "stable facts, or interaction feedback. "
                    "Treat unresolved style/preference references as recall-worthy, "
                    "for example: 那套风格, 那个方式, 按之前那样, usual style, same way. "
                    "For digital-human conversations, recall when comfort, learning, coaching, "
                    "shopping, or role-interaction replies need user preferences, goals, "
                    "relationships, plans, or feedback corrections. "
                    "Do not recall for general knowledge requests, greetings, or one-off commands."
                ),
            },
            {
                "role": "user",
                "content": user_text.strip(),
            },
        ]
        chunks: list[str] = []
        async for chunk in client.chat_stream(messages):
            chunks.append(chunk)
        parsed = _extract_json_object("".join(chunks).strip())
        should_recall = bool(parsed.get("should_recall"))
        query = str(parsed.get("query") or user_text).strip()
        reason = str(parsed.get("reason") or "llm_decision").strip()
        raw_categories = parsed.get("categories") or ()
        if isinstance(raw_categories, str):
            categories = (raw_categories,)
        elif isinstance(raw_categories, list):
            categories = tuple(str(item) for item in raw_categories if str(item).strip())
        else:
            categories = ()
        return RecallDecision(should_recall, query=query, reason=reason, categories=categories)
