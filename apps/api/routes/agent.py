from __future__ import annotations

import tempfile
from dataclasses import asdict

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

from opentalking.agent.context_builder import default_knowledge_store, default_memory_store
from opentalking.agent.knowledge_store import (
    MAX_DOCUMENT_BYTES,
    DuplicateKnowledgeDocumentError,
    KnowledgeStore,
)

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentOptionsResponse(BaseModel):
    memory_enabled: bool = False
    knowledge_enabled: bool = True
    default_knowledge_base_id: str | None = None


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


class KnowledgeBaseResponse(BaseModel):
    id: str
    name: str
    document_count: int
    ready_document_count: int
    error_document_count: int
    created_at: str
    updated_at: str


class KnowledgeBasesResponse(BaseModel):
    knowledge_bases: list[str]
    knowledge_base_summaries: list[KnowledgeBaseResponse]


class RenameKnowledgeBaseRequest(BaseModel):
    name: str


class AvatarKnowledgeBasesRequest(BaseModel):
    knowledge_base_ids: list[str]


class AvatarKnowledgeBasesResponse(BaseModel):
    knowledge_base_ids: list[str]


class ImportKnowledgeDocumentsRequest(BaseModel):
    document_ids: list[str]


class LightRAGQueryRequest(BaseModel):
    query: str
    limit: int = 3


class LightRAGQueryResultResponse(BaseModel):
    doc_id: str
    text: str
    score: float


class LightRAGQueryResponse(BaseModel):
    available: bool
    indexed: bool
    reason: str
    results: list[LightRAGQueryResultResponse]


class DeleteKnowledgeDocumentResponse(BaseModel):
    deleted: bool


class DeleteKnowledgeBaseResponse(BaseModel):
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


async def _add_uploaded_document(
    store: KnowledgeStore,
    *,
    kb_id: str,
    file: UploadFile,
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
            doc = await store.add_document(
                kb_id=kb_id,
                filename=filename,
                mime_type=mime_type,
                source_path=tmp.name,
            )
        except DuplicateKnowledgeDocumentError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return KnowledgeDocumentResponse(**asdict(doc))


async def _add_uploaded_file(
    store: KnowledgeStore,
    *,
    file: UploadFile,
) -> KnowledgeDocumentResponse:
    filename = file.filename or "document.txt"
    mime_type = file.content_type or "application/octet-stream"
    total = 0
    with tempfile.NamedTemporaryFile(prefix="opentalking-kb-file-", delete=True) as tmp:
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
            doc = await store.add_file(
                filename=filename,
                mime_type=mime_type,
                source_path=tmp.name,
            )
        except DuplicateKnowledgeDocumentError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return KnowledgeDocumentResponse(**asdict(doc))


async def _knowledge_base_response(store: KnowledgeStore, kb_id: str) -> KnowledgeBaseResponse:
    for knowledge_base in await store.list_knowledge_bases():
        if knowledge_base.id == kb_id:
            return KnowledgeBaseResponse(**asdict(knowledge_base))
    raise HTTPException(status_code=404, detail="knowledge base not found")


@router.get("/knowledge-bases", response_model=KnowledgeBasesResponse)
async def list_knowledge_bases() -> KnowledgeBasesResponse:
    try:
        knowledge_bases = await default_knowledge_store().list_knowledge_bases()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    summaries = [
        KnowledgeBaseResponse(**asdict(knowledge_base))
        for knowledge_base in knowledge_bases
    ]
    return KnowledgeBasesResponse(
        knowledge_bases=[knowledge_base.id for knowledge_base in knowledge_bases],
        knowledge_base_summaries=summaries,
    )


@router.post("/knowledge-bases", response_model=KnowledgeBaseResponse)
async def create_knowledge_base(
    name: str = Form(...),
    document_ids: list[str] | None = Form(default=None),
    files: list[UploadFile] | None = File(default=None),
) -> KnowledgeBaseResponse:
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="knowledge base name is required")
    selected_document_ids = [doc_id.strip() for doc_id in document_ids or [] if doc_id.strip()]
    if not files and not selected_document_ids:
        raise HTTPException(status_code=400, detail="at least one file or document is required")
    store = default_knowledge_store()
    try:
        knowledge_base = await store.create_knowledge_base(clean_name)
        for doc_id in selected_document_ids:
            await store.add_existing_document(
                kb_id=knowledge_base.id,
                source_doc_id=doc_id,
            )
        for file in files or []:
            await _add_uploaded_document(store, kb_id=knowledge_base.id, file=file)
    except HTTPException:
        if "knowledge_base" in locals():
            try:
                await store.delete_knowledge_base(knowledge_base.id)
            except Exception:
                pass
        raise
    except KeyError as exc:
        if "knowledge_base" in locals():
            try:
                await store.delete_knowledge_base(knowledge_base.id)
            except Exception:
                pass
        raise HTTPException(status_code=404, detail="knowledge file not found") from exc
    except DuplicateKnowledgeDocumentError as exc:
        if "knowledge_base" in locals():
            try:
                await store.delete_knowledge_base(knowledge_base.id)
            except Exception:
                pass
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        if "knowledge_base" in locals():
            try:
                await store.delete_knowledge_base(knowledge_base.id)
            except Exception:
                pass
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await _knowledge_base_response(store, knowledge_base.id)


@router.patch("/knowledge-bases/{kb_id}", response_model=KnowledgeBaseResponse)
async def rename_knowledge_base(
    kb_id: str,
    request: RenameKnowledgeBaseRequest,
) -> KnowledgeBaseResponse:
    try:
        knowledge_base = await default_knowledge_store().rename_knowledge_base(
            kb_id,
            request.name,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="knowledge base not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return KnowledgeBaseResponse(**asdict(knowledge_base))


@router.delete("/knowledge-bases/{kb_id}", response_model=DeleteKnowledgeBaseResponse)
async def delete_knowledge_base(kb_id: str) -> DeleteKnowledgeBaseResponse:
    try:
        deleted = await default_knowledge_store().delete_knowledge_base(kb_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="knowledge base not found")
    return DeleteKnowledgeBaseResponse(deleted=True)


@router.post(
    "/knowledge-bases/{kb_id}/lightrag/query",
    response_model=LightRAGQueryResponse,
)
async def query_lightrag_index(
    kb_id: str,
    request: LightRAGQueryRequest,
) -> LightRAGQueryResponse:
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    limit = min(max(1, request.limit), 20)
    store = default_knowledge_store()
    status = store.knowledge_index.status(kb_id=kb_id)
    results = []
    if status.available and status.indexed:
        try:
            results = store.knowledge_index.query(kb_id=kb_id, query=query, limit=limit)
        except Exception:
            return LightRAGQueryResponse(
                available=status.available,
                indexed=status.indexed,
                reason="query_failed",
                results=[],
            )
    return LightRAGQueryResponse(
        available=status.available,
        indexed=status.indexed,
        reason=status.reason,
        results=[
            LightRAGQueryResultResponse(**asdict(result))
            for result in results
        ],
    )


@router.get(
    "/avatars/{avatar_id}/knowledge-bases",
    response_model=AvatarKnowledgeBasesResponse,
)
async def get_avatar_knowledge_bases(avatar_id: str) -> AvatarKnowledgeBasesResponse:
    try:
        knowledge_base_ids = await default_knowledge_store().get_avatar_knowledge_bases(avatar_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AvatarKnowledgeBasesResponse(knowledge_base_ids=knowledge_base_ids)


@router.put(
    "/avatars/{avatar_id}/knowledge-bases",
    response_model=AvatarKnowledgeBasesResponse,
)
async def set_avatar_knowledge_bases(
    avatar_id: str,
    request: AvatarKnowledgeBasesRequest,
) -> AvatarKnowledgeBasesResponse:
    try:
        knowledge_base_ids = await default_knowledge_store().set_avatar_knowledge_bases(
            avatar_id,
            request.knowledge_base_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AvatarKnowledgeBasesResponse(knowledge_base_ids=knowledge_base_ids)


@router.get(
    "/knowledge-documents",
    response_model=KnowledgeDocumentsResponse,
)
async def list_all_knowledge_documents() -> KnowledgeDocumentsResponse:
    try:
        docs = await default_knowledge_store().list_all_documents()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return KnowledgeDocumentsResponse(
        documents=[KnowledgeDocumentResponse(**asdict(doc)) for doc in docs]
    )


@router.post(
    "/knowledge-documents",
    response_model=KnowledgeDocumentResponse,
)
async def upload_knowledge_file(
    file: UploadFile = File(...),
) -> KnowledgeDocumentResponse:
    return await _add_uploaded_file(default_knowledge_store(), file=file)


@router.delete(
    "/knowledge-documents/{file_id}",
    response_model=DeleteKnowledgeDocumentResponse,
)
async def delete_knowledge_file(file_id: str) -> DeleteKnowledgeDocumentResponse:
    try:
        deleted = await default_knowledge_store().delete_file(file_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="knowledge file not found")
    return DeleteKnowledgeDocumentResponse(deleted=True)


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
    return await _add_uploaded_document(default_knowledge_store(), kb_id=kb_id, file=file)


@router.post(
    "/knowledge-bases/{kb_id}/documents/import",
    response_model=KnowledgeDocumentsResponse,
)
async def import_knowledge_documents(
    kb_id: str,
    request: ImportKnowledgeDocumentsRequest,
) -> KnowledgeDocumentsResponse:
    document_ids = [doc_id.strip() for doc_id in request.document_ids if doc_id.strip()]
    if not document_ids:
        raise HTTPException(status_code=400, detail="at least one document is required")
    store = default_knowledge_store()
    imported = []
    try:
        for doc_id in document_ids:
            imported.append(
                await store.add_existing_document(kb_id=kb_id, source_doc_id=doc_id)
            )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="knowledge file not found") from exc
    except DuplicateKnowledgeDocumentError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return KnowledgeDocumentsResponse(
        documents=[KnowledgeDocumentResponse(**asdict(doc)) for doc in imported]
    )


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
