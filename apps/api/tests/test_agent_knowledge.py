from __future__ import annotations

import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from apps.api.routes import agent as agent_routes
from opentalking.agent import knowledge_store as knowledge_store_module
from opentalking.agent.knowledge_store import KnowledgeStore


api_app = FastAPI()
api_app.include_router(agent_routes.router)


@pytest.mark.asyncio
async def test_knowledge_store_lists_created_knowledge_bases(tmp_path: Path) -> None:
    store = KnowledgeStore(db_path=tmp_path / "agent.sqlite", knowledge_root=tmp_path / "knowledge")
    await store.initialize()

    assert await store.list_knowledge_bases() == []

    created = await store.create_knowledge_base("产品知识库")
    bases = await store.list_knowledge_bases()

    assert created.name == "产品知识库"
    assert any(item.id == created.id and item.document_count == 0 for item in bases)
    assert all(item.id != "default" for item in bases)


@pytest.mark.asyncio
async def test_knowledge_store_persists_avatar_knowledge_selection(tmp_path: Path) -> None:
    store = KnowledgeStore(db_path=tmp_path / "agent.sqlite", knowledge_root=tmp_path / "knowledge")
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

    store = KnowledgeStore(db_path=db_path, knowledge_root=tmp_path / "knowledge")
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
    store = KnowledgeStore(db_path=tmp_path / "agent.sqlite", knowledge_root=tmp_path / "knowledge")
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
    store = KnowledgeStore(db_path=db_path, knowledge_root=tmp_path / "knowledge")
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

    store = KnowledgeStore(db_path=db_path, knowledge_root=tmp_path / "knowledge")
    await store.initialize()

    assert await store.get_avatar_knowledge_bases("singer") == ["kb_b", "kb_a", "kb_c"]


@pytest.mark.asyncio
async def test_knowledge_store_delete_base_preserves_db_when_file_cleanup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "custom.md"
    source.write_text("custom knowledge base content", encoding="utf-8")
    store = KnowledgeStore(db_path=tmp_path / "agent.sqlite", knowledge_root=tmp_path / "knowledge")
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
async def test_agent_knowledge_document_routes_upload_list_delete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = KnowledgeStore(
        db_path=tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
    )
    monkeypatch.setattr(agent_routes, "default_knowledge_store", lambda: store)
    knowledge_base = await store.create_knowledge_base("产品知识库")
    kb_id = knowledge_base.id

    app = FastAPI()
    app.include_router(agent_routes.router)
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


@pytest.mark.asyncio
async def test_agent_knowledge_routes_reuse_uploaded_documents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = KnowledgeStore(db_path=tmp_path / "agent.sqlite", knowledge_root=tmp_path / "knowledge")
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

        duplicate_response = await client.post(
            "/agent/knowledge-documents",
            files={"file": ("policy.md", b"shared policy text", "text/markdown")},
        )
        assert duplicate_response.status_code == 200, duplicate_response.text
        assert duplicate_response.json()["id"] == source["id"]

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

        pool_after_delete = await client.get("/agent/knowledge-documents")
        assert pool_after_delete.status_code == 200, pool_after_delete.text
        assert [document["filename"] for document in pool_after_delete.json()["documents"]] == ["faq.txt"]


@pytest.mark.asyncio
async def test_agent_knowledge_base_routes_create_list_and_avatar_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = KnowledgeStore(db_path=tmp_path / "agent.sqlite", knowledge_root=tmp_path / "knowledge")
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
    store = KnowledgeStore(db_path=tmp_path / "agent.sqlite", knowledge_root=tmp_path / "knowledge")
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
    store = KnowledgeStore(
        db_path=tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
    )
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
