import { useEffect } from "react";
import type { AvatarSummary } from "../lib/api";
import type { TtsProviderExtended } from "../constants/ttsBailian";

type VoiceOpt = { id: string; label: string; targetModel?: string | null };

export const SETTINGS_DOCK_EXPANDED_KEY = "opentalking-settings-dock-expanded";

const MODEL_LABELS: Record<string, string> = {
  flashtalk: "FlashTalk",
  musetalk: "MuseTalk",
  wav2lip: "Wav2Lip",
};

interface SettingsPanelProps {
  /** 展开时显示表单；收起时仅保留右侧竖条入口 */
  expanded: boolean;
  onExpandedChange: (expanded: boolean) => void;
  avatars: AvatarSummary[];
  models: string[];
  avatarId: string;
  model: string;
  onAvatarChange: (id: string) => void;
  onModelChange: (m: string) => void;
  edgeVoice: string;
  onEdgeVoiceChange: (voiceId: string) => void;
  edgeVoiceOptions: { id: string; label: string }[];
  ttsProvider: TtsProviderExtended;
  onTtsProviderChange: (provider: TtsProviderExtended) => void;
  qwenModel: string;
  onQwenModelChange: (modelId: string) => void;
  qwenModelOptions: { id: string; label: string }[];
  qwenVoice: string;
  onQwenVoiceChange: (voiceId: string) => void;
  qwenVoiceOptions: VoiceOpt[];
  llmSystemPrompt: string;
  onLlmSystemPromptChange: (value: string) => void;
  onReferenceImageChange: (file: File | null) => void;
  onSavePrompt: () => void;
  onSaveReferenceImage: () => void;
  promptSaving?: boolean;
  referenceSaving?: boolean;
  onOpenVoiceClone?: () => void;
}

export function SettingsPanel({
  expanded,
  onExpandedChange,
  avatars,
  models,
  avatarId,
  model,
  onAvatarChange,
  onModelChange,
  edgeVoice,
  onEdgeVoiceChange,
  edgeVoiceOptions,
  ttsProvider,
  onTtsProviderChange,
  qwenModel,
  onQwenModelChange,
  qwenModelOptions,
  qwenVoice,
  onQwenVoiceChange,
  qwenVoiceOptions,
  llmSystemPrompt,
  onLlmSystemPromptChange,
  onReferenceImageChange,
  onSavePrompt,
  onSaveReferenceImage,
  promptSaving = false,
  referenceSaving = false,
  onOpenVoiceClone,
}: SettingsPanelProps) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape" && expanded) {
        onExpandedChange(false);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [expanded, onExpandedChange]);

  return (
    <aside
      className="pointer-events-none fixed bottom-0 right-0 top-14 z-40 flex max-sm:top-12"
      aria-label="设置侧栏"
    >
      <div className="pointer-events-auto flex h-full max-h-[calc(100dvh-3.5rem)] flex-row items-stretch sm:max-h-[calc(100dvh-3.5rem)]">
        {/* 可展开内容区 */}
        <div
          id="settings-dock-panel"
          className={`glass flex h-full min-h-0 flex-col overflow-hidden border-white/15 transition-[max-width,opacity,border-width] duration-300 ease-out ${
            expanded
              ? "max-w-[min(22rem,calc(100vw-3.25rem))] border-l opacity-100"
              : "max-w-0 border-l-0 opacity-0"
          }`}
        >
          <div
            className={`flex shrink-0 items-center justify-between border-b border-white/10 px-4 py-3 ${
              expanded ? "" : "pointer-events-none opacity-0"
            }`}
          >
            <h3 className="text-base font-semibold text-white">会话与音色</h3>
            <button
              type="button"
              onClick={() => onExpandedChange(false)}
              className="rounded-lg px-2 py-1 text-xs font-medium text-cyan-200/90 transition-colors hover:bg-white/10 hover:text-white"
              title="收起侧栏"
            >
              收起
            </button>
          </div>

          <div
            className={`min-h-0 flex-1 overflow-y-auto px-4 pb-6 pt-2 ${
              expanded ? "" : "pointer-events-none invisible"
            }`}
          >
            <div className="mb-5">
              <label className="mb-2 block text-xs font-medium uppercase tracking-wider text-slate-400">
                数字人形象
              </label>
              <div className="flex flex-col gap-2">
                {avatars.map((a) => (
                  <button
                    key={a.id}
                    type="button"
                    onClick={() => onAvatarChange(a.id)}
                    className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors ${
                      a.id === avatarId
                        ? "bg-cyan-500/20 text-white ring-1 ring-cyan-500/40"
                        : "text-slate-300 hover:bg-white/10"
                    }`}
                  >
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/10 text-xs text-slate-400">
                      {a.id.charAt(0).toUpperCase()}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm">{a.name ?? a.id}</div>
                      <div className="text-xs text-slate-500">{a.model_type}</div>
                    </div>
                  </button>
                ))}
              </div>
            </div>

            <div className="mb-5">
              <label className="mb-2 block text-xs font-medium uppercase tracking-wider text-slate-400">
                驱动模型
              </label>
              <select
                value={model}
                onChange={(e) => onModelChange(e.target.value)}
                className="w-full rounded-xl bg-white/10 px-3 py-2.5 text-sm text-slate-100 outline-none transition-colors focus:bg-white/15"
              >
                {models.map((m) => (
                  <option key={m} value={m} className="bg-slate-900">
                    {MODEL_LABELS[m] ?? m}
                  </option>
                ))}
              </select>
            </div>

            <div className="mb-5 border-t border-white/10 pt-5">
              <p className="mb-3 text-xs font-medium uppercase tracking-wider text-slate-400">
                会话自定义（Prompt / 参考图）
              </p>
              <label className="mb-3 block">
                <span className="mb-1.5 block text-[11px] text-slate-500">LLM System Prompt</span>
                <textarea
                  value={llmSystemPrompt}
                  onChange={(e) => onLlmSystemPromptChange(e.target.value)}
                  rows={4}
                  className="w-full resize-none rounded-xl bg-white/10 px-3 py-2.5 text-sm text-slate-100 outline-none transition-colors focus:bg-white/15"
                  placeholder="输入新的系统提示词（保存后对新会话生效；未点保存时「开始」也会带上当前框内内容）"
                />
              </label>
              <label className="mb-3 block">
                <span className="mb-1.5 block text-[11px] text-slate-500">自定义参考图（可选）</span>
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  className="w-full rounded-xl bg-white/10 px-3 py-2 text-xs text-slate-200 file:mr-3 file:rounded-lg file:border-0 file:bg-cyan-600 file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-white hover:file:bg-cyan-500"
                  onChange={(e) => onReferenceImageChange(e.target.files?.[0] ?? null)}
                />
              </label>
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={onSavePrompt}
                  disabled={promptSaving}
                  className="rounded-xl bg-cyan-600/90 px-3 py-2.5 text-sm font-medium text-white transition-colors hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {promptSaving ? "保存中..." : "只保存 Prompt"}
                </button>
                <button
                  type="button"
                  onClick={onSaveReferenceImage}
                  disabled={referenceSaving}
                  className="rounded-xl bg-indigo-600/90 px-3 py-2.5 text-sm font-medium text-white transition-colors hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {referenceSaving ? "上传中..." : "只上传参考图"}
                </button>
              </div>
            </div>

            <div className="mb-5 border-t border-white/10 pt-5">
              <p className="mb-3 text-xs font-medium uppercase tracking-wider text-slate-400">
                朗读与合成（TTS）
              </p>
              <label className="mb-3 block">
                <span className="mb-1.5 block text-[11px] text-slate-500">合成线路</span>
                <select
                  value={ttsProvider}
                  onChange={(e) => onTtsProviderChange(e.target.value as TtsProviderExtended)}
                  className="w-full rounded-xl bg-white/10 px-3 py-2.5 text-sm text-slate-100 outline-none transition-colors focus:bg-white/15"
                >
                  <option value="edge" className="bg-slate-900">
                    微软 Edge（Neural）
                  </option>
                  <option value="dashscope" className="bg-slate-900">
                    百炼 Qwen-TTS Realtime
                  </option>
                  <option value="cosyvoice" className="bg-slate-900">
                    百炼 CosyVoice
                  </option>
                  <option value="sambert" className="bg-slate-900">
                    百炼 Sambert
                  </option>
                </select>
              </label>

              {ttsProvider === "edge" ? (
                <label className="block">
                  <span className="mb-1.5 block text-[11px] text-slate-500">朗读音色</span>
                  <select
                    value={edgeVoice}
                    onChange={(e) => onEdgeVoiceChange(e.target.value)}
                    className="w-full rounded-xl bg-white/10 px-3 py-2.5 text-sm text-slate-100 outline-none transition-colors focus:bg-white/15"
                  >
                    {edgeVoiceOptions.map((o) => (
                      <option key={o.id} value={o.id} className="bg-slate-900">
                        {o.label}
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                <>
                  <label className="mb-3 block">
                    <span className="mb-1.5 block text-[11px] text-slate-500">模型</span>
                    <select
                      value={qwenModel}
                      onChange={(e) => onQwenModelChange(e.target.value)}
                      className="w-full rounded-xl bg-white/10 px-3 py-2.5 text-sm text-slate-100 outline-none transition-colors focus:bg-white/15"
                    >
                      {qwenModelOptions.map((o) => (
                        <option key={o.id} value={o.id} className="bg-slate-900">
                          {o.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  {qwenVoiceOptions.length > 0 ? (
                    <label className="block">
                      <span className="mb-1.5 block text-[11px] text-slate-500">音色</span>
                      <select
                        value={qwenVoice}
                        onChange={(e) => onQwenVoiceChange(e.target.value)}
                        className="w-full rounded-xl bg-white/10 px-3 py-2.5 text-sm text-slate-100 outline-none transition-colors focus:bg-white/15"
                      >
                        {qwenVoiceOptions.map((o) => (
                          <option key={o.id} value={o.id} className="bg-slate-900">
                            {o.label}
                          </option>
                        ))}
                      </select>
                    </label>
                  ) : null}
                </>
              )}
            </div>

            {onOpenVoiceClone ? (
              <div className="border-t border-white/10 pt-5">
                <p className="mb-2 text-xs leading-relaxed text-slate-500">
                  在百炼开通音色复刻后，可录制样本写入音色库；保存后音色列表会出现「✦」条目。
                </p>
                <button
                  type="button"
                  onClick={() => onOpenVoiceClone()}
                  className="w-full rounded-xl bg-violet-600/85 px-3 py-2.5 text-sm font-medium text-white transition-colors hover:bg-violet-500"
                >
                  打开音色复刻
                </button>
              </div>
            ) : null}
          </div>
        </div>

        {/* 右侧常驻拉手：收起 / 展开 */}
        <button
          type="button"
          onClick={() => onExpandedChange(!expanded)}
          aria-expanded={expanded}
          aria-controls="settings-dock-panel"
          title={expanded ? "收起设置" : "展开设置"}
          className="flex w-[52px] shrink-0 flex-col items-center justify-center gap-2 rounded-l-2xl border border-r-0 border-white/25 bg-gradient-to-b from-cyan-500 via-cyan-600 to-violet-700 py-5 shadow-[0_0_24px_rgba(34,211,238,0.25)] transition-[filter] hover:brightness-110 active:brightness-95 sm:w-14"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="currentColor"
            className={`h-5 w-5 text-white transition-transform duration-300 ${expanded ? "rotate-180" : ""}`}
            aria-hidden
          >
            <path d="M15.41 7.41 14 6l-6 6 6 6 1.41-1.41L10.83 12z" />
          </svg>
          <span
            className="select-none text-xs font-bold tracking-[0.2em] text-white"
            style={{ writingMode: "vertical-rl", textOrientation: "mixed" }}
          >
            设置
          </span>
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="h-4 w-4 text-white/90"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.75}
            aria-hidden
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.248a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.212-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z"
            />
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
          </svg>
        </button>
      </div>
    </aside>
  );
}
