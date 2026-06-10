from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from opentalking.agent.knowledge_store import KnowledgeStore
from opentalking.agent.memory_store import AgentMemoryStore
from opentalking.agent.prompt import build_agent_context_prompt


@dataclass(frozen=True)
class AgentSessionConfig:
    user_id: str | None = None
    agent_enabled: bool = False
    memory_enabled: bool = False
    knowledge_enabled: bool = False
    knowledge_base_id: str | None = None
    knowledge_base_ids: list[str] | None = None

    @property
    def has_memory(self) -> bool:
        return bool(self.agent_enabled and self.memory_enabled and self.user_id)

    @property
    def has_knowledge(self) -> bool:
        return bool(
            self.agent_enabled
            and self.knowledge_enabled
            and self.selected_knowledge_base_ids
        )

    @property
    def selected_knowledge_base_ids(self) -> list[str]:
        selected: list[str] = []
        seen: set[str] = set()
        candidates = (
            self.knowledge_base_ids
            if self.knowledge_base_ids
            else [self.knowledge_base_id]
        )
        for candidate in candidates:
            kb_id = str(candidate or "").strip()
            if not kb_id or kb_id in seen:
                continue
            selected.append(kb_id)
            seen.add(kb_id)
        return selected


def default_memory_store() -> AgentMemoryStore:
    from opentalking.core.config import get_settings

    settings = get_settings()
    return AgentMemoryStore(Path(settings.agent_memory_sqlite_path))


def default_knowledge_store() -> KnowledgeStore:
    from opentalking.core.config import get_settings

    settings = get_settings()
    return KnowledgeStore(
        db_path=Path(settings.agent_memory_sqlite_path),
        knowledge_root=Path(settings.agent_knowledge_root),
        use_chunk_fallback=bool(settings.agent_lightrag_chunk_fallback_enabled),
    )


async def build_agent_context(
    *,
    config: AgentSessionConfig,
    avatar_id: str,
    query: str = "",
    store: AgentMemoryStore | None = None,
    knowledge_store: KnowledgeStore | None = None,
) -> str | None:
    memories = []
    if config.has_memory:
        memory_store = store or default_memory_store()
        memories = await memory_store.list_memories(
            user_id=str(config.user_id),
            avatar_id=avatar_id,
            limit=8,
        )
    knowledge_chunks = []
    if config.has_knowledge and query.strip():
        kb_store = knowledge_store or default_knowledge_store()
        chunks = await kb_store.query_many(
            kb_ids=config.selected_knowledge_base_ids,
            query=query,
            limit=3,
        )
        knowledge_chunks = [
            f"source: {chunk.filename}\n{chunk.text}"
            for chunk in chunks
            if chunk.text.strip()
        ]
    return build_agent_context_prompt(memories=memories, knowledge_chunks=knowledge_chunks)
