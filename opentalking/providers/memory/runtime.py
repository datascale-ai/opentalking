from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from opentalking.core.config import Settings, get_settings
from opentalking.providers.memory.base import MemoryProvider
from opentalking.providers.memory.bm25 import memories_to_prompt, rank_items_bm25
from opentalking.providers.memory.decision_agent import (
    MemoryDecisionAgent,
    MemoryLLMRecallJudge,
    MemoryWriteDecision,
    RecallDecision,
    canonical_relation_correction_memory,
    needs_recent_context_for_smart_write,
    should_include_assistant_context_for_smart_write,
)
from opentalking.providers.memory.factory import build_memory_provider
from opentalking.providers.memory.schemas import MemoryItem

log = logging.getLogger(__name__)


def _settings_choice(settings: Settings, field: str, default: str, allowed: set[str]) -> str:
    value = str(getattr(settings, field, default) or default).strip().lower()
    return value if value in allowed else default


def _memory_recall_backend(settings: Settings) -> str:
    return _settings_choice(settings, "memory_recall_backend", "hybrid", {"bm25", "mem0", "hybrid"})


def _memory_write_mode(settings: Settings) -> str:
    return _settings_choice(settings, "memory_write_mode", "hybrid", {"raw", "mem0", "hybrid"})


def _memory_decision_mode(settings: Settings) -> str:
    return _settings_choice(settings, "memory_decision_mode", "rule", {"rule", "hybrid", "llm"})


def _memory_decision_timeout_ms(settings: Settings) -> int:
    return max(1, int(getattr(settings, "memory_decision_timeout_ms", 800) or 800))


def _memory_smart_write_enabled(settings: Settings) -> bool:
    return bool(getattr(settings, "memory_smart_write_enabled", True))


def _memory_summary_enabled(settings: Settings) -> bool:
    return bool(getattr(settings, "memory_summary_enabled", False))


def _memory_summary_turn_window(settings: Settings) -> int:
    return max(1, int(getattr(settings, "memory_summary_turn_window", 8) or 8))


def _memory_summary_max_items(settings: Settings) -> int:
    return max(1, int(getattr(settings, "memory_summary_max_items", 3) or 3))


@dataclass(frozen=True)
class MemoryScope:
    enabled: bool
    profile_id: str
    character_id: str
    library_id: str


def normalize_memory_scope(
    *,
    settings: Settings | None = None,
    memory_enabled: bool | str | None = None,
    profile_id: str | None = None,
    character_id: str | None = None,
    avatar_id: str | None = None,
    library_id: str | None = None,
) -> MemoryScope:
    cfg = settings or get_settings()
    enabled = cfg.memory_enabled
    if isinstance(memory_enabled, bool):
        enabled = memory_enabled
    elif isinstance(memory_enabled, str) and memory_enabled.strip():
        enabled = memory_enabled.strip().lower() in {"1", "true", "yes", "on"}
    return MemoryScope(
        enabled=bool(enabled),
        profile_id=(profile_id or cfg.memory_default_profile_id or "default").strip() or "default",
        character_id=(character_id or avatar_id or "").strip(),
        library_id=(library_id or cfg.memory_default_library_id or "default").strip() or "default",
    )


class MemorySummaryAgent:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def summarize(self, turns: list[dict[str, str]], *, max_items: int) -> str:
        if not turns:
            return ""
        if self.settings.llm_base_url:
            try:
                summary = await self._summarize_with_llm(turns, max_items=max_items)
            except Exception:  # noqa: BLE001
                log.warning("memory summary LLM call failed; using local fallback", exc_info=True)
            else:
                if summary.strip():
                    return summary.strip()
        return self._fallback_summary(turns, max_items=max_items)

    async def _summarize_with_llm(self, turns: list[dict[str, str]], *, max_items: int) -> str:
        from opentalking.providers.llm.openai_compatible.adapter import OpenAICompatibleLLMClient

        client = OpenAICompatibleLLMClient(
            base_url=self.settings.llm_base_url,
            api_key=self.settings.llm_api_key,
            model=self.settings.llm_model,
        )
        transcript = "\n".join(
            f"{turn.get('role', '').strip()}: {turn.get('content', '').strip()}"
            for turn in turns
            if turn.get("content", "").strip()
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You summarize digital-human chat history into durable user memories. "
                    "Return concise Chinese bullet-style facts only. Focus on user preferences, "
                    "important people/entities, confirmed decisions or plans, goals and progress, "
                    "and feedback or corrections about the interaction style."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Extract at most {max_items} durable memories from this conversation. "
                    "Ignore greetings, transient wording, one-off requests, and assistant-only facts.\n\n"
                    f"{transcript}"
                ),
            },
        ]
        chunks: list[str] = []
        async for chunk in client.chat_stream(messages):
            chunks.append(chunk)
        return "".join(chunks).strip()

    def _fallback_summary(self, turns: list[dict[str, str]], *, max_items: int) -> str:
        snippets: list[str] = []
        for turn in turns:
            if turn.get("role") != "user":
                continue
            content = turn.get("content", "").strip()
            if not content:
                continue
            snippets.append(content)
            if len(snippets) >= max_items:
                break
        return "；".join(snippets)


class MemoryRuntime:
    def __init__(
        self,
        *,
        scope: MemoryScope,
        provider: MemoryProvider | None = None,
        decision_agent: MemoryDecisionAgent | None = None,
        settings: Settings | None = None,
        summary_agent: Any | None = None,
        decision_judge: Any | None = None,
    ) -> None:
        self.scope = scope
        self.provider = provider or build_memory_provider()
        self.decision_agent = decision_agent or MemoryDecisionAgent()
        self.settings = settings or get_settings()
        self.summary_agent = summary_agent or MemorySummaryAgent(self.settings)
        self.decision_judge = decision_judge or MemoryLLMRecallJudge(self.settings)
        self._write_tasks: set[asyncio.Task[None]] = set()
        self._summary_turn_buffer: list[dict[str, str]] = []
        self._recent_turn_buffer: list[dict[str, str]] = []

    @property
    def enabled(self) -> bool:
        return bool(self.scope.enabled and self.scope.character_id)

    async def retrieve_prompt(self, query: str) -> str:
        if not self.enabled:
            return ""
        decision = await self._decide_recall(query)
        log.info(
            "memory.recall decision should=%s reason=%s categories=%s",
            decision.should_recall,
            decision.reason,
            ",".join(decision.categories),
        )
        if not decision.should_recall:
            return ""
        recall_query = decision.query or query
        backend = _memory_recall_backend(self.settings)
        if backend in {"mem0", "hybrid"}:
            searched = await self._search_items(recall_query)
            if searched:
                log.info("memory.recall injected count=%d backend=mem0", len(searched))
                return memories_to_prompt(searched)
            if backend == "mem0":
                return ""
        return await self._retrieve_bm25_prompt(recall_query)

    async def _decide_recall(self, query: str) -> RecallDecision:
        rule_decision = self.decision_agent.decide_recall(query)
        mode = _memory_decision_mode(self.settings)
        if mode == "rule":
            return rule_decision
        if rule_decision.reason in {"empty", "low_value", "high_risk_ignored"}:
            return rule_decision
        if mode == "hybrid" and rule_decision.reason != "no_marker":
            return rule_decision
        judged = await self._judge_recall(query)
        return judged if judged is not None else rule_decision

    async def _judge_recall(self, query: str) -> RecallDecision | None:
        decide_recall = getattr(self.decision_judge, "decide_recall", None)
        if not callable(decide_recall):
            return None
        try:
            decision = await asyncio.wait_for(
                decide_recall(query),
                timeout=_memory_decision_timeout_ms(self.settings) / 1000.0,
            )
        except TimeoutError:
            log.warning("memory decision judge timed out")
            return None
        except Exception:  # noqa: BLE001
            log.warning("memory decision judge failed", exc_info=True)
            return None
        if not isinstance(decision, RecallDecision):
            return None
        if decision.should_recall and not decision.query.strip():
            return RecallDecision(
                True,
                query=query,
                reason=decision.reason or "llm_decision",
                categories=decision.categories,
            )
        return decision

    async def _search_items(self, query: str) -> list[MemoryItem] | None:
        search_items = getattr(self.provider, "search_items", None)
        if not callable(search_items):
            return None
        try:
            return await asyncio.wait_for(
                search_items(
                    query=query,
                    library_id=self.scope.library_id,
                    profile_id=self.scope.profile_id,
                    character_id=self.scope.character_id,
                    limit=max(0, int(self.settings.memory_recall_limit)),
                ),
                timeout=max(0.001, float(self.settings.memory_recall_timeout_ms) / 1000.0),
            )
        except TimeoutError:
            log.warning("memory search timed out")
            return None
        except Exception:  # noqa: BLE001
            log.warning("memory search failed", exc_info=True)
            return None

    async def _retrieve_bm25_prompt(self, query: str) -> str:
        try:
            candidates = await asyncio.wait_for(
                self.provider.list_items(
                    library_id=self.scope.library_id,
                    profile_id=self.scope.profile_id,
                    character_id=self.scope.character_id,
                ),
                timeout=max(0.001, float(self.settings.memory_recall_timeout_ms) / 1000.0),
            )
        except TimeoutError:
            log.warning("memory retrieval timed out")
            return ""
        except Exception:  # noqa: BLE001
            log.warning("memory retrieval failed", exc_info=True)
            return ""
        ranked = rank_items_bm25(
            query,
            candidates,
            limit=max(0, int(self.settings.memory_recall_limit)),
            min_score=float(self.settings.memory_recall_min_score),
        )
        log.info("memory.recall injected count=%d backend=bm25", len(ranked))
        return memories_to_prompt(ranked)

    def schedule_write(
        self,
        *,
        user_text: str,
        assistant_text: str,
        interrupted: bool,
    ) -> None:
        if not self.enabled:
            return
        decision = self.decision_agent.decide_conversation_write_decision(
            user_text=user_text,
            assistant_text=assistant_text,
            interrupted=interrupted,
        )
        log.info(
            "memory.write decision action=%s category=%s confidence=%s reason=%s",
            decision.action,
            decision.category,
            decision.confidence,
            decision.reason,
        )
        summary_buffered = False
        if _memory_summary_enabled(self.settings) and self._should_buffer_summary(decision):
            summary_buffered = self._buffer_summary_turn(
                user_text=user_text,
                assistant_text=assistant_text,
                interrupted=interrupted,
            )
        if decision.action == "reject":
            self._remember_recent_turn(
                user_text=user_text,
                assistant_text=assistant_text,
                interrupted=interrupted,
            )
            return
        if _memory_summary_enabled(self.settings) and not summary_buffered:
            self._buffer_summary_turn(
                user_text=user_text,
                assistant_text=assistant_text,
                interrupted=interrupted,
            )
        if decision.action == "summary_only":
            self._remember_recent_turn(
                user_text=user_text,
                assistant_text=assistant_text,
                interrupted=interrupted,
            )
            return
        if decision.action == "direct_write":
            if decision.items:
                task = asyncio.create_task(self._write_items(decision.items))
                self._track_task(task)
            self._remember_recent_turn(
                user_text=user_text,
                assistant_text=assistant_text,
                interrupted=interrupted,
            )
            return
        if not decision.items:
            self._remember_recent_turn(
                user_text=user_text,
                assistant_text=assistant_text,
                interrupted=interrupted,
            )
            return

        context_turns = self._smart_write_context(user_text=user_text)
        task = asyncio.create_task(
            self._write_conversation_turn(
                user_text=user_text,
                assistant_text=assistant_text,
                decision=decision,
                context_turns=context_turns,
            )
        )
        self._track_task(task)
        self._remember_recent_turn(
            user_text=user_text,
            assistant_text=assistant_text,
            interrupted=interrupted,
        )

    async def import_turns(
        self,
        turns: list[dict[str, str]],
        *,
        source: str | None = None,
    ) -> int:
        if not self.enabled:
            return 0
        items = self.decision_agent.decide_import(turns, source=source)
        if not items:
            return 0
        return await self.provider.add_items(
            library_id=self.scope.library_id,
            profile_id=self.scope.profile_id,
            character_id=self.scope.character_id,
            items=items,
        )

    def _track_task(self, task: asyncio.Task[None]) -> None:
        self._write_tasks.add(task)
        task.add_done_callback(self._write_tasks.discard)

    def _should_buffer_summary(self, decision: MemoryWriteDecision) -> bool:
        return decision.reason not in {
            "interrupted_or_empty_assistant",
            "invalid",
            "low_value",
            "sensitive",
            "memory_check_question",
            "recall_question",
        }

    def _buffer_summary_turn(
        self,
        *,
        user_text: str,
        assistant_text: str,
        interrupted: bool,
    ) -> bool:
        user = user_text.strip()
        assistant = assistant_text.strip()
        if interrupted or not user or not assistant:
            return False
        self._summary_turn_buffer.extend(
            [
                {"role": "user", "content": user},
                {"role": "assistant", "content": assistant},
            ]
        )
        turn_count = sum(1 for turn in self._summary_turn_buffer if turn.get("role") == "user")
        log.info(
            "memory.summary buffered turns=%d window=%d",
            turn_count,
            _memory_summary_turn_window(self.settings),
        )
        if turn_count < _memory_summary_turn_window(self.settings):
            return True
        turns = list(self._summary_turn_buffer)
        self._summary_turn_buffer.clear()
        task = asyncio.create_task(self._write_summary(turns=turns, turn_count=turn_count))
        self._track_task(task)
        return True

    def _remember_recent_turn(
        self,
        *,
        user_text: str,
        assistant_text: str,
        interrupted: bool,
    ) -> None:
        user = user_text.strip()
        assistant = assistant_text.strip()
        if interrupted or not user or not assistant:
            return
        self._recent_turn_buffer.extend(
            [
                {"role": "user", "content": user},
                {"role": "assistant", "content": assistant},
            ]
        )
        max_turns = max(2, _memory_summary_turn_window(self.settings) * 2)
        if len(self._recent_turn_buffer) > max_turns:
            self._recent_turn_buffer = self._recent_turn_buffer[-max_turns:]

    def _smart_write_context(self, *, user_text: str) -> list[dict[str, str]]:
        if not needs_recent_context_for_smart_write(user_text):
            return []
        return list(self._recent_turn_buffer)

    async def _write_conversation_turn(
        self,
        *,
        user_text: str,
        assistant_text: str,
        decision: MemoryWriteDecision,
        context_turns: list[dict[str, str]],
    ) -> None:
        write_mode = _memory_write_mode(self.settings)
        should_try_smart = _memory_smart_write_enabled(self.settings) and write_mode in {
            "mem0",
            "hybrid",
        }
        allow_raw_fallback = decision.confidence != "medium"
        canonical_item = canonical_relation_correction_memory(
            current_text=user_text,
            context_turns=context_turns,
        )
        if should_try_smart:
            add_conversation_turns = getattr(self.provider, "add_conversation_turns", None)
            if callable(add_conversation_turns):
                try:
                    turns = [
                        *context_turns,
                        {"role": "user", "content": user_text.strip()},
                    ]
                    include_assistant_context = should_include_assistant_context_for_smart_write(user_text)
                    if include_assistant_context:
                        turns.append({"role": "assistant", "content": assistant_text.strip()})
                    stored = await add_conversation_turns(
                        library_id=self.scope.library_id,
                        profile_id=self.scope.profile_id,
                        character_id=self.scope.character_id,
                        turns=turns,
                        include_assistant_context=include_assistant_context,
                        metadata={
                            "category": decision.category,
                            "confidence": decision.confidence,
                            "decision_reason": decision.reason,
                            "write_action": decision.action,
                        },
                    )
                    log.info(
                        "memory.write stored count=%s provider=mem0 category=%s confidence=%s",
                        stored,
                        decision.category,
                        decision.confidence,
                    )
                    if canonical_item is not None:
                        await self._write_items([canonical_item])
                        return
                    if stored > 0:
                        return
                    if decision.category == "mem0_candidate":
                        return
                    if write_mode != "hybrid" or not allow_raw_fallback:
                        return
                except Exception:  # noqa: BLE001
                    log.warning("memory smart write failed", exc_info=True)
                    if decision.category == "mem0_candidate":
                        return
                    if write_mode != "hybrid" or not allow_raw_fallback:
                        return
            elif write_mode != "hybrid":
                return
        await self._write_items([canonical_item] if canonical_item is not None else decision.items)

    async def _write_items(self, items: list[MemoryItem]) -> None:
        try:
            stored = await self.provider.add_items(
                library_id=self.scope.library_id,
                profile_id=self.scope.profile_id,
                character_id=self.scope.character_id,
                items=items,
            )
            log.info("memory.write stored count=%s provider=raw", stored)
        except Exception:  # noqa: BLE001
            log.warning("memory write failed", exc_info=True)

    async def _write_summary(self, *, turns: list[dict[str, str]], turn_count: int) -> None:
        try:
            summary = await self.summary_agent.summarize(
                turns,
                max_items=_memory_summary_max_items(self.settings),
            )
            if not summary.strip():
                return
            metadata = {
                "source_type": "session_summary",
                "layer": "episodic",
                "category": "episode_summary",
                "turn_count": turn_count,
            }
            add_summary = getattr(self.provider, "add_summary", None)
            if callable(add_summary):
                stored = await add_summary(
                    library_id=self.scope.library_id,
                    profile_id=self.scope.profile_id,
                    character_id=self.scope.character_id,
                    summary=summary,
                    metadata=metadata,
                )
                log.info("memory.summary stored count=%s", stored)
                return
            stored = await self.provider.add_items(
                library_id=self.scope.library_id,
                profile_id=self.scope.profile_id,
                character_id=self.scope.character_id,
                items=[
                    MemoryItem(
                        id="",
                        text=summary,
                        type="summary",
                        metadata=metadata,
                    )
                ],
            )
            log.info("memory.summary stored count=%s", stored)
        except Exception:  # noqa: BLE001
            log.warning("memory summary write failed", exc_info=True)

    async def drain(self) -> None:
        tasks = [task for task in self._write_tasks if not task.done()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def build_memory_runtime(
    *,
    memory_enabled: bool | str | None,
    profile_id: str | None,
    character_id: str | None,
    avatar_id: str | None,
    library_id: str | None,
    settings: Settings | None = None,
) -> MemoryRuntime:
    scope = normalize_memory_scope(
        settings=settings,
        memory_enabled=memory_enabled,
        profile_id=profile_id,
        character_id=character_id,
        avatar_id=avatar_id,
        library_id=library_id,
    )
    return MemoryRuntime(scope=scope, settings=settings)
