from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from opentalking.core.config import Settings, get_settings
from opentalking.providers.memory.base import MemoryProvider
from opentalking.providers.memory.bm25 import memories_to_prompt, rank_items_bm25
from opentalking.providers.memory.decision_agent import MemoryDecisionAgent
from opentalking.providers.memory.factory import build_memory_provider
from opentalking.providers.memory.schemas import MemoryItem

log = logging.getLogger(__name__)


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


class MemoryRuntime:
    def __init__(
        self,
        *,
        scope: MemoryScope,
        provider: MemoryProvider | None = None,
        decision_agent: MemoryDecisionAgent | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.scope = scope
        self.provider = provider or build_memory_provider()
        self.decision_agent = decision_agent or MemoryDecisionAgent()
        self.settings = settings or get_settings()
        self._write_tasks: set[asyncio.Task[None]] = set()

    @property
    def enabled(self) -> bool:
        return bool(self.scope.enabled and self.scope.character_id)

    async def retrieve_prompt(self, query: str) -> str:
        if not self.enabled:
            return ""
        decision = self.decision_agent.decide_recall(query)
        if not decision.should_recall:
            return ""
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
            decision.query or query,
            candidates,
            limit=max(0, int(self.settings.memory_recall_limit)),
            min_score=float(self.settings.memory_recall_min_score),
        )
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
        items = self.decision_agent.decide_conversation_write(
            user_text=user_text,
            assistant_text=assistant_text,
            interrupted=interrupted,
        )
        if not items:
            return
        task = asyncio.create_task(self._write_items(items))
        self._write_tasks.add(task)
        task.add_done_callback(self._write_tasks.discard)

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

    async def _write_items(self, items: list[MemoryItem]) -> None:
        try:
            await self.provider.add_items(
                library_id=self.scope.library_id,
                profile_id=self.scope.profile_id,
                character_id=self.scope.character_id,
                items=items,
            )
        except Exception:  # noqa: BLE001
            log.warning("memory write failed", exc_info=True)

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
