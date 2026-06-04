from __future__ import annotations

import base64
import hashlib
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


SUPPORTED_TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}
SUPPORTED_PDF_EXTENSIONS = {".pdf"}
SUPPORTED_EXTENSIONS = SUPPORTED_TEXT_EXTENSIONS | SUPPORTED_PDF_EXTENSIONS
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
MAX_CHUNK_CHARS = 1200
CHUNK_OVERLAP_CHARS = 160
PDF_TEXT_MIN_CHARS = 12
PDF_OCR_MAX_PAGES = 3


@dataclass(frozen=True)
class KnowledgeDocument:
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


@dataclass(frozen=True)
class KnowledgeChunk:
    id: str
    doc_id: str
    kb_id: str
    filename: str
    text: str
    score: float


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _safe_kb_id(value: str | None) -> str:
    kb_id = (value or "default").strip() or "default"
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", kb_id):
        raise ValueError("knowledge base id must contain only letters, digits, _ or -")
    return kb_id


def _safe_filename(filename: str) -> str:
    name = Path(filename or "document.txt").name.strip() or "document.txt"
    return re.sub(r"[^A-Za-z0-9._()\-\u4e00-\u9fff ]+", "_", name)[:160] or "document.txt"


def _tokenize(text: str) -> set[str]:
    lowered = text.lower()
    tokens = set(re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", lowered))
    for index in range(max(0, len(lowered) - 1)):
        pair = lowered[index:index + 2]
        if re.fullmatch(r"[\u4e00-\u9fff]{2}", pair):
            tokens.add(pair)
    return tokens


def _read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _has_enough_text(text: str) -> bool:
    return len(re.sub(r"\s+", "", text or "")) >= PDF_TEXT_MIN_CHARS


def _extract_pdf_with_pdftotext(path: Path) -> tuple[str, str | None]:
    if shutil.which("pdftotext") is None:
        return "", "PDF indexing requires pypdf, PyPDF2, or pdftotext in the API environment"
    try:
        result = subprocess.run(
            ["pdftotext", "-f", "1", "-l", "100", "-layout", str(path), "-"],
            check=False,
            capture_output=True,
            timeout=30,
        )
    except Exception as exc:  # noqa: BLE001
        return "", f"failed to run pdftotext: {exc}"
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        return "", stderr or "pdftotext failed to extract PDF text"
    return result.stdout.decode("utf-8", errors="replace"), None


def _render_pdf_pages(path: Path, *, max_pages: int = PDF_OCR_MAX_PAGES) -> tuple[list[Path], tempfile.TemporaryDirectory[str] | None, str | None]:
    if shutil.which("pdftoppm") is None:
        return [], None, "PDF OCR requires pdftoppm to render scanned pages"
    tmpdir = tempfile.TemporaryDirectory(prefix="opentalking-kb-ocr-")
    prefix = str(Path(tmpdir.name) / "page")
    try:
        result = subprocess.run(
            [
                "pdftoppm",
                "-f",
                "1",
                "-l",
                str(max(1, max_pages)),
                "-r",
                "180",
                "-png",
                str(path),
                prefix,
            ],
            check=False,
            capture_output=True,
            timeout=60,
        )
    except Exception as exc:  # noqa: BLE001
        tmpdir.cleanup()
        return [], None, f"failed to render PDF pages for OCR: {exc}"
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        tmpdir.cleanup()
        return [], None, stderr or "pdftoppm failed to render PDF pages for OCR"
    images = sorted(Path(tmpdir.name).glob("page-*.png"))
    if not images:
        tmpdir.cleanup()
        return [], None, "PDF OCR produced no rendered pages"
    return images, tmpdir, None


def _extract_pdf_with_tesseract(path: Path) -> tuple[str, str | None]:
    if shutil.which("tesseract") is None:
        return "", "tesseract is not installed"
    images, tmpdir, error = _render_pdf_pages(path)
    if error:
        return "", error
    assert tmpdir is not None
    try:
        parts: list[str] = []
        for image in images:
            result = subprocess.run(
                ["tesseract", str(image), "stdout", "-l", "chi_sim+eng", "--psm", "6"],
                check=False,
                capture_output=True,
                timeout=60,
            )
            if result.returncode != 0:
                stderr = result.stderr.decode("utf-8", errors="replace").strip()
                return "", stderr or "tesseract failed to extract PDF text"
            text = result.stdout.decode("utf-8", errors="replace").strip()
            if text:
                parts.append(text)
        return "\n\n".join(parts), None
    finally:
        tmpdir.cleanup()


def _settings_dashscope_api_key() -> str:
    try:
        from opentalking.core.config import get_settings

        settings = get_settings()
        return (
            os.environ.get("DASHSCOPE_API_KEY", "").strip()
            or os.environ.get("OPENTALKING_DASHSCOPE_API_KEY", "").strip()
            or os.environ.get("OPENTALKING_LLM_API_KEY", "").strip()
            or str(getattr(settings, "llm_api_key", "") or "").strip()
            or str(getattr(settings, "stt_dashscope_api_key", "") or "").strip()
            or str(getattr(settings, "tts_dashscope_api_key", "") or "").strip()
        )
    except Exception:
        return (
            os.environ.get("DASHSCOPE_API_KEY", "").strip()
            or os.environ.get("OPENTALKING_DASHSCOPE_API_KEY", "").strip()
            or os.environ.get("OPENTALKING_LLM_API_KEY", "").strip()
        )


def _settings_dashscope_base_http_url() -> str:
    raw = (
        os.environ.get("OPENTALKING_DASHSCOPE_BASE_HTTP_URL", "").strip()
        or os.environ.get("DASHSCOPE_BASE_HTTP_URL", "").strip()
    )
    if raw:
        return raw.rstrip("/")
    try:
        from opentalking.core.config import get_settings

        base_url = str(getattr(get_settings(), "llm_base_url", "") or "").strip()
    except Exception:
        base_url = os.environ.get("OPENTALKING_LLM_BASE_URL", "").strip()
    if "dashscope-intl.aliyuncs.com" in base_url:
        return "https://dashscope-intl.aliyuncs.com/api/v1"
    if "dashscope-us.aliyuncs.com" in base_url:
        return "https://dashscope-us.aliyuncs.com/api/v1"
    return ""


def _dashscope_text_from_response(response: object) -> str:
    output = getattr(response, "output", None)
    if isinstance(output, dict):
        choices = output.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, list):
                texts = [str(item.get("text", "")).strip() for item in content if isinstance(item, dict)]
                return "\n".join(text for text in texts if text).strip()
            if isinstance(content, str):
                return content.strip()
        text = output.get("text")
        if isinstance(text, str):
            return text.strip()
    return ""


def _extract_pdf_with_dashscope_ocr(path: Path) -> tuple[str, str | None]:
    api_key = _settings_dashscope_api_key()
    if not api_key:
        return "", "DashScope OCR requires DASHSCOPE_API_KEY or OPENTALKING_LLM_API_KEY"
    images, tmpdir, error = _render_pdf_pages(path)
    if error:
        return "", error
    assert tmpdir is not None
    try:
        import dashscope  # type: ignore
        from dashscope import MultiModalConversation  # type: ignore

        base_http_url = _settings_dashscope_base_http_url()
        if base_http_url:
            dashscope.base_http_api_url = base_http_url
        model = os.environ.get("OPENTALKING_AGENT_OCR_MODEL", "qwen-vl-ocr-latest").strip()
        parts: list[str] = []
        for image in images:
            encoded = base64.b64encode(image.read_bytes()).decode("ascii")
            response = MultiModalConversation.call(
                api_key=api_key,
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "image": f"data:image/png;base64,{encoded}",
                                "min_pixels": 32 * 32 * 3,
                                "max_pixels": 32 * 32 * 8192,
                                "enable_rotate": True,
                            },
                            {"text": "请对图片进行 OCR，只输出图中的原始文字，不要解释，不要总结。"},
                        ],
                    }
                ],
                ocr_options={"task": "text_recognition"},
            )
            status_code = getattr(response, "status_code", None)
            if status_code and int(status_code) >= 400:
                code = getattr(response, "code", "") or status_code
                message = getattr(response, "message", "") or "DashScope OCR failed"
                return "", f"{code}: {message}"
            text = _dashscope_text_from_response(response)
            if text:
                parts.append(text)
        return "\n\n".join(parts), None
    except Exception as exc:  # noqa: BLE001
        return "", f"DashScope OCR failed: {exc}"
    finally:
        tmpdir.cleanup()


def _extract_scanned_pdf_text(path: Path) -> tuple[str, str | None]:
    text, error = _extract_pdf_with_tesseract(path)
    if _has_enough_text(text):
        return text, None
    if shutil.which("tesseract") is not None and not error:
        error = "tesseract returned no extractable text"
    dashscope_text, dashscope_error = _extract_pdf_with_dashscope_ocr(path)
    if _has_enough_text(dashscope_text):
        return dashscope_text, None
    detail = dashscope_error or error or "OCR returned no extractable text"
    return "", (
        "PDF appears to be scanned/image-only. OCR could not extract text: "
        f"{detail}"
    )


def _extract_pdf_with_fallbacks(path: Path, initial_text: str = "", initial_error: str | None = None) -> tuple[str, str | None]:
    if _has_enough_text(initial_text):
        return initial_text, None
    pdftotext_text, pdftotext_error = _extract_pdf_with_pdftotext(path)
    if _has_enough_text(pdftotext_text):
        return pdftotext_text, None
    ocr_text, ocr_error = _extract_scanned_pdf_text(path)
    if _has_enough_text(ocr_text):
        return ocr_text, None
    return "", ocr_error or pdftotext_error or initial_error or "document has no extractable text"


def _extract_text(path: Path) -> tuple[str, str | None]:
    suffix = path.suffix.lower()
    if suffix in SUPPORTED_TEXT_EXTENSIONS:
        return _read_text_file(path), None
    if suffix in SUPPORTED_PDF_EXTENSIONS:
        try:
            from pypdf import PdfReader  # type: ignore
        except Exception:
            try:
                from PyPDF2 import PdfReader  # type: ignore
            except Exception:
                return _extract_pdf_with_fallbacks(path)
        try:
            reader = PdfReader(str(path))
            parts = [(page.extract_text() or "") for page in reader.pages[:100]]
            text = "\n\n".join(parts)
            return _extract_pdf_with_fallbacks(path, initial_text=text)
        except Exception as exc:  # noqa: BLE001
            return _extract_pdf_with_fallbacks(path, initial_error=f"failed to extract PDF text: {exc}")
    return "", "unsupported document type"


def _split_chunks(text: str) -> list[str]:
    normalized = re.sub(r"\r\n?", "\n", text).strip()
    if not normalized:
        return []
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", normalized) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > MAX_CHUNK_CHARS:
            if current:
                chunks.append(current.strip())
                current = ""
            start = 0
            while start < len(paragraph):
                end = min(len(paragraph), start + MAX_CHUNK_CHARS)
                chunks.append(paragraph[start:end].strip())
                if end >= len(paragraph):
                    break
                start = max(start + 1, end - CHUNK_OVERLAP_CHARS)
            continue
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) > MAX_CHUNK_CHARS and current:
            chunks.append(current.strip())
            current = paragraph
        else:
            current = candidate
    if current:
        chunks.append(current.strip())
    return [chunk for chunk in chunks if chunk]


class KnowledgeStore:
    def __init__(self, *, db_path: str | Path, knowledge_root: str | Path) -> None:
        self.db_path = Path(db_path)
        self.knowledge_root = Path(knowledge_root)

    async def initialize(self) -> None:
        self._initialize_sync()

    async def add_document(
        self,
        *,
        kb_id: str,
        filename: str,
        mime_type: str,
        source_path: str | Path,
    ) -> KnowledgeDocument:
        return self._add_document_sync(kb_id, filename, mime_type, Path(source_path))

    async def list_documents(self, *, kb_id: str) -> list[KnowledgeDocument]:
        return self._list_documents_sync(kb_id)

    async def delete_document(self, *, kb_id: str, doc_id: str) -> bool:
        return self._delete_document_sync(kb_id, doc_id)

    async def query(self, *, kb_id: str, query: str, limit: int = 3) -> list[KnowledgeChunk]:
        return self._query_sync(kb_id, query, limit)

    async def reindex_document(self, *, kb_id: str, doc_id: str) -> KnowledgeDocument:
        return self._reindex_document_sync(kb_id, doc_id)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_sync(self) -> None:
        self.knowledge_root.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_documents (
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
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                  id TEXT PRIMARY KEY,
                  doc_id TEXT NOT NULL,
                  kb_id TEXT NOT NULL,
                  chunk_index INTEGER NOT NULL,
                  text TEXT NOT NULL,
                  tokens TEXT NOT NULL,
                  FOREIGN KEY(doc_id) REFERENCES knowledge_documents(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_knowledge_documents_kb
                ON knowledge_documents(kb_id, updated_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_kb
                ON knowledge_chunks(kb_id, doc_id, chunk_index)
                """
            )

    def _add_document_sync(
        self,
        kb_id: str,
        filename: str,
        mime_type: str,
        source_path: Path,
    ) -> KnowledgeDocument:
        self._initialize_sync()
        kb_id = _safe_kb_id(kb_id)
        filename = _safe_filename(filename)
        if not source_path.is_file():
            raise ValueError("uploaded file is missing")
        size = source_path.stat().st_size
        if size <= 0:
            raise ValueError("uploaded file is empty")
        if size > MAX_DOCUMENT_BYTES:
            raise ValueError("document is larger than 20MB")
        suffix = Path(filename).suffix.lower() or source_path.suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise ValueError("only .txt, .md and .pdf documents are supported")

        doc_id = _new_id("doc")
        kb_dir = self.knowledge_root / kb_id / "documents"
        kb_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{doc_id}{suffix}"
        stored_path = kb_dir / stored_name
        shutil.copyfile(source_path, stored_path)
        sha256 = hashlib.sha256(stored_path.read_bytes()).hexdigest()
        text, error = _extract_text(stored_path)
        chunks = _split_chunks(text)
        status = "ready" if chunks else "error"
        if not chunks and not error:
            error = "document has no extractable text"
        now = _utc_now()

        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute(
                """
                INSERT INTO knowledge_documents(
                  id, kb_id, filename, mime_type, bytes, sha256, status, error,
                  chunk_count, stored_path, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    kb_id,
                    filename,
                    mime_type or "application/octet-stream",
                    size,
                    sha256,
                    status,
                    error,
                    len(chunks),
                    str(stored_path),
                    now,
                    now,
                ),
            )
            for index, chunk in enumerate(chunks):
                conn.execute(
                    """
                    INSERT INTO knowledge_chunks(id, doc_id, kb_id, chunk_index, text, tokens)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _new_id("chunk"),
                        doc_id,
                        kb_id,
                        index,
                        chunk,
                        " ".join(sorted(_tokenize(chunk))),
                    ),
                )
        return self._get_document_sync(kb_id, doc_id)

    def _list_documents_sync(self, kb_id: str) -> list[KnowledgeDocument]:
        self._initialize_sync()
        kb_id = _safe_kb_id(kb_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, kb_id, filename, mime_type, bytes, sha256, status, error,
                       chunk_count, created_at, updated_at
                FROM knowledge_documents
                WHERE kb_id = ?
                ORDER BY updated_at DESC, created_at DESC
                """,
                (kb_id,),
            ).fetchall()
        return [_document_from_row(row) for row in rows]

    def _get_document_sync(self, kb_id: str, doc_id: str) -> KnowledgeDocument:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, kb_id, filename, mime_type, bytes, sha256, status, error,
                       chunk_count, created_at, updated_at
                FROM knowledge_documents
                WHERE kb_id = ? AND id = ?
                """,
                (kb_id, doc_id),
            ).fetchone()
        if row is None:
            raise RuntimeError("failed to load knowledge document")
        return _document_from_row(row)

    def _document_path_sync(self, kb_id: str, doc_id: str) -> Path | None:
        kb_id = _safe_kb_id(kb_id)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT stored_path FROM knowledge_documents WHERE kb_id = ? AND id = ?",
                (kb_id, doc_id),
            ).fetchone()
        if row is None:
            return None
        return Path(str(row["stored_path"]))

    def _reindex_document_sync(self, kb_id: str, doc_id: str) -> KnowledgeDocument:
        self._initialize_sync()
        kb_id = _safe_kb_id(kb_id)
        stored_path = self._document_path_sync(kb_id, doc_id)
        if stored_path is None:
            raise KeyError("knowledge document not found")
        if not stored_path.is_file():
            raise ValueError("stored knowledge document file is missing")
        text, error = _extract_text(stored_path)
        chunks = _split_chunks(text)
        status = "ready" if chunks else "error"
        if not chunks and not error:
            error = "document has no extractable text"
        now = _utc_now()
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("DELETE FROM knowledge_chunks WHERE kb_id = ? AND doc_id = ?", (kb_id, doc_id))
            conn.execute(
                """
                UPDATE knowledge_documents
                SET status = ?, error = ?, chunk_count = ?, updated_at = ?
                WHERE kb_id = ? AND id = ?
                """,
                (status, error, len(chunks), now, kb_id, doc_id),
            )
            for index, chunk in enumerate(chunks):
                conn.execute(
                    """
                    INSERT INTO knowledge_chunks(id, doc_id, kb_id, chunk_index, text, tokens)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _new_id("chunk"),
                        doc_id,
                        kb_id,
                        index,
                        chunk,
                        " ".join(sorted(_tokenize(chunk))),
                    ),
                )
        return self._get_document_sync(kb_id, doc_id)

    def _delete_document_sync(self, kb_id: str, doc_id: str) -> bool:
        self._initialize_sync()
        kb_id = _safe_kb_id(kb_id)
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            row = conn.execute(
                "SELECT stored_path FROM knowledge_documents WHERE kb_id = ? AND id = ?",
                (kb_id, doc_id),
            ).fetchone()
            if row is None:
                return False
            conn.execute("DELETE FROM knowledge_chunks WHERE kb_id = ? AND doc_id = ?", (kb_id, doc_id))
            conn.execute("DELETE FROM knowledge_documents WHERE kb_id = ? AND id = ?", (kb_id, doc_id))
        try:
            Path(str(row["stored_path"])).unlink(missing_ok=True)
        except Exception:
            pass
        return True

    def _query_sync(self, kb_id: str, query: str, limit: int) -> list[KnowledgeChunk]:
        self._initialize_sync()
        kb_id = _safe_kb_id(kb_id)
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []
        safe_limit = min(8, max(1, int(limit)))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.id, c.doc_id, c.kb_id, c.text, c.tokens, d.filename
                FROM knowledge_chunks c
                JOIN knowledge_documents d ON d.id = c.doc_id
                WHERE c.kb_id = ? AND d.status = 'ready'
                """,
                (kb_id,),
            ).fetchall()
        scored: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            chunk_tokens = set(str(row["tokens"] or "").split())
            overlap = query_tokens & chunk_tokens
            if not overlap:
                continue
            score = len(overlap) / max(1.0, len(query_tokens) ** 0.5)
            scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            KnowledgeChunk(
                id=str(row["id"]),
                doc_id=str(row["doc_id"]),
                kb_id=str(row["kb_id"]),
                filename=str(row["filename"]),
                text=str(row["text"]),
                score=float(score),
            )
            for score, row in scored[:safe_limit]
        ]


def _document_from_row(row: sqlite3.Row) -> KnowledgeDocument:
    return KnowledgeDocument(
        id=str(row["id"]),
        kb_id=str(row["kb_id"]),
        filename=str(row["filename"]),
        mime_type=str(row["mime_type"]),
        bytes=int(row["bytes"]),
        sha256=str(row["sha256"]),
        status=str(row["status"]),
        error=str(row["error"]) if row["error"] is not None else None,
        chunk_count=int(row["chunk_count"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )
