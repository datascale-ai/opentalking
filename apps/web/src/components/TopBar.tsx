import type { ConnectionStatus } from "../types";

const DOT_COLORS: Record<ConnectionStatus, string> = {
  idle: "bg-slate-500",
  connecting: "bg-yellow-500 animate-pulse-dot",
  queued: "bg-amber-500 animate-pulse-dot",
  live: "bg-green-500",
  expiring: "bg-amber-500",
  error: "bg-red-500",
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

interface TopBarProps {
  connection: ConnectionStatus;
  flashtalkRecording?: boolean;
  flashtalkRecordPhase?: FlashtalkRecordPhase;
  flashtalkRecordBusy?: boolean;
  recordingSaving?: boolean;
  onFlashtalkRecordStart?: () => void;
  onFlashtalkRecordStop?: () => void;
  onFlashtalkRecordSave?: () => void;
  /** 上传整段音频，推理结束后下载对齐音视频（不经 WebRTC 实时预览） */
  flashtalkOfflineBundleBusy?: boolean;
  onFlashtalkOfflineBundleClick?: () => void;
}

export function TopBar({
  connection,
  flashtalkRecording = false,
  flashtalkRecordPhase = "idle",
  flashtalkRecordBusy = false,
  recordingSaving = false,
  onFlashtalkRecordStart,
  onFlashtalkRecordStop,
  onFlashtalkRecordSave,
  flashtalkOfflineBundleBusy = false,
  onFlashtalkOfflineBundleClick,
}: TopBarProps) {
  const busy = flashtalkRecordBusy || recordingSaving || flashtalkOfflineBundleBusy;

  return (
    <div className="glass fixed inset-x-0 top-0 z-30 flex items-center justify-between pr-[3.25rem] pl-5 py-3 sm:pr-16">
      <span className="text-lg font-semibold tracking-tight text-white">OpenTalking</span>

      <div className="flex min-w-0 max-w-[min(100vw-6rem,28rem)] flex-wrap items-center justify-end gap-1.5 sm:gap-2">
        {flashtalkRecording ? (
          <div className="flex flex-wrap items-center justify-end gap-1.5">
            {onFlashtalkOfflineBundleClick ? (
              <button
                type="button"
                disabled={busy}
                onClick={onFlashtalkOfflineBundleClick}
                className="rounded-full border border-sky-400/35 bg-sky-500/15 px-2.5 py-1 text-[11px] font-medium text-sky-100 shadow-lg shadow-black/20 transition hover:bg-sky-500/25 disabled:cursor-not-allowed disabled:opacity-45 sm:px-3 sm:text-xs"
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
                className="rounded-full border border-emerald-400/40 bg-emerald-500/20 px-2.5 py-1 text-[11px] font-medium text-emerald-100 shadow-lg shadow-black/20 transition hover:bg-emerald-500/30 disabled:cursor-not-allowed disabled:opacity-45 sm:px-3 sm:text-xs"
                title="从此时起把 FlashTalk 输出帧写入服务端，可随时结束并导出 MP4"
              >
                {busy ? "请稍候..." : "开始录制"}
              </button>
            ) : null}
            {flashtalkRecordPhase === "recording" ? (
              <>
                <span className="hidden rounded-full bg-red-500/25 px-2 py-0.5 text-[10px] font-medium text-red-100 sm:inline">
                  录制中
                </span>
                <button
                  type="button"
                  disabled={busy}
                  onClick={onFlashtalkRecordStop}
                  className="rounded-full border border-red-400/40 bg-red-500/20 px-2.5 py-1 text-[11px] font-medium text-red-50 shadow-lg shadow-black/20 transition hover:bg-red-500/30 disabled:cursor-not-allowed disabled:opacity-45 sm:px-3 sm:text-xs"
                  title="停止写入帧；之后可保存本次片段"
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
                  className="rounded-full border border-white/15 bg-white/10 px-2.5 py-1 text-[11px] font-medium text-white shadow-lg shadow-black/20 transition hover:border-white/30 hover:bg-white/20 disabled:cursor-not-allowed disabled:opacity-45 sm:px-3 sm:text-xs"
                  title="从服务端生成并下载本次结束录制前的 MP4"
                >
                  {recordingSaving ? "导出中..." : "保存视频"}
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={onFlashtalkRecordStart}
                  className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] font-medium text-slate-200 transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-45 sm:px-3 sm:text-xs"
                  title="丢弃当前未保存片段并开始新一轮录制"
                >
                  重新录制
                </button>
              </>
            ) : null}
          </div>
        ) : null}
        <p className="hidden text-[10px] text-slate-500 sm:block">设置见右侧色条</p>
        <div className="flex items-center gap-1.5" title={DOT_LABELS[connection]}>
          <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${DOT_COLORS[connection]}`} />
          <span className="text-xs text-slate-400">{DOT_LABELS[connection]}</span>
        </div>
      </div>
    </div>
  );
}
