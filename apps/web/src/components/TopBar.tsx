import type { ConnectionStatus } from "../types";

const DOT_COLORS: Record<ConnectionStatus, string> = {
  idle: "bg-slate-500",
  connecting: "bg-yellow-500 animate-pulse-dot",
  live: "bg-green-500",
  error: "bg-red-500",
};

const DOT_LABELS: Record<ConnectionStatus, string> = {
  idle: "未连接",
  connecting: "连接中",
  live: "已连接",
  error: "连接错误",
};

interface TopBarProps {
  connection: ConnectionStatus;
}

export function TopBar({ connection }: TopBarProps) {
  return (
    <div className="glass fixed inset-x-0 top-0 z-30 flex items-center justify-between pr-[3.25rem] pl-5 py-3 sm:pr-16">
      <span className="text-lg font-semibold tracking-tight text-white">OpenTalking</span>

      <div className="flex min-w-0 items-center justify-end gap-2 sm:gap-3">
        <p className="hidden text-[10px] text-slate-500 sm:block">设置见右侧色条</p>
        <div className="flex items-center gap-1.5" title={DOT_LABELS[connection]}>
          <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${DOT_COLORS[connection]}`} />
          <span className="text-xs text-slate-400">{DOT_LABELS[connection]}</span>
        </div>
      </div>
    </div>
  );
}
