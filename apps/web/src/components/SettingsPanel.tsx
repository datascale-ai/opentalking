import { useEffect, useState, type ReactNode } from "react";
import type { AvatarSummary } from "../lib/api";
import { modelConnectionBadge, type ModelStatus } from "../lib/modelStatus";
import type { TtsProviderExtended } from "../constants/ttsBailian";

type VoiceOpt = { id: string; label: string; targetModel?: string | null };
export type Wav2LipPostprocessMode = "auto" | "basic" | "opentalking_improved" | "easy_improved" | "easy_enhanced";
export type FasterLivePortraitConfig = {
  head_motion_multiplier: number;
  pose_motion_multiplier: number;
  yaw_multiplier: number;
  pitch_multiplier: number;
  roll_multiplier: number;
  animation_region: "lip" | "all" | "exp" | "pose" | "eyes";
  expression_multiplier: number;
  mouth_open_multiplier: number;
  mouth_corner_multiplier: number;
  cheek_jaw_multiplier: number;
  driving_multiplier: number;
  cfg_scale: number;
  flag_stitching: boolean;
  flag_pasteback: boolean;
  flag_relative_motion: boolean;
  flag_normalize_lip: boolean;
  flag_lip_retargeting: boolean;
};

export const DEFAULT_FASTLIVEPORTRAIT_CONFIG: FasterLivePortraitConfig = {
  head_motion_multiplier: 0.3,
  pose_motion_multiplier: 0.35,
  yaw_multiplier: 0.85,
  pitch_multiplier: 1.0,
  roll_multiplier: 0.85,
  animation_region: "lip",
  expression_multiplier: 1.0,
  mouth_open_multiplier: 1.25,
  mouth_corner_multiplier: 0.85,
  cheek_jaw_multiplier: 0.9,
  driving_multiplier: 1.0,
  cfg_scale: 4.0,
  flag_stitching: true,
  flag_pasteback: true,
  flag_relative_motion: true,
  flag_normalize_lip: true,
  flag_lip_retargeting: false,
};

export const SETTINGS_DOCK_EXPANDED_KEY = "opentalking-settings-dock-expanded";

const MODEL_LABELS: Record<string, string> = {
  flashhead: "FlashHead",
  fasterliveportrait: "FasterLivePortrait",
  flashtalk: "FlashTalk",
  mock: "无驱动模式",
  musetalk: "MuseTalk",
  quicktalk: "QuickTalk",
  wav2lip: "Wav2Lip",
};

const TTS_PROVIDER_LABELS: Record<TtsProviderExtended, string> = {
  edge: "Edge",
  dashscope: "Qwen",
  cosyvoice: "Cosy",
  sambert: "Sambert",
  local_cosyvoice: "Local CosyVoice",
};

const TTS_PROVIDER_SUBTITLES: Record<TtsProviderExtended, string> = {
  edge: "Neural",
  dashscope: "Realtime",
  cosyvoice: "Bailian",
  sambert: "Bailian",
  local_cosyvoice: "本地模型",
};

const ASR_PROVIDER_LABELS: Record<string, string> = {
  dashscope: "API 语音识别",
  sensevoice: "SenseVoiceSmall",
};

const ASR_PROVIDER_SUBTITLES: Record<string, string> = {
  dashscope: "DashScope API",
  sensevoice: "本地模型",
};

const ASR_PROVIDER_MODELS: Record<string, string> = {
  dashscope: "paraformer-realtime-v2",
  sensevoice: "iic/SenseVoiceSmall",
};

const WAV2LIP_POSTPROCESS_OPTIONS: { id: Wav2LipPostprocessMode; label: string }[] = [
  { id: "auto", label: "自动推荐" },
  { id: "basic", label: "基础" },
  { id: "opentalking_improved", label: "OpenTalking 优化" },
  { id: "easy_improved", label: "Easy-Wav2Lip 优化" },
];

const FASTERLIVEPORTRAIT_CONTROLS: {
  key: Exclude<keyof FasterLivePortraitConfig, "animation_region" | "flag_stitching" | "flag_pasteback" | "flag_relative_motion" | "flag_normalize_lip" | "flag_lip_retargeting">;
  label: string;
  min: number;
  max: number;
  step: number;
}[] = [
  { key: "head_motion_multiplier", label: "整体头部", min: 0, max: 2, step: 0.05 },
  { key: "pose_motion_multiplier", label: "姿态晃动", min: 0, max: 2, step: 0.05 },
  { key: "yaw_multiplier", label: "左右摇头", min: 0, max: 2, step: 0.05 },
  { key: "pitch_multiplier", label: "上下点头", min: 0, max: 2, step: 0.05 },
  { key: "roll_multiplier", label: "左右歪头", min: 0, max: 2, step: 0.05 },
  { key: "expression_multiplier", label: "表情唇形", min: 0, max: 3, step: 0.05 },
  { key: "mouth_open_multiplier", label: "张嘴开合", min: 0, max: 3, step: 0.05 },
  { key: "mouth_corner_multiplier", label: "嘴角牵动", min: 0, max: 3, step: 0.05 },
  { key: "cheek_jaw_multiplier", label: "脸颊下颌", min: 0, max: 3, step: 0.05 },
  { key: "driving_multiplier", label: "整体驱动", min: 0, max: 2, step: 0.05 },
  { key: "cfg_scale", label: "音频跟随", min: 0, max: 10, step: 0.25 },
];

const FASTERLIVEPORTRAIT_SWITCHES: {
  key: Extract<keyof FasterLivePortraitConfig, "flag_stitching" | "flag_pasteback" | "flag_relative_motion" | "flag_normalize_lip" | "flag_lip_retargeting">;
  label: string;
  caption: string;
}[] = [
  { key: "flag_stitching", label: "Stitching", caption: "稳定面部边缘" },
  { key: "flag_pasteback", label: "拼回原图", caption: "保持 source 原始构图" },
  { key: "flag_relative_motion", label: "相对运动", caption: "保留数字人基础姿态" },
  { key: "flag_normalize_lip", label: "唇形归一", caption: "减少初始嘴型偏差" },
  { key: "flag_lip_retargeting", label: "唇形重定向", caption: "增强嘴部跟随" },
];

const FASTERLIVEPORTRAIT_ANIMATION_REGION_OPTIONS: {
  id: FasterLivePortraitConfig["animation_region"];
  label: string;
}[] = [
  { id: "lip", label: "只驱动嘴部" },
  { id: "all", label: "全表情" },
  { id: "exp", label: "表情" },
  { id: "pose", label: "姿态" },
  { id: "eyes", label: "眼睛" },
];

interface SettingsPanelProps {
  /** 展开时显示表单；收起时仅保留右侧竖条入口 */
  expanded: boolean;
  onExpandedChange: (expanded: boolean) => void;
  avatars: AvatarSummary[];
  models: string[];
  modelStatuses: ModelStatus[];
  avatarId: string;
  model: string;
  modelConnected: boolean;
  wav2lipPostprocessMode: Wav2LipPostprocessMode;
  wav2lipPostprocessModeLocked: boolean;
  fasterliveportraitConfig: FasterLivePortraitConfig;
  fasterliveportraitApplying?: boolean;
  fasterliveportraitDirty?: boolean;
  fasterliveportraitLive?: boolean;
  onFasterLivePortraitConfigChange: (config: FasterLivePortraitConfig) => void;
  onApplyFasterLivePortraitConfig: () => void;
  onResetFasterLivePortraitConfig: () => void;
  onAvatarChange: (id: string) => void;
  onModelChange: (m: string) => void;
  onWav2LipPostprocessModeChange: (mode: Wav2LipPostprocessMode) => void;
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
  onSavePrompt: () => void;
  promptSaving?: boolean;
  onOpenVoiceClone?: () => void;
  voiceApplyNotice?: string | null;
  ttsPreviewText: string;
  onTtsPreviewTextChange: (value: string) => void;
  onPreviewTts: () => void;
  ttsPreviewing?: boolean;
  asrProvider: string;
  asrModel: string;
  onAsrProviderChange: (provider: string) => void;
  configLocked?: boolean;
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
  connected?: boolean;
  statusLabel?: string;
  statusTone?: "connected" | "disconnected" | "selfTest";
};

function LevelOneButton({
  option,
  selected,
  onClick,
  compact = false,
  disabled = false,
}: {
  option: ColumnOption;
  selected: boolean;
  onClick: () => void;
  compact?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`flex shrink-0 flex-col justify-center rounded-lg border transition disabled:cursor-not-allowed disabled:opacity-55 ${
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
        {option.statusLabel && !compact ? (
          <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-semibold ${
            option.statusTone === "connected"
              ? "border-emerald-200 bg-emerald-50 text-emerald-700"
              : option.statusTone === "selfTest"
                ? "border-cyan-200 bg-cyan-50 text-cyan-700"
              : "border-slate-200 bg-slate-50 text-slate-500"
          }`}>
            {option.statusLabel}
          </span>
        ) : null}
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
  modelStatuses,
  avatarId,
  model,
  modelConnected,
  wav2lipPostprocessMode,
  wav2lipPostprocessModeLocked,
  fasterliveportraitConfig,
  fasterliveportraitApplying = false,
  fasterliveportraitDirty = false,
  fasterliveportraitLive = false,
  onFasterLivePortraitConfigChange,
  onApplyFasterLivePortraitConfig,
  onResetFasterLivePortraitConfig,
  onModelChange,
  onWav2LipPostprocessModeChange,
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
  onSavePrompt,
  promptSaving = false,
  onOpenVoiceClone,
  voiceApplyNotice = null,
  ttsPreviewText,
  onTtsPreviewTextChange,
  onPreviewTts,
  ttsPreviewing = false,
  asrProvider,
  asrModel,
  onAsrProviderChange,
  configLocked = false,
}: SettingsPanelProps) {
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({
    avatars: true,
    model: true,
    asr: true,
    voice: true,
    role: true,
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
  const modelStatusById = new Map(modelStatuses.map((item) => [item.id, item]));
  const modelOptions = models.map((m) => {
    const badge = modelConnectionBadge(modelStatusById.get(m));
    return {
      id: m,
      label: MODEL_LABELS[m] ?? m,
      subtitle: m === "mock" ? "本地自测" : m,
      connected: badge.connected,
      statusLabel: badge.label,
      statusTone: badge.tone,
    };
  });
  const selectedModelBadge = modelConnectionBadge(modelStatusById.get(model), modelConnected);
  const qwenModelColumnOptions = qwenModelOptions.map((option) => ({
    id: option.id,
    label: option.label,
    subtitle: option.id,
    hasChildren: true,
  }));
  const providerOptions: ColumnOption[] = (["edge", "dashscope", "cosyvoice", "sambert", "local_cosyvoice"] as TtsProviderExtended[]).map((p) => ({
    id: p,
    label: TTS_PROVIDER_LABELS[p],
    subtitle: TTS_PROVIDER_SUBTITLES[p],
    hasChildren: p !== ttsProvider || qwenModelColumnOptions.length > 1,
  }));
  const selectedProvider = providerOptions.find((option) => option.id === ttsProvider) ?? providerOptions[0];
  const asrProviderOptions: ColumnOption[] = ["sensevoice", "dashscope"].map((p) => ({
    id: p,
    label: ASR_PROVIDER_LABELS[p] ?? p,
    subtitle: ASR_PROVIDER_SUBTITLES[p] ?? p,
  }));
  const selectedAsrLabel = ASR_PROVIDER_LABELS[asrProvider] ?? asrProvider;
  const selectedAsrModel = ASR_PROVIDER_MODELS[asrProvider] ?? (asrModel || "OPENTALKING_STT_MODEL");
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

  const providerHasSingleModel = (provider: TtsProviderExtended) => {
    if (provider === "edge") return true;
    if (provider !== ttsProvider) return false;
    return qwenModelColumnOptions.length <= 1;
  };

  const handleProviderSelect = (provider: TtsProviderExtended) => {
    onTtsProviderChange(provider);
    setVoiceView(providerHasSingleModel(provider) ? "voices" : "models");
  };

  const handleVoiceBack = () => {
    if (voiceView === "voices" && ttsProvider !== "edge" && !providerHasSingleModel(ttsProvider)) {
      setVoiceView("models");
      return;
    }
    setVoiceView("providers");
  };

  const updateFasterLivePortraitValue = (
    key: Exclude<keyof FasterLivePortraitConfig, "animation_region" | "flag_stitching" | "flag_pasteback" | "flag_relative_motion" | "flag_normalize_lip" | "flag_lip_retargeting">,
    rawValue: string,
  ) => {
    const numeric = Number(rawValue);
    if (!Number.isFinite(numeric)) return;
    onFasterLivePortraitConfigChange({
      ...fasterliveportraitConfig,
      [key]: numeric,
    });
  };

  const updateFasterLivePortraitSwitch = (
    key: Extract<keyof FasterLivePortraitConfig, "flag_stitching" | "flag_pasteback" | "flag_relative_motion" | "flag_normalize_lip" | "flag_lip_retargeting">,
    value: boolean,
  ) => {
    onFasterLivePortraitConfigChange({
      ...fasterliveportraitConfig,
      [key]: value,
    });
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
          action={
            <span className={`shrink-0 rounded-full border px-2 py-0.5 text-xs font-semibold ${
              selectedModelBadge.tone === "connected"
                ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                : selectedModelBadge.tone === "selfTest"
                  ? "border-cyan-200 bg-cyan-50 text-cyan-700"
                : "border-slate-200 bg-slate-50 text-slate-500"
            }`}>
              {selectedModelBadge.label}
            </span>
          }
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
            {!selectedModelBadge.connected ? (
              <p className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-medium text-slate-500">
                当前模型未连接，启动对应模型服务后即可使用。
              </p>
            ) : null}
            {model === "wav2lip" ? (
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-2">
                <p className="mb-2 px-1 text-xs font-semibold text-slate-500">口型融合模式</p>
                <div className="grid grid-cols-1 gap-1">
                  {WAV2LIP_POSTPROCESS_OPTIONS.map((option) => {
                    const selected = option.id === wav2lipPostprocessMode;
                    return (
                      <button
                        key={option.id}
                        type="button"
                        disabled={wav2lipPostprocessModeLocked}
                        onClick={() => onWav2LipPostprocessModeChange(option.id)}
                        className={`rounded-md border px-2.5 py-2 text-left text-xs font-semibold transition ${
                          selected
                            ? "border-cyan-300 bg-white text-cyan-800 shadow-sm"
                            : "border-transparent bg-transparent text-slate-700 hover:border-slate-200 hover:bg-white"
                        } ${
                          wav2lipPostprocessModeLocked
                            ? "cursor-not-allowed opacity-60 hover:border-transparent hover:bg-transparent"
                            : ""
                        }`}
                      >
                        {option.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            ) : null}
            {model === "fasterliveportrait" ? (
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-2">
                <div className="mb-2 flex items-center justify-between gap-2 px-1">
                  <p className="text-xs font-semibold text-slate-500">FasterLivePortrait 幅度</p>
                  <span className="text-[11px] font-medium text-slate-400">
                    {fasterliveportraitLive ? "运行中可应用" : "下次启动生效"}
                  </span>
                </div>
                <div className="space-y-2">
                  <div className="rounded-md border border-slate-200 bg-white px-2.5 py-2">
                    <p className="mb-1.5 text-xs font-semibold text-slate-700">驱动区域</p>
                    <div className="grid grid-cols-2 gap-1">
                      {FASTERLIVEPORTRAIT_ANIMATION_REGION_OPTIONS.map((option) => {
                        const selected = fasterliveportraitConfig.animation_region === option.id;
                        return (
                          <button
                            key={option.id}
                            type="button"
                            onClick={() => onFasterLivePortraitConfigChange({
                              ...fasterliveportraitConfig,
                              animation_region: option.id,
                            })}
                            className={`rounded-md border px-2 py-1.5 text-left text-xs font-semibold transition ${
                              selected
                                ? "border-cyan-300 bg-cyan-50 text-cyan-800"
                                : "border-slate-200 bg-white text-slate-600 hover:border-cyan-200 hover:text-cyan-700"
                            }`}
                          >
                            {option.label}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                  {FASTERLIVEPORTRAIT_CONTROLS.map((control) => {
                    const value = fasterliveportraitConfig[control.key];
                    return (
                      <label key={control.key} className="block rounded-md border border-slate-200 bg-white px-2.5 py-2">
                        <span className="mb-1.5 flex items-center justify-between gap-2">
                          <span className="truncate text-xs font-semibold text-slate-700">{control.label}</span>
                          <input
                            type="number"
                            min={control.min}
                            max={control.max}
                            step={control.step}
                            value={value}
                            onChange={(e) => updateFasterLivePortraitValue(control.key, e.target.value)}
                            className="h-7 w-20 rounded-md border border-slate-200 bg-slate-50 px-2 text-right text-xs font-semibold text-slate-700 outline-none focus:border-cyan-300"
                          />
                        </span>
                        <input
                          type="range"
                          min={control.min}
                          max={control.max}
                          step={control.step}
                          value={value}
                          onChange={(e) => updateFasterLivePortraitValue(control.key, e.target.value)}
                          className="w-full accent-cyan-600"
                        />
                      </label>
                    );
                  })}
                  <div className="grid grid-cols-1 gap-2">
                    {FASTERLIVEPORTRAIT_SWITCHES.map((control) => (
                      <label
                        key={control.key}
                        className="flex items-center justify-between gap-3 rounded-md border border-slate-200 bg-white px-2.5 py-2"
                      >
                        <span className="min-w-0">
                          <span className="block truncate text-xs font-semibold text-slate-700">{control.label}</span>
                          <span className="mt-0.5 block truncate text-[11px] font-medium text-slate-400">{control.caption}</span>
                        </span>
                        <input
                          type="checkbox"
                          checked={Boolean(fasterliveportraitConfig[control.key])}
                          onChange={(e) => updateFasterLivePortraitSwitch(control.key, e.target.checked)}
                          className="h-4 w-4 shrink-0 accent-cyan-600"
                        />
                      </label>
                    ))}
                  </div>
                </div>
                <div className="mt-3 flex gap-2">
                  <button
                    type="button"
                    onClick={onApplyFasterLivePortraitConfig}
                    disabled={fasterliveportraitApplying || !fasterliveportraitDirty}
                    className="min-h-9 flex-1 rounded-lg bg-cyan-600 px-3 py-2 text-xs font-semibold text-white transition hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {fasterliveportraitApplying ? "应用中..." : fasterliveportraitLive ? "实时应用" : "应用配置"}
                  </button>
                  <button
                    type="button"
                    onClick={onResetFasterLivePortraitConfig}
                    disabled={fasterliveportraitApplying}
                    className="min-h-9 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-600 transition hover:border-cyan-200 hover:text-cyan-700 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    重置
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        </SettingsSection>

        <SettingsSection
          id="asr"
          title="语音识别"
          open={openSections.asr}
          onToggle={toggleSection}
        >
          <div className="space-y-2 rounded-lg border border-slate-200 bg-white p-3">
            <p className="text-xs font-semibold text-slate-500">
              STT: {selectedAsrLabel}
            </p>
            <p className="mt-1 truncate text-sm font-semibold text-slate-900">{selectedAsrModel}</p>
            <div className="grid grid-cols-1 gap-1">
              {asrProviderOptions.map((option) => (
                <LevelOneButton
                  key={option.id}
                  option={option}
                  selected={option.id === asrProvider}
                  onClick={() => onAsrProviderChange(option.id)}
                  disabled={configLocked}
                />
              ))}
            </div>
            {configLocked ? (
              <p className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium leading-relaxed text-amber-700">
                当前数字人运行中，停止后可修改语音识别配置。
              </p>
            ) : (
              <p className="mt-2 text-xs leading-relaxed text-slate-500">默认由 OPENTALKING_STT_DEFAULT_PROVIDER 控制；连续语音和上传语音共用该本地/API STT 配置，选择 API 语音识别时走 DashScope STT 链路。</p>
            )}
          </div>
        </SettingsSection>

        <SettingsSection
          id="voice"
          title="语音合成"
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
                <DrillHeader
                  title={voiceView === "models" ? "选择模型" : `选择音色 · ${selectedProvider.label}`}
                  onBack={handleVoiceBack}
                />
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
          title="人设"
          open={openSections.role}
          onToggle={toggleSection}
        >
          <div className="space-y-3">
            <label className="block">
              <span className="mb-1.5 block text-xs text-slate-500">人设定义</span>
              <textarea
                value={llmSystemPrompt}
                onChange={(e) => onLlmSystemPromptChange(e.target.value)}
                rows={5}
                className="w-full resize-none rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-cyan-300 focus:bg-white"
                placeholder={"你可以在这里定义数字人的身份、说话风格和边界。\n\n示例：你是一位温和专业的产品讲解员，回答简洁自然，优先用中文回复。遇到不确定的问题先说明不确定，再给出可执行建议。"}
              />
            </label>
            <button
              type="button"
              onClick={onSavePrompt}
              disabled={promptSaving}
              className="w-full rounded-lg bg-slate-950 px-3 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {promptSaving ? "保存中..." : "保存人设"}
            </button>
          </div>
        </SettingsSection>
      </div>
    </aside>
  );
}
