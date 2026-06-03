import type { ConnectionStatus } from "../types";

const DOT_COLORS: Record<ConnectionStatus, string> = {
  idle: "bg-slate-500",
  connecting: "bg-yellow-500 animate-pulse-dot",
  queued: "bg-amber-500 animate-pulse-dot",
  live: "bg-green-500",
  expiring: "bg-amber-500",
  error: "bg-red-500",
};

const PILL_COLORS: Record<ConnectionStatus, string> = {
  idle: "border-slate-200 bg-slate-50 text-slate-600",
  connecting: "border-yellow-200 bg-yellow-50 text-yellow-700",
  queued: "border-amber-200 bg-amber-50 text-amber-700",
  live: "border-emerald-200 bg-emerald-50 text-emerald-700",
  expiring: "border-amber-200 bg-amber-50 text-amber-700",
  error: "border-red-200 bg-red-50 text-red-700",
};

const DOT_LABELS: Record<ConnectionStatus, string> = {
  idle: "未连接",
  connecting: "连接中",
  queued: "排队中",
  live: "已连接",
  expiring: "即将到期",
  error: "连接错误",
};

export type FlashtalkRecordPhase = "idle" | "recording" | "stopped";
export type StudioWorkflow = "realtime" | "videoCreation" | "videoClone" | "assetLibrary";

interface TopBarProps {
  connection: ConnectionStatus;
  workflow?: StudioWorkflow;
  flashtalkRecording?: boolean;
  flashtalkRecordPhase?: FlashtalkRecordPhase;
  flashtalkRecordBusy?: boolean;
  recordingSaving?: boolean;
  onInactiveModuleClick?: (label: string) => void;
  onFlashtalkRecordStart?: () => void;
  onFlashtalkRecordStop?: () => void;
  onFlashtalkRecordSave?: () => void;
  /** 上传整段音频，推理结束后下载对齐音视频（不经 WebRTC 实时预览） */
  flashtalkOfflineBundleBusy?: boolean;
  onFlashtalkOfflineBundleClick?: () => void;
  onWorkflowChange?: (workflow: StudioWorkflow) => void;
}

export function TopBar({
  connection,
  workflow = "realtime",
  flashtalkRecording = false,
  flashtalkRecordPhase = "idle",
  flashtalkRecordBusy = false,
  recordingSaving = false,
  onInactiveModuleClick,
  onFlashtalkRecordStart,
  onFlashtalkRecordStop,
  onFlashtalkRecordSave,
  flashtalkOfflineBundleBusy = false,
  onFlashtalkOfflineBundleClick,
  onWorkflowChange,
}: TopBarProps) {
  const busy = flashtalkRecordBusy || recordingSaving || flashtalkOfflineBundleBusy;

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-4 shadow-sm">
      <div className="flex min-w-0 items-center gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-950 text-cyan-300">
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor" aria-hidden>
            <path d="M12 2l1.7 5.3L19 9l-5.3 1.7L12 16l-1.7-5.3L5 9l5.3-1.7L12 2Zm6 12 1 3 3 1-3 1-1 3-1-3-3-1 3-1 1-3Z" />
          </svg>
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-slate-950">
            <span className="sm:hidden">OpenTalking</span>
            <span className="hidden sm:inline">OpenTalking Studio</span>
          </p>
          <p className="hidden truncate text-xs text-slate-500 sm:block">实时数字人工作台</p>
        </div>
      </div>

      <nav className="hidden items-center gap-1 rounded-lg bg-slate-100 p-1 md:flex" aria-label="工作台模块">
        {[
          ["realtime", "实时对话"],
          ["videoCreation", "视频创作"],
          ["videoClone", "视频克隆"],
          ["assetLibrary", "资产库"],
        ].map(([id, label]) => {
          const active = workflow === id;
          return (
            <button
              key={id}
              type="button"
              onClick={() => onWorkflowChange?.(id as StudioWorkflow)}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition ${
                active
                  ? "bg-white text-cyan-700 shadow-sm"
                  : "text-slate-500 hover:bg-white/70 hover:text-slate-700"
              }`}
            >
              {label}
            </button>
          );
        })}
        {["运行监控"].map((item) => (
          <button
            key={item}
            type="button"
            className="rounded-md px-3 py-1.5 text-xs font-medium text-slate-500 transition hover:bg-white/70 hover:text-slate-700"
            title={`${item}规划中`}
            onClick={() => onInactiveModuleClick?.(item)}
          >
            {item}
          </button>
        ))}
      </nav>

      <div className="flex min-w-0 flex-wrap items-center justify-end gap-1.5 sm:gap-2">
        {flashtalkRecording ? (
          <div className="flex flex-wrap items-center justify-end gap-1.5">
            {onFlashtalkOfflineBundleClick ? (
              <button
                type="button"
                disabled={busy}
                onClick={onFlashtalkOfflineBundleClick}
                className="rounded-lg border border-sky-200 bg-sky-50 px-2.5 py-1.5 text-[11px] font-semibold text-sky-700 transition hover:bg-sky-100 disabled:cursor-not-allowed disabled:opacity-45 sm:px-3 sm:text-xs"
                title="上传整段音频：服务端跑完全部推理后再保存，下载已对齐的音视频 MP4（可不录屏）"
              >
                {flashtalkOfflineBundleBusy ? "离线导出中…" : "离线整段导出"}
              </button>
            ) : null}
            {flashtalkRecordPhase === "idle" ? (
              <button
                type="button"
                disabled={busy}
                onClick={onFlashtalkRecordStart}
                className="rounded-lg bg-cyan-600 px-2.5 py-1.5 text-[11px] font-semibold text-white transition hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-45 sm:px-3 sm:text-xs"
                title="从此时起录制浏览器中的数字人画面、用户麦克风和可用的远端音轨"
              >
                {busy ? "请稍候..." : "开始录制"}
              </button>
            ) : null}
            {flashtalkRecordPhase === "recording" ? (
              <>
                <span className="hidden rounded-full border border-red-200 bg-red-50 px-2 py-0.5 text-[10px] font-medium text-red-700 sm:inline">
                  录制中
                </span>
                <button
                  type="button"
                  disabled={busy}
                  onClick={onFlashtalkRecordStop}
                  className="rounded-lg bg-red-600 px-2.5 py-1.5 text-[11px] font-semibold text-white transition hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-45 sm:px-3 sm:text-xs"
                  title="停止浏览器录制；停止后会自动保存到导出视频资产库"
                >
                  {busy ? "请稍候..." : "结束录制"}
                </button>
              </>
            ) : null}
            {flashtalkRecordPhase === "stopped" ? (
              <>
                <button
                  type="button"
                  disabled={busy}
                  onClick={onFlashtalkRecordSave}
                  className="rounded-lg bg-slate-950 px-2.5 py-1.5 text-[11px] font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-45 sm:px-3 sm:text-xs"
                  title="重试保存上一次未上传成功的浏览器录制"
                >
                  {recordingSaving ? "导出中..." : "重试保存"}
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={onFlashtalkRecordStart}
                  className="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[11px] font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-45 sm:px-3 sm:text-xs"
                  title="开始新一轮浏览器录制"
                >
                  重新录制
                </button>
              </>
            ) : null}
          </div>
        ) : null}
        <div
          className={`flex items-center gap-1.5 rounded-full border px-2 py-1 text-xs font-medium sm:px-2.5 ${PILL_COLORS[connection]}`}
          title={DOT_LABELS[connection]}
        >
          <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${DOT_COLORS[connection]}`} />
          <span>{DOT_LABELS[connection]}</span>
        </div>
      </div>
    </header>
  );
}
