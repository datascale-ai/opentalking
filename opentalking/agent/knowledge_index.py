from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np


_LIGHTRAG_RUN_LOCK = threading.Lock()


@dataclass(frozen=True)
class LightRAGSearchResult:
    doc_id: str
    text: str
    score: float = 1.0


@dataclass(frozen=True)
class LightRAGStatus:
    available: bool
    indexed: bool
    reason: str = ""


class _LocalCharTokenizer:
    def encode(self, content: str) -> list[int]:
        return [ord(char) for char in content]

    def decode(self, tokens: list[int]) -> str:
        chars: list[str] = []
        for token in tokens:
            try:
                value = int(token)
            except (TypeError, ValueError):
                continue
            if 0 <= value <= 0x10FFFF:
                chars.append(chr(value))
        return "".join(chars)


class KnowledgeIndex(Protocol):
    def index_document(
        self,
        *,
        kb_id: str,
        doc_id: str,
        filename: str,
        text: str,
    ) -> None:
        ...

    def delete_document(self, *, kb_id: str, doc_id: str) -> None:
        ...

    def clear_knowledge_base(self, kb_id: str) -> None:
        ...

    def query(self, *, kb_id: str, query: str, limit: int) -> list[LightRAGSearchResult]:
        ...

    def status(self, *, kb_id: str) -> LightRAGStatus:
        ...


def _run_async(coro: Any) -> Any:
    async def run_with_fresh_shared_storage() -> Any:
        _reset_lightrag_shared_storage()
        try:
            return await coro
        finally:
            _reset_lightrag_shared_storage()

    with _LIGHTRAG_RUN_LOCK:
        wrapped = run_with_fresh_shared_storage()
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(wrapped)

        result: list[Any] = []
        errors: list[BaseException] = []

        def runner() -> None:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                result.append(loop.run_until_complete(wrapped))
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
                loop.close()

        thread = threading.Thread(
            target=runner,
            name="opentalking-lightrag-call",
            daemon=True,
        )
        thread.start()
        thread.join()
        if errors:
            raise errors[0]
        return result[0] if result else None


def _reset_lightrag_shared_storage() -> None:
    try:
        from lightrag.kg.shared_storage import finalize_share_data

        finalize_share_data()
    except Exception:
        pass


def _hash_embedding(texts: list[str], *, dim: int) -> np.ndarray:
    vectors = np.zeros((len(texts), dim), dtype=np.float32)
    for row, text in enumerate(texts):
        tokens = re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{1}", text.lower())
        if not tokens:
            tokens = [text[:64] or "empty"]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vectors[row, index] += sign
        norm = math.sqrt(float(np.dot(vectors[row], vectors[row])))
        if norm > 0:
            vectors[row] /= norm
    return vectors


class LightRAGKnowledgeIndex:
    def __init__(
        self,
        *,
        root: str | Path,
        query_mode: str = "hybrid",
        llm_base_url: str = "",
        llm_api_key: str = "",
        llm_model: str = "qwen-turbo",
        embedding_base_url: str = "",
        embedding_api_key: str = "",
        embedding_model: str = "text-embedding-v4",
        embedding_dim: int = 1024,
        embedding_max_token_size: int = 8192,
        language: str = "Chinese",
    ) -> None:
        self.root = Path(root)
        self.query_mode = query_mode.strip() or "hybrid"
        self.llm_base_url = llm_base_url.rstrip("/")
        self.llm_api_key = llm_api_key
        self.llm_model = llm_model.strip() or "qwen-turbo"
        self.embedding_base_url = (embedding_base_url or llm_base_url).rstrip("/")
        self.embedding_api_key = embedding_api_key or llm_api_key
        self.embedding_model = embedding_model.strip() or "text-embedding-v4"
        self.embedding_dim = max(8, int(embedding_dim))
        self.embedding_max_token_size = max(1, int(embedding_max_token_size))
        self.language = language.strip() or "Chinese"

    @property
    def uses_remote_models(self) -> bool:
        return bool(
            self.llm_base_url
            and self.llm_api_key
            and self.embedding_base_url
            and self.embedding_api_key
        )

    def index_document(
        self,
        *,
        kb_id: str,
        doc_id: str,
        filename: str,
        text: str,
    ) -> None:
        clean_text = text.strip()
        if not clean_text or not self._lightrag_available():
            return
        _run_async(
            self._index_document_async(
                kb_id=kb_id,
                doc_id=doc_id,
                filename=filename,
                text=clean_text,
            )
        )

    def delete_document(self, *, kb_id: str, doc_id: str) -> None:
        if not self._lightrag_available():
            return
        _run_async(self._delete_document_async(kb_id=kb_id, doc_id=doc_id))

    def clear_knowledge_base(self, kb_id: str) -> None:
        working_dir = self._working_dir(kb_id)
        if working_dir.exists():
            shutil.rmtree(working_dir)

    def query(self, *, kb_id: str, query: str, limit: int) -> list[LightRAGSearchResult]:
        clean_query = query.strip()
        if not clean_query or limit <= 0 or not self._lightrag_available():
            return []
        if not self.status(kb_id=kb_id).indexed:
            return []
        text = str(
            _run_async(self._query_async(kb_id=kb_id, query=clean_query, limit=limit)) or ""
        ).strip()
        if not text:
            return []
        return [LightRAGSearchResult(doc_id="", text=text, score=1.0)]

    def status(self, *, kb_id: str) -> LightRAGStatus:
        if not self._lightrag_available():
            return LightRAGStatus(available=False, indexed=False, reason="lightrag_not_installed")
        working_dir = self._working_dir(kb_id)
        if not working_dir.exists():
            return LightRAGStatus(available=True, indexed=False, reason="index_not_found")
        if self._doc_status_has_failure(working_dir):
            return LightRAGStatus(available=True, indexed=False, reason="index_failed")
        vector_chunk_count = self._vector_chunk_count(working_dir)
        if vector_chunk_count > 0:
            return LightRAGStatus(available=True, indexed=True, reason="")
        return LightRAGStatus(available=True, indexed=False, reason="index_empty")

    def _working_dir(self, kb_id: str) -> Path:
        return self.root / kb_id

    def _vector_chunk_count(self, working_dir: Path) -> int:
        path = working_dir / "vdb_chunks.json"
        if not path.is_file():
            return 0
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return 0
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, list):
                return len(data)
            if isinstance(data, dict):
                return len(data)
        if isinstance(payload, list):
            return len(payload)
        return 0

    def _doc_status_has_failure(self, working_dir: Path) -> bool:
        path = working_dir / "kv_store_doc_status.json"
        if not path.is_file():
            return False
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return True
        if not isinstance(payload, dict):
            return False
        records = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if not isinstance(records, dict):
            return False
        for record in records.values():
            status = record.get("status") if isinstance(record, dict) else record
            if str(status or "").lower() in {"failed", "error"}:
                return True
        return False

    def _lightrag_available(self) -> bool:
        try:
            import lightrag  # noqa: F401

            return True
        except Exception:
            return False

    async def _new_rag(self, kb_id: str) -> Any:
        from lightrag import LightRAG
        from lightrag.utils import Tokenizer

        working_dir = self._working_dir(kb_id)
        working_dir.mkdir(parents=True, exist_ok=True)
        rag = LightRAG(
            working_dir=str(working_dir),
            llm_model_func=self._llm_model_func(),
            llm_model_name=self.llm_model,
            embedding_func=self._embedding_func(),
            tokenizer=Tokenizer("opentalking-local-char", _LocalCharTokenizer()),
            tiktoken_model_name="",
            addon_params={"language": self.language},
        )
        await rag.initialize_storages()
        return rag

    async def _index_document_async(
        self,
        *,
        kb_id: str,
        doc_id: str,
        filename: str,
        text: str,
    ) -> None:
        rag = await self._new_rag(kb_id)
        try:
            if hasattr(rag, "adelete_by_doc_id"):
                try:
                    await rag.adelete_by_doc_id(doc_id)
                except Exception:
                    pass
            await rag.ainsert(text, ids=[doc_id], file_paths=[filename])
        finally:
            await self._finalize_rag(rag)

    async def _delete_document_async(self, *, kb_id: str, doc_id: str) -> None:
        rag = await self._new_rag(kb_id)
        try:
            if hasattr(rag, "adelete_by_doc_id"):
                await rag.adelete_by_doc_id(doc_id)
        finally:
            await self._finalize_rag(rag)

    async def _query_async(self, *, kb_id: str, query: str, limit: int) -> str:
        from lightrag import QueryParam

        rag = await self._new_rag(kb_id)
        try:
            mode = self.query_mode if self.uses_remote_models else "naive"
            param = QueryParam(
                mode=mode,
                only_need_context=True,
                top_k=max(1, limit),
                chunk_top_k=max(1, limit),
                enable_rerank=False,
            )
            return str(await rag.aquery(query, param=param) or "")
        finally:
            await self._finalize_rag(rag)

    async def _finalize_rag(self, rag: Any) -> None:
        finalize = getattr(rag, "finalize_storages", None)
        if finalize is not None:
            await finalize()

    def _llm_model_func(self) -> Any:
        if not self.uses_remote_models:
            async def local_llm_model_func(
                prompt: str,
                system_prompt: str | None = None,
                history_messages: list[dict[str, str]] | None = None,
                keyword_extraction: bool = False,
                **kwargs: Any,
            ) -> str:
                return ""

            return local_llm_model_func

        from lightrag.llm.openai import openai_complete_if_cache

        async def llm_model_func(
            prompt: str,
            system_prompt: str | None = None,
            history_messages: list[dict[str, str]] | None = None,
            keyword_extraction: bool = False,
            **kwargs: Any,
        ) -> str:
            return str(
                await openai_complete_if_cache(
                    self.llm_model,
                    prompt,
                    system_prompt=system_prompt,
                    history_messages=history_messages or [],
                    api_key=self.llm_api_key,
                    base_url=self.llm_base_url,
                    **kwargs,
                )
            )

        return llm_model_func

    def _embedding_func(self) -> Any:
        from lightrag.utils import wrap_embedding_func_with_attrs

        if not self.uses_remote_models:
            @wrap_embedding_func_with_attrs(
                embedding_dim=self.embedding_dim,
                max_token_size=self.embedding_max_token_size,
                model_name="opentalking-local-hash",
            )
            async def local_embedding_func(texts: list[str]) -> np.ndarray:
                return _hash_embedding(texts, dim=self.embedding_dim)

            return local_embedding_func

        from lightrag.llm.openai import openai_embed

        openai_embed_func = getattr(openai_embed, "func", openai_embed)

        @wrap_embedding_func_with_attrs(
            embedding_dim=self.embedding_dim,
            max_token_size=self.embedding_max_token_size,
            model_name=self.embedding_model,
        )
        async def embedding_func(texts: list[str]) -> np.ndarray:
            return await openai_embed_func(
                texts,
                model=self.embedding_model,
                api_key=self.embedding_api_key,
                base_url=self.embedding_base_url,
            )

        return embedding_func


def default_knowledge_index(knowledge_root: str | Path) -> KnowledgeIndex:
    from opentalking.core.config import get_settings

    settings = get_settings()
    root = Path(
        str(getattr(settings, "agent_lightrag_root", "") or "").strip()
        or (Path(knowledge_root) / "_lightrag")
    )
    return LightRAGKnowledgeIndex(
        root=root,
        query_mode=str(getattr(settings, "agent_lightrag_query_mode", "hybrid") or "hybrid"),
        llm_base_url=str(getattr(settings, "agent_lightrag_llm_base_url", "") or "").strip()
        or str(getattr(settings, "llm_base_url", "") or "").strip(),
        llm_api_key=str(getattr(settings, "agent_lightrag_llm_api_key", "") or "").strip()
        or str(getattr(settings, "llm_api_key", "") or "").strip(),
        llm_model=str(getattr(settings, "agent_lightrag_llm_model", "") or "").strip()
        or str(getattr(settings, "llm_model", "") or "qwen-turbo").strip(),
        embedding_base_url=str(getattr(settings, "agent_lightrag_embedding_base_url", "") or "").strip()
        or str(getattr(settings, "llm_base_url", "") or "").strip(),
        embedding_api_key=str(getattr(settings, "agent_lightrag_embedding_api_key", "") or "").strip()
        or str(getattr(settings, "llm_api_key", "") or "").strip(),
        embedding_model=str(
            getattr(settings, "agent_lightrag_embedding_model", "text-embedding-v4")
            or "text-embedding-v4"
        ),
        embedding_dim=int(getattr(settings, "agent_lightrag_embedding_dim", 1024) or 1024),
        embedding_max_token_size=int(
            getattr(settings, "agent_lightrag_embedding_max_token_size", 8192) or 8192
        ),
        language=str(getattr(settings, "agent_lightrag_language", "Chinese") or "Chinese"),
    )
