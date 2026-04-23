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
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60">
      <div className="glass animate-fade-in flex w-80 flex-col items-center gap-5 rounded-2xl p-8">
        {/* Avatar preview circle */}
        <div className="flex h-24 w-24 items-center justify-center rounded-full bg-white/10">
          <svg xmlns="http://www.w3.org/2000/svg" className="h-12 w-12 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.998 0A17.933 17.933 0 0 1 12 21.75c-2.676 0-5.216-.584-7.499-1.632Z" />
          </svg>
        </div>

        {/* Avatar info */}
        <div className="text-center">
          <h2 className="text-lg font-medium text-white">
            {avatar?.name ?? "Digital Avatar"}
          </h2>
          {avatar && (
            <span className="mt-1 inline-block rounded-full bg-white/10 px-3 py-0.5 text-xs text-slate-400">
              {avatar.model_type}
            </span>
          )}
        </div>

        {/* Queue status */}
        {queued && queueInfo && queueInfo.position > 0 && (
          <div className="w-full rounded-xl bg-amber-500/15 px-4 py-3 text-center">
            <p className="text-sm font-medium text-amber-300">排队等候中</p>
            <p className="mt-1 text-xs text-amber-200/70">
              前面还有 <span className="font-semibold text-amber-200">{queueInfo.position}</span> 人，请稍候…
            </p>
          </div>
        )}

        {/* Rejected notice */}
        {isRejected && (
          <div className="w-full rounded-xl bg-red-500/15 px-4 py-3 text-center">
            <p className="text-sm font-medium text-red-300">
              {queueInfo?.message === "queue_full" ? "当前排队已满" : "等待超时"}
            </p>
            <p className="mt-1 text-xs text-red-200/70">请稍后重试</p>
          </div>
        )}

        {/* Start button */}
        <button
          type="button"
          onClick={onStart}
          disabled={loading || queued}
          className="flex w-full items-center justify-center gap-2 rounded-full bg-cyan-500 px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-cyan-600 disabled:opacity-60"
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
      </div>
    </div>
  );
}
