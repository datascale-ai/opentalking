from __future__ import annotations

import tempfile
from dataclasses import asdict

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from opentalking.agent.context_builder import default_knowledge_store, default_memory_store
from opentalking.agent.knowledge_store import MAX_DOCUMENT_BYTES

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentOptionsResponse(BaseModel):
    memory_enabled: bool = False
    knowledge_enabled: bool = True
    default_knowledge_base_id: str = "default"


class AgentMemoryResponse(BaseModel):
    id: str
    user_id: str
    avatar_id: str
    kind: str
    content: str
    importance: float
    confidence: float
    source_turn_id: str | None
    created_at: str
    updated_at: str


class AgentMemoriesResponse(BaseModel):
    memories: list[AgentMemoryResponse]


class DeleteAgentMemoriesResponse(BaseModel):
    deleted: int


class KnowledgeDocumentResponse(BaseModel):
    id: str
    kb_id: str
    filename: str
    mime_type: str
    bytes: int
    sha256: str
    status: str
    error: str | None
    chunk_count: int
    created_at: str
    updated_at: str


class KnowledgeDocumentsResponse(BaseModel):
    documents: list[KnowledgeDocumentResponse]


class DeleteKnowledgeDocumentResponse(BaseModel):
    deleted: bool


def _require_scope(user_id: str, avatar_id: str) -> tuple[str, str]:
    user = user_id.strip()
    avatar = avatar_id.strip()
    if not user or not avatar:
        raise HTTPException(status_code=400, detail="user_id and avatar_id are required")
    return user[:512], avatar[:512]


@router.get("/options", response_model=AgentOptionsResponse)
async def get_agent_options() -> AgentOptionsResponse:
    return AgentOptionsResponse()


@router.get("/memories", response_model=AgentMemoriesResponse)
async def list_agent_memories(
    user_id: str = Query(...),
    avatar_id: str = Query(...),
) -> AgentMemoriesResponse:
    user, avatar = _require_scope(user_id, avatar_id)
    memories = await default_memory_store().list_memories(user_id=user, avatar_id=avatar)
    return AgentMemoriesResponse(
        memories=[AgentMemoryResponse(**asdict(memory)) for memory in memories]
    )


@router.delete("/memories", response_model=DeleteAgentMemoriesResponse)
async def clear_agent_memories(
    user_id: str = Query(...),
    avatar_id: str = Query(...),
) -> DeleteAgentMemoriesResponse:
    user, avatar = _require_scope(user_id, avatar_id)
    deleted = await default_memory_store().clear_memories(user_id=user, avatar_id=avatar)
    return DeleteAgentMemoriesResponse(deleted=deleted)


@router.get("/knowledge-bases", response_model=dict[str, list[str]])
async def list_knowledge_bases() -> dict[str, list[str]]:
    return {"knowledge_bases": ["default"]}


@router.get(
    "/knowledge-bases/{kb_id}/documents",
    response_model=KnowledgeDocumentsResponse,
)
async def list_knowledge_documents(kb_id: str) -> KnowledgeDocumentsResponse:
    try:
        docs = await default_knowledge_store().list_documents(kb_id=kb_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return KnowledgeDocumentsResponse(
        documents=[KnowledgeDocumentResponse(**asdict(doc)) for doc in docs]
    )


@router.post(
    "/knowledge-bases/{kb_id}/documents",
    response_model=KnowledgeDocumentResponse,
)
async def upload_knowledge_document(
    kb_id: str,
    file: UploadFile = File(...),
) -> KnowledgeDocumentResponse:
    filename = file.filename or "document.txt"
    mime_type = file.content_type or "application/octet-stream"
    total = 0
    with tempfile.NamedTemporaryFile(prefix="opentalking-kb-", delete=True) as tmp:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_DOCUMENT_BYTES:
                raise HTTPException(status_code=413, detail="document is larger than 20MB")
            tmp.write(chunk)
        tmp.flush()
        try:
            doc = await default_knowledge_store().add_document(
                kb_id=kb_id,
                filename=filename,
                mime_type=mime_type,
                source_path=tmp.name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return KnowledgeDocumentResponse(**asdict(doc))


@router.delete(
    "/knowledge-bases/{kb_id}/documents/{doc_id}",
    response_model=DeleteKnowledgeDocumentResponse,
)
async def delete_knowledge_document(kb_id: str, doc_id: str) -> DeleteKnowledgeDocumentResponse:
    try:
        deleted = await default_knowledge_store().delete_document(kb_id=kb_id, doc_id=doc_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="knowledge document not found")
    return DeleteKnowledgeDocumentResponse(deleted=True)


@router.post(
    "/knowledge-bases/{kb_id}/documents/{doc_id}/reindex",
    response_model=KnowledgeDocumentResponse,
)
async def reindex_knowledge_document(kb_id: str, doc_id: str) -> KnowledgeDocumentResponse:
    try:
        doc = await default_knowledge_store().reindex_document(kb_id=kb_id, doc_id=doc_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="knowledge document not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return KnowledgeDocumentResponse(**asdict(doc))
