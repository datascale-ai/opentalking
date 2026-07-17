from __future__ import annotations

from pathlib import Path


def test_asset_library_exposes_knowledge_base_tab_and_modal() -> None:
    source = Path("apps/web/src/components/AssetLibraryWorkspace.tsx").read_text(encoding="utf-8")

    assert 'type AssetTab = "exports" | "knowledge" | "memory" | "scenes" | "voices"' in source
    assert "知识库" in source
    assert "新建知识库" in source
    assert "从本地中间文件导入" in source
    assert "/agent/knowledge-bases" in source


def test_asset_library_supports_knowledge_document_actions() -> None:
    source = Path("apps/web/src/components/AssetLibraryWorkspace.tsx").read_text(encoding="utf-8")

    assert "handleUploadKnowledgeDocuments" in source
    assert "handleDeleteKnowledgeDocument" in source
    assert "handleReindexKnowledgeDocument" in source
    assert "apiPostForm<KnowledgeDocument>" in source


def test_asset_library_knowledge_documents_are_clickable_for_viewing() -> None:
    source = Path("apps/web/src/components/AssetLibraryWorkspace.tsx").read_text(encoding="utf-8")

    assert "openKnowledgeDocument" in source
    assert "/agent/knowledge-documents/${encodeURIComponent(document.id)}/file" in source
    assert "/agent/knowledge-bases/${encodeURIComponent(document.kb_id)}/documents/${encodeURIComponent(document.id)}/file" in source
    assert 'window.open(url, "_blank", "noopener,noreferrer")' in source
    assert source.count('title="查看文件"') >= 3


def test_asset_library_reuses_history_documents_in_create_and_upload_modals() -> None:
    source = Path("apps/web/src/components/AssetLibraryWorkspace.tsx").read_text(encoding="utf-8")

    knowledge_header_idx = source.index('<h2 className="text-sm font-semibold text-slate-950">知识库</h2>')
    upload_button_idx = source.index("onClick={openFilePoolUploadDialog}", knowledge_header_idx)
    create_button_idx = source.index("新建", knowledge_header_idx)
    assert upload_button_idx < create_button_idx

    assert "allKnowledgeDocuments" in source
    assert '"/agent/knowledge-documents"' in source
    assert "loadKnowledgeDocumentsForBases" not in source
    assert "Promise.all(bases.map" not in source
    assert "openFilePoolUploadDialog" in source
    assert "filePoolUploadOpen" in source
    assert "uploadFilesToFilePool" in source
    assert "handleDeleteFilePoolDocument" in source
    assert 'apiDelete(`/agent/knowledge-documents/${encodeURIComponent(document.id)}`)' in source
    assert "/documents/import" not in source
    assert 'form.append("document_ids"' in source
    assert "selectedHistoryDocumentIds" in source
    assert "uploadKnowledgeHistoryDocumentIds" not in source
    assert "添加文件到知识库" in source

    create_modal_idx = source.index("新建知识库")
    create_history_idx = source.index("历史文件", create_modal_idx)
    assert create_modal_idx < create_history_idx

    upload_modal_idx = source.index("添加文件到知识库")
    upload_files_idx = source.index("上传新文件", upload_modal_idx)
    assert "历史文件" not in source[upload_modal_idx:upload_files_idx]
    assert "onClick={openUploadKnowledgeDialog}" in source

    file_pool_modal_idx = source.index(">上传到文件池</h2>")
    file_pool_existing_idx = source.index("文件池文件", file_pool_modal_idx)
    file_pool_upload_idx = source.index("上传新文件", file_pool_modal_idx)
    assert file_pool_existing_idx < file_pool_upload_idx
    assert "allKnowledgeDocuments.map" in source[file_pool_modal_idx:file_pool_upload_idx]


def test_asset_library_limits_knowledge_upload_formats_and_normalizes_documents() -> None:
    source = Path("apps/web/src/components/AssetLibraryWorkspace.tsx").read_text(encoding="utf-8")

    assert 'const KNOWLEDGE_FILE_ACCEPT = ".txt,.md,.markdown,.pdf,.pptx,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.presentationml.presentation"' in source
    assert 'const KNOWLEDGE_FILE_FORMAT_LABEL = ".txt、.md、.markdown、.pdf、.pptx"' in source
    assert "KNOWLEDGE_FILE_HINT" in source
    assert "KNOWLEDGE_FILE_UNSUPPORTED_MESSAGE" in source
    assert "accept={KNOWLEDGE_FILE_ACCEPT}" in source
    assert source.count("{KNOWLEDGE_FILE_HINT}") >= 3
    assert "filterSupportedKnowledgeFiles" in source
    assert "unsupportedFiles.length" in source
    assert "onNotify?.(KNOWLEDGE_FILE_UNSUPPORTED_MESSAGE" in source
    assert "normalizeKnowledgeDocuments" in source
    assert "normalizeKnowledgeDocument" in source
    assert "String(record.id ??" in source
