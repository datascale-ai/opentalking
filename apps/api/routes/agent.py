from __future__ import annotations

import json
import tempfile
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from opentalking.agent.context_builder import default_knowledge_store, default_memory_store
from opentalking.agent.knowledge_store import (
    MAX_DOCUMENT_BYTES,
    DuplicateKnowledgeDocumentError,
    KnowledgeStore,
)
from opentalking.core.redis_keys import TASK_QUEUE, knowledge_index_job_key, knowledge_prepare_job_key

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
    index_phase: str = ""
    retry_count: int = 0
    index_error: str | None = None
    generation: int = 0


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
    background_tasks: BackgroundTasks | None = None,
    redis: object | None = None,
    enqueue_index: bool = True,
) -> KnowledgeDocumentResponse:
    filename = file.filename or "document.txt"
    mime_type = file.content_type or "application/octet-stream"
    total = 0
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="opentalking-kb-", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_DOCUMENT_BYTES:
                    raise HTTPException(status_code=413, detail="document is larger than 20MB")
                tmp.write(chunk)
        try:
            use_deferred = (
                background_tasks is not None and store.supports_deferred_indexing
            )
            if use_deferred:
                doc = await store.add_document_deferred(
                    kb_id=kb_id,
                    filename=filename,
                    mime_type=mime_type,
                    source_path=tmp_path,
                    consume_source=True,
                )
            else:
                doc = await store.add_document(
                    kb_id=kb_id,
                    filename=filename,
                    mime_type=mime_type,
                    source_path=tmp_path,
                )
            if enqueue_index and doc.status in {"uploaded", "indexing"}:
                await _enqueue_index_job(
                    store,
                    kb_id=kb_id,
                    doc_id=doc.id,
                    redis=redis,
                    background_tasks=background_tasks,
                    generation=doc.generation,
                    content_hash=doc.sha256,
                )
        except DuplicateKnowledgeDocumentError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
    return KnowledgeDocumentResponse(**asdict(doc))


async def _enqueue_index_job(
    store: KnowledgeStore,
    *,
    kb_id: str,
    doc_id: str,
    redis: object | None,
    background_tasks: BackgroundTasks | None,
    generation: int | None = None,
    content_hash: str | None = None,
) -> None:
    """Submit an idempotent index job without coupling it to the HTTP request."""
    task = {
        "cmd": "knowledge_index",
        "kb_id": kb_id,
        "doc_id": doc_id,
    }
    if generation is not None:
        task["generation"] = int(generation)
    if content_hash:
        task["content_hash"] = content_hash
    if redis is not None and hasattr(redis, "rpush"):
        key = knowledge_index_job_key(kb_id, doc_id)
        if hasattr(redis, "set"):
            claimed = await redis.set(key, "queued", nx=True, ex=24 * 60 * 60)  # type: ignore[attr-defined]
            if not claimed:
                return
        try:
            await redis.rpush(TASK_QUEUE, json.dumps(task, ensure_ascii=False))  # type: ignore[attr-defined]
        except Exception:
            # Do not leave an NX claim behind when the broker rejected the
            # enqueue; otherwise this document could be suppressed for a day.
            if hasattr(redis, "delete"):
                try:
                    await redis.delete(key)  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    pass
            raise
        return
    if background_tasks is not None:
        if generation is None:
            background_tasks.add_task(store.index_document, kb_id=kb_id, doc_id=doc_id)
        else:
            background_tasks.add_task(
                store.index_document_for_generation,
                kb_id=kb_id,
                doc_id=doc_id,
                generation=generation,
            )


async def _enqueue_index_batch_job(
    store: KnowledgeStore,
    *,
    kb_id: str,
    doc_ids: list[str],
    redis: object | None,
    background_tasks: BackgroundTasks | None,
) -> None:
    """Submit one batch task for a multi-document import."""
    unique_ids = list(dict.fromkeys(doc_id.strip() for doc_id in doc_ids if doc_id.strip()))
    if not unique_ids:
        return
    task = {"cmd": "knowledge_index_batch", "kb_id": kb_id, "doc_ids": unique_ids}
    # Capture the document generations/content hashes at enqueue time.  A
    # later reindex/delete must not allow an old batch result to overwrite the
    # newer generation.
    try:
        documents = [await store.get_document_status(kb_id=kb_id, doc_id=doc_id) for doc_id in unique_ids]
        task["generations"] = {document.id: document.generation for document in documents}
        task["content_hashes"] = {document.id: document.sha256 for document in documents}
    except Exception:
        # The worker will perform the authoritative existence check; enqueue
        # remains available for lightweight/fake stores used by integrations.
        pass
    if redis is not None and hasattr(redis, "rpush"):
        claimed_ids: list[str] = []
        try:
            for doc_id in unique_ids:
                key = knowledge_index_job_key(kb_id, doc_id)
                if not hasattr(redis, "set"):
                    claimed_ids.append(doc_id)
                    continue
                claimed = await redis.set(key, "queued", nx=True, ex=24 * 60 * 60)  # type: ignore[attr-defined]
                if claimed:
                    claimed_ids.append(doc_id)
            if not claimed_ids:
                return
            await redis.rpush(  # type: ignore[attr-defined]
                TASK_QUEUE,
                json.dumps({**task, "doc_ids": claimed_ids}, ensure_ascii=False),
            )
        except Exception:
            if hasattr(redis, "delete"):
                for doc_id in claimed_ids:
                    try:
                        await redis.delete(knowledge_index_job_key(kb_id, doc_id))  # type: ignore[attr-defined]
                    except Exception:  # noqa: BLE001
                        pass
            raise
        return
    if background_tasks is not None:
        background_tasks.add_task(store.index_documents, kb_id=kb_id, doc_ids=unique_ids)


async def _enqueue_file_prepare_job(
    store: KnowledgeStore,
    *,
    file_id: str,
    redis: object | None,
    background_tasks: BackgroundTasks | None,
) -> None:
    task = {"cmd": "knowledge_prepare_file", "file_id": file_id}
    if redis is not None and hasattr(redis, "rpush"):
        key = knowledge_prepare_job_key(file_id)
        if hasattr(redis, "set"):
            claimed = await redis.set(key, "queued", nx=True, ex=24 * 60 * 60)  # type: ignore[attr-defined]
            if not claimed:
                return
        try:
            await redis.rpush(TASK_QUEUE, json.dumps(task, ensure_ascii=False))  # type: ignore[attr-defined]
        except Exception:
            if hasattr(redis, "delete"):
                await redis.delete(key)  # type: ignore[attr-defined]
            raise
        return
    if background_tasks is not None:
        background_tasks.add_task(store.prepare_file, file_id)


async def _add_uploaded_file(
    store: KnowledgeStore,
    *,
    file: UploadFile,
) -> KnowledgeDocumentResponse:
    filename = file.filename or "document.txt"
    mime_type = file.content_type or "application/octet-stream"
    total = 0
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="opentalking-kb-file-", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_DOCUMENT_BYTES:
                    raise HTTPException(status_code=413, detail="document is larger than 20MB")
                tmp.write(chunk)
        try:
            doc = await store.add_file(
                filename=filename,
                mime_type=mime_type,
                source_path=tmp_path,
            )
        except DuplicateKnowledgeDocumentError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
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
    request: Request,
    background_tasks: BackgroundTasks,
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
        deferred_existing_ids: list[str] = []
        deferred_file_ids: list[str] = []
        for doc_id in selected_document_ids:
            add_existing = (
                store.add_existing_document_deferred
                if background_tasks is not None and store.supports_deferred_indexing
                else store.add_existing_document
            )
            doc = await add_existing(
                kb_id=knowledge_base.id,
                source_doc_id=doc_id,
            )
            if doc.status in {"uploaded", "indexing"}:
                deferred_existing_ids.append(doc.id)
        for file in files or []:
            uploaded_document = await _add_uploaded_document(
                store,
                kb_id=knowledge_base.id,
                file=file,
                background_tasks=background_tasks,
                redis=getattr(request.app.state, "redis", None),
                enqueue_index=False,
            )
            if uploaded_document.status in {"uploaded", "indexing"}:
                deferred_file_ids.append(uploaded_document.id)
        all_deferred_ids = deferred_existing_ids + deferred_file_ids
        if all_deferred_ids:
            await _enqueue_index_batch_job(
                store,
                kb_id=knowledge_base.id,
                doc_ids=all_deferred_ids,
                redis=getattr(request.app.state, "redis", None),
                background_tasks=background_tasks,
                )
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
    status = await store.index_status(kb_id=kb_id)
    results = []
    if status.available and status.indexed:
        try:
            chunk_results = await store.query_index(kb_id=kb_id, query=query, limit=limit)
            results = [
                LightRAGQueryResultResponse(
                    doc_id=chunk.doc_id,
                    text=chunk.text,
                    score=chunk.score,
                )
                for chunk in chunk_results
            ]
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
        results=results,
    )


@router.get(
    "/knowledge-bases/{kb_id}/documents/{doc_id}/status",
    response_model=KnowledgeDocumentResponse,
)
async def get_knowledge_document_status(kb_id: str, doc_id: str) -> KnowledgeDocumentResponse:
    try:
        document = await default_knowledge_store().get_document_status(
            kb_id=kb_id,
            doc_id=doc_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="knowledge document not found") from exc
    return KnowledgeDocumentResponse(**asdict(document))


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
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> KnowledgeDocumentResponse:
    store = default_knowledge_store()
    if not store.supports_deferred_indexing:
        return await _add_uploaded_file(store, file=file)
    filename = file.filename or "document.txt"
    mime_type = file.content_type or "application/octet-stream"
    total = 0
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="opentalking-kb-file-", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_DOCUMENT_BYTES:
                    raise HTTPException(status_code=413, detail="document is larger than 20MB")
                tmp.write(chunk)
        try:
            doc = await store.add_file_deferred(
                filename=filename,
                mime_type=mime_type,
                source_path=tmp_path,
                consume_source=True,
            )
            await _enqueue_file_prepare_job(
                store,
                file_id=doc.id,
                redis=getattr(request.app.state, "redis", None),
                background_tasks=background_tasks,
            )
        except DuplicateKnowledgeDocumentError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
    return KnowledgeDocumentResponse(**asdict(doc))


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


async def _knowledge_file_response(file_id: str) -> FileResponse:
    try:
        stored = await default_knowledge_store().get_file_content(file_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="knowledge file not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(
        stored.path,
        media_type=stored.mime_type,
        filename=stored.filename,
        content_disposition_type="inline",
    )


@router.get("/knowledge-documents/{file_id}/file")
async def view_knowledge_file(file_id: str) -> FileResponse:
    return await _knowledge_file_response(file_id)


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
    request: Request,
    background_tasks: BackgroundTasks,
    kb_id: str,
    file: UploadFile = File(...),
) -> KnowledgeDocumentResponse:
    return await _add_uploaded_document(
        default_knowledge_store(),
        kb_id=kb_id,
        file=file,
        background_tasks=background_tasks,
        redis=getattr(request.app.state, "redis", None),
    )


@router.post(
    "/knowledge-bases/{kb_id}/documents/import",
    response_model=KnowledgeDocumentsResponse,
)
async def import_knowledge_documents(
    kb_id: str,
    request: Request,
    body: ImportKnowledgeDocumentsRequest,
    background_tasks: BackgroundTasks,
) -> KnowledgeDocumentsResponse:
    document_ids = [doc_id.strip() for doc_id in body.document_ids if doc_id.strip()]
    if not document_ids:
        raise HTTPException(status_code=400, detail="at least one document is required")
    store = default_knowledge_store()
    imported = []
    deferred_ids: list[str] = []
    try:
        for doc_id in document_ids:
            add_existing = (
                store.add_existing_document_deferred
                if background_tasks is not None and store.supports_deferred_indexing
                else store.add_existing_document
            )
            doc = await add_existing(kb_id=kb_id, source_doc_id=doc_id)
            imported.append(doc)
            if doc.status in {"uploaded", "indexing"}:
                deferred_ids.append(doc.id)
        if deferred_ids:
            await _enqueue_index_batch_job(
                store,
                kb_id=kb_id,
                doc_ids=deferred_ids,
                redis=getattr(request.app.state, "redis", None),
                background_tasks=background_tasks,
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


async def _knowledge_document_response(kb_id: str, doc_id: str) -> FileResponse:
    try:
        stored = await default_knowledge_store().get_document_content(kb_id=kb_id, doc_id=doc_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="knowledge document not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(
        stored.path,
        media_type=stored.mime_type,
        filename=stored.filename,
        content_disposition_type="inline",
    )


@router.get("/knowledge-bases/{kb_id}/documents/{doc_id}/file")
async def view_knowledge_document(kb_id: str, doc_id: str) -> FileResponse:
    return await _knowledge_document_response(kb_id, doc_id)


@router.post(
    "/knowledge-bases/{kb_id}/documents/{doc_id}/reindex",
    response_model=KnowledgeDocumentResponse,
)
async def reindex_knowledge_document(
    request: Request,
    background_tasks: BackgroundTasks,
    kb_id: str,
    doc_id: str,
) -> KnowledgeDocumentResponse:
    store = default_knowledge_store()
    try:
        if store.supports_deferred_indexing:
            doc = await store.request_reindex(kb_id=kb_id, doc_id=doc_id)
            await _enqueue_index_job(
                store,
                kb_id=kb_id,
                doc_id=doc_id,
                redis=getattr(request.app.state, "redis", None),
                background_tasks=background_tasks,
                generation=doc.generation,
            )
        else:
            # Fallback/fake indexes retain the historical synchronous contract.
            doc = await store.reindex_document(kb_id=kb_id, doc_id=doc_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="knowledge document not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return KnowledgeDocumentResponse(**asdict(doc))
