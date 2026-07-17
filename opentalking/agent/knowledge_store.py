from __future__ import annotations

import base64
import hashlib
import logging
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

from opentalking.agent.knowledge_index import KnowledgeIndex, default_knowledge_index


logger = logging.getLogger(__name__)

SUPPORTED_TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}
SUPPORTED_PDF_EXTENSIONS = {".pdf"}
SUPPORTED_PRESENTATION_EXTENSIONS = {".pptx"}
SUPPORTED_EXTENSIONS = SUPPORTED_TEXT_EXTENSIONS | SUPPORTED_PDF_EXTENSIONS | SUPPORTED_PRESENTATION_EXTENSIONS
SUPPORTED_EXTENSIONS_LABEL = ".txt, .md, .markdown, .pdf and .pptx"
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
class KnowledgeBaseSummary:
    id: str
    name: str
    document_count: int
    ready_document_count: int
    error_document_count: int
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


@dataclass(frozen=True)
class KnowledgeStoredFile:
    path: Path
    filename: str
    mime_type: str


class DuplicateKnowledgeDocumentError(ValueError):
    """Raised when the same filename/content is uploaded twice."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _safe_kb_id(value: str | None) -> str:
    kb_id = (value or "").strip()
    if not kb_id:
        raise ValueError("knowledge base id is required")
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
            return raw.decode(encoding).replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


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


def _extract_pptx_text(path: Path) -> tuple[str, str | None]:
    if not path.is_file():
        return "", "pptx document is missing"
    if path.suffix.lower() != ".pptx":
        return "", "unsupported presentation type"
    try:
        import zipfile
        from xml.etree import ElementTree as ET
    except Exception as exc:  # pragma: no cover - stdlib import failure is unexpected
        return "", f"failed to load pptx parser: {exc}"
    if not zipfile.is_zipfile(path):
        return "", "invalid pptx archive"
    try:
        with zipfile.ZipFile(path) as zf:
            slide_names = sorted(
                name for name in zf.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
            )
            if not slide_names:
                return "", "pptx contains no slides"
            parts: list[str] = []
            for slide_name in slide_names:
                try:
                    root = ET.fromstring(zf.read(slide_name))
                except Exception:
                    continue
                slide_text = "".join(root.itertext()).strip()
                if slide_text:
                    parts.append(slide_text)
            text = "\n\n".join(part for part in parts if part).strip()
            if text:
                return text, None
            return "", "pptx contains no extractable text"
    except Exception as exc:  # noqa: BLE001
        return "", f"failed to extract pptx text: {exc}"


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
    if suffix in SUPPORTED_PRESENTATION_EXTENSIONS:
        return _extract_pptx_text(path)
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
    def __init__(
        self,
        *,
        db_path: str | Path,
        knowledge_root: str | Path,
        knowledge_index: KnowledgeIndex | None = None,
        use_chunk_fallback: bool = False,
    ) -> None:
        self.db_path = Path(db_path)
        self.knowledge_root = Path(knowledge_root)
        self._knowledge_index = knowledge_index
        self.use_chunk_fallback = use_chunk_fallback

    @property
    def knowledge_index(self) -> KnowledgeIndex:
        if self._knowledge_index is None:
            self._knowledge_index = default_knowledge_index(self.knowledge_root)
        return self._knowledge_index

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

    async def add_file(
        self,
        *,
        filename: str,
        mime_type: str,
        source_path: str | Path,
    ) -> KnowledgeDocument:
        return self._add_file_sync(filename, mime_type, Path(source_path))

    async def delete_file(self, file_id: str) -> bool:
        return self._delete_file_sync(file_id)

    async def list_all_documents(self) -> list[KnowledgeDocument]:
        return self._list_files_sync()

    async def get_file_content(self, file_id: str) -> KnowledgeStoredFile:
        return self._get_file_content_sync(file_id)

    async def add_existing_document(self, *, kb_id: str, source_doc_id: str) -> KnowledgeDocument:
        return self._add_existing_document_sync(kb_id=kb_id, source_doc_id=source_doc_id)

    async def delete_document(self, *, kb_id: str, doc_id: str) -> bool:
        return self._delete_document_sync(kb_id, doc_id)

    async def get_document_content(self, *, kb_id: str, doc_id: str) -> KnowledgeStoredFile:
        return self._get_document_content_sync(kb_id=kb_id, doc_id=doc_id)

    async def query(self, *, kb_id: str, query: str, limit: int = 3) -> list[KnowledgeChunk]:
        return self._query_sync(kb_id, query, limit)

    async def query_many(
        self,
        *,
        kb_ids: list[str],
        query: str,
        limit: int = 3,
    ) -> list[KnowledgeChunk]:
        return self._query_many_sync(kb_ids, query, limit)

    async def reindex_document(self, *, kb_id: str, doc_id: str) -> KnowledgeDocument:
        return self._reindex_document_sync(kb_id, doc_id)

    async def create_knowledge_base(self, name: str) -> KnowledgeBaseSummary:
        return self._create_knowledge_base_sync(name)

    async def rename_knowledge_base(self, kb_id: str, name: str) -> KnowledgeBaseSummary:
        return self._rename_knowledge_base_sync(kb_id, name)

    async def delete_knowledge_base(self, kb_id: str) -> bool:
        return self._delete_knowledge_base_sync(kb_id)

    async def list_knowledge_bases(self) -> list[KnowledgeBaseSummary]:
        return self._list_knowledge_bases_sync()

    async def get_avatar_knowledge_bases(self, avatar_id: str) -> list[str]:
        return self._get_avatar_knowledge_bases_sync(avatar_id)

    async def set_avatar_knowledge_bases(self, avatar_id: str, kb_ids: list[str]) -> list[str]:
        return self._set_avatar_knowledge_bases_sync(avatar_id, kb_ids)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_sync(self) -> None:
        self.knowledge_root.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_bases (
                  id TEXT PRIMARY KEY,
                  name TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS avatar_knowledge_bases (
                  avatar_id TEXT NOT NULL,
                  kb_id TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  position INTEGER NOT NULL DEFAULT 0,
                  PRIMARY KEY(avatar_id, kb_id),
                  FOREIGN KEY(kb_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
                )
                """
            )
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
                CREATE TABLE IF NOT EXISTS knowledge_files (
                  id TEXT PRIMARY KEY,
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
                CREATE TABLE IF NOT EXISTS knowledge_file_chunks (
                  id TEXT PRIMARY KEY,
                  file_id TEXT NOT NULL,
                  chunk_index INTEGER NOT NULL,
                  text TEXT NOT NULL,
                  tokens TEXT NOT NULL,
                  FOREIGN KEY(file_id) REFERENCES knowledge_files(id) ON DELETE CASCADE
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
                CREATE INDEX IF NOT EXISTS idx_knowledge_files_unique_content
                ON knowledge_files(filename, sha256)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_kb
                ON knowledge_chunks(kb_id, doc_id, chunk_index)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_knowledge_file_chunks_file
                ON knowledge_file_chunks(file_id, chunk_index)
                """
            )
            now = _utc_now()
            columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(avatar_knowledge_bases)").fetchall()
            }
            if "position" not in columns:
                conn.execute(
                    """
                    ALTER TABLE avatar_knowledge_bases
                    ADD COLUMN position INTEGER NOT NULL DEFAULT 0
                    """
                )
                rows = conn.execute(
                    """
                    SELECT rowid AS row_id, avatar_id
                    FROM avatar_knowledge_bases
                    ORDER BY avatar_id ASC, rowid ASC
                    """
                ).fetchall()
                positions_by_avatar: dict[str, int] = {}
                for row in rows:
                    avatar_id = str(row["avatar_id"])
                    position = positions_by_avatar.get(avatar_id, 0)
                    conn.execute(
                        """
                        UPDATE avatar_knowledge_bases
                        SET position = ?
                        WHERE rowid = ?
                        """,
                        (position, int(row["row_id"])),
                    )
                    positions_by_avatar[avatar_id] = position + 1
            conn.execute(
                """
                INSERT INTO knowledge_bases(id, name, created_at, updated_at)
                SELECT
                  d.kb_id,
                  d.kb_id,
                  COALESCE(MIN(d.created_at), ?),
                  COALESCE(MAX(d.updated_at), ?)
                FROM knowledge_documents d
                WHERE TRIM(d.kb_id) != ''
                GROUP BY d.kb_id
                ON CONFLICT(id) DO NOTHING
                """,
                (now, now),
            )

    def _create_knowledge_base_sync(self, name: str) -> KnowledgeBaseSummary:
        self._initialize_sync()
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("knowledge base name is required")
        kb_id = _safe_kb_id(_new_id("kb"))
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_bases(id, name, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (kb_id, clean_name, now, now),
            )
        return self._get_knowledge_base_summary_sync(kb_id)

    def _rename_knowledge_base_sync(self, kb_id: str, name: str) -> KnowledgeBaseSummary:
        self._initialize_sync()
        kb_id = _safe_kb_id(kb_id)
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("knowledge base name is required")
        now = _utc_now()
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE knowledge_bases
                SET name = ?, updated_at = ?
                WHERE id = ?
                """,
                (clean_name, now, kb_id),
            )
        if result.rowcount == 0:
            raise KeyError("knowledge base not found")
        return self._get_knowledge_base_summary_sync(kb_id)

    def _delete_knowledge_base_sync(self, kb_id: str) -> bool:
        self._initialize_sync()
        kb_id = _safe_kb_id(kb_id)
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            row = conn.execute(
                "SELECT id FROM knowledge_bases WHERE id = ?",
                (kb_id,),
            ).fetchone()
            if row is None:
                return False
            document_rows = conn.execute(
                "SELECT stored_path FROM knowledge_documents WHERE kb_id = ?",
                (kb_id,),
            ).fetchall()
        try:
            for document_row in document_rows:
                Path(str(document_row["stored_path"])).unlink(missing_ok=True)
            kb_dir = self.knowledge_root / kb_id
            if kb_dir.exists():
                shutil.rmtree(kb_dir)
            self.knowledge_index.clear_knowledge_base(kb_id)
        except FileNotFoundError:
            pass
        except Exception as exc:
            raise ValueError("failed to delete knowledge base files") from exc

        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("DELETE FROM avatar_knowledge_bases WHERE kb_id = ?", (kb_id,))
            conn.execute("DELETE FROM knowledge_chunks WHERE kb_id = ?", (kb_id,))
            conn.execute("DELETE FROM knowledge_documents WHERE kb_id = ?", (kb_id,))
            conn.execute("DELETE FROM knowledge_bases WHERE id = ?", (kb_id,))
        return True

    def _list_knowledge_bases_sync(self) -> list[KnowledgeBaseSummary]:
        self._initialize_sync()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  kb.id,
                  kb.name,
                  COUNT(d.id) AS document_count,
                  COALESCE(SUM(CASE WHEN d.status = 'ready' THEN 1 ELSE 0 END), 0) AS ready_document_count,
                  COALESCE(SUM(CASE WHEN d.status = 'error' THEN 1 ELSE 0 END), 0) AS error_document_count,
                  kb.created_at,
                  kb.updated_at
                FROM knowledge_bases kb
                LEFT JOIN knowledge_documents d ON d.kb_id = kb.id
                GROUP BY kb.id, kb.name, kb.created_at, kb.updated_at
                ORDER BY kb.created_at ASC, kb.id ASC
                """
            ).fetchall()
        return [_knowledge_base_summary_from_row(row) for row in rows]

    def _get_knowledge_base_summary_sync(self, kb_id: str) -> KnowledgeBaseSummary:
        kb_id = _safe_kb_id(kb_id)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                  kb.id,
                  kb.name,
                  COUNT(d.id) AS document_count,
                  COALESCE(SUM(CASE WHEN d.status = 'ready' THEN 1 ELSE 0 END), 0) AS ready_document_count,
                  COALESCE(SUM(CASE WHEN d.status = 'error' THEN 1 ELSE 0 END), 0) AS error_document_count,
                  kb.created_at,
                  kb.updated_at
                FROM knowledge_bases kb
                LEFT JOIN knowledge_documents d ON d.kb_id = kb.id
                WHERE kb.id = ?
                GROUP BY kb.id, kb.name, kb.created_at, kb.updated_at
                """,
                (kb_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("failed to load knowledge base")
        return _knowledge_base_summary_from_row(row)

    def _get_avatar_knowledge_bases_sync(self, avatar_id: str) -> list[str]:
        self._initialize_sync()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT kb_id
                FROM avatar_knowledge_bases
                WHERE avatar_id = ?
                ORDER BY position ASC, created_at ASC, kb_id ASC
                """,
                (avatar_id,),
            ).fetchall()
        return [str(row["kb_id"]) for row in rows]

    def _set_avatar_knowledge_bases_sync(self, avatar_id: str, kb_ids: list[str]) -> list[str]:
        self._initialize_sync()
        selected: list[str] = []
        seen: set[str] = set()
        for kb_id in kb_ids:
            safe_id = _safe_kb_id(kb_id)
            if safe_id in seen:
                continue
            selected.append(safe_id)
            seen.add(safe_id)

        if selected:
            placeholders = ", ".join("?" for _ in selected)
            with self._connect() as conn:
                rows = conn.execute(
                    f"SELECT id FROM knowledge_bases WHERE id IN ({placeholders})",
                    selected,
                ).fetchall()
            found = {str(row["id"]) for row in rows}
            if any(kb_id not in found for kb_id in selected):
                raise ValueError("knowledge base not found")

        now = _utc_now()
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute(
                "DELETE FROM avatar_knowledge_bases WHERE avatar_id = ?",
                (avatar_id,),
            )
            for position, kb_id in enumerate(selected):
                conn.execute(
                    """
                    INSERT INTO avatar_knowledge_bases(avatar_id, kb_id, created_at, position)
                    VALUES (?, ?, ?, ?)
                    """,
                    (avatar_id, kb_id, now, position),
                )
        return selected

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
            raise ValueError(f"only {SUPPORTED_EXTENSIONS_LABEL} documents are supported")
        sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
        with self._connect() as conn:
            existing_row = conn.execute(
                """
                SELECT id
                FROM knowledge_documents
                WHERE kb_id = ? AND filename = ? AND sha256 = ?
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
                """,
                (kb_id, filename, sha256),
            ).fetchone()
        if existing_row is not None:
            raise DuplicateKnowledgeDocumentError(f"knowledge document already exists: {filename}")

        doc_id = _new_id("doc")
        kb_dir = self.knowledge_root / kb_id / "documents"
        kb_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{doc_id}{suffix}"
        stored_path = kb_dir / stored_name
        shutil.copyfile(source_path, stored_path)
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
                INSERT INTO knowledge_bases(id, name, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (kb_id, kb_id, now, now),
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
        if status == "ready":
            self._index_document_best_effort_sync(
                kb_id=kb_id,
                doc_id=doc_id,
                filename=filename,
                text=text,
            )
        return self._get_document_sync(kb_id, doc_id)

    def _add_file_sync(
        self,
        filename: str,
        mime_type: str,
        source_path: Path,
    ) -> KnowledgeDocument:
        self._initialize_sync()
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
            raise ValueError(f"only {SUPPORTED_EXTENSIONS_LABEL} documents are supported")

        sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
        with self._connect() as conn:
            existing_row = conn.execute(
                """
                SELECT id
                FROM knowledge_files
                WHERE filename = ? AND sha256 = ?
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
                """,
                (filename, sha256),
            ).fetchone()
        if existing_row is not None:
            raise DuplicateKnowledgeDocumentError(f"knowledge file already exists: {filename}")

        file_id = _new_id("file")
        pool_dir = self.knowledge_root / "_file_pool"
        pool_dir.mkdir(parents=True, exist_ok=True)
        stored_path = pool_dir / f"{file_id}{suffix}"
        shutil.copyfile(source_path, stored_path)
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
                INSERT INTO knowledge_files(
                  id, filename, mime_type, bytes, sha256, status, error,
                  chunk_count, stored_path, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id,
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
                    INSERT INTO knowledge_file_chunks(id, file_id, chunk_index, text, tokens)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        _new_id("chunk"),
                        file_id,
                        index,
                        chunk,
                        " ".join(sorted(_tokenize(chunk))),
                    ),
                )
        return self._get_file_sync(file_id)

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

    def _list_files_sync(self) -> list[KnowledgeDocument]:
        self._initialize_sync()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, 'file_pool' AS kb_id, filename, mime_type, bytes, sha256, status, error,
                       chunk_count, created_at, updated_at
                FROM knowledge_files
                ORDER BY updated_at DESC, created_at DESC
                """
            ).fetchall()
        return [_document_from_row(row) for row in rows]

    def _get_file_sync(self, file_id: str) -> KnowledgeDocument:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, 'file_pool' AS kb_id, filename, mime_type, bytes, sha256, status, error,
                       chunk_count, created_at, updated_at
                FROM knowledge_files
                WHERE id = ?
                """,
                (file_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("failed to load knowledge file")
        return _document_from_row(row)

    def _get_file_content_sync(self, file_id: str) -> KnowledgeStoredFile:
        self._initialize_sync()
        clean_file_id = file_id.strip()
        if not clean_file_id:
            raise ValueError("knowledge file id is required")
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT filename, mime_type, stored_path
                FROM knowledge_files
                WHERE id = ?
                """,
                (clean_file_id,),
            ).fetchone()
        if row is None:
            raise KeyError("knowledge file not found")
        path = Path(str(row["stored_path"])).resolve()
        try:
            path.relative_to(self.knowledge_root.resolve())
        except ValueError as exc:
            raise ValueError("stored knowledge file path is invalid") from exc
        if not path.is_file():
            raise ValueError("stored knowledge file is missing")
        return KnowledgeStoredFile(
            path=path,
            filename=str(row["filename"]),
            mime_type=str(row["mime_type"] or "application/octet-stream"),
        )

    def _delete_file_sync(self, file_id: str) -> bool:
        self._initialize_sync()
        clean_file_id = file_id.strip()
        if not clean_file_id:
            raise ValueError("knowledge file id is required")
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            row = conn.execute(
                "SELECT filename, sha256, stored_path FROM knowledge_files WHERE id = ?",
                (clean_file_id,),
            ).fetchone()
            if row is None:
                return False
            reference_rows = conn.execute(
                """
                SELECT DISTINCT kb.id, kb.name
                FROM knowledge_documents d
                JOIN knowledge_bases kb ON kb.id = d.kb_id
                WHERE d.filename = ? AND d.sha256 = ?
                ORDER BY kb.created_at ASC, kb.id ASC
                """,
                (str(row["filename"]), str(row["sha256"])),
            ).fetchall()
            if reference_rows:
                names = "、".join(f"「{str(reference_row['name'])}」" for reference_row in reference_rows)
                raise ValueError(f"请先删除知识库{names}后再删除文件")
        try:
            Path(str(row["stored_path"])).unlink(missing_ok=True)
        except Exception as exc:
            raise ValueError("failed to delete knowledge file") from exc
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("DELETE FROM knowledge_file_chunks WHERE file_id = ?", (clean_file_id,))
            conn.execute("DELETE FROM knowledge_files WHERE id = ?", (clean_file_id,))
        return True

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

    def _get_document_content_sync(self, *, kb_id: str, doc_id: str) -> KnowledgeStoredFile:
        self._initialize_sync()
        kb_id = _safe_kb_id(kb_id)
        clean_doc_id = doc_id.strip()
        if not clean_doc_id:
            raise ValueError("knowledge document id is required")
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT filename, mime_type, stored_path
                FROM knowledge_documents
                WHERE kb_id = ? AND id = ?
                """,
                (kb_id, clean_doc_id),
            ).fetchone()
        if row is None:
            raise KeyError("knowledge document not found")
        path = Path(str(row["stored_path"])).resolve()
        try:
            path.relative_to(self.knowledge_root.resolve())
        except ValueError as exc:
            raise ValueError("stored knowledge document path is invalid") from exc
        if not path.is_file():
            raise ValueError("stored knowledge document file is missing")
        return KnowledgeStoredFile(
            path=path,
            filename=str(row["filename"]),
            mime_type=str(row["mime_type"] or "application/octet-stream"),
        )

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

    def _index_document_best_effort_sync(
        self,
        *,
        kb_id: str,
        doc_id: str,
        filename: str,
        text: str,
    ) -> None:
        try:
            self.knowledge_index.index_document(
                kb_id=kb_id,
                doc_id=doc_id,
                filename=filename,
                text=text,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "LightRAG indexing failed for knowledge document %s in %s; clearing stale index",
                doc_id,
                kb_id,
                exc_info=exc,
            )
            try:
                self.knowledge_index.clear_knowledge_base(kb_id)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "failed to clear LightRAG index after indexing failure for %s",
                    kb_id,
                    exc_info=True,
                )

    def _rebuild_knowledge_index_sync(self, kb_id: str) -> None:
        kb_id = _safe_kb_id(kb_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, filename, stored_path
                FROM knowledge_documents
                WHERE kb_id = ? AND status = 'ready'
                ORDER BY created_at ASC, id ASC
                """,
                (kb_id,),
            ).fetchall()
        self.knowledge_index.clear_knowledge_base(kb_id)
        for row in rows:
            stored_path = Path(str(row["stored_path"]))
            if not stored_path.is_file():
                continue
            text, _error = _extract_text(stored_path)
            if not _split_chunks(text):
                continue
            self._index_document_best_effort_sync(
                kb_id=kb_id,
                doc_id=str(row["id"]),
                filename=str(row["filename"]),
                text=text,
            )

    def _add_existing_document_sync(self, *, kb_id: str, source_doc_id: str) -> KnowledgeDocument:
        self._initialize_sync()
        kb_id = _safe_kb_id(kb_id)
        file_id = source_doc_id.strip()
        if not file_id:
            raise ValueError("knowledge file id is required")
        with self._connect() as conn:
            source_row = conn.execute(
                """
                SELECT filename, mime_type, bytes, sha256, status, error, chunk_count, stored_path
                FROM knowledge_files
                WHERE id = ?
                """,
                (file_id,),
            ).fetchone()
            if source_row is None:
                raise KeyError("knowledge file not found")
            existing_row = conn.execute(
                """
                SELECT id
                FROM knowledge_documents
                WHERE kb_id = ? AND filename = ? AND sha256 = ?
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
                """,
                (kb_id, str(source_row["filename"]), str(source_row["sha256"])),
            ).fetchone()
        if existing_row is not None:
            raise DuplicateKnowledgeDocumentError(
                f"knowledge document already exists: {str(source_row['filename'])}"
            )
        source_path = Path(str(source_row["stored_path"]))
        if not source_path.is_file():
            raise ValueError("stored knowledge document file is missing")
        suffix = Path(str(source_row["filename"])).suffix.lower() or source_path.suffix.lower()
        doc_id = _new_id("doc")
        kb_dir = self.knowledge_root / kb_id / "documents"
        kb_dir.mkdir(parents=True, exist_ok=True)
        stored_path = kb_dir / f"{doc_id}{suffix}"
        shutil.copyfile(source_path, stored_path)
        now = _utc_now()
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute(
                """
                INSERT INTO knowledge_bases(id, name, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (kb_id, kb_id, now, now),
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
                    doc_id,
                    kb_id,
                    str(source_row["filename"]),
                    str(source_row["mime_type"]),
                    int(source_row["bytes"]),
                    str(source_row["sha256"]),
                    str(source_row["status"]),
                    str(source_row["error"]) if source_row["error"] is not None else None,
                    int(source_row["chunk_count"]),
                    str(stored_path),
                    now,
                    now,
                ),
            )
            chunk_rows = conn.execute(
                """
                SELECT chunk_index, text, tokens
                FROM knowledge_file_chunks
                WHERE file_id = ?
                ORDER BY chunk_index ASC
                """,
                (file_id,),
            ).fetchall()
            for chunk_row in chunk_rows:
                conn.execute(
                    """
                    INSERT INTO knowledge_chunks(id, doc_id, kb_id, chunk_index, text, tokens)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _new_id("chunk"),
                        doc_id,
                        kb_id,
                        int(chunk_row["chunk_index"]),
                        str(chunk_row["text"]),
                        str(chunk_row["tokens"]),
                    ),
                )
        if str(source_row["status"]) == "ready" and chunk_rows:
            text = "\n\n".join(str(chunk_row["text"]) for chunk_row in chunk_rows).strip()
            self._index_document_best_effort_sync(
                kb_id=kb_id,
                doc_id=doc_id,
                filename=str(source_row["filename"]),
                text=text,
            )
        return self._get_document_sync(kb_id, doc_id)

    def _reindex_document_sync(self, kb_id: str, doc_id: str) -> KnowledgeDocument:
        self._initialize_sync()
        kb_id = _safe_kb_id(kb_id)
        stored_path = self._document_path_sync(kb_id, doc_id)
        if stored_path is None:
            raise KeyError("knowledge document not found")
        if not stored_path.is_file():
            raise ValueError("stored knowledge document file is missing")
        filename = self._get_document_sync(kb_id, doc_id).filename
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
        self.knowledge_index.delete_document(kb_id=kb_id, doc_id=doc_id)
        if status == "ready":
            self._index_document_best_effort_sync(
                kb_id=kb_id,
                doc_id=doc_id,
                filename=filename,
                text=text,
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
        try:
            Path(str(row["stored_path"])).unlink(missing_ok=True)
        except Exception as exc:
            raise ValueError("failed to delete knowledge document file") from exc
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("DELETE FROM knowledge_chunks WHERE kb_id = ? AND doc_id = ?", (kb_id, doc_id))
            conn.execute("DELETE FROM knowledge_documents WHERE kb_id = ? AND id = ?", (kb_id, doc_id))
        self._rebuild_knowledge_index_sync(kb_id)
        return True

    def _query_sync(self, kb_id: str, query: str, limit: int) -> list[KnowledgeChunk]:
        self._initialize_sync()
        kb_id = _safe_kb_id(kb_id)
        if not query.strip():
            return []
        safe_limit = min(8, max(1, int(limit)))
        chunks = self._query_lightrag_sync(kb_id, query, safe_limit)
        if chunks:
            return chunks

        if not self.use_chunk_fallback:
            return []

        return self._query_chunk_fallback_sync(kb_id, query, safe_limit)

    def _query_lightrag_sync(
        self,
        kb_id: str,
        query: str,
        safe_limit: int,
    ) -> list[KnowledgeChunk]:
        with self._connect() as conn:
            filename_rows = conn.execute(
                """
                SELECT id, filename
                FROM knowledge_documents
                WHERE kb_id = ? AND status = 'ready'
                ORDER BY updated_at DESC, created_at DESC
                """,
                (kb_id,),
            ).fetchall()
        filenames_by_doc_id = {str(row["id"]): str(row["filename"]) for row in filename_rows}
        fallback_filename = "LightRAG"
        try:
            results = self.knowledge_index.query(kb_id=kb_id, query=query, limit=safe_limit)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "LightRAG query failed for knowledge base %s; using chunk fallback if enabled",
                kb_id,
                exc_info=exc,
            )
            return []
        chunks = [
            KnowledgeChunk(
                id=_new_id("rag"),
                doc_id=result.doc_id,
                kb_id=kb_id,
                filename=filenames_by_doc_id.get(result.doc_id, fallback_filename),
                text=result.text,
                score=float(result.score),
            )
            for result in results[:safe_limit]
            if result.text.strip()
        ]
        return chunks

    def _query_chunk_fallback_sync(
        self,
        kb_id: str,
        query: str,
        safe_limit: int,
    ) -> list[KnowledgeChunk]:
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.id, c.doc_id, c.kb_id, d.filename, c.text, c.tokens
                FROM knowledge_chunks c
                JOIN knowledge_documents d ON d.id = c.doc_id
                WHERE c.kb_id = ? AND d.status = 'ready'
                ORDER BY d.updated_at DESC, c.chunk_index ASC
                """,
                (kb_id,),
            ).fetchall()
        scored: list[KnowledgeChunk] = []
        for row in rows:
            chunk_tokens = set(str(row["tokens"] or "").split())
            overlap = query_tokens & chunk_tokens
            if not overlap:
                continue
            score = len(overlap) / max(1, len(query_tokens))
            scored.append(
                KnowledgeChunk(
                    id=str(row["id"]),
                    doc_id=str(row["doc_id"]),
                    kb_id=str(row["kb_id"]),
                    filename=str(row["filename"]),
                    text=str(row["text"]),
                    score=score,
                )
            )
        scored.sort(key=lambda chunk: chunk.score, reverse=True)
        return scored[:safe_limit]

    def _query_many_sync(self, kb_ids: list[str], query: str, limit: int) -> list[KnowledgeChunk]:
        selected: list[str] = []
        seen: set[str] = set()
        for kb_id in kb_ids:
            safe_id = _safe_kb_id(kb_id)
            if safe_id in seen:
                continue
            selected.append(safe_id)
            seen.add(safe_id)
        if not selected:
            return []

        safe_limit = min(8, max(1, int(limit)))
        chunks: list[KnowledgeChunk] = []
        for kb_id in selected:
            chunks.extend(self._query_lightrag_sync(kb_id, query, safe_limit))
        chunks.sort(key=lambda chunk: chunk.score, reverse=True)
        if chunks:
            return chunks[:safe_limit]

        if not self.use_chunk_fallback:
            return []

        for kb_id in selected:
            chunks.extend(self._query_chunk_fallback_sync(kb_id, query, safe_limit))
        chunks.sort(key=lambda chunk: chunk.score, reverse=True)
        return chunks[:safe_limit]


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


def _knowledge_base_summary_from_row(row: sqlite3.Row) -> KnowledgeBaseSummary:
    return KnowledgeBaseSummary(
        id=str(row["id"]),
        name=str(row["name"]),
        document_count=int(row["document_count"]),
        ready_document_count=int(row["ready_document_count"]),
        error_document_count=int(row["error_document_count"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )
