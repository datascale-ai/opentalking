import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  apiDelete,
  apiGet,
  buildApiDownloadUrl,
  type ExportVideoItem,
} from "../lib/api";

type AssetLibraryWorkspaceProps = {
  refreshToken?: number;
  onNotify?: (message: string, tone?: "info" | "success" | "error") => void;
};

type AssetTab = "exports" | "avatars" | "voices";

const ASSET_TABS: { id: AssetTab; label: string; disabled?: boolean }[] = [
  { id: "exports", label: "导出视频" },
  { id: "avatars", label: "Avatar资产", disabled: true },
  { id: "voices", label: "声音资产", disabled: true },
];

const KIND_LABELS: Record<ExportVideoItem["kind"], string> = {
  realtime_dialogue: "实时对话",
  video_clone: "视频克隆",
  video_creation: "视频创作",
};

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

export function AssetLibraryWorkspace({ refreshToken = 0, onNotify }: AssetLibraryWorkspaceProps) {
  const [activeTab, setActiveTab] = useState<AssetTab>("exports");
  const [items, setItems] = useState<ExportVideoItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  useEffect(() => {
    void loadExports();
  }, [loadExports, refreshToken]);

  const totalSize = useMemo(
    () => items.reduce((sum, item) => sum + item.size_bytes, 0),
    [items],
  );

  const handleCopyPath = useCallback(async (path: string) => {
    try {
      await navigator.clipboard.writeText(path);
      onNotify?.("已复制服务端存放路径。", "success");
    } catch {
      onNotify?.("复制失败，请手动选择路径。", "error");
    }
  }, [onNotify]);

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

  return (
    <main className="flex min-h-0 flex-1 flex-col bg-slate-100 p-4">
      <section className="flex min-h-0 flex-1 flex-col rounded-lg border border-slate-200 bg-white shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
          <div>
            <p className="text-xs font-medium text-slate-500">Asset Library</p>
            <h1 className="text-base font-semibold text-slate-950">资产库</h1>
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <span>{items.length} 个导出</span>
            <span>{formatSize(totalSize)}</span>
            <button
              type="button"
              onClick={() => void loadExports()}
              disabled={loading}
              className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 font-semibold text-slate-700 transition hover:border-cyan-200 hover:text-cyan-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? "刷新中..." : "刷新"}
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
                onClick={() => setActiveTab(tab.id)}
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
          ) : (
            <div className="flex min-h-[18rem] items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50 text-sm font-medium text-slate-500">
              {activeTab === "avatars" ? "Avatar资产管理规划中" : "声音资产管理规划中"}
            </div>
          )}
        </div>
      </section>
    </main>
  );
}
