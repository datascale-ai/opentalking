from __future__ import annotations

import pytest

from opentalking.agent.context_builder import AgentSessionConfig, build_agent_context
from opentalking.agent.knowledge_store import KnowledgeStore
from opentalking.agent.memory_store import AgentMemoryStore, extract_explicit_memory
from opentalking.agent.prompt import inject_agent_context


def test_inject_agent_context_after_system_prompt() -> None:
    messages = [
        {"role": "system", "content": "base prompt"},
        {"role": "user", "content": "hello"},
    ]

    injected = inject_agent_context(messages, "agent context")

    assert injected == [
        {"role": "system", "content": "base prompt"},
        {"role": "system", "content": "agent context"},
        {"role": "user", "content": "hello"},
    ]


def test_extract_explicit_memory_from_user_text() -> None:
    assert extract_explicit_memory("请记住：我喜欢简短直接的回答。") == "我喜欢简短直接的回答"
    assert extract_explicit_memory("remember this: I prefer short replies") == "I prefer short replies"
    assert extract_explicit_memory("普通问题，不需要保存") is None


@pytest.mark.asyncio
async def test_memory_store_round_trip_builds_agent_context(tmp_path) -> None:
    store = AgentMemoryStore(tmp_path / "agent_memory.sqlite")
    turn = await store.save_turn(
        user_id="client_test",
        avatar_id="anchor",
        session_id="sess_one",
        user_text="请记住：我喜欢简短直接的回答。",
        assistant_text="好的，我会记住。",
    )

    memory = await store.save_explicit_memory_from_turn(
        user_id="client_test",
        avatar_id="anchor",
        source_turn_id=turn.id,
        user_text="请记住：我喜欢简短直接的回答。",
    )
    assert memory is not None
    assert memory.content == "我喜欢简短直接的回答"

    context = await build_agent_context(
        config=AgentSessionConfig(
            user_id="client_test",
            agent_enabled=True,
            memory_enabled=True,
        ),
        avatar_id="anchor",
        store=store,
    )

    assert context is not None
    assert "<long_term_memory>" in context
    assert "我喜欢简短直接的回答" in context


@pytest.mark.asyncio
async def test_knowledge_store_round_trip_builds_agent_context(tmp_path) -> None:
    source = tmp_path / "OpenTalking 知识.md"
    source.write_text(
        "OpenTalking 支持知识库上传。\n\n每个默认会话都会检索 default 知识库。",
        encoding="utf-8",
    )
    store = KnowledgeStore(
        db_path=tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
    )

    document = await store.add_document(
        kb_id="default",
        filename=source.name,
        mime_type="text/markdown",
        source_path=source,
    )

    assert document.status == "ready"
    assert document.chunk_count >= 1

    context = await build_agent_context(
        config=AgentSessionConfig(
            agent_enabled=True,
            knowledge_enabled=True,
            knowledge_base_id="default",
        ),
        avatar_id="anchor",
        query="默认会话会检索哪个知识库？",
        knowledge_store=store,
    )

    assert context is not None
    assert "<knowledge_base>" in context
    assert "OpenTalking 支持知识库上传" in context


@pytest.mark.asyncio
async def test_knowledge_store_reindexes_pdf_with_ocr_fallback(tmp_path, monkeypatch) -> None:
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"%PDF-1.7\n% fake scanned pdf")

    monkeypatch.setattr(
        "opentalking.agent.knowledge_store._extract_text",
        lambda path: ("", "document has no extractable text"),
    )
    store = KnowledgeStore(
        db_path=tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
    )
    document = await store.add_document(
        kb_id="default",
        filename=source.name,
        mime_type="application/pdf",
        source_path=source,
    )
    assert document.status == "error"
    assert document.chunk_count == 0

    monkeypatch.setattr(
        "opentalking.agent.knowledge_store._extract_text",
        lambda path: ("扫描件 OCR 文本：OpenTalking 知识库可以重新索引。", None),
    )
    reindexed = await store.reindex_document(kb_id="default", doc_id=document.id)
    chunks = await store.query(kb_id="default", query="重新索引知识库", limit=3)

    assert reindexed.status == "ready"
    assert reindexed.chunk_count == 1
    assert chunks
    assert "OpenTalking 知识库可以重新索引" in chunks[0].text
