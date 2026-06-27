import { useEffect, useMemo, useState } from "react";
import {
  ApiError,
  createMemoryLibrary,
  deleteMemoryItem,
  getMemoryItems,
  getMemoryLibraries,
} from "../lib/api";
import type { MemoryItem, MemoryLibrary } from "../types";
import { WeChatMemoryImportPanel } from "./WeChatMemoryImportPanel";

type MemoryPanelProps = {
  characterId: string | null;
  selectedLibraryId: string | null;
  memoryEnabled?: boolean;
  profileId?: string;
  avatarModel?: string;
  compact?: boolean;
  mode?: "select" | "manage";
  refreshToken?: number;
  onLibrarySelect: (libraryId: string | null) => void;
  onMemoryEnabledChange?: (enabled: boolean) => void;
  onLibrariesChange?: (libraries: MemoryLibrary[]) => void;
};

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.detail) return error.detail;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

export function MemoryPanel({
  characterId,
  selectedLibraryId,
  memoryEnabled = false,
  profileId = "default",
  avatarModel = "mock",
  compact = false,
  mode = "manage",
  refreshToken = 0,
  onLibrarySelect,
  onMemoryEnabledChange,
  onLibrariesChange,
}: MemoryPanelProps) {
  const isManageMode = mode === "manage";
  const [libraries, setLibraries] = useState<MemoryLibrary[]>([]);
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [loadingLibraries, setLoadingLibraries] = useState(false);
  const [loadingItems, setLoadingItems] = useState(false);
  const [busy, setBusy] = useState(false);
  const [newLibraryName, setNewLibraryName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const selectedLibrary = useMemo(
    () => libraries.find((library) => library.id === selectedLibraryId) ?? null,
    [libraries, selectedLibraryId],
  );

  const refreshLibraries = async () => {
    if (!characterId) {
      setLibraries([]);
      setItems([]);
      onLibrariesChange?.([]);
      return;
    }
    setLoadingLibraries(true);
    setError(null);
    try {
      const result = await getMemoryLibraries(profileId, characterId);
      setLibraries(result.items);
      onLibrariesChange?.(result.items);
      if (selectedLibraryId && !result.items.some((library) => library.id === selectedLibraryId)) {
        onLibrarySelect(null);
        onMemoryEnabledChange?.(false);
      }
    } catch (e) {
      setError(getErrorMessage(e, "读取记忆库失败"));
      setLibraries([]);
      setItems([]);
      onLibrariesChange?.([]);
    } finally {
      setLoadingLibraries(false);
    }
  };

  const refreshItems = async () => {
    if (!isManageMode) return;
    if (!characterId || !selectedLibraryId) {
      setItems([]);
      return;
    }
    setLoadingItems(true);
    setError(null);
    try {
      const result = await getMemoryItems(selectedLibraryId, profileId, characterId);
      setItems(result.items);
    } catch (e) {
      setError(getErrorMessage(e, "读取记忆条目失败"));
      setItems([]);
    } finally {
      setLoadingItems(false);
    }
  };

  useEffect(() => {
    void refreshLibraries();
  }, [characterId, profileId, refreshToken]);

  useEffect(() => {
    void refreshItems();
  }, [characterId, profileId, selectedLibraryId, isManageMode]);

  const handleCreateLibrary = async () => {
    if (!isManageMode) return;
    if (!characterId) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const created = await createMemoryLibrary({
        name: newLibraryName.trim() || undefined,
        profile_id: profileId,
        character_id: characterId,
      });
      setNewLibraryName("");
      onLibrarySelect(created.id);
      onMemoryEnabledChange?.(true);
      await refreshLibraries();
      setNotice("记忆库已创建");
    } catch (e) {
      setError(getErrorMessage(e, "创建记忆库失败"));
    } finally {
      setBusy(false);
    }
  };

  const handleDeleteItem = async (item: MemoryItem) => {
    if (!isManageMode) return;
    if (!characterId || !selectedLibraryId) return;
    if (!window.confirm("确认删除这条记忆？")) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await deleteMemoryItem(selectedLibraryId, item.id, profileId, characterId);
      await Promise.all([refreshLibraries(), refreshItems()]);
      setNotice("记忆已删除");
    } catch (e) {
      setError(getErrorMessage(e, "删除记忆失败"));
    } finally {
      setBusy(false);
    }
  };

  const disabled = !characterId || busy || loadingLibraries;

  if (!isManageMode) {
    return (
      <div className={`space-y-2 ${compact ? "" : "rounded-lg border border-slate-200 bg-white p-3"}`}>
        {error ? (
          <p className="rounded-md border border-rose-200 bg-rose-50 px-2.5 py-2 text-xs font-medium text-rose-700">
            {error}
          </p>
        ) : null}
        {libraries.length ? (
          libraries.map((library) => {
            const selected = library.id === selectedLibraryId && memoryEnabled;
            const memoryLibraryReady = library.memory_count > 0;
            return (
              <button
                key={library.id}
                type="button"
                disabled={disabled || !memoryLibraryReady}
                onClick={() => {
                  const nextSelected = selected ? null : library.id;
                  onLibrarySelect(nextSelected);
                  onMemoryEnabledChange?.(Boolean(nextSelected));
                }}
                className={`flex min-h-9 w-full items-center justify-between gap-2 rounded-md border px-2.5 py-2 text-left text-xs font-semibold transition ${
                  selected
                    ? "border-cyan-300 bg-white text-cyan-800 shadow-sm"
                    : memoryLibraryReady
                      ? "border-slate-200 bg-white text-slate-700 hover:border-cyan-200 hover:text-cyan-700"
                      : "cursor-not-allowed border-slate-100 bg-slate-50 text-slate-400"
                } ${disabled ? "cursor-not-allowed opacity-60" : ""}`}
              >
                <span className="min-w-0 truncate">{library.name || library.id}</span>
                <span className={`shrink-0 text-[11px] ${selected ? "text-cyan-700" : memoryLibraryReady ? "text-emerald-600" : "text-slate-400"}`}>
                  {selected ? "已挂载" : memoryLibraryReady ? "已就绪" : "空库"}
                </span>
              </button>
            );
          })
        ) : (
          <p className="rounded-md border border-dashed border-slate-200 bg-white px-2.5 py-2 text-xs text-slate-500">
            {loadingLibraries ? "正在读取记忆库..." : "暂无记忆库"}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className={`grid min-h-[24rem] gap-4 xl:grid-cols-[20rem_minmax(0,1fr)] ${compact ? "" : ""}`}>
      <aside className="min-h-0 rounded-lg border border-slate-200 bg-white">
        <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-3 py-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-950">记忆库</h2>
            <p className="text-xs text-slate-500">{libraries.length} 个分类</p>
          </div>
          <button
            type="button"
            onClick={() => void handleCreateLibrary()}
            disabled={disabled}
            className="rounded-lg bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? "处理中..." : "新建"}
          </button>
        </div>
        <div className="border-b border-slate-100 p-3">
          <input
            value={newLibraryName}
            onChange={(event) => setNewLibraryName(event.target.value)}
            disabled={disabled}
            placeholder="新建记忆库名称"
            className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-cyan-300 focus:bg-white disabled:opacity-60"
          />
        </div>
        <div className="max-h-[32rem] space-y-2 overflow-y-auto p-3">
          {error ? (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm font-medium text-red-700">{error}</div>
          ) : null}
          {!loadingLibraries && !libraries.length ? (
            <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-center text-sm font-medium text-slate-500">
              暂无记忆库
            </div>
          ) : null}
          {libraries.map((library) => {
            const selected = library.id === selectedLibraryId;
            return (
              <button
                key={library.id}
                type="button"
                onClick={() => {
                  onLibrarySelect(library.id);
                  onMemoryEnabledChange?.(true);
                }}
                className={`w-full rounded-lg border p-3 text-left transition ${
                  selected
                    ? "border-cyan-300 bg-cyan-50 text-cyan-800"
                    : "border-slate-200 bg-white text-slate-700 hover:border-slate-300"
                }`}
              >
                <span className="block truncate text-sm font-semibold">{library.name || library.id}</span>
                <span className="mt-1 block text-xs text-slate-500">
                  {library.memory_count} 条记忆
                </span>
                <span className="mt-1 block truncate text-[11px] text-slate-400">{library.id}</span>
              </button>
            );
          })}
        </div>
      </aside>

      <section className="min-w-0 rounded-lg border border-slate-200 bg-white">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 px-4 py-3">
          <div className="min-w-0">
            <h2 className="truncate text-sm font-semibold text-slate-950">
              {selectedLibrary?.name || selectedLibrary?.id || "管理记忆库"}
            </h2>
            <p className="mt-1 text-xs text-slate-500">
              {selectedLibrary ? `${formatDate(selectedLibrary.updated_at)} 更新` : "未选择记忆库"}
            </p>
          </div>
          <button
            type="button"
            onClick={() => void refreshItems()}
            disabled={!selectedLibraryId || loadingItems}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-cyan-200 hover:text-cyan-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loadingItems ? "刷新中..." : "刷新条目"}
          </button>
        </div>

        <div className="space-y-4 p-4">
          <WeChatMemoryImportPanel
            avatarId={characterId}
            avatarModel={avatarModel}
            profileId={profileId}
            memoryLibraryId={selectedLibraryId || "default"}
            disabled={busy || loadingLibraries}
            onCommitted={async (result) => {
              onLibrarySelect(result.memory_library_id);
              onMemoryEnabledChange?.(true);
              await refreshLibraries();
              await refreshItems();
            }}
          />

          {notice ? (
            <p className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-medium text-emerald-700">
              {notice}
            </p>
          ) : null}

          <div className="min-h-[14rem]">
            <div className="mb-2 flex items-center justify-between gap-2">
              <p className="text-xs font-semibold text-slate-500">记忆条目</p>
              <span className="text-xs text-slate-400">{items.length} 条</span>
            </div>
            {loadingItems ? (
              <div className="flex min-h-[12rem] items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50 text-sm font-medium text-slate-500">
                记忆加载中...
              </div>
            ) : !selectedLibraryId ? (
              <div className="flex min-h-[12rem] items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50 text-sm font-medium text-slate-500">
                请选择记忆库
              </div>
            ) : items.length ? (
              <div className="space-y-2">
                {items.map((item) => (
                  <article key={item.id} className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-slate-200 bg-white p-3">
                    <div className="min-w-0 flex-1">
                      <p className="break-words text-sm leading-relaxed text-slate-800">{item.text}</p>
                      <p className="mt-1 truncate text-xs text-slate-500">
                        {item.type} · {formatDate(item.created_at)}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => void handleDeleteItem(item)}
                      disabled={busy}
                      className="shrink-0 rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-semibold text-red-700 transition hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      删除
                    </button>
                  </article>
                ))}
              </div>
            ) : (
              <div className="flex min-h-[12rem] items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50 text-sm font-medium text-slate-500">
                当前记忆库暂无条目
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
