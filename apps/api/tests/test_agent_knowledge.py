from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from apps.api.routes import agent as agent_routes
from opentalking.agent.knowledge_store import KnowledgeStore


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

    app = FastAPI()
    app.include_router(agent_routes.router)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        upload = await client.post(
            "/agent/knowledge-bases/default/documents",
            files={
                "file": (
                    "产品知识.md",
                    "OpenTalking 的 default 知识库会在对话时被检索。",
                    "text/markdown",
                )
            },
        )
        assert upload.status_code == 200, upload.text
        created = upload.json()
        assert created["filename"] == "产品知识.md"
        assert created["status"] == "ready"
        assert created["chunk_count"] >= 1

        listed = await client.get("/agent/knowledge-bases/default/documents")
        assert listed.status_code == 200, listed.text
        documents = listed.json()["documents"]
        assert [document["id"] for document in documents] == [created["id"]]

        deleted = await client.delete(f"/agent/knowledge-bases/default/documents/{created['id']}")
        assert deleted.status_code == 200, deleted.text
        assert deleted.json() == {"deleted": True}

        listed_after_delete = await client.get("/agent/knowledge-bases/default/documents")
        assert listed_after_delete.status_code == 200, listed_after_delete.text
        assert listed_after_delete.json() == {"documents": []}


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
    monkeypatch.setattr(
        "opentalking.agent.knowledge_store._extract_text",
        lambda path: ("", "document has no extractable text"),
    )

    app = FastAPI()
    app.include_router(agent_routes.router)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        upload = await client.post(
            "/agent/knowledge-bases/default/documents",
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
            f"/agent/knowledge-bases/default/documents/{failed['id']}/reindex"
        )

        assert reindexed.status_code == 200, reindexed.text
        payload = reindexed.json()
        assert payload["status"] == "ready"
        assert payload["chunk_count"] == 1
