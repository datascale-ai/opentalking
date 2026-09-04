from __future__ import annotations

import json
import sqlite3
import asyncio
from pathlib import Path

import httpx
import numpy as np
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from apps.api.routes import agent as agent_routes
from opentalking.agent import knowledge_store as knowledge_store_module
from opentalking.agent.knowledge_index import (
    LightRAGKnowledgeIndex,
    LightRAGSearchResult,
    LightRAGStatus,
)
from opentalking.agent.knowledge_store import KnowledgeStore


api_app = FastAPI()
api_app.include_router(agent_routes.router)
api_app.include_router(agent_routes.router, prefix="/api")


class FakeKnowledgeIndex:
    def __init__(self) -> None:
        self.indexed: list[dict[str, str]] = []
        self.cleared: list[str] = []
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
        self.cleared.append(kb_id)
        self.indexed = [item for item in self.indexed if item["kb_id"] != kb_id]

    def query(self, *, kb_id: str, query: str, limit: int) -> list[LightRAGSearchResult]:
        return [
            LightRAGSearchResult(
                doc_id=item["doc_id"],
                text=f"LightRAG result for {query}: {item['text']}",
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


class DeferredFakeKnowledgeIndex(FakeKnowledgeIndex):
    """Opt into the production deferred route without importing LightRAG."""


DeferredFakeKnowledgeIndex.__module__ = "opentalking.agent.knowledge_index"


class BatchFakeKnowledgeIndex(FakeKnowledgeIndex):
    def __init__(self) -> None:
        super().__init__()
        self.batch_calls: list[list[str]] = []

    def index_documents(self, *, kb_id: str, documents: list[dict[str, str]]) -> None:
        self.batch_calls.append([item["doc_id"] for item in documents])
        for item in documents:
            self.index_document(kb_id=kb_id, **item)


BatchFakeKnowledgeIndex.__module__ = "opentalking.agent.knowledge_index"


class FailedKnowledgeIndex(FakeKnowledgeIndex):
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
        raise RuntimeError("LightRAG index failed")


class SelectiveFailedKnowledgeIndex(FakeKnowledgeIndex):
    def __init__(self, fail_doc_id: str) -> None:
        super().__init__()
        self.fail_doc_id = fail_doc_id

    def delete_document(self, *, kb_id: str, doc_id: str) -> None:
        super().delete_document(kb_id=kb_id, doc_id=doc_id)

    def index_documents(self, *, kb_id: str, documents: list[dict[str, str]]) -> None:
        for item in documents:
            self.index_document(kb_id=kb_id, **item)
            if item["doc_id"] == self.fail_doc_id:
                raise RuntimeError("one document failed")


class QueryFailedKnowledgeIndex(FakeKnowledgeIndex):
    def query(self, *, kb_id: str, query: str, limit: int) -> list[LightRAGSearchResult]:
        raise RuntimeError("LightRAG query failed")


class LightRAGOnlyGuardStore(KnowledgeStore):
    async def query(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("LightRAG-only diagnostics must not call KnowledgeStore.query")

    async def query_many(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("LightRAG-only diagnostics must not call KnowledgeStore.query_many")


def make_knowledge_store(tmp_path: Path, *, db_path: Path | None = None) -> KnowledgeStore:
    return KnowledgeStore(
        db_path=db_path or tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
        knowledge_index=FakeKnowledgeIndex(),
    )


class CaptureRedis:
    def __init__(self) -> None:
        self.values: list[tuple[str, str]] = []
        self.keys: set[str] = set()

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None):
        if nx and key in self.keys:
            return None
        self.keys.add(key)
        return True

    async def rpush(self, key: str, value: str) -> int:
        self.values.append((key, value))
        return len(self.values)


def stored_document_path(db_path: Path, *, kb_id: str, doc_id: str) -> Path:
    with sqlite3.connect(str(db_path)) as conn:
        row = conn.execute(
            "SELECT stored_path FROM knowledge_documents WHERE kb_id = ? AND id = ?",
            (kb_id, doc_id),
        ).fetchone()
    assert row is not None
    return Path(str(row[0]))


def stored_file_path(db_path: Path, *, file_id: str) -> Path:
    with sqlite3.connect(str(db_path)) as conn:
        row = conn.execute(
            "SELECT stored_path FROM knowledge_files WHERE id = ?",
            (file_id,),
        ).fetchone()
    assert row is not None
    return Path(str(row[0]))


@pytest.mark.asyncio
async def test_deferred_upload_persists_without_waiting_for_index(tmp_path: Path) -> None:
    index = FakeKnowledgeIndex()
    store = KnowledgeStore(
        db_path=tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
        knowledge_index=index,
    )
    path = tmp_path / "large.md"
    path.write_text("知识库内容。" * 3000, encoding="utf-8")

    doc = await store.add_document_deferred(
        kb_id="kb_deferred",
        filename="large.md",
        mime_type="text/markdown",
        source_path=path,
    )

    assert doc.status == "uploaded"
    assert doc.chunk_count == 0
    assert index.indexed == []

    indexed = await store.index_document(kb_id=doc.kb_id, doc_id=doc.id)
    assert indexed.status == "ready"
    assert indexed.chunk_count > 1
    assert index.indexed


@pytest.mark.asyncio
async def test_stale_index_generation_is_rejected_after_reindex_request(tmp_path: Path) -> None:
    index = FakeKnowledgeIndex()
    store = KnowledgeStore(
        db_path=tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
        knowledge_index=index,
    )
    source = tmp_path / "generation.md"
    source.write_text("generation content", encoding="utf-8")
    document = await store.add_document_deferred(
        kb_id="kb_generation",
        filename=source.name,
        mime_type="text/markdown",
        source_path=source,
    )
    current = await store.request_reindex(kb_id=document.kb_id, doc_id=document.id)
    assert current.generation == document.generation + 1

    with pytest.raises(knowledge_store_module.KnowledgeStaleJobError):
        await store.index_document_for_generation(
            kb_id=document.kb_id,
            doc_id=document.id,
            generation=document.generation,
        )


@pytest.mark.asyncio
async def test_deferred_index_failure_preserves_fast_index_for_worker_retry(tmp_path: Path) -> None:
    index = FailedKnowledgeIndex()
    store = KnowledgeStore(
        db_path=tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
        knowledge_index=index,
    )
    source = tmp_path / "failed.md"
    source.write_text("可重试的索引内容", encoding="utf-8")
    document = await store.add_document_deferred(
        kb_id="kb_retry",
        filename=source.name,
        mime_type="text/markdown",
        source_path=source,
    )

    with pytest.raises(RuntimeError, match="LightRAG index failed"):
        await store.index_document(kb_id=document.kb_id, doc_id=document.id)

    failed = await store.list_documents(kb_id=document.kb_id)
    assert failed[0].status == "ready_fast"
    assert failed[0].index_phase == "enrichment"
    assert failed[0].index_error and "LightRAG index failed" in failed[0].index_error

    # The local chunk index remains available even when the legacy fallback
    # flag is disabled; ``ready_fast`` is an intentionally queryable state.
    chunks = await store.query(
        kb_id=document.kb_id,
        query="可重试 索引 内容",
        limit=3,
    )
    assert chunks


@pytest.mark.asyncio
async def test_batch_index_failure_cleans_document_indexes_individually(tmp_path: Path) -> None:
    index = SelectiveFailedKnowledgeIndex("doc_fail")
    store = KnowledgeStore(
        db_path=tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
        knowledge_index=index,
    )
    kb = await store.create_knowledge_base("批量失败知识库")
    docs = []
    for doc_id, name in (("doc_ok", "ok.md"), ("doc_fail", "fail.md")):
        source = tmp_path / name
        source.write_text(name, encoding="utf-8")
        document = await store.add_document_deferred(
            kb_id=kb.id,
            filename=name,
            mime_type="text/markdown",
            source_path=source,
        )
        # Make IDs deterministic only for the fake's failure selector.
        with sqlite3.connect(str(tmp_path / "agent.sqlite")) as conn:
            conn.execute("UPDATE knowledge_documents SET id = ? WHERE id = ?", (doc_id, document.id))
        docs.append(doc_id)

    with pytest.raises(RuntimeError, match="one document failed"):
        await store.index_documents(kb_id=kb.id, doc_ids=docs)

    assert index.cleared == []
    assert set(index.deleted) == {(kb.id, "doc_ok"), (kb.id, "doc_fail")}


@pytest.mark.asyncio
async def test_index_job_enqueue_is_idempotent(tmp_path: Path) -> None:
    store = make_knowledge_store(tmp_path)
    broker = CaptureRedis()

    await agent_routes._enqueue_index_job(
        store,
        kb_id="kb1",
        doc_id="doc1",
        redis=broker,
        background_tasks=None,
    )
    await agent_routes._enqueue_index_job(
        store,
        kb_id="kb1",
        doc_id="doc1",
        redis=broker,
        background_tasks=None,
    )

    assert len(broker.values) == 1
    assert json.loads(broker.values[0][1])["cmd"] == "knowledge_index"


@pytest.mark.asyncio
async def test_batch_index_documents_uses_one_index_batch(tmp_path: Path) -> None:
    index = BatchFakeKnowledgeIndex()
    store = KnowledgeStore(
        db_path=tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
        knowledge_index=index,
    )
    kb = await store.create_knowledge_base("批量知识库")
    docs = []
    for name, text in (("one.md", "第一份批量内容"), ("two.md", "第二份批量内容")):
        source = tmp_path / name
        source.write_text(text, encoding="utf-8")
        docs.append(
            await store.add_document_deferred(
                kb_id=kb.id,
                filename=name,
                mime_type="text/markdown",
                source_path=source,
            )
        )

    indexed = await store.index_documents(kb_id=kb.id, doc_ids=[doc.id for doc in docs])

    assert index.batch_calls == [[doc.id for doc in docs]]
    assert all(doc.status == "ready" for doc in indexed)


def test_embedding_cache_survives_index_instance_restart(tmp_path: Path) -> None:
    first = LightRAGKnowledgeIndex(
        root=tmp_path / "lightrag",
        embedding_dim=8,
    )
    text = "相同 chunk 内容"
    key = first._embedding_cache_key(text)  # noqa: SLF001
    vector = np.asarray([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8], dtype="float32")
    first._save_embedding_cache(key, vector)  # noqa: SLF001

    second = LightRAGKnowledgeIndex(
        root=tmp_path / "lightrag",
        embedding_dim=8,
    )
    rows, missing = second._cached_embedding_rows([text])  # noqa: SLF001

    assert missing == []
    assert rows[0] is not None
    assert rows[0].tolist() == pytest.approx(vector.tolist())


def test_lightrag_batch_uses_one_ainsert_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    index = LightRAGKnowledgeIndex(root=tmp_path / "lightrag")
    calls: list[tuple[object, object, object]] = []

    class FakeRag:
        async def adelete_by_doc_id(self, _doc_id: str) -> None:
            return None

        async def ainsert(self, inputs, *, ids, file_paths):
            calls.append((inputs, ids, file_paths))

        async def finalize_storages(self) -> None:
            return None

    async def fake_new_rag(_kb_id: str) -> FakeRag:
        return FakeRag()

    monkeypatch.setattr(index, "_new_rag", fake_new_rag)
    asyncio.run(
        index._index_documents_async(  # noqa: SLF001
            kb_id="kb_batch",
            documents=[
                {"doc_id": "doc_a", "filename": "a.md", "text": "A"},
                {"doc_id": "doc_b", "filename": "b.md", "text": "B"},
            ],
        )
    )

    assert calls == [(["A", "B"], ["doc_a", "doc_b"], ["a.md", "b.md"])]


def test_lightrag_new_rag_passes_bounded_embedding_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = LightRAGKnowledgeIndex(root=tmp_path / "lightrag", embedding_dim=8)
    index.embedding_batch_size = 7
    index.embedding_concurrency = 3
    index.insert_concurrency = 2
    captured: dict[str, object] = {}

    class FakeRag:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        async def initialize_storages(self) -> None:
            return None

    class FakeLightRAGModule:
        LightRAG = FakeRag

    class FakeTokenizer:
        def __init__(self, *_args: object) -> None:
            return None

    monkeypatch.setitem(__import__("sys").modules, "lightrag", FakeLightRAGModule())
    utils = __import__("types").ModuleType("lightrag.utils")
    utils.Tokenizer = FakeTokenizer
    utils.wrap_embedding_func_with_attrs = lambda **_kwargs: (lambda func: func)
    monkeypatch.setitem(__import__("sys").modules, "lightrag.utils", utils)
    rag = asyncio.run(index._new_rag("kb_options"))  # noqa: SLF001

    assert isinstance(rag, FakeRag)
    assert captured["embedding_batch_num"] == 7
    assert captured["embedding_func_max_async"] == 3
    assert captured["max_parallel_insert"] == 2


def test_embedding_batches_respect_item_and_token_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    index = LightRAGKnowledgeIndex(root=tmp_path / "lightrag", embedding_dim=8)
    index.embedding_batch_size = 2
    index.embedding_batch_token_limit = 5
    calls: list[list[str]] = []

    async def provider(values: list[str]) -> np.ndarray:
        calls.append(values)
        return np.ones((len(values), 8), dtype="float32")

    monkeypatch.setattr(index, "_embedding_cache_limit", 0)
    result = asyncio.run(index._embed_with_cache(["aa", "bbb", "cccc", "dd"], provider))  # noqa: SLF001

    assert result.shape == (4, 8)
    assert calls == [["aa", "bbb"], ["cccc"], ["dd"]]


@pytest.mark.asyncio
async def test_knowledge_store_lists_created_knowledge_bases(tmp_path: Path) -> None:
    store = make_knowledge_store(tmp_path)
    await store.initialize()

    assert await store.list_knowledge_bases() == []

    created = await store.create_knowledge_base("产品知识库")
    bases = await store.list_knowledge_bases()

    assert created.name == "产品知识库"
    assert any(item.id == created.id and item.document_count == 0 for item in bases)
    assert all(item.id != "default" for item in bases)


@pytest.mark.asyncio
async def test_knowledge_store_persists_avatar_knowledge_selection(tmp_path: Path) -> None:
    store = make_knowledge_store(tmp_path)
    await store.initialize()
    product = await store.create_knowledge_base("产品知识库")
    support = await store.create_knowledge_base("售后知识库")

    saved = await store.set_avatar_knowledge_bases(
        "singer",
        [product.id, support.id, product.id],
    )
    loaded = await store.get_avatar_knowledge_bases("singer")

    assert saved == [product.id, support.id]
    assert loaded == [product.id, support.id]
    assert await store.get_avatar_knowledge_bases("other") == []


@pytest.mark.asyncio
async def test_knowledge_store_backfills_bases_from_existing_documents(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.sqlite"
    now = "2026-01-01T00:00:00+00:00"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE knowledge_documents (
              id TEXT PRIMARY KEY,
              kb_id TEXT NOT NULL,
              filename TEXT NOT NULL,
              mime_type TEXT NOT NULL,
              bytes INTEGER NOT NULL,
              sha256 TEXT NOT NULL,
              status TEXT NOT NULL,
              error TEXT,
              chunk_count INTEGER NOT NULL DEFAULT 0,
              stored_path TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO knowledge_documents(
              id, kb_id, filename, mime_type, bytes, sha256, status, error,
              chunk_count, stored_path, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "doc_legacy",
                "legacy",
                "legacy.md",
                "text/markdown",
                12,
                "abc",
                "ready",
                None,
                1,
                str(tmp_path / "legacy.md"),
                now,
                now,
            ),
        )

    store = make_knowledge_store(tmp_path, db_path=db_path)
    await store.initialize()

    bases = await store.list_knowledge_bases()
    legacy = next(item for item in bases if item.id == "legacy")

    assert legacy.name == "legacy"
    assert legacy.document_count == 1
    assert legacy.ready_document_count == 1
    assert legacy.error_document_count == 0


@pytest.mark.asyncio
async def test_knowledge_store_add_document_creates_custom_base_summary(tmp_path: Path) -> None:
    source = tmp_path / "custom.md"
    source.write_text("custom knowledge base content", encoding="utf-8")
    store = make_knowledge_store(tmp_path)
    await store.initialize()

    await store.add_document(
        kb_id="custom",
        filename="custom.md",
        mime_type="text/markdown",
        source_path=source,
    )

    bases = await store.list_knowledge_bases()
    custom = next(item for item in bases if item.id == "custom")

    assert custom.name == "custom"
    assert custom.document_count == 1
    assert custom.ready_document_count == 1


@pytest.mark.asyncio
async def test_knowledge_store_persists_avatar_selection_positions(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.sqlite"
    store = make_knowledge_store(tmp_path, db_path=db_path)
    await store.initialize()
    first = await store.create_knowledge_base("First")
    second = await store.create_knowledge_base("Second")
    third = await store.create_knowledge_base("Third")

    saved = await store.set_avatar_knowledge_bases("singer", [third.id, first.id, second.id])
    loaded = await store.get_avatar_knowledge_bases("singer")
    with sqlite3.connect(str(db_path)) as conn:
        positions = conn.execute(
            """
            SELECT kb_id, position
            FROM avatar_knowledge_bases
            WHERE avatar_id = ?
            ORDER BY position ASC
            """,
            ("singer",),
        ).fetchall()

    assert saved == [third.id, first.id, second.id]
    assert loaded == [third.id, first.id, second.id]
    assert positions == [(third.id, 0), (first.id, 1), (second.id, 2)]


@pytest.mark.asyncio
async def test_knowledge_store_migrates_avatar_selection_positions_by_rowid(tmp_path: Path) -> None:
    db_path = tmp_path / "agent.sqlite"
    now = "2026-01-01T00:00:00+00:00"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE knowledge_bases (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE avatar_knowledge_bases (
              avatar_id TEXT NOT NULL,
              kb_id TEXT NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY(avatar_id, kb_id),
              FOREIGN KEY(kb_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
            )
            """
        )
        for kb_id in ("kb_b", "kb_a", "kb_c"):
            conn.execute(
                """
                INSERT INTO knowledge_bases(id, name, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (kb_id, kb_id, now, now),
            )
            conn.execute(
                """
                INSERT INTO avatar_knowledge_bases(avatar_id, kb_id, created_at)
                VALUES (?, ?, ?)
                """,
                ("singer", kb_id, now),
            )

    store = make_knowledge_store(tmp_path, db_path=db_path)
    await store.initialize()

    assert await store.get_avatar_knowledge_bases("singer") == ["kb_b", "kb_a", "kb_c"]


@pytest.mark.asyncio
async def test_knowledge_store_delete_base_preserves_db_when_file_cleanup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "custom.md"
    source.write_text("custom knowledge base content", encoding="utf-8")
    store = make_knowledge_store(tmp_path)
    await store.initialize()
    created = await store.create_knowledge_base("Custom")
    await store.add_document(
        kb_id=created.id,
        filename="custom.md",
        mime_type="text/markdown",
        source_path=source,
    )
    stored_file = next((tmp_path / "knowledge" / created.id / "documents").glob("doc_*.md"))
    original_unlink = knowledge_store_module.Path.unlink

    def fail_stored_file_unlink(self: Path, *args, **kwargs) -> None:
        if self == stored_file:
            raise PermissionError("locked")
        original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(knowledge_store_module.Path, "unlink", fail_stored_file_unlink)

    with pytest.raises(ValueError, match="failed to delete knowledge base files"):
        await store.delete_knowledge_base(created.id)

    bases = await store.list_knowledge_bases()
    assert any(item.id == created.id for item in bases)
    assert stored_file.exists()


@pytest.mark.asyncio
async def test_knowledge_store_delete_document_removes_db_file_and_rebuilds_index(
    tmp_path: Path,
) -> None:
    first_source = tmp_path / "first.md"
    first_source.write_text("第一份资料", encoding="utf-8")
    second_source = tmp_path / "second.md"
    second_source.write_text("第二份资料", encoding="utf-8")
    db_path = tmp_path / "agent.sqlite"
    index = FakeKnowledgeIndex()
    store = KnowledgeStore(
        db_path=db_path,
        knowledge_root=tmp_path / "knowledge",
        knowledge_index=index,
    )
    knowledge_base = await store.create_knowledge_base("产品知识库")
    first = await store.add_document(
        kb_id=knowledge_base.id,
        filename=first_source.name,
        mime_type="text/markdown",
        source_path=first_source,
    )
    second = await store.add_document(
        kb_id=knowledge_base.id,
        filename=second_source.name,
        mime_type="text/markdown",
        source_path=second_source,
    )
    first_stored_path = stored_document_path(db_path, kb_id=knowledge_base.id, doc_id=first.id)

    deleted = await store.delete_document(kb_id=knowledge_base.id, doc_id=first.id)

    assert deleted is True
    assert not first_stored_path.exists()
    assert index.cleared == [knowledge_base.id]
    assert [item["doc_id"] for item in index.indexed] == [second.id]
    with sqlite3.connect(str(db_path)) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM knowledge_documents WHERE id = ?",
            (first.id,),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE doc_id = ?",
            (first.id,),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM knowledge_documents WHERE id = ?",
            (second.id,),
        ).fetchone()[0] == 1


@pytest.mark.asyncio
async def test_knowledge_store_delete_document_preserves_db_when_file_cleanup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "policy.md"
    source.write_text("删除单个文档时，文件删不掉就不能先删 DB。", encoding="utf-8")
    db_path = tmp_path / "agent.sqlite"
    store = make_knowledge_store(tmp_path, db_path=db_path)
    knowledge_base = await store.create_knowledge_base("产品知识库")
    document = await store.add_document(
        kb_id=knowledge_base.id,
        filename=source.name,
        mime_type="text/markdown",
        source_path=source,
    )
    stored_path = stored_document_path(db_path, kb_id=knowledge_base.id, doc_id=document.id)
    original_unlink = knowledge_store_module.Path.unlink

    def fail_stored_file_unlink(self: Path, *args, **kwargs) -> None:
        if self == stored_path:
            raise PermissionError("locked")
        original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(knowledge_store_module.Path, "unlink", fail_stored_file_unlink)

    with pytest.raises(ValueError, match="failed to delete knowledge document file"):
        await store.delete_document(kb_id=knowledge_base.id, doc_id=document.id)

    assert stored_path.exists()
    with sqlite3.connect(str(db_path)) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM knowledge_documents WHERE id = ?",
            (document.id,),
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE doc_id = ?",
            (document.id,),
        ).fetchone()[0] == document.chunk_count


@pytest.mark.asyncio
async def test_knowledge_store_delete_file_removes_pool_file_chunks_and_physical_file(
    tmp_path: Path,
) -> None:
    source = tmp_path / "shared.md"
    source.write_text("共享文件池也要完整删除。", encoding="utf-8")
    db_path = tmp_path / "agent.sqlite"
    store = make_knowledge_store(tmp_path, db_path=db_path)
    file_document = await store.add_file(
        filename=source.name,
        mime_type="text/markdown",
        source_path=source,
    )
    stored_path = stored_file_path(db_path, file_id=file_document.id)

    deleted = await store.delete_file(file_document.id)

    assert deleted is True
    assert not stored_path.exists()
    with sqlite3.connect(str(db_path)) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM knowledge_files WHERE id = ?",
            (file_document.id,),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM knowledge_file_chunks WHERE file_id = ?",
            (file_document.id,),
        ).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_knowledge_store_delete_file_preserves_db_when_file_cleanup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "shared.md"
    source.write_text("文件池删除失败也不能留下 DB 和文件不一致。", encoding="utf-8")
    db_path = tmp_path / "agent.sqlite"
    store = make_knowledge_store(tmp_path, db_path=db_path)
    file_document = await store.add_file(
        filename=source.name,
        mime_type="text/markdown",
        source_path=source,
    )
    stored_path = stored_file_path(db_path, file_id=file_document.id)
    original_unlink = knowledge_store_module.Path.unlink

    def fail_stored_file_unlink(self: Path, *args, **kwargs) -> None:
        if self == stored_path:
            raise PermissionError("locked")
        original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(knowledge_store_module.Path, "unlink", fail_stored_file_unlink)

    with pytest.raises(ValueError, match="failed to delete knowledge file"):
        await store.delete_file(file_document.id)

    assert stored_path.exists()
    with sqlite3.connect(str(db_path)) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM knowledge_files WHERE id = ?",
            (file_document.id,),
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM knowledge_file_chunks WHERE file_id = ?",
            (file_document.id,),
        ).fetchone()[0] == file_document.chunk_count


@pytest.mark.asyncio
async def test_knowledge_store_indexes_ready_documents_with_lightrag(tmp_path: Path) -> None:
    source = tmp_path / "policy.md"
    source.write_text("LightRAG 应该索引这份产品政策。", encoding="utf-8")
    index = FakeKnowledgeIndex()
    store = KnowledgeStore(
        db_path=tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
        knowledge_index=index,
    )
    knowledge_base = await store.create_knowledge_base("产品知识库")

    document = await store.add_document(
        kb_id=knowledge_base.id,
        filename=source.name,
        mime_type="text/markdown",
        source_path=source,
    )

    assert document.status == "ready"
    assert index.indexed == [
        {
            "kb_id": knowledge_base.id,
            "doc_id": document.id,
            "filename": "policy.md",
            "text": "LightRAG 应该索引这份产品政策。",
        }
    ]


@pytest.mark.asyncio
async def test_knowledge_store_queries_lightrag_instead_of_sqlite_chunks(tmp_path: Path) -> None:
    source = tmp_path / "policy.md"
    source.write_text("这段文本不包含用户查询词，但是会由 LightRAG 返回。", encoding="utf-8")
    index = FakeKnowledgeIndex()
    store = KnowledgeStore(
        db_path=tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
        knowledge_index=index,
    )
    knowledge_base = await store.create_knowledge_base("产品知识库")
    await store.add_document(
        kb_id=knowledge_base.id,
        filename=source.name,
        mime_type="text/markdown",
        source_path=source,
    )

    chunks = await store.query_many(kb_ids=[knowledge_base.id], query="完全不同的查询词", limit=3)

    assert chunks
    assert chunks[0].filename == "policy.md"
    assert chunks[0].text.startswith("LightRAG result for 完全不同的查询词")


@pytest.mark.asyncio
async def test_knowledge_store_rolls_back_lightrag_index_on_index_failure(tmp_path: Path) -> None:
    source = tmp_path / "policy.md"
    source.write_text("LightRAG 失败时不能留下半成品索引。", encoding="utf-8")
    index = FailedKnowledgeIndex()
    store = KnowledgeStore(
        db_path=tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
        knowledge_index=index,
    )
    knowledge_base = await store.create_knowledge_base("产品知识库")

    document = await store.add_document(
        kb_id=knowledge_base.id,
        filename=source.name,
        mime_type="text/markdown",
        source_path=source,
    )

    assert document.status == "ready"
    assert index.cleared == [knowledge_base.id]
    assert index.status(kb_id=knowledge_base.id).indexed is False


def test_lightrag_index_reports_unavailable_without_silent_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = LightRAGKnowledgeIndex(root=tmp_path / "lightrag")
    monkeypatch.setattr(index, "_lightrag_available", lambda: False)

    status = index.status(kb_id="kb_missing")

    assert status.available is False
    assert status.indexed is False
    assert status.reason == "lightrag_not_installed"


def test_lightrag_index_reports_empty_vector_chunks_as_not_indexed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = LightRAGKnowledgeIndex(root=tmp_path / "lightrag")
    monkeypatch.setattr(index, "_lightrag_available", lambda: True)
    working_dir = tmp_path / "lightrag" / "kb_empty"
    working_dir.mkdir(parents=True)
    (working_dir / "vdb_chunks.json").write_text(
        json.dumps({"embedding_dim": 64, "data": [], "matrix": ""}),
        encoding="utf-8",
    )

    status = index.status(kb_id="kb_empty")

    assert status.available is True
    assert status.indexed is False
    assert status.reason == "index_empty"


def test_lightrag_index_reports_failed_doc_status_as_not_indexed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = LightRAGKnowledgeIndex(root=tmp_path / "lightrag")
    monkeypatch.setattr(index, "_lightrag_available", lambda: True)
    working_dir = tmp_path / "lightrag" / "kb_failed"
    working_dir.mkdir(parents=True)
    (working_dir / "kv_store_doc_status.json").write_text(
        json.dumps({"doc_failed": {"status": "failed", "error": "boom"}}),
        encoding="utf-8",
    )

    status = index.status(kb_id="kb_failed")

    assert status.available is True
    assert status.indexed is False
    assert status.reason == "index_failed"


def test_lightrag_index_can_run_locally_without_tiktoken_network_cache(
    tmp_path: Path,
) -> None:
    index = LightRAGKnowledgeIndex(root=tmp_path / "lightrag", embedding_dim=64)

    index.index_document(
        kb_id="kb_smoke",
        doc_id="doc_smoke",
        filename="mixed.md",
        text=(
            "如果用户说“我部署卡住了，训练也卡住了”，健身教练可以回答："
            "先检查基础层，训练里就是动作质量和恢复，部署里就是 WSL2、镜像和依赖。"
        ),
    )
    results = index.query(
        kb_id="kb_smoke",
        query="我部署卡住了，训练也卡住了",
        limit=1,
    )

    assert results
    assert "先检查基础层" in results[0].text


@pytest.mark.asyncio
async def test_lightrag_index_runs_inside_existing_event_loop(tmp_path: Path) -> None:
    index = LightRAGKnowledgeIndex(root=tmp_path / "lightrag", embedding_dim=64)

    index.index_document(
        kb_id="kb_async",
        doc_id="doc_async",
        filename="mixed.md",
        text=(
            "如果用户说“我部署卡住了，训练也卡住了”，健身教练可以回答："
            "先检查基础层，训练里就是动作质量和恢复，部署里就是 WSL2、镜像和依赖。"
        ),
    )
    status = index.status(kb_id="kb_async")
    results = index.query(
        kb_id="kb_async",
        query="我部署卡住了，训练也卡住了",
        limit=1,
    )

    assert status.indexed is True
    assert results
    assert "先检查基础层" in results[0].text


@pytest.mark.asyncio
async def test_knowledge_store_does_not_fall_back_to_chunks_by_default_when_lightrag_query_fails(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mixed.md"
    source.write_text(
        "如果用户说“我部署卡住了，训练也卡住了”，健身教练可以回答：先检查基础层。",
        encoding="utf-8",
    )
    store = KnowledgeStore(
        db_path=tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
        knowledge_index=QueryFailedKnowledgeIndex(),
    )
    knowledge_base = await store.create_knowledge_base("混合知识库")
    await store.add_document(
        kb_id=knowledge_base.id,
        filename=source.name,
        mime_type="text/markdown",
        source_path=source,
    )

    chunks = await store.query(
        kb_id=knowledge_base.id,
        query="我部署卡住了，训练也卡住了",
        limit=3,
    )

    assert chunks == []


@pytest.mark.asyncio
async def test_knowledge_store_can_enable_chunk_fallback_when_lightrag_query_fails(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mixed.md"
    source.write_text(
        "如果用户说“我部署卡住了，训练也卡住了”，健身教练可以回答：先检查基础层。",
        encoding="utf-8",
    )
    store = KnowledgeStore(
        db_path=tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
        knowledge_index=QueryFailedKnowledgeIndex(),
        use_chunk_fallback=True,
    )
    knowledge_base = await store.create_knowledge_base("混合知识库")
    await store.add_document(
        kb_id=knowledge_base.id,
        filename=source.name,
        mime_type="text/markdown",
        source_path=source,
    )

    chunks = await store.query(
        kb_id=knowledge_base.id,
        query="我部署卡住了，训练也卡住了",
        limit=3,
    )

    assert chunks
    assert "先检查基础层" in chunks[0].text


@pytest.mark.asyncio
async def test_agent_lightrag_query_route_uses_index_without_chunk_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "mixed.md"
    source.write_text(
        "如果用户说“我部署卡住了，训练也卡住了”，健身教练可以回答：\n"
        "先检查基础层，训练里就是动作质量和恢复，部署里就是 WSL2、镜像和依赖。",
        encoding="utf-8",
    )
    index = FakeKnowledgeIndex()
    store = LightRAGOnlyGuardStore(
        db_path=tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
        knowledge_index=index,
    )
    monkeypatch.setattr(agent_routes, "default_knowledge_store", lambda: store)
    knowledge_base = await store.create_knowledge_base("混合知识库")
    await store.add_document(
        kb_id=knowledge_base.id,
        filename=source.name,
        mime_type="text/markdown",
        source_path=source,
    )
    transport = ASGITransport(app=api_app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/agent/knowledge-bases/{knowledge_base.id}/lightrag/query",
            json={"query": "我部署卡住了，训练也卡住了", "limit": 1},
        )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "available": True,
        "indexed": True,
        "reason": "",
        "results": [
            {
                "doc_id": index.indexed[0]["doc_id"],
                "text": "LightRAG result for 我部署卡住了，训练也卡住了: "
                "如果用户说“我部署卡住了，训练也卡住了”，健身教练可以回答：\n"
                "先检查基础层，训练里就是动作质量和恢复，部署里就是 WSL2、镜像和依赖。",
                "score": 1.0,
            }
        ],
    }


@pytest.mark.asyncio
async def test_agent_lightrag_query_route_reports_unavailable_without_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = LightRAGKnowledgeIndex(root=tmp_path / "lightrag")
    monkeypatch.setattr(index, "_lightrag_available", lambda: False)
    store = LightRAGOnlyGuardStore(
        db_path=tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
        knowledge_index=index,
    )
    monkeypatch.setattr(agent_routes, "default_knowledge_store", lambda: store)
    transport = ASGITransport(app=api_app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/agent/knowledge-bases/kb_missing/lightrag/query",
            json={"query": "我部署卡住了，训练也卡住了"},
        )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "available": False,
        "indexed": False,
        "reason": "lightrag_not_installed",
        "results": [],
    }


@pytest.mark.asyncio
async def test_agent_lightrag_query_route_reports_query_failure_without_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "mixed.md"
    source.write_text("LightRAG 诊断路由只报告 LightRAG 自身状态。", encoding="utf-8")
    store = LightRAGOnlyGuardStore(
        db_path=tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
        knowledge_index=QueryFailedKnowledgeIndex(),
    )
    monkeypatch.setattr(agent_routes, "default_knowledge_store", lambda: store)
    knowledge_base = await store.create_knowledge_base("混合知识库")
    await store.add_document(
        kb_id=knowledge_base.id,
        filename=source.name,
        mime_type="text/markdown",
        source_path=source,
    )
    transport = ASGITransport(app=api_app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/agent/knowledge-bases/{knowledge_base.id}/lightrag/query",
            json={"query": "诊断 LightRAG", "limit": 1},
        )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "available": True,
        "indexed": True,
        "reason": "query_failed",
        "results": [],
    }


@pytest.mark.asyncio
async def test_knowledge_store_imports_existing_file_into_lightrag(tmp_path: Path) -> None:
    source = tmp_path / "shared.md"
    source.write_text("共享文件导入知识库时也要写入 LightRAG。", encoding="utf-8")
    index = FakeKnowledgeIndex()
    store = KnowledgeStore(
        db_path=tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
        knowledge_index=index,
    )
    knowledge_base = await store.create_knowledge_base("复用知识库")

    file_document = await store.add_file(
        filename=source.name,
        mime_type="text/markdown",
        source_path=source,
    )
    imported = await store.add_existing_document(
        kb_id=knowledge_base.id,
        source_doc_id=file_document.id,
    )

    assert imported.status == "ready"
    assert index.indexed == [
        {
            "kb_id": knowledge_base.id,
            "doc_id": imported.id,
            "filename": "shared.md",
            "text": "共享文件导入知识库时也要写入 LightRAG。",
        }
    ]


@pytest.mark.asyncio
async def test_knowledge_store_rebuilds_lightrag_index_after_document_delete(
    tmp_path: Path,
) -> None:
    first_source = tmp_path / "first.md"
    first_source.write_text("第一份资料", encoding="utf-8")
    second_source = tmp_path / "second.md"
    second_source.write_text("第二份资料", encoding="utf-8")
    index = FakeKnowledgeIndex()
    store = KnowledgeStore(
        db_path=tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
        knowledge_index=index,
    )
    knowledge_base = await store.create_knowledge_base("产品知识库")
    first = await store.add_document(
        kb_id=knowledge_base.id,
        filename=first_source.name,
        mime_type="text/markdown",
        source_path=first_source,
    )
    second = await store.add_document(
        kb_id=knowledge_base.id,
        filename=second_source.name,
        mime_type="text/markdown",
        source_path=second_source,
    )

    deleted = await store.delete_document(kb_id=knowledge_base.id, doc_id=first.id)

    assert deleted is True
    assert index.cleared == [knowledge_base.id]
    assert [item["doc_id"] for item in index.indexed] == [second.id]
    assert index.indexed[0]["text"] == "第二份资料"


@pytest.mark.asyncio
async def test_knowledge_store_clears_lightrag_index_when_base_is_deleted(
    tmp_path: Path,
) -> None:
    source = tmp_path / "policy.md"
    source.write_text("删除知识库时 LightRAG 工作目录也要清理。", encoding="utf-8")
    index = FakeKnowledgeIndex()
    store = KnowledgeStore(
        db_path=tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
        knowledge_index=index,
    )
    knowledge_base = await store.create_knowledge_base("产品知识库")
    await store.add_document(
        kb_id=knowledge_base.id,
        filename=source.name,
        mime_type="text/markdown",
        source_path=source,
    )

    deleted = await store.delete_knowledge_base(knowledge_base.id)

    assert deleted is True
    assert knowledge_base.id in index.cleared


@pytest.mark.asyncio
async def test_knowledge_store_delete_base_removes_db_rows_files_and_index(
    tmp_path: Path,
) -> None:
    first_source = tmp_path / "first.md"
    first_source.write_text("第一份资料", encoding="utf-8")
    second_source = tmp_path / "second.md"
    second_source.write_text("第二份资料", encoding="utf-8")
    db_path = tmp_path / "agent.sqlite"
    index = FakeKnowledgeIndex()
    store = KnowledgeStore(
        db_path=db_path,
        knowledge_root=tmp_path / "knowledge",
        knowledge_index=index,
    )
    knowledge_base = await store.create_knowledge_base("产品知识库")
    first = await store.add_document(
        kb_id=knowledge_base.id,
        filename=first_source.name,
        mime_type="text/markdown",
        source_path=first_source,
    )
    second = await store.add_document(
        kb_id=knowledge_base.id,
        filename=second_source.name,
        mime_type="text/markdown",
        source_path=second_source,
    )
    await store.set_avatar_knowledge_bases("avatar", [knowledge_base.id])
    first_path = stored_document_path(db_path, kb_id=knowledge_base.id, doc_id=first.id)
    second_path = stored_document_path(db_path, kb_id=knowledge_base.id, doc_id=second.id)

    deleted = await store.delete_knowledge_base(knowledge_base.id)

    assert deleted is True
    assert not first_path.exists()
    assert not second_path.exists()
    assert not (tmp_path / "knowledge" / knowledge_base.id).exists()
    assert knowledge_base.id in index.cleared
    with sqlite3.connect(str(db_path)) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM knowledge_bases WHERE id = ?",
            (knowledge_base.id,),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM knowledge_documents WHERE kb_id = ?",
            (knowledge_base.id,),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE kb_id = ?",
            (knowledge_base.id,),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM avatar_knowledge_bases WHERE kb_id = ?",
            (knowledge_base.id,),
        ).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_agent_knowledge_document_routes_upload_list_delete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = make_knowledge_store(tmp_path)
    monkeypatch.setattr(agent_routes, "default_knowledge_store", lambda: store)
    knowledge_base = await store.create_knowledge_base("产品知识库")
    kb_id = knowledge_base.id

    app = FastAPI()
    app.include_router(agent_routes.router)
    app.include_router(agent_routes.router, prefix="/api")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        upload = await client.post(
            f"/agent/knowledge-bases/{kb_id}/documents",
            files={
                "file": (
                    "产品知识.md",
                    "OpenTalking 的自建知识库会在对话时被检索。",
                    "text/markdown",
                )
            },
        )
        assert upload.status_code == 200, upload.text
        created = upload.json()
        assert created["filename"] == "产品知识.md"
        assert created["status"] == "ready"
        assert created["chunk_count"] >= 1

        viewed = await client.get(f"/agent/knowledge-bases/{kb_id}/documents/{created['id']}/file")
        assert viewed.status_code == 200, viewed.text
        assert viewed.text == "OpenTalking 的自建知识库会在对话时被检索。"
        assert viewed.headers["content-type"].startswith("text/markdown")
        assert "inline" in viewed.headers["content-disposition"]
        assert "filename*" in viewed.headers["content-disposition"]

        viewed_api_prefixed = await client.get(f"/api/agent/knowledge-bases/{kb_id}/documents/{created['id']}/file")
        assert viewed_api_prefixed.status_code == 200, viewed_api_prefixed.text
        assert viewed_api_prefixed.text == "OpenTalking 的自建知识库会在对话时被检索。"

        listed = await client.get(f"/agent/knowledge-bases/{kb_id}/documents")
        assert listed.status_code == 200, listed.text
        documents = listed.json()["documents"]
        assert [document["id"] for document in documents] == [created["id"]]

        deleted = await client.delete(f"/agent/knowledge-bases/{kb_id}/documents/{created['id']}")
        assert deleted.status_code == 200, deleted.text
        assert deleted.json() == {"deleted": True}

        listed_after_delete = await client.get(f"/agent/knowledge-bases/{kb_id}/documents")
        assert listed_after_delete.status_code == 200, listed_after_delete.text
        assert listed_after_delete.json() == {"documents": []}

        viewed_after_delete = await client.get(f"/agent/knowledge-bases/{kb_id}/documents/{created['id']}/file")
        assert viewed_after_delete.status_code == 404, viewed_after_delete.text


@pytest.mark.asyncio
async def test_agent_knowledge_document_routes_accept_pptx(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = make_knowledge_store(tmp_path)
    monkeypatch.setattr(agent_routes, "default_knowledge_store", lambda: store)
    knowledge_base = await store.create_knowledge_base("PPTX知识库")
    pptx = tmp_path / "slides.pptx"
    pptx.write_bytes(b"fake pptx content")
    monkeypatch.setattr(
        "opentalking.agent.knowledge_store._extract_text",
        lambda path: ("PPTX 知识库文本", None),
    )

    app = FastAPI()
    app.include_router(agent_routes.router)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        upload = await client.post(
            f"/agent/knowledge-bases/{knowledge_base.id}/documents",
            files={"file": ("slides.pptx", pptx.read_bytes(), "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )

    assert upload.status_code == 200, upload.text
    created = upload.json()
    assert created["filename"] == "slides.pptx"
    assert created["mime_type"] == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    assert created["status"] == "ready"
    assert created["chunk_count"] == 1


@pytest.mark.asyncio
async def test_agent_knowledge_document_routes_reject_duplicate_kb_upload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = make_knowledge_store(tmp_path)
    monkeypatch.setattr(agent_routes, "default_knowledge_store", lambda: store)
    knowledge_base = await store.create_knowledge_base("产品知识库")
    transport = httpx.ASGITransport(app=api_app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.post(
            f"/agent/knowledge-bases/{knowledge_base.id}/documents",
            files={"file": ("产品知识.md", b"same content", "text/markdown")},
        )
        duplicate = await client.post(
            f"/agent/knowledge-bases/{knowledge_base.id}/documents",
            files={"file": ("产品知识.md", b"same content", "text/markdown")},
        )

    assert first.status_code == 200, first.text
    assert duplicate.status_code == 409, duplicate.text
    assert "already exists" in duplicate.json()["detail"]


@pytest.mark.asyncio
async def test_agent_knowledge_routes_reuse_uploaded_documents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_knowledge_store(tmp_path)
    monkeypatch.setattr(agent_routes, "default_knowledge_store", lambda: store)
    scoped_base = await store.create_knowledge_base("临时知识库")
    transport = ASGITransport(app=api_app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        kb_only_response = await client.post(
            f"/agent/knowledge-bases/{scoped_base.id}/documents",
            files={"file": ("kb-only.md", b"kb scoped text", "text/markdown")},
        )
        assert kb_only_response.status_code == 200, kb_only_response.text

        empty_pool_response = await client.get("/agent/knowledge-documents")
        assert empty_pool_response.status_code == 200, empty_pool_response.text
        assert empty_pool_response.json() == {"documents": []}

        source_response = await client.post(
            "/agent/knowledge-documents",
            files={"file": ("policy.md", b"shared policy text", "text/markdown")},
        )
        assert source_response.status_code == 200, source_response.text
        source = source_response.json()
        assert source["kb_id"] == "file_pool"

        viewed_source_response = await client.get(f"/agent/knowledge-documents/{source['id']}/file")
        assert viewed_source_response.status_code == 200, viewed_source_response.text
        assert viewed_source_response.text == "shared policy text"
        assert viewed_source_response.headers["content-type"].startswith("text/markdown")
        assert "inline" in viewed_source_response.headers["content-disposition"]

        viewed_api_prefixed_source_response = await client.get(f"/api/agent/knowledge-documents/{source['id']}/file")
        assert viewed_api_prefixed_source_response.status_code == 200, viewed_api_prefixed_source_response.text
        assert viewed_api_prefixed_source_response.text == "shared policy text"

        duplicate_response = await client.post(
            "/agent/knowledge-documents",
            files={"file": ("policy.md", b"shared policy text", "text/markdown")},
        )
        assert duplicate_response.status_code == 409, duplicate_response.text
        assert "already exists" in duplicate_response.json()["detail"]

        all_documents_response = await client.get("/agent/knowledge-documents")
        assert all_documents_response.status_code == 200, all_documents_response.text
        all_documents = all_documents_response.json()["documents"]
        assert [document["id"] for document in all_documents] == [source["id"]]

        created_response = await client.post(
            "/agent/knowledge-bases",
            data={"name": "复用知识库", "document_ids": source["id"]},
        )
        assert created_response.status_code == 200, created_response.text
        created = created_response.json()
        assert created["document_count"] == 1

        reused_documents_response = await client.get(
            f"/agent/knowledge-bases/{created['id']}/documents"
        )
        assert reused_documents_response.status_code == 200, reused_documents_response.text
        reused_documents = reused_documents_response.json()["documents"]
        assert len(reused_documents) == 1
        assert reused_documents[0]["filename"] == "policy.md"
        assert reused_documents[0]["sha256"] == source["sha256"]

        second_response = await client.post(
            "/agent/knowledge-documents",
            files={"file": ("faq.txt", b"shared faq text", "text/plain")},
        )
        assert second_response.status_code == 200, second_response.text
        second = second_response.json()

        imported_response = await client.post(
            f"/agent/knowledge-bases/{created['id']}/documents/import",
            json={"document_ids": [second["id"]]},
        )
        assert imported_response.status_code == 200, imported_response.text
        assert [document["filename"] for document in imported_response.json()["documents"]] == ["faq.txt"]

        duplicate_import_response = await client.post(
            f"/agent/knowledge-bases/{created['id']}/documents/import",
            json={"document_ids": [second["id"]]},
        )
        assert duplicate_import_response.status_code == 409, duplicate_import_response.text
        assert "already exists" in duplicate_import_response.json()["detail"]

        final_documents_response = await client.get(
            f"/agent/knowledge-bases/{created['id']}/documents"
        )
        assert final_documents_response.status_code == 200, final_documents_response.text
        assert {document["filename"] for document in final_documents_response.json()["documents"]} == {
            "policy.md",
            "faq.txt",
        }

        blocked_pool_delete = await client.delete(f"/agent/knowledge-documents/{source['id']}")
        assert blocked_pool_delete.status_code == 400, blocked_pool_delete.text
        assert "复用知识库" in blocked_pool_delete.json()["detail"]

        deleted_knowledge_base = await client.delete(f"/agent/knowledge-bases/{created['id']}")
        assert deleted_knowledge_base.status_code == 200, deleted_knowledge_base.text

        deleted_pool_file = await client.delete(f"/agent/knowledge-documents/{source['id']}")
        assert deleted_pool_file.status_code == 200, deleted_pool_file.text
        assert deleted_pool_file.json() == {"deleted": True}

        viewed_deleted_source_response = await client.get(f"/agent/knowledge-documents/{source['id']}/file")
        assert viewed_deleted_source_response.status_code == 404, viewed_deleted_source_response.text

        pool_after_delete = await client.get("/agent/knowledge-documents")
        assert pool_after_delete.status_code == 200, pool_after_delete.text
        assert [document["filename"] for document in pool_after_delete.json()["documents"]] == ["faq.txt"]


@pytest.mark.asyncio
async def test_agent_knowledge_base_routes_create_list_and_avatar_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_knowledge_store(tmp_path)
    monkeypatch.setattr(agent_routes, "default_knowledge_store", lambda: store)
    transport = ASGITransport(app=api_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/agent/knowledge-bases", data={"name": "产品知识库"})
        assert response.status_code == 400

        response = await client.post(
            "/agent/knowledge-bases",
            data={"name": "产品知识库"},
            files=[("files", ("product.txt", b"hello product", "text/plain"))],
        )
        assert response.status_code == 200
        created = response.json()
        assert created["name"] == "产品知识库"
        assert created["document_count"] == 1

        listed = await client.get("/agent/knowledge-bases")
        assert listed.status_code == 200
        listed_payload = listed.json()
        assert created["id"] in listed_payload["knowledge_bases"]
        assert any(
            item["id"] == created["id"]
            for item in listed_payload["knowledge_base_summaries"]
        )

        selected = await client.put(
            "/agent/avatars/singer/knowledge-bases",
            json={"knowledge_base_ids": [created["id"]]},
        )
        assert selected.status_code == 200
        assert selected.json()["knowledge_base_ids"] == [created["id"]]

        loaded = await client.get("/agent/avatars/singer/knowledge-bases")
        assert loaded.status_code == 200
        assert loaded.json()["knowledge_base_ids"] == [created["id"]]


@pytest.mark.asyncio
async def test_agent_knowledge_base_routes_rename_delete_without_default_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_knowledge_store(tmp_path)
    monkeypatch.setattr(agent_routes, "default_knowledge_store", lambda: store)
    transport = ASGITransport(app=api_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created_response = await client.post(
            "/agent/knowledge-bases",
            data={"name": "Original"},
            files=[("files", ("product.txt", b"hello product", "text/plain"))],
        )
        assert created_response.status_code == 200, created_response.text
        created = created_response.json()

        renamed_response = await client.patch(
            f"/agent/knowledge-bases/{created['id']}",
            json={"name": "Renamed"},
        )
        assert renamed_response.status_code == 200, renamed_response.text
        renamed = renamed_response.json()
        assert renamed["id"] == created["id"]
        assert renamed["name"] == "Renamed"
        assert renamed["document_count"] == 1

        empty_rename = await client.patch(
            f"/agent/knowledge-bases/{created['id']}",
            json={"name": " "},
        )
        assert empty_rename.status_code == 400

        missing_rename = await client.patch(
            "/agent/knowledge-bases/kb_missing",
            json={"name": "Missing"},
        )
        assert missing_rename.status_code == 404

        await client.put(
            "/agent/avatars/singer/knowledge-bases",
            json={"knowledge_base_ids": [created["id"]]},
        )

        deleted_response = await client.delete(f"/agent/knowledge-bases/{created['id']}")
        assert deleted_response.status_code == 200, deleted_response.text
        assert deleted_response.json() == {"deleted": True}

        loaded = await client.get("/agent/avatars/singer/knowledge-bases")
        assert loaded.status_code == 200
        assert loaded.json()["knowledge_base_ids"] == []
        assert not (tmp_path / "knowledge" / created["id"]).exists()

        missing_delete = await client.delete("/agent/knowledge-bases/kb_missing")
        assert missing_delete.status_code == 404

        default_delete = await client.delete("/agent/knowledge-bases/default")
        assert default_delete.status_code == 404


@pytest.mark.asyncio
async def test_agent_knowledge_document_route_reindexes_failed_document(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = make_knowledge_store(tmp_path)
    monkeypatch.setattr(agent_routes, "default_knowledge_store", lambda: store)
    knowledge_base = await store.create_knowledge_base("扫描知识库")
    kb_id = knowledge_base.id
    monkeypatch.setattr(
        "opentalking.agent.knowledge_store._extract_text",
        lambda path: ("", "document has no extractable text"),
    )

    app = FastAPI()
    app.include_router(agent_routes.router)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        upload = await client.post(
            f"/agent/knowledge-bases/{kb_id}/documents",
            files={"file": ("scan.pdf", b"%PDF-1.7\n% fake", "application/pdf")},
        )
        assert upload.status_code == 200, upload.text
        failed = upload.json()
        assert failed["status"] == "error"

        monkeypatch.setattr(
            "opentalking.agent.knowledge_store._extract_text",
            lambda path: ("OCR 后的知识库文本", None),
        )
        reindexed = await client.post(
            f"/agent/knowledge-bases/{kb_id}/documents/{failed['id']}/reindex"
        )

        assert reindexed.status_code == 200, reindexed.text
        payload = reindexed.json()
        assert payload["status"] == "ready"
        assert payload["chunk_count"] == 1


@pytest.mark.asyncio
async def test_agent_knowledge_document_reindex_returns_before_background_index(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    index = DeferredFakeKnowledgeIndex()
    store = KnowledgeStore(
        db_path=tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
        knowledge_index=index,
    )
    monkeypatch.setattr(agent_routes, "default_knowledge_store", lambda: store)
    knowledge_base = await store.create_knowledge_base("异步重建知识库")
    source = tmp_path / "reindex.md"
    source.write_text("原始文档内容", encoding="utf-8")
    document = await store.add_document_deferred(
        kb_id=knowledge_base.id,
        filename=source.name,
        mime_type="text/markdown",
        source_path=source,
    )

    broker = CaptureRedis()
    app = FastAPI()
    app.state.redis = broker
    app.include_router(agent_routes.router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/agent/knowledge-bases/{knowledge_base.id}/documents/{document.id}/reindex"
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "uploaded"
    assert index.indexed == []
    assert len(broker.values) == 1
    task = json.loads(broker.values[0][1])
    assert task["cmd"] == "knowledge_index"
    assert task["kb_id"] == knowledge_base.id
    assert task["doc_id"] == document.id
    assert task["generation"] == 1


@pytest.mark.asyncio
async def test_agent_knowledge_document_status_endpoint_exposes_index_phase(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store = KnowledgeStore(
        db_path=tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
        knowledge_index=DeferredFakeKnowledgeIndex(),
    )
    monkeypatch.setattr(agent_routes, "default_knowledge_store", lambda: store)
    kb = await store.create_knowledge_base("状态知识库")
    source = tmp_path / "status.md"
    source.write_text("状态查询内容", encoding="utf-8")
    document = await store.add_document_deferred(
        kb_id=kb.id,
        filename=source.name,
        mime_type="text/markdown",
        source_path=source,
    )
    app = FastAPI()
    app.include_router(agent_routes.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/agent/knowledge-bases/{kb.id}/documents/{document.id}/status"
        )
    assert response.status_code == 200
    assert response.json()["status"] == "uploaded"
    assert response.json()["index_phase"] == "queued"
