import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  apiDelete,
  apiGet,
  apiPost,
  apiPostForm,
  buildApiDownloadUrl,
  buildApiUrl,
  createSceneComposition,
  deleteSceneBackground,
  deleteSceneComposition,
  listSceneBackgrounds,
  listSceneCompositions,
  uploadSceneBackground,
  type AvatarSummary,
  type ExportVideoItem,
  type KnowledgeBaseSummary,
  type KnowledgeBasesResponse,
  type KnowledgeDocument,
  type KnowledgeDocumentsResponse,
  type SceneBackgroundAsset,
  type SceneComposition,
} from "../lib/api";
import { MemoryPanel } from "./MemoryPanel";
import type { MemoryLibrary } from "../types";

type AssetTab = "exports" | "knowledge" | "memory" | "scenes" | "voices";
export type AssetLibraryTab = AssetTab;

type AssetLibraryWorkspaceProps = {
  refreshToken?: number;
  onNotify?: (message: string, tone?: "info" | "success" | "error") => void;
  initialTab?: AssetTab;
  activeTabOverride?: AssetTab | null;
  onActiveTabChange?: (tab: AssetTab) => void;
  memoryCharacterId?: string | null;
  memoryLibraryId?: string | null;
  memoryEnabled?: boolean;
  memoryLibraries?: MemoryLibrary[];
  profileId?: string;
  onMemoryLibrarySelect?: (libraryId: string | null) => void;
  onMemoryEnabledChange?: (enabled: boolean) => void;
  onMemoryLibrariesChange?: (libraries: MemoryLibrary[]) => void;
  onRefreshMemoryLibraries?: () => void;
  avatars?: AvatarSummary[];
  onSceneCompositionsChange?: (scenes: SceneComposition[]) => void;
  selectedSceneIdsByAvatar?: Record<string, string>;
  onSceneSelect?: (scene: SceneComposition) => void;
  onSceneClear?: (avatarId: string) => void;
  onSceneBackgroundsChange?: (backgrounds: SceneBackgroundAsset[]) => void;
};

const ASSET_TABS: { id: AssetTab; label: string; disabled?: boolean }[] = [
  { id: "exports", label: "导出视频" },
  { id: "knowledge", label: "知识库" },
  { id: "memory", label: "记忆库" },
  { id: "scenes", label: "场景资产" },
  { id: "voices", label: "声音资产", disabled: true },
];

const KIND_LABELS: Record<ExportVideoItem["kind"], string> = {
  realtime_dialogue: "实时对话",
  video_clone: "视频克隆",
  video_creation: "视频创作",
};

const KNOWLEDGE_FILE_ACCEPT = ".txt,.md,.markdown,.pdf,text/plain,text/markdown,application/pdf";
const KNOWLEDGE_FILE_EXTENSIONS = new Set([".txt", ".md", ".markdown", ".pdf"]);
const KNOWLEDGE_FILE_FORMAT_LABEL = ".txt、.md、.markdown、.pdf";
const KNOWLEDGE_FILE_HINT = `支持格式：${KNOWLEDGE_FILE_FORMAT_LABEL}`;
const KNOWLEDGE_FILE_UNSUPPORTED_MESSAGE = `仅支持 ${KNOWLEDGE_FILE_FORMAT_LABEL} 文件，已忽略不支持的文件。`;

function formatDuration(seconds: number | null): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return "-";
  const total = Math.round(seconds);
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  return `${mins}:${String(secs).padStart(2, "0")}`;
}

function formatSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let size = bytes;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size >= 10 || index === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[index]}`;
}

function formatCreatedAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function metadataLine(item: ExportVideoItem): string {
  return [
    item.model ? `模型 ${item.model}` : null,
    item.avatar_id ? `Avatar ${item.avatar_id}` : null,
    item.session_id ? `Session ${item.session_id}` : null,
  ].filter(Boolean).join(" · ") || "无关联会话信息";
}

function knowledgeStatusLabel(document: KnowledgeDocument): string {
  if (document.status === "ready") return "已索引";
  if (document.status === "error") return "索引失败";
  return document.status || "处理中";
}

function normalizeKnowledgeBases(response: KnowledgeBasesResponse): KnowledgeBaseSummary[] {
  const now = new Date(0).toISOString();
  const placeholder = (id: string): KnowledgeBaseSummary => ({
    id,
    name: id,
    document_count: 0,
    ready_document_count: 0,
    error_document_count: 0,
    created_at: now,
    updated_at: now,
  });
  const byId = new Map<string, KnowledgeBaseSummary>();
  for (const summary of response.knowledge_base_summaries ?? []) {
    if (summary.id) byId.set(summary.id, summary);
  }
  for (const item of response.knowledge_bases ?? []) {
    if (typeof item === "string") {
      const id = item.trim();
      if (id && !byId.has(id)) byId.set(id, placeholder(id));
    } else if (item?.id && !byId.has(item.id)) {
      byId.set(item.id, item);
    }
  }
  return Array.from(byId.values());
}

async function apiPatchJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(buildApiUrl(path), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (response.ok) return response.json() as Promise<T>;
  const text = await response.text();
  let detail: string | null = null;
  try {
    const parsed = JSON.parse(text) as { detail?: unknown };
    if (typeof parsed.detail === "string") detail = parsed.detail;
    else if (parsed.detail != null) detail = JSON.stringify(parsed.detail);
  } catch {
    detail = null;
  }
  throw new ApiError(response.status, detail, text);
}

function appendUniqueFiles(current: File[], incoming: File[]): File[] {
  const seen = new Set(current.map((file) => `${file.name}:${file.size}:${file.lastModified}`));
  const next = [...current];
  for (const file of incoming) {
    const key = `${file.name}:${file.size}:${file.lastModified}`;
    if (!seen.has(key)) {
      seen.add(key);
      next.push(file);
    }
  }
  return next;
}

function knowledgeFileExtension(filename: string): string {
  const dotIndex = filename.lastIndexOf(".");
  return dotIndex >= 0 ? filename.slice(dotIndex).toLowerCase() : "";
}

function filterSupportedKnowledgeFiles(files: File[]): { supportedFiles: File[]; unsupportedFiles: File[] } {
  const supportedFiles: File[] = [];
  const unsupportedFiles: File[] = [];
  for (const file of files) {
    if (KNOWLEDGE_FILE_EXTENSIONS.has(knowledgeFileExtension(file.name))) supportedFiles.push(file);
    else unsupportedFiles.push(file);
  }
  return { supportedFiles, unsupportedFiles };
}

function documentFingerprint(document: KnowledgeDocument): string {
  return `${document.filename}:${document.sha256}`;
}

function normalizeKnowledgeDocument(item: unknown, index = 0): KnowledgeDocument | null {
  if (!item || typeof item !== "object") return null;
  const record = item as Partial<KnowledgeDocument>;
  const fallbackId = `${String(record.kb_id ?? "unknown")}:${String(record.filename ?? "document")}:${index}`;
  const bytes = Number(record.bytes ?? 0);
  const chunkCount = Number(record.chunk_count ?? 0);
  return {
    id: String(record.id ?? fallbackId),
    kb_id: String(record.kb_id ?? ""),
    filename: String(record.filename ?? "未命名文件"),
    mime_type: String(record.mime_type ?? "application/octet-stream"),
    bytes: Number.isFinite(bytes) ? bytes : 0,
    sha256: String(record.sha256 ?? fallbackId),
    status: String(record.status ?? "processing"),
    error: typeof record.error === "string" ? record.error : null,
    chunk_count: Number.isFinite(chunkCount) ? chunkCount : 0,
    created_at: String(record.created_at ?? ""),
    updated_at: String(record.updated_at ?? ""),
  };
}

function normalizeKnowledgeDocuments(items: unknown): KnowledgeDocument[] {
  if (!Array.isArray(items)) return [];
  return items.flatMap((item, index) => {
    const normalized = normalizeKnowledgeDocument(item, index);
    return normalized ? [normalized] : [];
  });
}

function mergeKnowledgeDocuments(current: KnowledgeDocument[], incoming: KnowledgeDocument[]): KnowledgeDocument[] {
  return [
    ...incoming,
    ...current.filter((document) => !incoming.some((item) => item.id === document.id)),
  ];
}

export function AssetLibraryWorkspace({
  refreshToken = 0,
  onNotify,
  initialTab = "exports",
  activeTabOverride = null,
  onActiveTabChange,
  memoryCharacterId = null,
  memoryLibraryId = null,
  memoryEnabled = false,
  memoryLibraries = [],
  profileId = "default",
  onMemoryLibrarySelect,
  onMemoryEnabledChange,
  onMemoryLibrariesChange,
  onRefreshMemoryLibraries,
  avatars,
  onSceneCompositionsChange,
  selectedSceneIdsByAvatar = {},
  onSceneSelect,
  onSceneClear,
  onSceneBackgroundsChange,
}: AssetLibraryWorkspaceProps) {
  const [activeTab, setActiveTab] = useState<AssetTab>(initialTab);
  const [items, setItems] = useState<ExportVideoItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBaseSummary[]>([]);
  const [selectedKnowledgeId, setSelectedKnowledgeId] = useState<string | null>(null);
  const [knowledgeDocuments, setKnowledgeDocuments] = useState<KnowledgeDocument[]>([]);
  const [allKnowledgeDocuments, setAllKnowledgeDocuments] = useState<KnowledgeDocument[]>([]);
  const [knowledgeLoading, setKnowledgeLoading] = useState(false);
  const [allKnowledgeDocumentsLoading, setAllKnowledgeDocumentsLoading] = useState(false);
  const [documentLoading, setDocumentLoading] = useState(false);
  const [knowledgeError, setKnowledgeError] = useState<string | null>(null);
  const [knowledgeActionId, setKnowledgeActionId] = useState<string | null>(null);
  const [documentActionId, setDocumentActionId] = useState<string | null>(null);
  const [filePoolActionId, setFilePoolActionId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [filePoolUploadOpen, setFilePoolUploadOpen] = useState(false);
  const [newKnowledgeName, setNewKnowledgeName] = useState("");
  const [selectedHistoryDocumentIds, setSelectedHistoryDocumentIds] = useState<string[]>([]);
  const [newKnowledgeFiles, setNewKnowledgeFiles] = useState<File[]>([]);
  const [uploadKnowledgeFiles, setUploadKnowledgeFiles] = useState<File[]>([]);
  const [filePoolFiles, setFilePoolFiles] = useState<File[]>([]);
  const [creatingKnowledge, setCreatingKnowledge] = useState(false);
  const [filePoolUploading, setFilePoolUploading] = useState(false);
  const [memoryRefreshToken, setMemoryRefreshToken] = useState(0);
  const [sceneBackgrounds, setSceneBackgrounds] = useState<SceneBackgroundAsset[]>([]);
  const [sceneCompositions, setSceneCompositions] = useState<SceneComposition[]>([]);
  const [sceneLoading, setSceneLoading] = useState(false);
  const [sceneName, setSceneName] = useState("");
  const [sceneAvatarId, setSceneAvatarId] = useState("");
  const [sceneBackgroundId, setSceneBackgroundId] = useState("");
  const [backgroundName, setBackgroundName] = useState("");
  const [backgroundFile, setBackgroundFile] = useState<File | null>(null);
  const newKnowledgeFileInputRef = useRef<HTMLInputElement>(null);
  const uploadKnowledgeFileInputRef = useRef<HTMLInputElement>(null);
  const filePoolUploadInputRef = useRef<HTMLInputElement>(null);

  const loadExports = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await apiGet<{ items: ExportVideoItem[] }>("/exports/videos");
      setItems(result.items);
    } catch (err) {
      console.warn("load export videos failed", err);
      const detail = err instanceof ApiError ? err.detail : null;
      setError(detail || "导出视频加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadKnowledgeBases = useCallback(async () => {
    setKnowledgeLoading(true);
    setKnowledgeError(null);
    try {
      const response = await apiGet<KnowledgeBasesResponse>("/agent/knowledge-bases");
      const bases = normalizeKnowledgeBases(response);
      setKnowledgeBases(bases);
      setSelectedKnowledgeId((current) => {
        if (current && bases.some((base) => base.id === current)) return current;
        return bases[0]?.id ?? null;
      });
    } catch (err) {
      console.warn("load knowledge bases failed", err);
      const detail = err instanceof ApiError ? err.detail : null;
      setKnowledgeError(detail || "知识库加载失败");
    } finally {
      setKnowledgeLoading(false);
    }
  }, []);

  const loadKnowledgeDocuments = useCallback(async (kbId: string) => {
    setDocumentLoading(true);
    try {
      const response = await apiGet<KnowledgeDocumentsResponse>(
        `/agent/knowledge-bases/${encodeURIComponent(kbId)}/documents`,
      );
      setKnowledgeDocuments(normalizeKnowledgeDocuments(response.documents));
    } catch (err) {
      console.warn("load knowledge documents failed", err);
      const detail = err instanceof ApiError ? err.detail : null;
      onNotify?.(detail ? `知识库文件加载失败：${detail}` : "知识库文件加载失败。", "error");
      setKnowledgeDocuments([]);
    } finally {
      setDocumentLoading(false);
    }
  }, [onNotify]);

  const loadAllKnowledgeDocuments = useCallback(async () => {
    setAllKnowledgeDocumentsLoading(true);
    try {
      const response = await apiGet<KnowledgeDocumentsResponse>("/agent/knowledge-documents");
      setAllKnowledgeDocuments(normalizeKnowledgeDocuments(response.documents));
    } catch (err) {
      console.warn("load all knowledge documents failed", err);
      const detail = err instanceof ApiError ? err.detail : null;
      onNotify?.(detail ? `历史文件加载失败：${detail}` : "历史文件加载失败。", "error");
      setAllKnowledgeDocuments([]);
    } finally {
      setAllKnowledgeDocumentsLoading(false);
    }
  }, [onNotify]);

  const loadScenes = useCallback(async () => {
    setSceneLoading(true);
    try {
      const [backgrounds, scenes] = await Promise.all([
        listSceneBackgrounds(),
        listSceneCompositions(),
      ]);
      setSceneBackgrounds(backgrounds.items);
      setSceneCompositions(scenes.items);
      onSceneBackgroundsChange?.(backgrounds.items);
      onSceneCompositionsChange?.(scenes.items);
      setSceneAvatarId((current) => current || avatars?.[0]?.id || "");
    } catch (err) {
      console.warn("load scene assets failed", err);
      const detail = err instanceof ApiError ? err.detail : null;
      onNotify?.(detail ? `场景资产加载失败：${detail}` : "场景资产加载失败。", "error");
    } finally {
      setSceneLoading(false);
    }
  }, [avatars, onNotify, onSceneBackgroundsChange, onSceneCompositionsChange]);

  useEffect(() => {
    if (activeTabOverride) setActiveTab(activeTabOverride);
  }, [activeTabOverride]);

  useEffect(() => {
    if (activeTab === "exports") void loadExports();
  }, [activeTab, loadExports, refreshToken]);

  useEffect(() => {
    if (activeTab === "knowledge") {
      void loadKnowledgeBases();
      void loadAllKnowledgeDocuments();
    }
  }, [activeTab, loadAllKnowledgeDocuments, loadKnowledgeBases, refreshToken]);

  useEffect(() => {
    if (activeTab === "knowledge" && selectedKnowledgeId) {
      void loadKnowledgeDocuments(selectedKnowledgeId);
    } else if (activeTab === "knowledge") {
      setKnowledgeDocuments([]);
    }
  }, [activeTab, loadKnowledgeDocuments, selectedKnowledgeId]);

  useEffect(() => {
    if (activeTab === "scenes") void loadScenes();
  }, [activeTab, loadScenes, refreshToken]);

  const totalSize = useMemo(
    () => items.reduce((sum, item) => sum + item.size_bytes, 0),
    [items],
  );

  const selectedKnowledgeBase = useMemo(
    () => knowledgeBases.find((base) => base.id === selectedKnowledgeId) ?? null,
    [knowledgeBases, selectedKnowledgeId],
  );

  const createDisabled = (
    !newKnowledgeName.trim()
    || (newKnowledgeFiles.length === 0 && selectedHistoryDocumentIds.length === 0)
    || creatingKnowledge
  );
  const uploadDisabled = (
    !selectedKnowledgeId
    || documentActionId === "__upload__"
    || uploadKnowledgeFiles.length === 0
  );
  const filePoolUploadDisabled = filePoolUploading || filePoolFiles.length === 0;

  const handleTabChange = useCallback((tab: AssetTab) => {
    setActiveTab(tab);
    onActiveTabChange?.(tab);
  }, [onActiveTabChange]);

  const handleRefresh = useCallback(() => {
    if (activeTab === "knowledge") {
      void loadKnowledgeBases();
      void loadAllKnowledgeDocuments();
      if (selectedKnowledgeId) void loadKnowledgeDocuments(selectedKnowledgeId);
      return;
    }
    if (activeTab === "memory") {
      onRefreshMemoryLibraries?.();
      setMemoryRefreshToken((value) => value + 1);
      return;
    }
    if (activeTab === "scenes") {
      void loadScenes();
      return;
    }
    if (activeTab === "exports") void loadExports();
  }, [activeTab, loadAllKnowledgeDocuments, loadExports, loadKnowledgeBases, loadKnowledgeDocuments, loadScenes, onRefreshMemoryLibraries, selectedKnowledgeId]);

  const handleCopyPath = useCallback(async (path: string) => {
    try {
      await navigator.clipboard.writeText(path);
      onNotify?.("已复制服务端存放路径。", "success");
    } catch {
      onNotify?.("复制失败，请手动选择路径。", "error");
    }
  }, [onNotify]);

  const openCreateKnowledgeDialog = useCallback(() => {
    setCreateOpen(true);
    void loadAllKnowledgeDocuments();
  }, [loadAllKnowledgeDocuments]);

  const closeCreateKnowledgeDialog = useCallback(() => {
    if (creatingKnowledge) return;
    setCreateOpen(false);
  }, [creatingKnowledge]);

  const openFilePoolUploadDialog = useCallback(() => {
    setFilePoolUploadOpen(true);
    setFilePoolFiles([]);
    void loadAllKnowledgeDocuments();
    if (filePoolUploadInputRef.current) filePoolUploadInputRef.current.value = "";
  }, [loadAllKnowledgeDocuments]);

  const closeFilePoolUploadDialog = useCallback(() => {
    if (filePoolUploading) return;
    setFilePoolUploadOpen(false);
    setFilePoolFiles([]);
    if (filePoolUploadInputRef.current) filePoolUploadInputRef.current.value = "";
  }, [filePoolUploading]);

  const openUploadKnowledgeDialog = useCallback(() => {
    if (!selectedKnowledgeBase) return;
    setUploadOpen(true);
    setUploadKnowledgeFiles([]);
    if (uploadKnowledgeFileInputRef.current) uploadKnowledgeFileInputRef.current.value = "";
  }, [selectedKnowledgeBase]);

  const closeUploadKnowledgeDialog = useCallback(() => {
    if (documentActionId === "__upload__") return;
    setUploadOpen(false);
    setUploadKnowledgeFiles([]);
    if (uploadKnowledgeFileInputRef.current) uploadKnowledgeFileInputRef.current.value = "";
  }, [documentActionId]);

  const toggleDocumentId = useCallback((
    current: string[],
    documentId: string,
    setter: (next: string[]) => void,
  ) => {
    setter(
      current.includes(documentId)
        ? current.filter((id) => id !== documentId)
        : [...current, documentId],
    );
  }, []);

  const uploadFilesToFilePool = useCallback(async (files: File[]) => {
    const uploaded: KnowledgeDocument[] = [];
    for (const file of files) {
      const form = new FormData();
      form.set("file", file);
      const document = await apiPostForm<KnowledgeDocument>("/agent/knowledge-documents", form);
      const normalized = normalizeKnowledgeDocument(document, uploaded.length);
      if (normalized) uploaded.push(normalized);
    }
    if (uploaded.length) {
      setAllKnowledgeDocuments((prev) => mergeKnowledgeDocuments(prev, uploaded));
    }
    return uploaded;
  }, []);

  const handleDelete = useCallback(async (item: ExportVideoItem) => {
    const confirmed = window.confirm(`删除导出视频「${item.title}」？此操作会删除服务端文件目录。`);
    if (!confirmed) return;
    setDeletingId(item.id);
    try {
      await apiDelete(`/exports/videos/${item.id}`);
      setItems((prev) => prev.filter((candidate) => candidate.id !== item.id));
      onNotify?.("导出视频已删除。", "success");
    } catch (err) {
      console.warn("delete export video failed", err);
      const detail = err instanceof ApiError ? err.detail : null;
      onNotify?.(detail ? `删除失败：${detail}` : "删除失败，请稍后重试。", "error");
    } finally {
      setDeletingId(null);
    }
  }, [onNotify]);

  const handleCreateKnowledgeBase = useCallback(async () => {
    if (createDisabled) return;
    setCreatingKnowledge(true);
    try {
      const uploadedPoolFiles = newKnowledgeFiles.length
        ? await uploadFilesToFilePool(newKnowledgeFiles)
        : [];
      const documentIds = Array.from(new Set([
        ...selectedHistoryDocumentIds,
        ...uploadedPoolFiles.map((document) => document.id),
      ]));
      const form = new FormData();
      form.set("name", newKnowledgeName.trim());
      for (const docId of documentIds) form.append("document_ids", docId);
      const created = await apiPostForm<KnowledgeBaseSummary>("/agent/knowledge-bases", form);
      setKnowledgeBases((prev) => [...prev.filter((base) => base.id !== created.id), created]);
      setSelectedKnowledgeId(created.id);
      setCreateOpen(false);
      setNewKnowledgeName("");
      setSelectedHistoryDocumentIds([]);
      setNewKnowledgeFiles([]);
      onNotify?.("知识库已创建。", "success");
      void loadKnowledgeBases();
      void loadKnowledgeDocuments(created.id);
      void loadAllKnowledgeDocuments();
    } catch (err) {
      console.warn("create knowledge base failed", err);
      const detail = err instanceof ApiError ? err.detail : null;
      onNotify?.(detail ? `创建失败：${detail}` : "创建失败，请稍后重试。", "error");
    } finally {
      setCreatingKnowledge(false);
    }
  }, [
    createDisabled,
    loadAllKnowledgeDocuments,
    loadKnowledgeBases,
    loadKnowledgeDocuments,
    newKnowledgeFiles,
    newKnowledgeName,
    onNotify,
    selectedHistoryDocumentIds,
    uploadFilesToFilePool,
  ]);

  const handleRenameKnowledgeBase = useCallback(async (base: KnowledgeBaseSummary) => {
    const nextName = window.prompt("知识库名称", base.name)?.trim();
    if (!nextName || nextName === base.name) return;
    setKnowledgeActionId(base.id);
    try {
      const updated = await apiPatchJson<KnowledgeBaseSummary>(
        `/agent/knowledge-bases/${encodeURIComponent(base.id)}`,
        { name: nextName },
      );
      setKnowledgeBases((prev) => prev.map((item) => item.id === updated.id ? updated : item));
      onNotify?.("知识库已重命名。", "success");
    } catch (err) {
      console.warn("rename knowledge base failed", err);
      const detail = err instanceof ApiError ? err.detail : null;
      onNotify?.(detail ? `重命名失败：${detail}` : "重命名失败，请稍后重试。", "error");
    } finally {
      setKnowledgeActionId(null);
    }
  }, [onNotify]);

  const handleDeleteKnowledgeBase = useCallback(async (base: KnowledgeBaseSummary) => {
    const confirmed = window.confirm(`删除知识库「${base.name}」？此操作会删除其中的文件。`);
    if (!confirmed) return;
    setKnowledgeActionId(base.id);
    try {
      await apiDelete<{ deleted: boolean }>(`/agent/knowledge-bases/${encodeURIComponent(base.id)}`);
      setKnowledgeBases((prev) => prev.filter((item) => item.id !== base.id));
      setSelectedKnowledgeId((current) => current === base.id ? null : current);
      setKnowledgeDocuments((prev) => selectedKnowledgeId === base.id ? [] : prev);
      onNotify?.("知识库已删除。", "success");
      void loadKnowledgeBases();
      void loadAllKnowledgeDocuments();
    } catch (err) {
      console.warn("delete knowledge base failed", err);
      const detail = err instanceof ApiError ? err.detail : null;
      onNotify?.(detail ? `删除失败：${detail}` : "删除失败，请稍后重试。", "error");
    } finally {
      setKnowledgeActionId(null);
    }
  }, [loadAllKnowledgeDocuments, loadKnowledgeBases, onNotify, selectedKnowledgeId]);

  const handleDeleteFilePoolDocument = useCallback(async (document: KnowledgeDocument) => {
    const confirmed = window.confirm(`删除文件池文件「${document.filename}」？如果文件已导入知识库，需要先删除对应知识库。`);
    if (!confirmed) return;
    setFilePoolActionId(document.id);
    try {
      await apiDelete(`/agent/knowledge-documents/${encodeURIComponent(document.id)}`);
      setAllKnowledgeDocuments((prev) => prev.filter((item) => item.id !== document.id));
      onNotify?.("文件池文件已删除。", "success");
    } catch (err) {
      console.warn("delete file pool document failed", err);
      const detail = err instanceof ApiError ? err.detail : null;
      onNotify?.(detail ? `删除失败：${detail}` : "删除失败，请稍后重试。", "error");
    } finally {
      setFilePoolActionId(null);
    }
  }, [onNotify]);

  const handleUploadFilePoolDocuments = useCallback(async () => {
    if (filePoolUploadDisabled) return;
    setFilePoolUploading(true);
    try {
      await uploadFilesToFilePool(filePoolFiles);
      onNotify?.("文件已上传到文件池。", "success");
      setFilePoolUploadOpen(false);
      setFilePoolFiles([]);
      void loadAllKnowledgeDocuments();
      if (filePoolUploadInputRef.current) filePoolUploadInputRef.current.value = "";
    } catch (err) {
      console.warn("upload file pool documents failed", err);
      const detail = err instanceof ApiError ? err.detail : null;
      onNotify?.(detail ? `上传失败：${detail}` : "上传失败，请稍后重试。", "error");
    } finally {
      setFilePoolUploading(false);
    }
  }, [filePoolFiles, filePoolUploadDisabled, loadAllKnowledgeDocuments, onNotify, uploadFilesToFilePool]);

  const handleUploadSceneBackground = useCallback(async () => {
    if (!backgroundFile) return;
    try {
      const uploaded = await uploadSceneBackground({
        file: backgroundFile,
        name: backgroundName.trim() || backgroundFile.name,
      });
      const nextBackgrounds = [uploaded, ...sceneBackgrounds.filter((item) => item.id !== uploaded.id)];
      setSceneBackgrounds(nextBackgrounds);
      onSceneBackgroundsChange?.(nextBackgrounds);
      setBackgroundFile(null);
      setBackgroundName("");
      onNotify?.("背景资产已上传。", "success");
    } catch (err) {
      console.warn("upload scene background failed", err);
      const detail = err instanceof ApiError ? err.detail : null;
      onNotify?.(detail ? `上传失败：${detail}` : "上传失败，请稍后重试。", "error");
    }
  }, [backgroundFile, backgroundName, onNotify, onSceneBackgroundsChange, sceneBackgrounds]);

  const handleCreateSceneComposition = useCallback(async () => {
    if (!sceneName.trim() || !sceneAvatarId) return;
    try {
      const created = await createSceneComposition({
        name: sceneName.trim(),
        avatar_id: sceneAvatarId,
        background_id: sceneBackgroundId || null,
        avatar_fit: "contain",
        avatar_scale: 1,
        avatar_anchor: "center",
        matting_required: true,
        subtitle_style: "lower-third",
      });
      const nextScenes = [created, ...sceneCompositions.filter((item) => item.id !== created.id)];
      setSceneCompositions(nextScenes);
      onSceneCompositionsChange?.(nextScenes);
      onSceneSelect?.(created);
      setSceneName("");
      onNotify?.("场景组合已创建。", "success");
    } catch (err) {
      console.warn("create scene composition failed", err);
      const detail = err instanceof ApiError ? err.detail : null;
      onNotify?.(detail ? `创建失败：${detail}` : "创建失败，请稍后重试。", "error");
    }
  }, [onNotify, onSceneCompositionsChange, onSceneSelect, sceneAvatarId, sceneBackgroundId, sceneCompositions, sceneName]);

  const handleDeleteSceneBackground = useCallback(async (background: SceneBackgroundAsset) => {
    try {
      await deleteSceneBackground(background.id);
      await loadScenes();
      onNotify?.("背景资产已删除。", "success");
    } catch (err) {
      console.warn("delete scene background failed", err);
      const detail = err instanceof ApiError ? err.detail : null;
      onNotify?.(detail ? `删除失败：${detail}` : "删除失败，请稍后重试。", "error");
    }
  }, [loadScenes, onNotify]);

  const handleDeleteSceneComposition = useCallback(async (scene: SceneComposition) => {
    try {
      await deleteSceneComposition(scene.id);
      await loadScenes();
      onNotify?.("场景组合已删除。", "success");
    } catch (err) {
      console.warn("delete scene composition failed", err);
      const detail = err instanceof ApiError ? err.detail : null;
      onNotify?.(detail ? `删除失败：${detail}` : "删除失败，请稍后重试。", "error");
    }
  }, [loadScenes, onNotify]);

  const handleUploadKnowledgeDocuments = useCallback(async () => {
    if (!selectedKnowledgeId || uploadDisabled) return;
    setDocumentActionId("__upload__");
    try {
      const uploaded: KnowledgeDocument[] = [];
      for (const file of uploadKnowledgeFiles) {
        const form = new FormData();
        form.set("file", file);
        const document = await apiPostForm<KnowledgeDocument>(
          `/agent/knowledge-bases/${encodeURIComponent(selectedKnowledgeId)}/documents`,
          form,
        );
        const normalized = normalizeKnowledgeDocument(document, uploaded.length);
        if (normalized) uploaded.push(normalized);
      }
      setKnowledgeDocuments((prev) => [
        ...uploaded,
        ...prev.filter((document) => !uploaded.some((item) => item.id === document.id)),
      ]);
      onNotify?.("知识库文件已添加。", "success");
      setUploadOpen(false);
      setUploadKnowledgeFiles([]);
      void loadKnowledgeBases();
      void loadKnowledgeDocuments(selectedKnowledgeId);
      if (uploadKnowledgeFileInputRef.current) uploadKnowledgeFileInputRef.current.value = "";
    } catch (err) {
      console.warn("upload knowledge documents failed", err);
      const detail = err instanceof ApiError ? err.detail : null;
      onNotify?.(detail ? `上传失败：${detail}` : "上传失败，请稍后重试。", "error");
    } finally {
      setDocumentActionId(null);
    }
  }, [
    loadAllKnowledgeDocuments,
    loadKnowledgeBases,
    loadKnowledgeDocuments,
    onNotify,
    selectedKnowledgeId,
    uploadDisabled,
    uploadKnowledgeFiles,
  ]);

  const handleDeleteKnowledgeDocument = useCallback(async (document: KnowledgeDocument) => {
    if (!selectedKnowledgeId) return;
    const confirmed = window.confirm(`删除文件「${document.filename}」？`);
    if (!confirmed) return;
    setDocumentActionId(document.id);
    try {
      await apiDelete<{ deleted: boolean }>(
        `/agent/knowledge-bases/${encodeURIComponent(selectedKnowledgeId)}/documents/${encodeURIComponent(document.id)}`,
      );
      setKnowledgeDocuments((prev) => prev.filter((item) => item.id !== document.id));
      onNotify?.("知识库文件已删除。", "success");
      void loadKnowledgeBases();
      void loadAllKnowledgeDocuments();
    } catch (err) {
      console.warn("delete knowledge document failed", err);
      const detail = err instanceof ApiError ? err.detail : null;
      onNotify?.(detail ? `删除失败：${detail}` : "删除失败，请稍后重试。", "error");
    } finally {
      setDocumentActionId(null);
    }
  }, [loadAllKnowledgeDocuments, loadKnowledgeBases, onNotify, selectedKnowledgeId]);

  const handleReindexKnowledgeDocument = useCallback(async (document: KnowledgeDocument) => {
    if (!selectedKnowledgeId) return;
    setDocumentActionId(document.id);
    try {
      const updated = await apiPost<KnowledgeDocument>(
        `/agent/knowledge-bases/${encodeURIComponent(selectedKnowledgeId)}/documents/${encodeURIComponent(document.id)}/reindex`,
      );
      const normalized = normalizeKnowledgeDocument(updated);
      if (normalized) {
        setKnowledgeDocuments((prev) => prev.map((item) => item.id === normalized.id ? normalized : item));
      }
      onNotify?.("知识库文件已重建索引。", "success");
      void loadKnowledgeBases();
      void loadAllKnowledgeDocuments();
    } catch (err) {
      console.warn("reindex knowledge document failed", err);
      const detail = err instanceof ApiError ? err.detail : null;
      onNotify?.(detail ? `重建失败：${detail}` : "重建失败，请稍后重试。", "error");
    } finally {
      setDocumentActionId(null);
    }
  }, [loadAllKnowledgeDocuments, loadKnowledgeBases, onNotify, selectedKnowledgeId]);

  const renderHistoryDocumentOptions = ({
    selectedIds,
    onToggle,
    disabledFingerprints,
    busy = false,
  }: {
    selectedIds: string[];
    onToggle: (documentId: string) => void;
    disabledFingerprints?: Set<string>;
    busy?: boolean;
  }) => (
    <div className="mt-2 max-h-44 space-y-2 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 p-2">
      {allKnowledgeDocumentsLoading ? (
        <div className="flex min-h-20 items-center justify-center text-sm font-medium text-slate-500">
          历史文件加载中...
        </div>
      ) : allKnowledgeDocuments.length ? (
        allKnowledgeDocuments.map((document) => {
          const alreadyAdded = Boolean(disabledFingerprints?.has(documentFingerprint(document)));
          const checked = alreadyAdded || selectedIds.includes(document.id);
          return (
            <label
              key={document.id}
              className={`flex cursor-pointer items-start gap-2 rounded-md bg-white px-3 py-2 text-sm ${
                alreadyAdded ? "opacity-70" : ""
              }`}
            >
              <input
                type="checkbox"
                checked={checked}
                disabled={busy || alreadyAdded}
                onChange={() => onToggle(document.id)}
                className="mt-0.5 h-4 w-4 shrink-0 rounded border-slate-300 text-cyan-600 focus:ring-cyan-500 disabled:cursor-not-allowed"
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-semibold text-slate-800">{document.filename}</span>
                <span className="mt-0.5 block truncate text-xs text-slate-500">
                  {formatSize(document.bytes)} · {knowledgeStatusLabel(document)} · 来自 {document.kb_id}
                </span>
              </span>
              {alreadyAdded ? (
                <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-500">
                  已存在
                </span>
              ) : null}
            </label>
          );
        })
      ) : (
        <div className="flex min-h-20 items-center justify-center text-sm font-medium text-slate-500">
          暂无历史文件
        </div>
      )}
    </div>
  );

  const renderKnowledgeTab = () => (
    <div className="grid min-h-[24rem] gap-4 xl:grid-cols-[20rem_minmax(0,1fr)]">
      <aside className="min-h-0 rounded-lg border border-slate-200 bg-white">
        <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-3 py-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-950">知识库</h2>
            <p className="text-xs text-slate-500">{knowledgeBases.length} 个分类</p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              disabled={filePoolUploading}
              onClick={openFilePoolUploadDialog}
              className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-cyan-200 hover:text-cyan-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {filePoolUploading ? "上传中..." : "上传文件"}
            </button>
            <button
              type="button"
              onClick={openCreateKnowledgeDialog}
              className="rounded-lg bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-cyan-500"
            >
              新建
            </button>
          </div>
        </div>
        <div className="max-h-[32rem] space-y-2 overflow-y-auto p-3">
          {knowledgeError ? (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm font-medium text-red-700">{knowledgeError}</div>
          ) : null}
          {!knowledgeLoading && !knowledgeBases.length ? (
            <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-center text-sm font-medium text-slate-500">
              暂无知识库
            </div>
          ) : null}
          {knowledgeBases.map((base) => {
            const selected = base.id === selectedKnowledgeId;
            return (
              <button
                key={base.id}
                type="button"
                onClick={() => setSelectedKnowledgeId(base.id)}
                className={`w-full rounded-lg border p-3 text-left transition ${
                  selected
                    ? "border-cyan-300 bg-cyan-50 text-cyan-800"
                    : "border-slate-200 bg-white text-slate-700 hover:border-slate-300"
                }`}
              >
                <span className="block truncate text-sm font-semibold">{base.name}</span>
                <span className="mt-1 block text-xs text-slate-500">
                  {base.document_count} 文件 · {base.ready_document_count} 可用 · {base.error_document_count} 异常
                </span>
                <span className="mt-1 block truncate text-[11px] text-slate-400">{base.id}</span>
              </button>
            );
          })}
        </div>
      </aside>

      <section className="min-w-0 rounded-lg border border-slate-200 bg-white">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 px-4 py-3">
          <div className="min-w-0">
            <h2 className="truncate text-sm font-semibold text-slate-950">{selectedKnowledgeBase?.name ?? "知识库"}</h2>
            <p className="mt-1 text-xs text-slate-500">
              {selectedKnowledgeBase ? `${formatCreatedAt(selectedKnowledgeBase.updated_at)} 更新` : "未选择知识库"}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => onNotify?.("LightRAG 中间文件导入后续适配。", "info")}
              className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-cyan-200 hover:text-cyan-700"
            >
              从本地中间文件导入
            </button>
            <button
              type="button"
              disabled={!selectedKnowledgeBase || documentActionId === "__upload__"}
              onClick={openUploadKnowledgeDialog}
              className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-cyan-200 hover:text-cyan-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {documentActionId === "__upload__" ? "上传中..." : "上传文件"}
            </button>
            <button
              type="button"
              disabled={!selectedKnowledgeBase || knowledgeActionId === selectedKnowledgeBase.id}
              onClick={() => selectedKnowledgeBase ? void handleRenameKnowledgeBase(selectedKnowledgeBase) : undefined}
              className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-cyan-200 hover:text-cyan-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              重命名
            </button>
            <button
              type="button"
              disabled={!selectedKnowledgeBase || knowledgeActionId === selectedKnowledgeBase.id}
              onClick={() => selectedKnowledgeBase ? void handleDeleteKnowledgeBase(selectedKnowledgeBase) : undefined}
              className="rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-semibold text-red-700 transition hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              删除
            </button>
          </div>
        </div>

        <div className="min-h-[20rem] p-4">
          {documentLoading ? (
            <div className="flex min-h-[18rem] items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50 text-sm font-medium text-slate-500">
              文件加载中...
            </div>
          ) : !selectedKnowledgeBase ? (
            <div className="flex min-h-[18rem] items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50 text-sm font-medium text-slate-500">
              请选择知识库
            </div>
          ) : knowledgeDocuments.length ? (
            <div className="space-y-2">
              {knowledgeDocuments.map((document) => (
                <article key={document.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white p-3">
                  <div className="min-w-0">
                    <h3 className="truncate text-sm font-semibold text-slate-950">{document.filename}</h3>
                    <p className="mt-1 text-xs text-slate-500">
                      {formatSize(document.bytes)} · {knowledgeStatusLabel(document)} · {document.chunk_count} chunks
                    </p>
                    {document.error ? <p className="mt-1 break-words text-xs text-red-600">{document.error}</p> : null}
                  </div>
                  <div className="flex shrink-0 flex-wrap gap-2">
                    <button
                      type="button"
                      disabled={documentActionId === document.id}
                      onClick={() => void handleReindexKnowledgeDocument(document)}
                      className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-cyan-200 hover:text-cyan-700 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      重建索引
                    </button>
                    <button
                      type="button"
                      disabled={documentActionId === document.id}
                      onClick={() => void handleDeleteKnowledgeDocument(document)}
                      className="rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-semibold text-red-700 transition hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      删除
                    </button>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="flex min-h-[18rem] items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50 text-sm font-medium text-slate-500">
              暂无文件
            </div>
          )}
        </div>
      </section>
    </div>
  );

  const renderMemoryTab = () => (
    <MemoryPanel
      mode="manage"
      characterId={memoryCharacterId}
      selectedLibraryId={memoryLibraryId}
      memoryEnabled={memoryEnabled}
      profileId={profileId}
      refreshToken={memoryRefreshToken}
      onLibrarySelect={onMemoryLibrarySelect ?? (() => undefined)}
      onMemoryEnabledChange={onMemoryEnabledChange}
      onLibrariesChange={onMemoryLibrariesChange}
    />
  );

  const avatarById = useMemo(() => new Map((avatars ?? []).map((avatar) => [avatar.id, avatar])), [avatars]);
  const sceneGroups = useMemo(() => {
    const avatarGroups = (avatars ?? [])
      .map((avatar) => ({
        avatar,
        scenes: sceneCompositions.filter((scene) => scene.avatar_id === avatar.id),
      }))
      .filter((group) => group.scenes.length > 0);
    const knownAvatarIds = new Set((avatars ?? []).map((avatar) => avatar.id));
    const orphanScenes = sceneCompositions.filter((scene) => !knownAvatarIds.has(scene.avatar_id));
    if (orphanScenes.length > 0) {
      avatarGroups.push({
        avatar: { id: "__unknown__", name: "未识别形象" } as AvatarSummary,
        scenes: orphanScenes,
      });
    }
    return avatarGroups;
  }, [avatars, sceneCompositions]);

  const renderScenesTab = () => (
    <div className="grid min-h-[24rem] gap-4 xl:grid-cols-[22rem_minmax(0,1fr)]">
      <aside className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-950">背景资产</h2>
        <p className="mt-1 text-xs leading-relaxed text-slate-500">
          背景是资产库能力，可被工作台、沉浸模式和后续视频创作复用。
        </p>
        <div className="mt-4 space-y-3">
          <label className="block text-xs font-semibold text-slate-600" htmlFor="scene-background-name">
            背景名称
          </label>
          <input
            id="scene-background-name"
            value={backgroundName}
            onChange={(event) => setBackgroundName(event.target.value)}
            className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none focus:border-cyan-300 focus:bg-white"
          />
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp,video/mp4,video/webm,video/quicktime"
            onChange={(event) => setBackgroundFile(event.currentTarget.files?.[0] ?? null)}
            className="block w-full text-xs text-slate-600"
          />
          <button
            type="button"
            disabled={!backgroundFile}
            onClick={() => void handleUploadSceneBackground()}
            className="w-full rounded-lg bg-cyan-600 px-3 py-2 text-sm font-semibold text-white transition hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            上传背景
          </button>
        </div>
        <div className="mt-5 space-y-2">
          {sceneLoading ? (
            <p className="text-sm text-slate-500">背景资产加载中...</p>
          ) : sceneBackgrounds.length ? sceneBackgrounds.map((background) => (
            <div key={background.id} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
              <p className="truncate text-sm font-semibold text-slate-900">{background.name}</p>
              <p className="mt-1 text-xs text-slate-500">{background.kind} · {formatSize(background.size_bytes)}</p>
              <button
                type="button"
                onClick={() => void handleDeleteSceneBackground(background)}
                className="mt-2 text-xs font-semibold text-rose-600 hover:text-rose-500"
              >
                删除
              </button>
            </div>
          )) : (
            <p className="rounded-lg border border-dashed border-slate-200 bg-slate-50 p-4 text-center text-sm text-slate-500">
              暂无背景资产
            </p>
          )}
        </div>
      </aside>
      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-950">场景组合</h2>
        <p className="mt-1 text-xs leading-relaxed text-slate-500">
          场景组合保存数字人、背景、构图和字幕样式，可在实时对话和沉浸模式中复用。
        </p>
        <div className="mt-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_12rem_12rem_auto] md:items-end">
          <label className="block text-xs font-semibold text-slate-600">
            场景名称
            <input
              value={sceneName}
              onChange={(event) => setSceneName(event.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none focus:border-cyan-300 focus:bg-white"
            />
          </label>
          <label className="block text-xs font-semibold text-slate-600">
            数字人
            <select
              value={sceneAvatarId}
              onChange={(event) => setSceneAvatarId(event.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
            >
              {(avatars ?? []).map((avatar) => (
                <option key={avatar.id} value={avatar.id}>{avatar.name ?? avatar.id}</option>
              ))}
            </select>
          </label>
          <label className="block text-xs font-semibold text-slate-600">
            背景
            <select
              value={sceneBackgroundId}
              onChange={(event) => setSceneBackgroundId(event.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
            >
              <option value="">纯色背景</option>
              {sceneBackgrounds.map((background) => (
                <option key={background.id} value={background.id}>{background.name}</option>
              ))}
            </select>
          </label>
          <button
            type="button"
            disabled={!sceneName.trim() || !sceneAvatarId}
            onClick={() => void handleCreateSceneComposition()}
            className="rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            创建
          </button>
        </div>
        <div className="mt-5 space-y-4">
          {sceneGroups.length ? sceneGroups.map(({ avatar, scenes }) => (
            <section key={avatar.id} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="text-sm font-semibold text-slate-950">{avatar.name ?? avatar.id}</p>
                  <p className="text-xs text-slate-500">{scenes.length} 个场景组合</p>
                </div>
                {selectedSceneIdsByAvatar[avatar.id] ? (
                  <button
                    type="button"
                    onClick={() => onSceneClear?.(avatar.id)}
                    className="text-xs font-semibold text-slate-500 hover:text-slate-800"
                  >
                    取消默认
                  </button>
                ) : null}
              </div>
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {scenes.map((scene) => {
                  const selected = selectedSceneIdsByAvatar[scene.avatar_id] === scene.id;
                  const sceneAvatar = avatarById.get(scene.avatar_id);
                  return (
                    <article
                      key={scene.id}
                      className={`rounded-lg border p-3 transition ${
                        selected
                          ? "border-cyan-300 bg-cyan-50"
                          : "border-slate-200 bg-white"
                      }`}
                    >
                      <p className="truncate text-sm font-semibold text-slate-950">{scene.name}</p>
                      <p className="mt-1 truncate text-xs text-slate-500">Avatar {sceneAvatar?.name ?? scene.avatar_id}</p>
                      <p className="mt-1 truncate text-xs text-slate-500">Background {scene.background_id ?? scene.background_color}</p>
                      <div className="mt-3 flex items-center gap-3">
                        <button
                          type="button"
                          aria-pressed={selected}
                          onClick={() => onSceneSelect?.(scene)}
                          className={`text-xs font-semibold ${
                            selected ? "text-cyan-800" : "text-cyan-700 hover:text-cyan-600"
                          }`}
                        >
                          {selected ? "当前默认" : "设为默认"}
                        </button>
                        <button
                          type="button"
                          onClick={() => void handleDeleteSceneComposition(scene)}
                          className="text-xs font-semibold text-rose-600 hover:text-rose-500"
                        >
                          删除
                        </button>
                      </div>
                    </article>
                  );
                })}
              </div>
            </section>
          )) : (
            <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-500">
              暂无场景组合
            </div>
          )}
        </div>
      </section>
    </div>
  );

  return (
    <main className="flex min-h-0 flex-1 flex-col bg-slate-100 p-4">
      <section className="flex min-h-0 flex-1 flex-col rounded-lg border border-slate-200 bg-white shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
          <div>
            <p className="text-xs font-medium text-slate-500">Asset Library</p>
            <h1 className="text-base font-semibold text-slate-950">资产库</h1>
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-500">
            {activeTab === "knowledge" ? (
              <>
                <span>{knowledgeBases.length} 个知识库</span>
                <span>{knowledgeDocuments.length} 个文件</span>
              </>
            ) : activeTab === "memory" ? (
              <>
                <span>{memoryLibraries.length} 个记忆库</span>
                <span>{memoryLibraries.reduce((sum, library) => sum + library.memory_count, 0)} 条记忆</span>
              </>
            ) : activeTab === "scenes" ? (
              <>
                <span>{sceneBackgrounds.length} 个背景</span>
                <span>{sceneCompositions.length} 个组合</span>
              </>
            ) : (
              <>
                <span>{items.length} 个导出</span>
                <span>{formatSize(totalSize)}</span>
              </>
            )}
            <button
              type="button"
              onClick={handleRefresh}
              disabled={activeTab === "knowledge" ? knowledgeLoading : activeTab === "scenes" ? sceneLoading : loading}
              className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 font-semibold text-slate-700 transition hover:border-cyan-200 hover:text-cyan-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {(activeTab === "knowledge" ? knowledgeLoading : activeTab === "scenes" ? sceneLoading : loading) ? "刷新中..." : "刷新"}
            </button>
          </div>
        </div>

        <div className="border-b border-slate-200 px-4 py-3">
          <div className="flex flex-wrap gap-2" role="tablist" aria-label="资产类型">
            {ASSET_TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                disabled={tab.disabled}
                onClick={() => handleTabChange(tab.id)}
                className={`rounded-lg border px-3 py-2 text-sm font-semibold transition ${
                  activeTab === tab.id
                    ? "border-cyan-300 bg-cyan-50 text-cyan-700"
                    : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"
                } disabled:cursor-not-allowed disabled:border-slate-100 disabled:bg-slate-50 disabled:text-slate-400`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {activeTab === "exports" ? (
            <div className="space-y-3">
              {error ? (
                <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm font-medium text-red-700">{error}</div>
              ) : null}
              {!loading && !items.length ? (
                <div className="flex min-h-[18rem] items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50 text-sm font-medium text-slate-500">
                  暂无导出视频
                </div>
              ) : null}
              {items.map((item) => (
                <article key={item.id} className="grid gap-3 rounded-lg border border-slate-200 bg-white p-3 shadow-sm lg:grid-cols-[14rem_minmax(0,1fr)]">
                  <video
                    className="aspect-video w-full rounded-md border border-slate-200 bg-slate-950 object-contain"
                    src={buildApiDownloadUrl(item.download_url)}
                    muted
                    controls
                    preload="metadata"
                  />
                  <div className="min-w-0 space-y-3">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <h2 className="truncate text-sm font-semibold text-slate-950">{item.title}</h2>
                        <p className="mt-1 text-xs text-slate-500">{KIND_LABELS[item.kind]} · {formatDuration(item.duration_sec)} · {formatSize(item.size_bytes)} · {formatCreatedAt(item.created_at)}</p>
                      </div>
                      <div className="flex shrink-0 flex-wrap gap-2">
                        <a
                          href={buildApiDownloadUrl(item.download_url)}
                          download
                          className="rounded-lg bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-cyan-500"
                        >
                          下载
                        </a>
                        <button
                          type="button"
                          onClick={() => void handleCopyPath(item.path)}
                          className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-cyan-200 hover:text-cyan-700"
                        >
                          复制路径
                        </button>
                        <button
                          type="button"
                          disabled={deletingId === item.id}
                          onClick={() => void handleDelete(item)}
                          className="rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-semibold text-red-700 transition hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {deletingId === item.id ? "删除中..." : "删除"}
                        </button>
                      </div>
                    </div>
                    <div className="grid gap-2 text-xs text-slate-600 md:grid-cols-2">
                      <div className="rounded-lg bg-slate-50 p-2">
                        <p className="font-semibold text-slate-500">存放路径</p>
                        <p className="mt-1 break-all font-mono text-[11px] text-slate-800">{item.path}</p>
                      </div>
                      <div className="rounded-lg bg-slate-50 p-2">
                        <p className="font-semibold text-slate-500">关联信息</p>
                        <p className="mt-1 break-words text-slate-800">{metadataLine(item)}</p>
                      </div>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          ) : activeTab === "knowledge" ? (
            renderKnowledgeTab()
          ) : activeTab === "memory" ? (
            renderMemoryTab()
          ) : activeTab === "scenes" ? (
            renderScenesTab()
          ) : (
            <div className="flex min-h-[18rem] items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50 text-sm font-medium text-slate-500">
              声音资产管理规划中
            </div>
          )}
        </div>
      </section>

      {createOpen ? (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/40 p-4">
          <div className="w-full max-w-lg rounded-lg bg-white shadow-xl">
            <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
              <h2 className="text-base font-semibold text-slate-950">新建知识库</h2>
              <button
                type="button"
                onClick={closeCreateKnowledgeDialog}
                className="rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-sm font-semibold text-slate-600 hover:border-slate-300"
              >
                关闭
              </button>
            </div>
            <div className="space-y-4 p-4">
              <label className="block text-sm font-semibold text-slate-700">
                名称
                <input
                  type="text"
                  value={newKnowledgeName}
                  onChange={(event) => setNewKnowledgeName(event.target.value)}
                  className="mt-2 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-cyan-400 focus:ring-2 focus:ring-cyan-100"
                />
              </label>
              <div>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-semibold text-slate-700">历史文件</p>
                  <span className="text-xs text-slate-500">{allKnowledgeDocuments.length} 个</span>
                </div>
                {renderHistoryDocumentOptions({
                  selectedIds: selectedHistoryDocumentIds,
                  onToggle: (documentId) =>
                    toggleDocumentId(selectedHistoryDocumentIds, documentId, setSelectedHistoryDocumentIds),
                  busy: creatingKnowledge,
                })}
              </div>
              <div>
                <input
                  ref={newKnowledgeFileInputRef}
                  type="file"
                  accept={KNOWLEDGE_FILE_ACCEPT}
                  multiple
                  className="hidden"
                  onChange={(event) => {
                    const { supportedFiles, unsupportedFiles } = filterSupportedKnowledgeFiles(
                      Array.from(event.currentTarget.files ?? []),
                    );
                    if (unsupportedFiles.length) {
                      onNotify?.(KNOWLEDGE_FILE_UNSUPPORTED_MESSAGE, "error");
                    }
                    if (supportedFiles.length) {
                      setNewKnowledgeFiles((prev) => appendUniqueFiles(prev, supportedFiles));
                    }
                    event.currentTarget.value = "";
                  }}
                />
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-slate-700">上传新文件</p>
                    <p className="mt-1 text-xs text-slate-500">{KNOWLEDGE_FILE_HINT}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => newKnowledgeFileInputRef.current?.click()}
                    className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-cyan-200 hover:text-cyan-700"
                  >
                    选择文件
                  </button>
                </div>
                <div className="mt-2 max-h-44 space-y-2 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 p-2">
                  {newKnowledgeFiles.length ? (
                    newKnowledgeFiles.map((file, index) => (
                      <div key={`${file.name}:${file.size}:${file.lastModified}`} className="flex items-center justify-between gap-3 rounded-md bg-white px-3 py-2 text-sm">
                        <span className="min-w-0 truncate text-slate-700">{file.name} · {formatSize(file.size)}</span>
                        <button
                          type="button"
                          onClick={() => setNewKnowledgeFiles((prev) => prev.filter((_, candidateIndex) => candidateIndex !== index))}
                          className="shrink-0 text-xs font-semibold text-red-600 hover:text-red-700"
                        >
                          移除
                        </button>
                      </div>
                    ))
                  ) : (
                    <div className="flex min-h-20 items-center justify-center text-sm font-medium text-slate-500">
                      暂无文件
                    </div>
                  )}
                </div>
              </div>
            </div>
            <div className="flex justify-end gap-2 border-t border-slate-200 px-4 py-3">
              <button
                type="button"
                onClick={closeCreateKnowledgeDialog}
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition hover:border-slate-300"
              >
                取消
              </button>
              <button
                type="button"
                disabled={createDisabled}
                onClick={() => void handleCreateKnowledgeBase()}
                className="rounded-lg bg-cyan-600 px-3 py-2 text-sm font-semibold text-white transition hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {creatingKnowledge ? "创建中..." : "创建"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {filePoolUploadOpen ? (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/40 p-4">
          <div className="w-full max-w-lg rounded-lg bg-white shadow-xl">
            <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
              <div className="min-w-0">
                <h2 className="truncate text-base font-semibold text-slate-950">上传到文件池</h2>
                <p className="mt-1 truncate text-xs text-slate-500">文件池里的文件会出现在新建知识库弹窗中</p>
              </div>
              <button
                type="button"
                onClick={closeFilePoolUploadDialog}
                className="rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-sm font-semibold text-slate-600 hover:border-slate-300"
              >
                关闭
              </button>
            </div>
            <div className="space-y-4 p-4">
              <div>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-semibold text-slate-700">文件池文件</p>
                  <span className="text-xs text-slate-500">{allKnowledgeDocuments.length} 个</span>
                </div>
                <div className="mt-2 max-h-52 space-y-2 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 p-2">
                  {allKnowledgeDocumentsLoading ? (
                    <div className="flex min-h-20 items-center justify-center text-sm font-medium text-slate-500">
                      文件池文件加载中...
                    </div>
                  ) : allKnowledgeDocuments.length ? (
                    allKnowledgeDocuments.map((document) => (
                      <div key={document.id} className="flex items-center justify-between gap-3 rounded-md bg-white px-3 py-2 text-sm">
                        <span className="min-w-0 flex-1">
                          <span className="block truncate font-semibold text-slate-800">{document.filename}</span>
                          <span className="mt-0.5 block truncate text-xs text-slate-500">
                            {formatSize(document.bytes)} · {knowledgeStatusLabel(document)} · {document.chunk_count} chunks
                          </span>
                        </span>
                        <button
                          type="button"
                          disabled={filePoolUploading || filePoolActionId === document.id}
                          onClick={() => void handleDeleteFilePoolDocument(document)}
                          className="shrink-0 text-xs font-semibold text-red-600 hover:text-red-700 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {filePoolActionId === document.id ? "删除中..." : "删除"}
                        </button>
                      </div>
                    ))
                  ) : (
                    <div className="flex min-h-20 items-center justify-center text-sm font-medium text-slate-500">
                      暂无文件池文件
                    </div>
                  )}
                </div>
              </div>
              <div>
                <input
                  ref={filePoolUploadInputRef}
                  type="file"
                  accept={KNOWLEDGE_FILE_ACCEPT}
                  multiple
                  className="hidden"
                  onChange={(event) => {
                    const { supportedFiles, unsupportedFiles } = filterSupportedKnowledgeFiles(
                      Array.from(event.currentTarget.files ?? []),
                    );
                    if (unsupportedFiles.length) {
                      onNotify?.(KNOWLEDGE_FILE_UNSUPPORTED_MESSAGE, "error");
                    }
                    if (supportedFiles.length) {
                      setFilePoolFiles((prev) => appendUniqueFiles(prev, supportedFiles));
                    }
                    event.currentTarget.value = "";
                  }}
                />
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-slate-700">上传新文件</p>
                    <p className="mt-1 text-xs text-slate-500">{KNOWLEDGE_FILE_HINT}</p>
                  </div>
                  <button
                    type="button"
                    disabled={filePoolUploading}
                    onClick={() => filePoolUploadInputRef.current?.click()}
                    className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-cyan-200 hover:text-cyan-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    选择文件
                  </button>
                </div>
                <div className="mt-2 max-h-44 space-y-2 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 p-2">
                  {filePoolFiles.length ? (
                    filePoolFiles.map((file, index) => (
                      <div key={`${file.name}:${file.size}:${file.lastModified}`} className="flex items-center justify-between gap-3 rounded-md bg-white px-3 py-2 text-sm">
                        <span className="min-w-0 truncate text-slate-700">{file.name} · {formatSize(file.size)}</span>
                        <button
                          type="button"
                          disabled={filePoolUploading}
                          onClick={() => setFilePoolFiles((prev) => prev.filter((_, candidateIndex) => candidateIndex !== index))}
                          className="shrink-0 text-xs font-semibold text-red-600 hover:text-red-700 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          移除
                        </button>
                      </div>
                    ))
                  ) : (
                    <div className="flex min-h-20 items-center justify-center text-sm font-medium text-slate-500">
                      暂无新文件
                    </div>
                  )}
                </div>
              </div>
            </div>
            <div className="flex justify-end gap-2 border-t border-slate-200 px-4 py-3">
              <button
                type="button"
                onClick={closeFilePoolUploadDialog}
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition hover:border-slate-300"
              >
                取消
              </button>
              <button
                type="button"
                disabled={filePoolUploadDisabled}
                onClick={() => void handleUploadFilePoolDocuments()}
                className="rounded-lg bg-cyan-600 px-3 py-2 text-sm font-semibold text-white transition hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {filePoolUploading ? "上传中..." : "上传"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {uploadOpen ? (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/40 p-4">
          <div className="w-full max-w-lg rounded-lg bg-white shadow-xl">
            <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
              <div className="min-w-0">
                <h2 className="truncate text-base font-semibold text-slate-950">添加文件到知识库</h2>
                <p className="mt-1 truncate text-xs text-slate-500">{selectedKnowledgeBase?.name ?? "未选择知识库"}</p>
              </div>
              <button
                type="button"
                onClick={closeUploadKnowledgeDialog}
                className="rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-sm font-semibold text-slate-600 hover:border-slate-300"
              >
                关闭
              </button>
            </div>
            <div className="space-y-4 p-4">
              <div>
                <input
                  ref={uploadKnowledgeFileInputRef}
                  type="file"
                  accept={KNOWLEDGE_FILE_ACCEPT}
                  multiple
                  className="hidden"
                  onChange={(event) => {
                    const { supportedFiles, unsupportedFiles } = filterSupportedKnowledgeFiles(
                      Array.from(event.currentTarget.files ?? []),
                    );
                    if (unsupportedFiles.length) {
                      onNotify?.(KNOWLEDGE_FILE_UNSUPPORTED_MESSAGE, "error");
                    }
                    if (supportedFiles.length) {
                      setUploadKnowledgeFiles((prev) => appendUniqueFiles(prev, supportedFiles));
                    }
                    event.currentTarget.value = "";
                  }}
                />
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-slate-700">上传新文件</p>
                    <p className="mt-1 text-xs text-slate-500">{KNOWLEDGE_FILE_HINT}</p>
                  </div>
                  <button
                    type="button"
                    disabled={documentActionId === "__upload__"}
                    onClick={() => uploadKnowledgeFileInputRef.current?.click()}
                    className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-cyan-200 hover:text-cyan-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    选择文件
                  </button>
                </div>
                <div className="mt-2 max-h-44 space-y-2 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 p-2">
                  {uploadKnowledgeFiles.length ? (
                    uploadKnowledgeFiles.map((file, index) => (
                      <div key={`${file.name}:${file.size}:${file.lastModified}`} className="flex items-center justify-between gap-3 rounded-md bg-white px-3 py-2 text-sm">
                        <span className="min-w-0 truncate text-slate-700">{file.name} · {formatSize(file.size)}</span>
                        <button
                          type="button"
                          disabled={documentActionId === "__upload__"}
                          onClick={() => setUploadKnowledgeFiles((prev) => prev.filter((_, candidateIndex) => candidateIndex !== index))}
                          className="shrink-0 text-xs font-semibold text-red-600 hover:text-red-700 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          移除
                        </button>
                      </div>
                    ))
                  ) : (
                    <div className="flex min-h-20 items-center justify-center text-sm font-medium text-slate-500">
                      暂无新文件
                    </div>
                  )}
                </div>
              </div>
            </div>
            <div className="flex justify-end gap-2 border-t border-slate-200 px-4 py-3">
              <button
                type="button"
                onClick={closeUploadKnowledgeDialog}
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition hover:border-slate-300"
              >
                取消
              </button>
              <button
                type="button"
                disabled={uploadDisabled}
                onClick={() => void handleUploadKnowledgeDocuments()}
                className="rounded-lg bg-cyan-600 px-3 py-2 text-sm font-semibold text-white transition hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {documentActionId === "__upload__" ? "添加中..." : "添加"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}
