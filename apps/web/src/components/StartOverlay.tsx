import type { AvatarSummary } from "../lib/api";

interface StartOverlayProps {
  avatars: AvatarSummary[];
  avatar: AvatarSummary | null;
  avatarId: string;
  loading: boolean;
  onAvatarChange: (id: string) => void;
  onStart: () => void;
  visible: boolean;
}

function avatarTitle(avatar: AvatarSummary | null): string {
  if (!avatar) return "Digital Avatar";
  if (avatar.id === "flashtalk-demo-idle-all") {
    return `${avatar.name ?? "FlashTalk Demo"} Idle`;
  }
  return avatar.name ?? avatar.id;
}

function avatarSubtitle(avatar: AvatarSummary | null): string | null {
  if (!avatar) return null;
  if (avatar.id === "flashtalk-demo-idle-all") {
    return "uses idle.png for the full online session";
  }
  if (avatar.manifest_id && avatar.manifest_id !== avatar.id) {
    return `${avatar.id} · manifest ${avatar.manifest_id}`;
  }
  return avatar.id;
}

export function StartOverlay({
  avatars,
  avatar,
  avatarId,
  loading,
  onAvatarChange,
  onStart,
  visible,
}: StartOverlayProps) {
  if (!visible) return null;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60">
      <div className="glass animate-fade-in flex w-[22rem] flex-col gap-5 rounded-2xl p-8">
        {/* Avatar preview circle */}
        <div className="mx-auto flex h-24 w-24 items-center justify-center rounded-full bg-white/10">
          <svg xmlns="http://www.w3.org/2000/svg" className="h-12 w-12 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.998 0A17.933 17.933 0 0 1 12 21.75c-2.676 0-5.216-.584-7.499-1.632Z" />
          </svg>
        </div>

        {/* Avatar info */}
        <div className="text-center">
          <h2 className="text-lg font-medium text-white">
            {avatarTitle(avatar)}
          </h2>
          {avatarSubtitle(avatar) && (
            <p className="mt-1 text-xs text-slate-400">{avatarSubtitle(avatar)}</p>
          )}
        </div>

        <div>
          <label className="mb-2 block text-xs font-medium uppercase tracking-wider text-slate-400">
            Demo
          </label>
          <div className="flex max-h-44 flex-col gap-2 overflow-y-auto pr-1">
            {avatars.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => onAvatarChange(item.id)}
                className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors ${
                  item.id === avatarId
                    ? "bg-cyan-500/20 text-white ring-1 ring-cyan-500/40"
                    : "bg-white/5 text-slate-300 hover:bg-white/10"
                }`}
              >
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/10 text-xs text-slate-400">
                  {item.id.charAt(0).toUpperCase()}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm">{avatarTitle(item)}</div>
                  <div className="text-xs text-slate-500">{avatarSubtitle(item)}</div>
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Start button */}
        <button
          type="button"
          onClick={onStart}
          disabled={loading || !avatar}
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
          ) : (
            "开始对话"
          )}
        </button>
      </div>
    </div>
  );
}
