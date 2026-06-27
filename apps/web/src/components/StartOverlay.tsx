import type { QueueInfo } from "../types";
import type { AvatarSummary } from "../lib/api";

interface StartOverlayProps {
  avatar: AvatarSummary | null;
  loading: boolean;
  queued?: boolean;
  queueInfo?: QueueInfo | null;
  onStart: () => void;
  visible: boolean;
}

export function StartOverlay({ avatar, loading, queued, queueInfo, onStart, visible }: StartOverlayProps) {
  if (!visible) return null;

  const isRejected = queueInfo && queueInfo.position === -1;

  return (
    <div className="absolute inset-0 z-20 flex items-center justify-center bg-slate-100/80 px-4 pt-16 backdrop-blur-[2px]">
      <div className="animate-fade-in flex w-full max-w-sm flex-col items-center gap-4 rounded-lg border border-slate-200 bg-white/95 p-5 text-slate-900 shadow-xl shadow-slate-300/50">
        {/* Avatar preview circle */}
        <div className="flex h-20 w-20 items-center justify-center rounded-lg bg-slate-100">
          <svg xmlns="http://www.w3.org/2000/svg" className="h-10 w-10 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.998 0A17.933 17.933 0 0 1 12 21.75c-2.676 0-5.216-.584-7.499-1.632Z" />
          </svg>
        </div>

        {/* Avatar info */}
        <div className="text-center">
          <p className="mb-1 text-xs font-medium text-slate-500">会话未连接</p>
          <h2 className="text-lg font-semibold text-slate-950">
            {avatar?.name ?? "Digital Avatar"}
          </h2>
          {avatar && (
            <span className="mt-1 inline-block rounded-full border border-slate-200 bg-slate-50 px-3 py-0.5 text-xs text-slate-500">
              {avatar.model_type}
            </span>
          )}
        </div>

        {/* Queue status */}
        {queued && queueInfo && queueInfo.position > 0 && (
          <div className="w-full rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-center">
            <p className="text-sm font-medium text-amber-700">排队等候中</p>
            <p className="mt-1 text-xs text-amber-700/70">
              前面还有 <span className="font-semibold text-amber-800">{queueInfo.position}</span> 人，请稍候…
            </p>
          </div>
        )}

        {/* Rejected notice */}
        {isRejected && (
          <div className="w-full rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-center">
            <p className="text-sm font-medium text-red-700">
              {queueInfo?.message === "queue_full" ? "当前排队已满" : "等待超时"}
            </p>
            <p className="mt-1 text-xs text-red-600/70">请稍后重试</p>
          </div>
        )}

        {/* Start button */}
        <button
          type="button"
          onClick={onStart}
          disabled={loading || queued}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-cyan-600 px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-cyan-500 disabled:opacity-60"
        >
          {loading ? (
            <>
              <svg className="h-4 w-4 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              连接中...
            </>
          ) : queued ? (
            <>
              <svg className="h-4 w-4 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              排队中...
            </>
          ) : (
            "开始对话"
          )}
        </button>
        <p className="text-center text-xs leading-relaxed text-slate-500">
          启动后将建立 WebRTC 预览，并启用文本、语音和音频驱动能力。
        </p>
      </div>
    </div>
  );
}
