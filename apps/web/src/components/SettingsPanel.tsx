import { useEffect, useState, type ReactNode } from "react";
import type { AvatarSummary } from "../lib/api";
import type { TtsProviderExtended } from "../constants/ttsBailian";

type VoiceOpt = { id: string; label: string; targetModel?: string | null };

export const SETTINGS_DOCK_EXPANDED_KEY = "opentalking-settings-dock-expanded";

const MODEL_LABELS: Record<string, string> = {
  flashhead: "FlashHead",
  flashtalk: "FlashTalk",
  musetalk: "MuseTalk",
  quicktalk: "QuickTalk",
  wav2lip: "Wav2Lip",
};

const TTS_PROVIDER_LABELS: Record<TtsProviderExtended, string> = {
  edge: "Edge",
  dashscope: "Qwen",
  cosyvoice: "Cosy",
  sambert: "Sambert",
};

const TTS_PROVIDER_SUBTITLES: Record<TtsProviderExtended, string> = {
  edge: "Neural",
  dashscope: "Realtime",
  cosyvoice: "Bailian",
  sambert: "Bailian",
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
  voiceApplyNotice?: string | null;
  ttsPreviewText: string;
  onTtsPreviewTextChange: (value: string) => void;
  onPreviewTts: () => void;
  ttsPreviewing?: boolean;
}

type SettingsSectionProps = {
  id: string;
  title: string;
  action?: ReactNode;
  children: ReactNode;
  open: boolean;
  onToggle: (id: string) => void;
};

function SettingsSection({ id, title, action, children, open, onToggle }: SettingsSectionProps) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white shadow-sm shadow-slate-200/40">
      <div className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
        <button
          type="button"
          onClick={() => onToggle(id)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
          aria-expanded={open}
          aria-controls={`settings-section-${id}`}
        >
          <svg
            className={`h-3.5 w-3.5 shrink-0 text-slate-400 transition-transform ${open ? "rotate-90" : ""}`}
            viewBox="0 0 20 20"
            fill="currentColor"
            aria-hidden
          >
            <path d="M7 4l6 6-6 6V4z" />
          </svg>
          <h3 className="truncate text-sm font-semibold text-slate-900">{title}</h3>
        </button>
        {action}
      </div>
      {open ? (
        <div id={`settings-section-${id}`} className="p-4">
          {children}
        </div>
      ) : null}
    </section>
  );
}

type ColumnOption = {
  id: string;
  label: string;
  subtitle?: string;
  hasChildren?: boolean;
};

function LevelOneButton({
  option,
  selected,
  onClick,
  compact = false,
}: {
  option: ColumnOption;
  selected: boolean;
  onClick: () => void;
  compact?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex shrink-0 flex-col justify-center rounded-lg border transition ${
        selected
          ? "border-cyan-300 bg-cyan-50 text-cyan-800 shadow-sm"
          : "border-slate-200 bg-white text-slate-700 hover:border-slate-300"
      } ${compact ? "h-14 w-14 items-center text-center" : "h-16 w-full items-start px-3 text-left"}`}
      title={option.label}
    >
      <span className="flex w-full min-w-0 items-center justify-between gap-2">
        <span className={`${compact ? "max-w-[3rem] text-xs" : "min-w-0 flex-1 text-sm"} truncate font-semibold leading-tight`}>
          {option.label}
        </span>
        {option.hasChildren && !compact ? (
          <span className={`shrink-0 text-lg leading-none ${selected ? "text-cyan-600" : "text-slate-400"}`}>›</span>
        ) : null}
      </span>
      {option.subtitle ? (
        <span className={`${compact ? "max-w-[3rem] text-[10px]" : "max-w-[15rem] text-xs"} mt-0.5 truncate font-medium leading-tight text-slate-400`}>
          {option.subtitle}
        </span>
      ) : null}
    </button>
  );
}

function DrillHeader({ title, onBack }: { title: string; onBack: () => void }) {
  return (
    <div className="mb-3 flex items-center gap-2">
      <button
        type="button"
        onClick={onBack}
        className="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs font-semibold text-slate-600 transition hover:border-cyan-200 hover:text-cyan-700"
      >
        ‹ 返回
      </button>
      <span className="truncate text-xs font-semibold text-slate-500">{title}</span>
    </div>
  );
}

function LevelTwoList({
  title,
  options,
  value,
  onChange,
  emptyText,
}: {
  title: string;
  options: ColumnOption[];
  value: string;
  onChange: (id: string) => void;
  emptyText?: string;
}) {
  return (
    <div className="min-w-0 rounded-lg border border-slate-200 bg-slate-50 p-2">
      <p className="mb-2 px-1 text-xs font-semibold text-slate-500">{title}</p>
      {options.length ? (
        <div className="max-h-44 space-y-1 overflow-y-auto pr-1">
          {options.map((option) => {
            const selected = option.id === value;
            return (
              <button
                key={option.id}
                type="button"
                onClick={() => onChange(option.id)}
                className={`flex w-full items-center gap-2 rounded-md border px-2.5 py-2 text-left transition ${
                  selected
                    ? "border-cyan-300 bg-white text-cyan-800 shadow-sm"
                    : "border-transparent bg-transparent text-slate-700 hover:border-slate-200 hover:bg-white"
                }`}
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs font-semibold">{option.label}</span>
                  {option.subtitle ? (
                    <span className="mt-0.5 block truncate text-[11px] text-slate-400">{option.subtitle}</span>
                  ) : null}
                </span>
                {option.hasChildren ? (
                  <span className={`shrink-0 text-lg leading-none ${selected ? "text-cyan-600" : "text-slate-400"}`}>›</span>
                ) : null}
              </button>
            );
          })}
        </div>
      ) : (
        <p className="rounded-md border border-dashed border-slate-200 bg-white px-2.5 py-2 text-xs leading-relaxed text-slate-500">
          {emptyText ?? "暂无可用选项"}
        </p>
      )}
    </div>
  );
}

export function SettingsPanel({
  expanded,
  onExpandedChange,
  avatars,
  models,
  avatarId,
  model,
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
  voiceApplyNotice = null,
  ttsPreviewText,
  onTtsPreviewTextChange,
  onPreviewTts,
  ttsPreviewing = false,
}: SettingsPanelProps) {
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({
    avatars: true,
    model: true,
    voice: true,
    role: true,
    reference: true,
  });
  const [voiceView, setVoiceView] = useState<"providers" | "models" | "voices">("providers");

  useEffect(() => {
    if (!voiceApplyNotice) return;
    setOpenSections((prev) => ({ ...prev, voice: true }));
    setVoiceView("voices");
  }, [voiceApplyNotice]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape" && expanded) {
        onExpandedChange(false);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [expanded, onExpandedChange]);

  const toggleSection = (id: string) => {
    setOpenSections((prev) => ({ ...prev, [id]: !prev[id] }));
  };
  const currentAvatar = avatars.find((a) => a.id === avatarId) ?? null;
  const modelOptions = models.map((m) => ({
    id: m,
    label: MODEL_LABELS[m] ?? m,
    subtitle: m,
  }));
  const providerOptions: ColumnOption[] = (["edge", "dashscope", "cosyvoice", "sambert"] as TtsProviderExtended[]).map((p) => ({
    id: p,
    label: TTS_PROVIDER_LABELS[p],
    subtitle: TTS_PROVIDER_SUBTITLES[p],
    hasChildren: true,
  }));
  const selectedProvider = providerOptions.find((option) => option.id === ttsProvider) ?? providerOptions[0];
  const qwenModelColumnOptions = qwenModelOptions.map((option) => ({
    id: option.id,
    label: option.label,
    subtitle: option.id,
    hasChildren: true,
  }));
  const qwenVoiceColumnOptions = qwenVoiceOptions.map((option) => ({
    id: option.id,
    label: option.label,
    subtitle: option.targetModel ?? option.id,
  }));
  const edgeVoiceColumnOptions = edgeVoiceOptions.map((option) => ({
    id: option.id,
    label: option.label,
    subtitle: option.id,
  }));

  const handleProviderSelect = (provider: TtsProviderExtended) => {
    onTtsProviderChange(provider);
    setVoiceView(provider === "edge" ? "voices" : "models");
  };

  const handleVoiceBack = () => {
    if (voiceView === "voices" && ttsProvider !== "edge") {
      setVoiceView("models");
      return;
    }
    setVoiceView("providers");
  };

  return (
    <aside className="flex min-h-0 flex-col border-r border-slate-200 bg-slate-50/70 lg:h-full lg:w-[360px] lg:shrink-0 lg:overflow-hidden">
      <div className="shrink-0 p-4 pb-3">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs font-medium text-slate-500">当前工作流</p>
            <h2 className="text-lg font-semibold text-slate-950">实时对话</h2>
          </div>
          <span className="rounded-full border border-cyan-200 bg-cyan-50 px-2 py-0.5 text-xs font-medium text-cyan-700">
            Studio
          </span>
        </div>
      </div>

      <div className="space-y-4 p-4 pt-0 lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
        <SettingsSection
          id="avatars"
          title="数字人形象"
          open={openSections.avatars}
          onToggle={toggleSection}
        >
          {currentAvatar ? (
            <div className="rounded-lg border border-cyan-200 bg-cyan-50 p-3">
              <p className="truncate text-sm font-semibold text-slate-950">
                {currentAvatar.name ?? currentAvatar.id}
              </p>
              <p className="mt-1 truncate text-xs font-medium text-cyan-700">
                数字人形象资产
              </p>
              <p className="mt-2 text-xs leading-relaxed text-slate-600">
                启动前可在中间区域查看照片并切换数字人形象。
              </p>
            </div>
          ) : (
            <p className="rounded-lg border border-dashed border-slate-200 bg-slate-50 p-3 text-xs text-slate-500">
              正在读取数字人资产...
            </p>
          )}
        </SettingsSection>

        <SettingsSection
          id="model"
          title="驱动模型"
          open={openSections.model}
          onToggle={toggleSection}
        >
          <div className="space-y-2">
            {modelOptions.map((option) => (
              <LevelOneButton
                key={option.id}
                option={option}
                selected={option.id === model}
                onClick={() => onModelChange(option.id)}
              />
            ))}
          </div>
        </SettingsSection>

        <SettingsSection
          id="voice"
          title="声音与角色"
          open={openSections.voice}
          onToggle={toggleSection}
          action={
            onOpenVoiceClone ? (
              <button
                type="button"
                onClick={() => onOpenVoiceClone()}
                className="shrink-0 text-xs font-medium text-cyan-700 hover:text-cyan-600"
              >
                复刻音色
              </button>
            ) : null
          }
        >
          <div className="space-y-3">
            {voiceApplyNotice ? (
              <p className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-medium text-emerald-800">
                {voiceApplyNotice}
              </p>
            ) : null}
            {voiceView !== "providers" ? (
              <>
                <DrillHeader title={voiceView === "models" ? "选择模型" : "选择音色"} onBack={handleVoiceBack} />
                <div className="flex gap-3">
                  <div className="flex w-14 shrink-0 flex-col gap-2">
                    {voiceView === "models" || ttsProvider === "edge"
                      ? providerOptions.map((option) => (
                          <LevelOneButton
                            key={option.id}
                            option={option}
                            selected={option.id === ttsProvider}
                            onClick={() => handleProviderSelect(option.id as TtsProviderExtended)}
                            compact
                          />
                        ))
                      : qwenModelColumnOptions.map((option) => (
                          <LevelOneButton
                            key={option.id}
                            option={option}
                            selected={option.id === qwenModel}
                            onClick={() => onQwenModelChange(option.id)}
                            compact
                          />
                        ))}
                  </div>
                  <div className="min-w-0 flex-1 space-y-2">
                    {voiceView === "models" ? (
                      <LevelTwoList
                        title={`${selectedProvider.label} 模型`}
                        options={qwenModelColumnOptions}
                        value={qwenModel}
                        onChange={(modelId) => {
                          onQwenModelChange(modelId);
                          setVoiceView("voices");
                        }}
                      />
                    ) : ttsProvider === "edge" ? (
                      <LevelTwoList
                        title="朗读音色"
                        options={edgeVoiceColumnOptions}
                        value={edgeVoice}
                        onChange={onEdgeVoiceChange}
                      />
                    ) : (
                      <LevelTwoList
                        title="音色"
                        options={qwenVoiceColumnOptions}
                        value={qwenVoice}
                        onChange={onQwenVoiceChange}
                        emptyText="当前模型没有可用音色。若选择的是音色复刻模型，请先完成录音复刻。"
                      />
                    )}
                  </div>
                </div>
              </>
            ) : (
              <div className="space-y-2">
                {providerOptions.map((option) => (
                  <LevelOneButton
                    key={option.id}
                    option={option}
                    selected={option.id === ttsProvider}
                    onClick={() => handleProviderSelect(option.id as TtsProviderExtended)}
                  />
                ))}
              </div>
            )}

            {voiceView !== "providers" ? null : (
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                <p className="text-xs font-semibold text-slate-500">当前选择</p>
                {ttsProvider === "edge" ? (
                  <p className="mt-1 truncate text-sm font-semibold text-slate-900">
                    {edgeVoiceOptions.find((option) => option.id === edgeVoice)?.label ?? edgeVoice}
                  </p>
                ) : (
                  <div className="mt-1 space-y-1">
                    <p className="truncate text-sm font-semibold text-slate-900">
                      {qwenModelOptions.find((option) => option.id === qwenModel)?.label ?? qwenModel}
                    </p>
                    <p className="truncate text-xs font-medium text-slate-500">
                      {qwenVoiceOptions.find((option) => option.id === qwenVoice)?.label ?? (qwenVoice || "暂无音色")}
                    </p>
                  </div>
                )}
              </div>
            )}

            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
              <label className="block">
                <span className="mb-1.5 block text-xs text-slate-500">音色试听</span>
                <textarea
                  value={ttsPreviewText}
                  onChange={(e) => onTtsPreviewTextChange(e.target.value)}
                  rows={2}
                  maxLength={240}
                  className="w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 outline-none transition focus:border-cyan-300"
                />
              </label>
              <div className="mt-2 flex items-center justify-between gap-2">
                <span className="text-xs text-slate-400">{ttsPreviewText.trim().length}/240</span>
                <button
                  type="button"
                  onClick={onPreviewTts}
                  disabled={ttsPreviewing || !ttsPreviewText.trim()}
                  className="rounded-lg bg-cyan-600 px-3 py-2 text-xs font-semibold text-white transition hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {ttsPreviewing ? "试听中..." : "试听一句"}
                </button>
              </div>
            </div>

          </div>
        </SettingsSection>

        <SettingsSection
          id="role"
          title="角色"
          open={openSections.role}
          onToggle={toggleSection}
        >
          <div className="space-y-3">
            <label className="block">
              <span className="mb-1.5 block text-xs text-slate-500">角色设定</span>
              <textarea
                value={llmSystemPrompt}
                onChange={(e) => onLlmSystemPromptChange(e.target.value)}
                rows={5}
                className="w-full resize-none rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-cyan-300 focus:bg-white"
                placeholder={"你可以在这里定义数字人的角色、说话风格和边界。\n\n示例：你是一位温和专业的产品讲解员，回答简洁自然，优先用中文回复。遇到不确定的问题先说明不确定，再给出可执行建议。"}
              />
            </label>
            <button
              type="button"
              onClick={onSavePrompt}
              disabled={promptSaving}
              className="w-full rounded-lg bg-slate-950 px-3 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {promptSaving ? "保存中..." : "保存角色"}
            </button>
          </div>
        </SettingsSection>

        <SettingsSection
          id="reference"
          title="参考图"
          open={openSections.reference}
          onToggle={toggleSection}
        >
          <div className="space-y-3">
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600 file:mr-3 file:rounded-md file:border-0 file:bg-cyan-600 file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-white hover:file:bg-cyan-500"
              onChange={(e) => onReferenceImageChange(e.target.files?.[0] ?? null)}
            />
            <button
              type="button"
              onClick={onSaveReferenceImage}
              disabled={referenceSaving}
              className="w-full rounded-lg border border-cyan-200 bg-cyan-50 px-3 py-2.5 text-sm font-semibold text-cyan-700 transition hover:bg-cyan-100 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {referenceSaving ? "上传中..." : "上传参考图"}
            </button>
          </div>
        </SettingsSection>
      </div>
    </aside>
  );
}
