import { useMemo, useState } from "react";
import {
  ApiError,
  commitWeChatImportJob,
  selectWeChatImportSpeaker,
  uploadWeChatImport,
} from "../lib/api";
import type { WeChatImportCommitResult, WeChatImportJob } from "../types";

type WeChatMemoryImportPanelProps = {
  avatarId: string | null;
  avatarModel?: string;
  profileId: string;
  memoryLibraryId: string | null;
  disabled?: boolean;
  onCommitted: (result: WeChatImportCommitResult) => void | Promise<void>;
};

function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.detail) return error.detail;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

function safePersonaId(value: string | null): string {
  const clean = (value || "wechat-persona").replace(/[^A-Za-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
  return `wechat-${clean || "persona"}`.slice(0, 80);
}

export function WeChatMemoryImportPanel({
  avatarId,
  avatarModel = "mock",
  profileId,
  memoryLibraryId,
  disabled = false,
  onCommitted,
}: WeChatMemoryImportPanelProps) {
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<WeChatImportJob | null>(null);
  const [selectedSpeakerId, setSelectedSpeakerId] = useState("");
  const [personaId, setPersonaId] = useState(safePersonaId(avatarId));
  const [personaName, setPersonaName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const selectedSpeaker = useMemo(
    () => job?.speakers.find((speaker) => speaker.id === selectedSpeakerId) ?? null,
    [job, selectedSpeakerId],
  );

  const handleUpload = async () => {
    if (!file || !avatarId) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const created = await uploadWeChatImport(file, {
        profileId,
        memoryLibraryId: memoryLibraryId || "default",
        avatarId,
        avatarModel,
        characterId: avatarId,
      });
      setJob(created);
      const firstSpeaker = created.speakers[0] ?? null;
      setSelectedSpeakerId(created.selected_speaker_id || firstSpeaker?.id || "");
      setPersonaName(firstSpeaker?.name || "微信数字人");
      setPersonaId(safePersonaId(firstSpeaker?.id || avatarId));
      setNotice(created.status === "draft_ready" ? "人设草稿已生成" : "请选择要创建数字人的说话人");
    } catch (e) {
      setError(getErrorMessage(e, "上传失败"));
    } finally {
      setBusy(false);
    }
  };

  const handleSelectSpeaker = async () => {
    if (!job || !selectedSpeakerId) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const selected = await selectWeChatImportSpeaker(job.id, selectedSpeakerId);
      setJob(selected);
      setPersonaName(selectedSpeaker?.name || personaName || "微信数字人");
      setPersonaId(safePersonaId(selectedSpeakerId));
      setNotice("人设草稿已生成");
    } catch (e) {
      setError(getErrorMessage(e, "选择说话人失败"));
    } finally {
      setBusy(false);
    }
  };

  const handleCommit = async () => {
    if (!job || job.status !== "draft_ready") return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const committed = await commitWeChatImportJob(job.id, {
        personaId: personaId || safePersonaId(selectedSpeakerId || avatarId),
        personaName: personaName || selectedSpeaker?.name || "微信数字人",
      });
      await onCommitted(committed);
      setJob({ ...job, status: "committed" });
      setNotice(`已保存数字人，并导入 ${committed.memory_imported} 条记忆`);
    } catch (e) {
      setError(getErrorMessage(e, "保存失败"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-950">微信聊天记录导入</h3>
          <p className="text-xs text-slate-500">将微信导出记录生成数字人人设和长期记忆</p>
        </div>
        <button
          type="button"
          onClick={() => void handleUpload()}
          disabled={disabled || busy || !file || !avatarId}
          className="rounded-lg bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? "处理中..." : "上传"}
        </button>
      </div>

      <div className="mt-3 grid gap-3 md:grid-cols-[minmax(0,1fr)_12rem]">
        <input
          type="file"
          accept=".json,.csv,.txt,.html,.htm,.zip"
          disabled={disabled || busy}
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 file:mr-3 file:rounded-md file:border-0 file:bg-slate-100 file:px-2.5 file:py-1 file:text-xs file:font-semibold file:text-slate-700 disabled:opacity-60"
        />
        <input
          value={personaId}
          onChange={(event) => setPersonaId(event.target.value)}
          disabled={disabled || busy}
          placeholder="数字人 ID"
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 outline-none focus:border-cyan-300 disabled:opacity-60"
        />
      </div>

      {job?.status === "needs_speaker_selection" ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <select
            value={selectedSpeakerId}
            onChange={(event) => setSelectedSpeakerId(event.target.value)}
            disabled={disabled || busy}
            className="min-h-9 min-w-44 rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-medium text-slate-700 outline-none focus:border-cyan-300 disabled:opacity-60"
          >
            {job.speakers.map((speaker) => (
              <option key={speaker.id} value={speaker.id}>
                {speaker.name || speaker.id} ({speaker.message_count})
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => void handleSelectSpeaker()}
            disabled={disabled || busy || !selectedSpeakerId}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-cyan-200 hover:text-cyan-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            生成人设草稿
          </button>
        </div>
      ) : null}

      {job?.status === "draft_ready" ? (
        <div className="mt-3 space-y-3">
          <input
            value={personaName}
            onChange={(event) => setPersonaName(event.target.value)}
            disabled={disabled || busy}
            placeholder="数字人名称"
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 outline-none focus:border-cyan-300 disabled:opacity-60"
          />
          <textarea
            value={job.persona_md || ""}
            readOnly
            rows={6}
            className="w-full resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs leading-relaxed text-slate-700 outline-none"
          />
          <button
            type="button"
            onClick={() => void handleCommit()}
            disabled={disabled || busy || !personaId}
            className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            保存数字人
          </button>
        </div>
      ) : null}

      {notice ? <p className="mt-3 text-xs font-medium text-emerald-700">{notice}</p> : null}
      {error ? <p className="mt-3 text-xs font-medium text-red-700">{error}</p> : null}
    </div>
  );
}
