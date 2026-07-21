from __future__ import annotations

import zipfile

import pytest

from opentalking.agent import knowledge_store as knowledge_store_module
from opentalking.agent.context_builder import AgentSessionConfig, build_agent_context
from opentalking.agent.knowledge_index import LightRAGSearchResult, LightRAGStatus
from opentalking.agent.knowledge_store import KnowledgeStore
from opentalking.agent.memory_store import AgentMemoryStore, extract_explicit_memory
from opentalking.agent.prompt import build_agent_context_prompt, inject_agent_context


def test_knowledge_store_unsupported_file_message_lists_all_supported_formats(tmp_path) -> None:
    source = tmp_path / "sheet.csv"
    source.write_text("question,answer\nhello,world\n", encoding="utf-8")
    store = KnowledgeStore(
        db_path=tmp_path / "knowledge.sqlite3",
        knowledge_root=tmp_path / "knowledge",
        knowledge_index=FakeKnowledgeIndex(),
    )

    with pytest.raises(ValueError, match=r"\.txt, \.md, \.markdown, \.pdf and \.pptx"):
        store._add_file_sync(  # noqa: SLF001
            filename=source.name,
            mime_type="text/csv",
            source_path=source,
        )


def test_knowledge_store_extracts_pptx_text(tmp_path) -> None:
    pptx = tmp_path / "slides.pptx"
    with zipfile.ZipFile(pptx, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">
  <Default Extension=\"xml\" ContentType=\"application/xml\"/>
  <Override PartName=\"/ppt/presentation.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml\"/>
  <Override PartName=\"/ppt/slides/slide1.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.presentationml.slide+xml\"/>
</Types>
""",
        )
        zf.writestr(
            "ppt/presentation.xml",
            """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<p:presentation xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\">
  <p:sldIdLst><p:sldId id=\"256\" r:id=\"rId1\" xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\"/></p:sldIdLst>
</p:presentation>
""",
        )
        zf.writestr(
            "ppt/slides/slide1.xml",
            """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<p:sld xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\">
  <p:cSld>
    <p:spTree>
      <p:sp>
        <p:txBody>
          <a:p xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\">
            <a:r><a:t>知识库支持 PPTX</a:t></a:r>
          </a:p>
        </p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
</p:sld>
""",
        )

    text, error = knowledge_store_module._extract_text(pptx)

    assert error is None
    assert "知识库支持 PPTX" in text


class FakeKnowledgeIndex:
    def __init__(self) -> None:
        self.indexed: list[dict[str, str]] = []
        self.deleted: list[tuple[str, str]] = []

    def index_document(
        self,
        *,
        kb_id: str,
        doc_id: str,
        filename: str,
        text: str,
    ) -> None:
        self.indexed.append(
            {
                "kb_id": kb_id,
                "doc_id": doc_id,
                "filename": filename,
                "text": text,
            }
        )

    def delete_document(self, *, kb_id: str, doc_id: str) -> None:
        self.deleted.append((kb_id, doc_id))
        self.indexed = [
            item
            for item in self.indexed
            if not (item["kb_id"] == kb_id and item["doc_id"] == doc_id)
        ]

    def clear_knowledge_base(self, kb_id: str) -> None:
        self.indexed = [item for item in self.indexed if item["kb_id"] != kb_id]

    def query(self, *, kb_id: str, query: str, limit: int) -> list[LightRAGSearchResult]:
        return [
            LightRAGSearchResult(
                doc_id=item["doc_id"],
                text=item["text"],
                score=1.0,
            )
            for item in self.indexed
            if item["kb_id"] == kb_id
        ][:limit]

    def status(self, *, kb_id: str) -> LightRAGStatus:
        return LightRAGStatus(
            available=True,
            indexed=any(item["kb_id"] == kb_id for item in self.indexed),
            reason="",
        )


class EmptyKnowledgeIndex(FakeKnowledgeIndex):
    def query(self, *, kb_id: str, query: str, limit: int) -> list[LightRAGSearchResult]:
        return []


class FirstKnowledgeBaseMissesIndex(FakeKnowledgeIndex):
    def __init__(self, missed_kb_id: str) -> None:
        super().__init__()
        self.missed_kb_id = missed_kb_id

    def query(self, *, kb_id: str, query: str, limit: int) -> list[LightRAGSearchResult]:
        if kb_id == self.missed_kb_id:
            return []
        return super().query(kb_id=kb_id, query=query, limit=limit)


class QueryTrackingKnowledgeStore:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def query_many(self, *, kb_ids: list[str], query: str, limit: int = 3):  # type: ignore[no-untyped-def]
        self.calls.append({"kb_ids": kb_ids, "query": query, "limit": limit})
        return []


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


def test_agent_context_tells_model_to_use_retrieved_knowledge() -> None:
    context = build_agent_context_prompt(
        memories=[],
        knowledge_chunks=["source: mixed.md\n先检查基础层，部署里就是 WSL2、镜像和依赖。"],
    )

    assert context is not None
    assert "如果知识库片段和用户问题直接相关，必须优先依据知识库片段回答" in context


def test_agent_context_stays_empty_when_nothing_is_retrieved() -> None:
    assert build_agent_context_prompt(memories=[], knowledge_chunks=[]) is None


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
        knowledge_index=FakeKnowledgeIndex(),
    )
    knowledge_base = await store.create_knowledge_base(name="对话知识库")

    document = await store.add_document(
        kb_id=knowledge_base.id,
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
            knowledge_base_id=knowledge_base.id,
        ),
        avatar_id="anchor",
        query="默认会话会检索哪个知识库？",
        knowledge_store=store,
    )

    assert context is not None
    assert "<knowledge_base>" in context
    assert "OpenTalking 支持知识库上传" in context


@pytest.mark.asyncio
async def test_knowledge_store_builds_agent_context_across_multiple_kbs(tmp_path) -> None:
    store = KnowledgeStore(
        db_path=tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
        knowledge_index=FakeKnowledgeIndex(),
    )
    first = await store.create_knowledge_base(name="产品知识库")
    second = await store.create_knowledge_base(name="售后知识库")

    first_doc = tmp_path / "first.md"
    first_doc.write_text("产品知识库：OpenTalking 支持多知识库检索。", encoding="utf-8")
    second_doc = tmp_path / "second.md"
    second_doc.write_text("售后知识库：退货和退款政策。", encoding="utf-8")

    await store.add_document(
        kb_id=first.id,
        filename=first_doc.name,
        mime_type="text/markdown",
        source_path=first_doc,
    )
    await store.add_document(
        kb_id=second.id,
        filename=second_doc.name,
        mime_type="text/markdown",
        source_path=second_doc,
    )

    context = await build_agent_context(
        config=AgentSessionConfig(
            agent_enabled=True,
            knowledge_enabled=True,
            knowledge_base_ids=[first.id, second.id],
        ),
        avatar_id="anchor",
        query="支持什么检索和退款？",
        knowledge_store=store,
    )

    assert context is not None
    assert "OpenTalking 支持多知识库检索" in context
    assert "退货和退款政策" in context


@pytest.mark.asyncio
async def test_agent_context_does_not_query_knowledge_when_no_base_is_selected() -> None:
    store = QueryTrackingKnowledgeStore()

    context = await build_agent_context(
        config=AgentSessionConfig(
            agent_enabled=True,
            knowledge_enabled=True,
            knowledge_base_ids=[],
        ),
        avatar_id="anchor",
        query="取消勾选后还会查旧知识库吗？",
        knowledge_store=store,  # type: ignore[arg-type]
    )

    assert context is None
    assert store.calls == []


@pytest.mark.asyncio
async def test_multi_kb_query_uses_lightrag_before_any_chunk_fallback(tmp_path) -> None:
    store = KnowledgeStore(
        db_path=tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
    )
    first = await store.create_knowledge_base(name="部署知识库")
    second = await store.create_knowledge_base(name="产品知识库")
    store._knowledge_index = FirstKnowledgeBaseMissesIndex(first.id)

    first_doc = tmp_path / "deploy.md"
    first_doc.write_text(
        "如果用户说“我部署卡住了，训练也卡住了”，健身教练可以回答：先检查基础层。",
        encoding="utf-8",
    )
    second_doc = tmp_path / "product.md"
    second_doc.write_text("LightRAG 命中的产品资料。", encoding="utf-8")

    await store.add_document(
        kb_id=first.id,
        filename=first_doc.name,
        mime_type="text/markdown",
        source_path=first_doc,
    )
    await store.add_document(
        kb_id=second.id,
        filename=second_doc.name,
        mime_type="text/markdown",
        source_path=second_doc,
    )

    chunks = await store.query_many(
        kb_ids=[first.id, second.id],
        query="我部署卡住了，训练也卡住了",
        limit=3,
    )

    assert chunks
    assert [chunk.kb_id for chunk in chunks] == [second.id]
    assert "LightRAG 命中的产品资料" in chunks[0].text
    assert "先检查基础层" not in chunks[0].text


@pytest.mark.asyncio
async def test_knowledge_store_falls_back_to_chunks_when_lightrag_misses(tmp_path) -> None:
    source = tmp_path / "mixed-deploy.md"
    source.write_text(
        "如果用户说“我部署卡住了，训练也卡住了”，健身教练可以回答：\n"
        "先检查基础层，训练里就是动作质量和恢复，部署里就是 WSL2、镜像和依赖。",
        encoding="utf-8",
    )
    store = KnowledgeStore(
        db_path=tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
        knowledge_index=EmptyKnowledgeIndex(),
        use_chunk_fallback=True,
    )
    knowledge_base = await store.create_knowledge_base(name="混合部署知识库")
    await store.add_document(
        kb_id=knowledge_base.id,
        filename=source.name,
        mime_type="text/markdown",
        source_path=source,
    )

    context = await build_agent_context(
        config=AgentSessionConfig(
            agent_enabled=True,
            knowledge_enabled=True,
            knowledge_base_id=knowledge_base.id,
        ),
        avatar_id="fitness-coach",
        query="我部署卡住了，训练也卡住了",
        knowledge_store=store,
    )

    assert context is not None
    assert "先检查基础层" in context
    assert "WSL2、镜像和依赖" in context


@pytest.mark.asyncio
async def test_knowledge_store_does_not_use_chunk_fallback_by_default_when_lightrag_misses(tmp_path) -> None:
    source = tmp_path / "mixed-deploy.md"
    source.write_text(
        "如果用户说“我部署卡住了，训练也卡住了”，健身教练可以回答：\n"
        "先检查基础层，训练里就是动作质量和恢复，部署里就是 WSL2、镜像和依赖。",
        encoding="utf-8",
    )
    store = KnowledgeStore(
        db_path=tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
        knowledge_index=EmptyKnowledgeIndex(),
    )
    knowledge_base = await store.create_knowledge_base(name="混合部署知识库")
    await store.add_document(
        kb_id=knowledge_base.id,
        filename=source.name,
        mime_type="text/markdown",
        source_path=source,
    )

    context = await build_agent_context(
        config=AgentSessionConfig(
            agent_enabled=True,
            knowledge_enabled=True,
            knowledge_base_id=knowledge_base.id,
        ),
        avatar_id="fitness-coach",
        query="我部署卡住了，训练也卡住了",
        knowledge_store=store,
    )

    assert context is None


@pytest.mark.asyncio
async def test_knowledge_store_can_enable_chunk_fallback_when_lightrag_misses(tmp_path) -> None:
    source = tmp_path / "mixed-deploy.md"
    source.write_text(
        "如果用户说“我部署卡住了，训练也卡住了”，健身教练可以回答：\n"
        "先检查基础层，训练里就是动作质量和恢复，部署里就是 WSL2、镜像和依赖。",
        encoding="utf-8",
    )
    store = KnowledgeStore(
        db_path=tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
        knowledge_index=EmptyKnowledgeIndex(),
        use_chunk_fallback=True,
    )
    knowledge_base = await store.create_knowledge_base(name="混合部署知识库")
    await store.add_document(
        kb_id=knowledge_base.id,
        filename=source.name,
        mime_type="text/markdown",
        source_path=source,
    )

    context = await build_agent_context(
        config=AgentSessionConfig(
            agent_enabled=True,
            knowledge_enabled=True,
            knowledge_base_id=knowledge_base.id,
        ),
        avatar_id="fitness-coach",
        query="我部署卡住了，训练也卡住了",
        knowledge_store=store,
    )

    assert context is not None
    assert "先检查基础层" in context


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
        knowledge_index=FakeKnowledgeIndex(),
    )
    knowledge_base = await store.create_knowledge_base(name="扫描知识库")
    document = await store.add_document(
        kb_id=knowledge_base.id,
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
    reindexed = await store.reindex_document(kb_id=knowledge_base.id, doc_id=document.id)
    chunks = await store.query(kb_id=knowledge_base.id, query="重新索引知识库", limit=3)

    assert reindexed.status == "ready"
    assert reindexed.chunk_count == 1
    assert chunks
    assert "OpenTalking 知识库可以重新索引" in chunks[0].text
