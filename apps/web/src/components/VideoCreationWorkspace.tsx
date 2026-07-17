import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import { BailianVoiceClone } from "./BailianVoiceClone";
import type { FasterLivePortraitConfig } from "./SettingsPanel";
import {
  ApiError,
  buildApiDownloadUrl,
  buildApiUrl,
  createVideoCreationJob,
  apiPostForm,
  type AvatarSummary,
  type DuoDialogLine,
  type DuoDialogRequest,
  type DuoDialogSpeakerTTS,
  type ExportVideoItem,
  type IndexTTSConfig,
  type PersonMode,
  type SceneBackgroundAsset,
  type SceneComposition,
  type VideoCreationCompositionConfig,
  type VoiceCatalogItem,
} from "../lib/api";
import type { VoiceCloneApplication } from "../lib/voiceCloneApply";
import { modelLabel } from "../lib/modelLabels";
import {
  videoCreationCompositionForAvatar,
  videoCreationStateForAvatar,
} from "../light2d/avatarSelection";
import { EDGE_ZH_VOICES } from "../constants/edgeZhVoices";
import {
  COSYVOICE_MODEL_OPTIONS,
  COSYVOICE_VOICE_OPTIONS,
  LOCAL_COSYVOICE_MODEL_OPTIONS,
  LOCAL_F5_TTS_MODEL_OPTIONS,
  LOCAL_INDEXTTS_MODEL_OPTIONS,
  LOCAL_TTS_VOICE_OPTIONS,
  SAMBERT_MODEL_OPTIONS,
  XIAOMI_MIMO_MODEL_OPTIONS,
  XIAOMI_MIMO_VOICE_OPTIONS,
  type TtsProviderExtended,
} from "../constants/ttsBailian";
import {
  QWEN_TTS_MODEL_OPTIONS,
  QWEN_TTS_VOICE_OPTIONS,
  QWEN_VOICE_CLONE_TARGET_OPTIONS,
} from "../constants/ttsQwen";
import { buildTTSPreviewPayload, requestDuoDialogPreview, requestTTSPreview } from "../lib/ttsPreview";

export type VideoCreationAudioSource = "upload" | "tts_text" | "duo_dialog";
type VideoCreationMode = "spoken_video" | "reference_video";
type VideoCreationOutputAspect = "16:9" | "9:16" | "1:1";

type VoiceOpt = { id: string; label: string; targetModel?: string | null };
type DuoDialogRole = DuoDialogLine["role"];
type DuoDialogSpeakers = Record<DuoDialogRole, DuoDialogSpeakerTTS>;

type VideoCreationWorkspaceProps = {
  avatars: AvatarSummary[];
  avatarId: string;
  sceneBackgrounds: SceneBackgroundAsset[];
  sceneCompositions: SceneComposition[];
  selectedSceneIdsByAvatar?: Record<string, string>;
  models: string[];
  onAvatarChange: (id: string) => void;
  onAvatarUploaded: (avatar: AvatarSummary) => void;
  onVoiceCloned: (application: VoiceCloneApplication) => void | Promise<void>;
  onExportCreated?: (item: ExportVideoItem) => void;
  onGoAssetLibrary?: () => void;
  onNotify?: (message: string, tone?: "info" | "success" | "error") => void;
  ttsProvider: TtsProviderExtended;
  onTtsProviderChange: (provider: TtsProviderExtended) => void;
  qwenModel: string;
  onQwenModelChange: (modelId: string) => void;
  qwenModelOptions: { id: string; label: string }[];
  qwenVoice: string;
  onQwenVoiceChange: (voiceId: string) => void;
  qwenVoiceOptions: VoiceOpt[];
  edgeVoice: string;
  onEdgeVoiceChange: (voiceId: string) => void;
  voiceCatalog: VoiceCatalogItem[];
  fasterliveportraitConfig: FasterLivePortraitConfig;
  onFasterLivePortraitConfigChange: (config: FasterLivePortraitConfig) => void;
};

const UPLOAD_AUDIO_SOURCE_OPTION: { id: VideoCreationAudioSource; label: string } = { id: "upload", label: "上传音频" };
const TTS_TEXT_AUDIO_SOURCE_OPTION: { id: VideoCreationAudioSource; label: string } = { id: "tts_text", label: "口播合成" };
const AUDIO_SOURCE_OPTIONS: { id: VideoCreationAudioSource; label: string }[] = [
  UPLOAD_AUDIO_SOURCE_OPTION,
  TTS_TEXT_AUDIO_SOURCE_OPTION,
];
const DUO_DIALOG_AUDIO_SOURCE_OPTION: { id: VideoCreationAudioSource; label: string } = { id: "duo_dialog", label: "双人对话" };
const PERSON_MODE_OPTIONS: { id: PersonMode; label: string }[] = [
  { id: "single", label: "单人" },
  { id: "double", label: "双人" },
];

const REFERENCE_DURATION_OPTIONS = [
  { value: 10, label: "10s" },
  { value: 30, label: "30s" },
  { value: 60, label: "1min" },
] as const;

const VIDEO_CREATION_MODELS = ["flashtalk", "flashhead", "fasterliveportrait", "musetalk", "quicktalk", "wav2lip"];
const VIDEO_CREATION_OUTPUT_SIZES = {
  "16:9": { label: "16:9", previewClassName: "aspect-video w-full" },
  "9:16": { label: "9:16", previewClassName: "aspect-[9/16] w-[min(100%,22rem)]" },
  "1:1": { label: "1:1", previewClassName: "aspect-square w-[min(100%,34rem)]" },
} as const satisfies Record<VideoCreationOutputAspect, { label: string; previewClassName: string }>;
const VIDEO_CREATION_OUTPUT_RESOLUTION_OPTIONS = [480, 720, 1080, 1440, 2160] as const;
type VideoCreationOutputResolution = number;
const MAX_VIDEO_CREATION_OUTPUT_RESOLUTION = 2160;
const VIDEO_CREATION_OUTPUT_ASPECTS = Object.keys(VIDEO_CREATION_OUTPUT_SIZES) as VideoCreationOutputAspect[];

function evenVideoDim(value: number): number {
  const rounded = Math.max(2, Math.round(value));
  return rounded % 2 === 0 ? rounded : rounded + 1;
}

function computeVideoCreationMaxResolution(avatar: AvatarSummary | null): number {
  const sourceWidth = Number(avatar?.width ?? 0);
  const sourceHeight = Number(avatar?.height ?? 0);
  const sourceShortEdge = Math.min(
    sourceWidth > 0 ? sourceWidth : Number.POSITIVE_INFINITY,
    sourceHeight > 0 ? sourceHeight : Number.POSITIVE_INFINITY,
  );
  if (!Number.isFinite(sourceShortEdge)) return MAX_VIDEO_CREATION_OUTPUT_RESOLUTION;
  return Math.min(MAX_VIDEO_CREATION_OUTPUT_RESOLUTION, Math.max(2, Math.floor(sourceShortEdge)));
}

function computeVideoCreationOutputSize(aspectRatio: VideoCreationOutputAspect, resolution: VideoCreationOutputResolution): { width: number; height: number } {
  if (aspectRatio === "16:9") {
    return { width: evenVideoDim((resolution * 16) / 9), height: evenVideoDim(resolution) };
  }
  if (aspectRatio === "9:16") {
    return { width: evenVideoDim(resolution), height: evenVideoDim((resolution * 16) / 9) };
  }
  return { width: evenVideoDim(resolution), height: evenVideoDim(resolution) };
}

function resolutionLabel(value: number): string {
  if (value === 480) return "480p";
  if (value === 720) return "720p";
  if (value === 1080) return "1080p";
  if (value === 1440) return "2K";
  if (value === 2160) return "4K";
  return `${value}px`;
}

function outputResolutionOptionLabel(value: number, maxResolution: number): string {
  if (value === maxResolution && !VIDEO_CREATION_OUTPUT_RESOLUTION_OPTIONS.includes(value as (typeof VIDEO_CREATION_OUTPUT_RESOLUTION_OPTIONS)[number])) {
    return `原分辨率 ${resolutionLabel(value)}`;
  }
  return resolutionLabel(value);
}
const VIDEO_CREATION_SCRIPT_MAX_CHARS = 1000;
const DUO_DIALOG_LINE_MAX_CHARS = 500;
const DEFAULT_DUO_DIALOG_GAP_MS = 120;
const DEFAULT_DUO_DIALOG_VOICES: Record<DuoDialogRole, string> = {
  left: "zh-CN-XiaoxiaoNeural",
  right: "zh-CN-YunxiNeural",
};
const DUO_DIALOG_ROLE_LABELS: Record<DuoDialogRole, string> = { left: "左侧", right: "右侧" };
const TTS_PROVIDER_OPTIONS: TtsProviderExtended[] = ["edge", "dashscope", "cosyvoice", "sambert", "local_cosyvoice", "indextts", "local_f5_tts", "xiaomi_mimo", "openai_compatible"];

function modelOptionsForProvider(provider: TtsProviderExtended): { id: string; label: string }[] {
  if (provider === "dashscope") {
    const ids = new Set(QWEN_TTS_MODEL_OPTIONS.map((item) => item.id));
    return [...QWEN_TTS_MODEL_OPTIONS, ...QWEN_VOICE_CLONE_TARGET_OPTIONS.filter((item) => !ids.has(item.id))];
  }
  if (provider === "cosyvoice") return COSYVOICE_MODEL_OPTIONS;
  if (provider === "sambert") return SAMBERT_MODEL_OPTIONS;
  if (provider === "local_cosyvoice") return LOCAL_COSYVOICE_MODEL_OPTIONS;
  if (provider === "indextts") return LOCAL_INDEXTTS_MODEL_OPTIONS;
  if (provider === "local_f5_tts") return LOCAL_F5_TTS_MODEL_OPTIONS;
  if (provider === "xiaomi_mimo") return XIAOMI_MIMO_MODEL_OPTIONS;
  return [];
}

function baseVoiceOptionsForProvider(provider: TtsProviderExtended): VoiceOpt[] {
  if (provider === "edge") return EDGE_ZH_VOICES.map((voice) => ({ id: voice.id, label: voice.label }));
  if (provider === "dashscope") return QWEN_TTS_VOICE_OPTIONS;
  if (provider === "cosyvoice") return COSYVOICE_VOICE_OPTIONS;
  if (provider === "xiaomi_mimo") return XIAOMI_MIMO_VOICE_OPTIONS;
  if (provider === "local_cosyvoice" || provider === "indextts" || provider === "local_f5_tts") return LOCAL_TTS_VOICE_OPTIONS;
  return [];
}

function voiceOptionsForProvider(provider: TtsProviderExtended, model: string | undefined, voiceCatalog: VoiceCatalogItem[]): VoiceOpt[] {
  const options = [...baseVoiceOptionsForProvider(provider)];
  for (const item of voiceCatalog) {
    if (item.provider !== provider) continue;
    if (item.target_model && model && item.target_model !== model) continue;
    options.push({ id: item.voice_id, label: item.display_label || item.voice_id, targetModel: item.target_model });
  }
  const seen = new Set<string>();
  return options.filter((item) => {
    if (seen.has(item.id)) return false;
    seen.add(item.id);
    return true;
  });
}

function defaultModelForProvider(provider: TtsProviderExtended): string | undefined {
  return modelOptionsForProvider(provider)[0]?.id;
}

function defaultVoiceForProvider(provider: TtsProviderExtended, model: string | undefined, voiceCatalog: VoiceCatalogItem[], fallback?: string): string | undefined {
  if (fallback && provider === "edge") return fallback;
  return voiceOptionsForProvider(provider, model, voiceCatalog)[0]?.id ?? fallback;
}

function normalizedSpeakerForProvider(provider: TtsProviderExtended, voiceCatalog: VoiceCatalogItem[], fallbackVoice?: string): DuoDialogSpeakerTTS {
  const model = defaultModelForProvider(provider);
  const voice = defaultVoiceForProvider(provider, model, voiceCatalog, fallbackVoice);
  return {
    tts_provider: provider,
    ...(model ? { tts_model: model } : {}),
    ...(voice && provider !== "sambert" && provider !== "openai_compatible" ? { voice } : {}),
  };
}

const FASTERLIVEPORTRAIT_ANIMATION_REGION_OPTIONS: { id: FasterLivePortraitConfig["animation_region"]; label: string }[] = [
  { id: "lip", label: "嘴部" },
  { id: "all", label: "全表情" },
  { id: "exp", label: "表情" },
  { id: "pose", label: "姿态" },
  { id: "eyes", label: "眼睛" },
];
export const DEFAULT_VIDEO_CREATION_FASTLIVEPORTRAIT_CONFIG = {
  head_motion_multiplier: 0.3,
  pose_motion_multiplier: 0.35,
  yaw_multiplier: 0.85,
  pitch_multiplier: 1.0,
  roll_multiplier: 0.85,
  animation_region: "lip",
  expression_multiplier: 1.0,
  mouth_open_multiplier: 0.9,
  mouth_corner_multiplier: 0.85,
  cheek_jaw_multiplier: 0.9,
  driving_multiplier: 1.0,
  cfg_scale: 3.0,
  flag_stitching: true,
  flag_pasteback: true,
  flag_relative_motion: true,
  flag_normalize_lip: false,
  flag_lip_retargeting: false,
} as const satisfies FasterLivePortraitConfig;
const FASTERLIVEPORTRAIT_SLIDERS: {
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
  { key: "mouth_open_multiplier", label: "张嘴开合", min: 0, max: 4, step: 0.05 },
  { key: "mouth_corner_multiplier", label: "嘴角牵动", min: 0, max: 3, step: 0.05 },
  { key: "cheek_jaw_multiplier", label: "脸颊下颌", min: 0, max: 3, step: 0.05 },
  { key: "driving_multiplier", label: "整体驱动", min: 0, max: 2, step: 0.05 },
  { key: "cfg_scale", label: "音频跟随", min: 0, max: 10, step: 0.25 },
];
const FASTERLIVEPORTRAIT_SWITCHES: {
  key: Extract<keyof FasterLivePortraitConfig, "flag_stitching" | "flag_pasteback" | "flag_relative_motion" | "flag_normalize_lip" | "flag_lip_retargeting">;
  label: string;
}[] = [
  { key: "flag_stitching", label: "Stitching" },
  { key: "flag_pasteback", label: "拼回原图" },
  { key: "flag_relative_motion", label: "相对运动" },
  { key: "flag_normalize_lip", label: "唇形归一" },
  { key: "flag_lip_retargeting", label: "唇形重定向" },
];

const INDEXTTS_PROVIDER_SET = new Set<TtsProviderExtended>(["indextts"]);

const DEFAULT_INDEXTTS_CONFIG: IndexTTSConfig = {
  emotion_mode: "voice",
  emo_alpha: 0.6,
  emo_text: "",
  emo_vector: [0, 0, 0, 0, 0, 0, 0, 0],
  use_random: false,
  interval_silence_ms: 0,
};

function buildIndexTTSQualityConfig(config: IndexTTSConfig): IndexTTSConfig {
  return {
    ...config,
    streaming_mode: "segment",
    max_text_tokens_per_segment: 80,
    quick_streaming_tokens: 4,
  };
}

const INDEXTTS_EMOTION_VECTOR_CONTROLS: { key: string; label: string; index: number }[] = [
  { key: "happy", label: "快乐", index: 0 },
  { key: "angry", label: "愤怒", index: 1 },
  { key: "sad", label: "悲伤", index: 2 },
  { key: "afraid", label: "恐惧", index: 3 },
  { key: "disgusted", label: "厌恶", index: 4 },
  { key: "melancholic", label: "忧郁", index: 5 },
  { key: "surprised", label: "惊讶", index: 6 },
  { key: "calm", label: "平静", index: 7 },
];

type IndexTTSEmotionPreset = {
  label: string;
  config: IndexTTSConfig & { emotion_mode: "vector" };
};

const INDEXTTS_EMOTION_PRESETS: IndexTTSEmotionPreset[] = [
  { label: "表达增强", config: { emotion_mode: "vector", emo_alpha: 1, emo_vector: [0.75, 0, 0, 0, 0, 0, 0.35, 0], use_random: false, interval_silence_ms: 0 } },
  { label: "快乐", config: { emotion_mode: "vector", emo_alpha: 1, emo_vector: [1, 0, 0, 0, 0, 0, 0, 0], use_random: false, interval_silence_ms: 0 } },
  { label: "愤怒", config: { emotion_mode: "vector", emo_alpha: 1, emo_vector: [0, 1, 0, 0, 0, 0, 0, 0], use_random: false, interval_silence_ms: 0 } },
  { label: "悲伤", config: { emotion_mode: "vector", emo_alpha: 1, emo_vector: [0, 0, 0.9, 0, 0, 0.3, 0, 0], use_random: false, interval_silence_ms: 0 } },
  { label: "惊讶", config: { emotion_mode: "vector", emo_alpha: 1, emo_vector: [0.15, 0, 0, 0.1, 0, 0, 1, 0], use_random: false, interval_silence_ms: 0 } },
  { label: "平静", config: { emotion_mode: "vector", emo_alpha: 1, emo_vector: [0, 0, 0, 0, 0, 0, 0, 0.8], use_random: false, interval_silence_ms: 0 } },
];

function freshIndexTTSConfig(): IndexTTSConfig {
  return { ...DEFAULT_INDEXTTS_CONFIG, emo_vector: [...(DEFAULT_INDEXTTS_CONFIG.emo_vector ?? [])] };
}

export function indexTTSEmotionPresetConfig(preset: IndexTTSEmotionPreset): IndexTTSConfig & {
  emotion_mode: "vector";
  emo_alpha: 1;
  emo_vector: number[];
  use_random: false;
} {
  const vector = preset.config.emo_vector ?? DEFAULT_INDEXTTS_CONFIG.emo_vector ?? [];
  return {
    ...preset.config,
    emotion_mode: "vector",
    emo_alpha: 1,
    emo_vector: [...vector],
    use_random: false,
    interval_silence_ms: numberOr(preset.config.interval_silence_ms, 0),
  };
}

export function indexTTSEmotionModeConfig(current: IndexTTSConfig, mode: IndexTTSConfig["emotion_mode"]): IndexTTSConfig {
  if (mode === "voice") {
    return {
      ...current,
      emotion_mode: "voice",
      emo_alpha: 0.6,
    };
  }
  return {
    ...current,
    emotion_mode: mode,
    emo_alpha: 1,
  };
}

function numberOr(value: unknown, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function indexTTSRequestConfig(config: IndexTTSConfig): IndexTTSConfig {
  const emotionMode = config.emotion_mode;
  const out: IndexTTSConfig = {
    emotion_mode: emotionMode,
    emo_alpha: numberOr(config.emo_alpha, 0.6),
    use_random: Boolean(config.use_random),
    interval_silence_ms: numberOr(config.interval_silence_ms, 0),
  };
  if (emotionMode === "text") {
    out.emo_text = (config.emo_text ?? "").trim();
  }
  if (emotionMode === "vector") {
    out.emo_vector = (config.emo_vector ?? DEFAULT_INDEXTTS_CONFIG.emo_vector ?? []).map((value) => numberOr(value, 0));
  }
  return out;
}

function freshDuoDialogLines(): DuoDialogLine[] {
  return [
    { id: "line-1", role: "left", text: "大家好，欢迎来到今天的双人对话。" },
    { id: "line-2", role: "right", text: "我们会用一问一答的方式介绍重点内容。" },
  ];
}

function duoDialogDefaultSpeakers(avatar: AvatarSummary | null, voiceCatalog: VoiceCatalogItem[] = []): DuoDialogSpeakers {
  const defaults: Record<string, string> = avatar?.duo_dialog?.default_voices ?? {};
  return {
    left: normalizedSpeakerForProvider("edge", voiceCatalog, defaults.left || defaults.female || DEFAULT_DUO_DIALOG_VOICES.left),
    right: normalizedSpeakerForProvider("edge", voiceCatalog, defaults.right || defaults.male || DEFAULT_DUO_DIALOG_VOICES.right),
  };
}

function duoDialogVoicesFromSpeakers(speakers: DuoDialogSpeakers): Record<DuoDialogRole, string> {
  return {
    left: speakers.left.voice || DEFAULT_DUO_DIALOG_VOICES.left,
    right: speakers.right.voice || DEFAULT_DUO_DIALOG_VOICES.right,
  };
}

function duoDialogRequest(lines: DuoDialogLine[], speakers: DuoDialogSpeakers, gapMs: number): DuoDialogRequest {
  return {
    lines: lines.map((line) => ({ id: line.id, role: line.role, text: line.text.trim() })),
    voices: duoDialogVoicesFromSpeakers(speakers),
    speakers,
    gap_ms: gapMs,
  };
}

function providerLabel(provider: TtsProviderExtended): string {
  if (provider === "edge") return "Edge TTS";
  if (provider === "dashscope") return "Qwen TTS";
  if (provider === "cosyvoice") return "CosyVoice";
  if (provider === "sambert") return "Sambert";
  if (provider === "indextts") return "Local IndexTTS";
  if (provider === "local_f5_tts") return "Local F5-TTS";
  if (provider === "xiaomi_mimo") return "小米 MiMo";
  if (provider === "openai_compatible") return "OpenAI-compatible TTS";
  return "Local CosyVoice";
}

function avatarNameFromFile(file: File): string {
  const stem = file.name.replace(/\.[^.]+$/, "").trim();
  return stem ? `视频创作 ${stem}` : "视频创作形象";
}

function sceneBackgroundUrl(background: SceneBackgroundAsset): string {
  return buildApiUrl(background.url);
}

export function VideoCreationWorkspace({
  avatars,
  avatarId,
  sceneBackgrounds,
  sceneCompositions,
  selectedSceneIdsByAvatar = {},
  models,
  onAvatarChange,
  onAvatarUploaded,
  onVoiceCloned,
  onExportCreated,
  onGoAssetLibrary,
  onNotify,
  ttsProvider,
  onTtsProviderChange,
  qwenModel,
  onQwenModelChange,
  qwenModelOptions,
  qwenVoice,
  onQwenVoiceChange,
  qwenVoiceOptions,
  edgeVoice,
  onEdgeVoiceChange,
  voiceCatalog,
  fasterliveportraitConfig,
  onFasterLivePortraitConfigChange,
}: VideoCreationWorkspaceProps) {
  const selectedAvatar = avatars.find((avatar) => avatar.id === avatarId) ?? avatars[0] ?? null;
  const [creationMode, setCreationMode] = useState<VideoCreationMode>("spoken_video");
  const [referenceDurationSec, setReferenceDurationSec] = useState<(typeof REFERENCE_DURATION_OPTIONS)[number]["value"]>(10);
  const [model, setModel] = useState(() => VIDEO_CREATION_MODELS.find((item) => models.includes(item)) ?? "fasterliveportrait");
  const [audioSource, setAudioSource] = useState<VideoCreationAudioSource>("upload");
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [sourceAssetBusy, setSourceAssetBusy] = useState(false);
  const [text, setText] = useState("欢迎使用 OpenTalking 视频创作。请选择数字人形象和音色，生成一段离线口播视频。");
  const [duoDialogLines, setDuoDialogLines] = useState<DuoDialogLine[]>(() => freshDuoDialogLines());
  const [duoDialogSpeakers, setDuoDialogSpeakers] = useState<DuoDialogSpeakers>(() => duoDialogDefaultSpeakers(selectedAvatar, voiceCatalog));
  const [duoDialogGapMs, setDuoDialogGapMs] = useState(DEFAULT_DUO_DIALOG_GAP_MS);
  const [draggingDuoLineId, setDraggingDuoLineId] = useState<string | null>(null);
  const [title, setTitle] = useState("数字人口播视频");
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState<ExportVideoItem | null>(null);
  const [cloneOpen, setCloneOpen] = useState(false);
  const [duoCloneTargetRole, setDuoCloneTargetRole] = useState<DuoDialogRole | null>(null);
  const [ttsPreviewing, setTtsPreviewing] = useState(false);
  const [indexttsConfig, setIndexttsConfig] = useState<IndexTTSConfig>(() => freshIndexTTSConfig());
  const [indexttsEmotionAudioFile, setIndexttsEmotionAudioFile] = useState<File | null>(null);
  const [activeIndexTTSPresetLabel, setActiveIndexTTSPresetLabel] = useState<string | null>(null);
  const [videoBackgroundId, setVideoBackgroundId] = useState<string | null>(null);
  const [videoAvatarAdjust, setVideoAvatarAdjust] = useState({ x: 0, y: 0, scale: 1 });
  const [videoOutputAspect, setVideoOutputAspect] = useState<VideoCreationOutputAspect>("16:9");
  const [videoOutputResolution, setVideoOutputResolution] = useState<VideoCreationOutputResolution>(1080);
  const [pendingSourceAssetFile, setPendingSourceAssetFile] = useState<File | null>(null);
  const sourceUploadRef = useRef<HTMLInputElement>(null);
  const ttsPreviewAudioRef = useRef<HTMLAudioElement | null>(null);
  const ttsPreviewUrlRef = useRef<string | null>(null);

  const availableVideoModels = useMemo(() => VIDEO_CREATION_MODELS.filter((item) => models.includes(item)), [models]);
  const regularEffectiveModel = availableVideoModels.includes(model)
    ? model
    : availableVideoModels[0] ?? model;
  const videoCreationState = videoCreationStateForAvatar(selectedAvatar, regularEffectiveModel);
  const effectiveModel = videoCreationState.model;
  const videoCreationModelOptions = videoCreationState.modelLocked
    ? ["mock"]
    : VIDEO_CREATION_MODELS;
  const selectedVoiceLabel = ttsProvider === "edge"
    ? EDGE_ZH_VOICES.find((voice) => voice.id === edgeVoice)?.label ?? edgeVoice
    : ttsProvider === "openai_compatible"
      ? "后端默认音色"
      : qwenVoiceOptions.find((voice) => voice.id === qwenVoice)?.label ?? qwenVoice;
  const cloneVoiceCount = voiceCatalog.filter((item) => item.source === "clone").length;
  const isReferenceVideoMode = !videoCreationState.referenceDisabled && creationMode === "reference_video";
  const duoDialogAvailable = !videoCreationState.duoDisabled && !isReferenceVideoMode && effectiveModel === "quicktalk" && selectedAvatar?.person_mode === "double" && Boolean(selectedAvatar?.duo_dialog);
  const duoDialogSelected = duoDialogAvailable && audioSource === "duo_dialog";
  const canPreviewTts = !isReferenceVideoMode && audioSource !== "upload" && !duoDialogSelected;
  const showIndexTTSControls = !isReferenceVideoMode && audioSource !== "upload" && audioSource !== "duo_dialog" && INDEXTTS_PROVIDER_SET.has(ttsProvider);
  const effectiveIndexTTSConfig = showIndexTTSControls ? buildIndexTTSQualityConfig(indexTTSRequestConfig(indexttsConfig)) : undefined;
  const showIndexTTSEmotionStrength = indexttsConfig.emotion_mode !== "voice";
  const availableAudioSourceOptions = useMemo(
    () => duoDialogAvailable ? [UPLOAD_AUDIO_SOURCE_OPTION, DUO_DIALOG_AUDIO_SOURCE_OPTION] : AUDIO_SOURCE_OPTIONS,
    [duoDialogAvailable],
  );
  const selectedScene = useMemo(() => {
    if (!selectedAvatar) return null;
    const selectedSceneId = selectedSceneIdsByAvatar[selectedAvatar.id];
    const avatarScenes = sceneCompositions.filter((scene) => scene.avatar_id === selectedAvatar.id);
    return avatarScenes.find((scene) => scene.id === selectedSceneId) ?? avatarScenes[0] ?? null;
  }, [sceneCompositions, selectedAvatar, selectedSceneIdsByAvatar]);
  const selectedVideoBackground = useMemo(
    () => videoCreationState.backgroundDisabled || !videoBackgroundId
      ? null
      : sceneBackgrounds.find((background) => background.id === videoBackgroundId) ?? null,
    [sceneBackgrounds, videoBackgroundId, videoCreationState.backgroundDisabled],
  );
  const videoAvatarAnchor = selectedScene?.avatar_anchor ?? "center";
  const videoAvatarFit = selectedScene?.avatar_fit ?? "contain";
  const videoAvatarBaseScale = selectedScene?.avatar_scale ?? 1;
  const videoAvatarDisplayScale = videoAvatarBaseScale * videoAvatarAdjust.scale;
  const maxSelectableOutputResolution = computeVideoCreationMaxResolution(selectedAvatar);
  const availableOutputResolutionOptions = useMemo(() => {
    const options: number[] = VIDEO_CREATION_OUTPUT_RESOLUTION_OPTIONS.filter((value) => value <= maxSelectableOutputResolution);
    if (!options.includes(maxSelectableOutputResolution)) {
      options.push(maxSelectableOutputResolution);
    }
    return [...new Set(options)].sort((left, right) => left - right);
  }, [maxSelectableOutputResolution]);
  const selectedOutputResolution = availableOutputResolutionOptions.includes(videoOutputResolution)
    ? videoOutputResolution
    : (availableOutputResolutionOptions[availableOutputResolutionOptions.length - 1] ?? availableOutputResolutionOptions[0] ?? MAX_VIDEO_CREATION_OUTPUT_RESOLUTION);
  const selectedVideoOutputSize = useMemo(() => {
    const base = VIDEO_CREATION_OUTPUT_SIZES[videoOutputAspect];
    const dimensions = computeVideoCreationOutputSize(videoOutputAspect, selectedOutputResolution);
    return { ...base, ...dimensions };
  }, [selectedOutputResolution, videoOutputAspect]);
  const videoAvatarPreviewLayer = useMemo(() => {
    const canvasW = selectedVideoOutputSize.width;
    const canvasH = selectedVideoOutputSize.height;
    const avatarW = Math.max(1, Number(selectedAvatar?.width || canvasW));
    const avatarH = Math.max(1, Number(selectedAvatar?.height || canvasH));
    const containScale = Math.min(canvasW / avatarW, canvasH / avatarH);
    const coverScale = Math.max(canvasW / avatarW, canvasH / avatarH);
    const fitScale = videoAvatarFit === "cover" ? coverScale : containScale;
    const layerW = Math.max(1, avatarW * fitScale * videoAvatarDisplayScale);
    const layerH = Math.max(1, avatarH * fitScale * videoAvatarDisplayScale);
    const originX = videoAvatarAnchor === "left"
      ? 0
      : videoAvatarAnchor === "right"
        ? canvasW - layerW
        : (canvasW - layerW) / 2;
    const originY = videoAvatarAnchor === "bottom" ? canvasH - layerH : (canvasH - layerH) / 2;
    return {
      leftPct: ((originX + videoAvatarAdjust.x) / canvasW) * 100,
      topPct: ((originY + videoAvatarAdjust.y) / canvasH) * 100,
      widthPct: (layerW / canvasW) * 100,
      heightPct: (layerH / canvasH) * 100,
    };
  }, [selectedAvatar?.height, selectedAvatar?.width, selectedVideoOutputSize.height, selectedVideoOutputSize.width, videoAvatarAdjust.x, videoAvatarAdjust.y, videoAvatarAnchor, videoAvatarDisplayScale, videoAvatarFit]);
  const compositionConfig = useMemo<VideoCreationCompositionConfig>(
    () => videoCreationCompositionForAvatar(selectedAvatar, {
      scene_composition_id: selectedScene?.id ?? null,
      background_id: videoBackgroundId,
      background_color: selectedScene?.background_color ?? "#ffffff",
      avatar_fit: videoAvatarFit,
      avatar_anchor: videoAvatarAnchor,
      avatar_scale: videoAvatarDisplayScale,
      avatar_offset_x: videoAvatarAdjust.x,
      avatar_offset_y: videoAvatarAdjust.y,
      output_width: selectedVideoOutputSize.width,
      output_height: selectedVideoOutputSize.height,
    }),
    [selectedAvatar, selectedScene?.background_color, selectedScene?.id, selectedVideoOutputSize.height, selectedVideoOutputSize.width, videoAvatarAdjust.scale, videoAvatarAdjust.x, videoAvatarAdjust.y, videoAvatarAnchor, videoAvatarDisplayScale, videoAvatarFit, videoBackgroundId],
  );

  const updateFasterLivePortraitNumber = useCallback((
    key: Exclude<keyof FasterLivePortraitConfig, "animation_region" | "flag_stitching" | "flag_pasteback" | "flag_relative_motion" | "flag_normalize_lip" | "flag_lip_retargeting">,
    value: string,
  ) => {
    const next = Number(value);
    if (!Number.isFinite(next)) return;
    onFasterLivePortraitConfigChange({ ...fasterliveportraitConfig, [key]: next });
  }, [fasterliveportraitConfig, onFasterLivePortraitConfigChange]);

  const updateFasterLivePortraitSwitch = useCallback((
    key: Extract<keyof FasterLivePortraitConfig, "flag_stitching" | "flag_pasteback" | "flag_relative_motion" | "flag_normalize_lip" | "flag_lip_retargeting">,
    checked: boolean,
  ) => {
    onFasterLivePortraitConfigChange({ ...fasterliveportraitConfig, [key]: checked });
  }, [fasterliveportraitConfig, onFasterLivePortraitConfigChange]);

  const updateIndexTTSNumber = useCallback((key: "emo_alpha" | "interval_silence_ms", value: string) => {
    const next = Number(value);
    if (!Number.isFinite(next)) return;
    setActiveIndexTTSPresetLabel(null);
    setIndexttsConfig((current) => ({ ...current, [key]: next }));
  }, []);

  const updateIndexTTSVector = useCallback((index: number, value: string) => {
    const next = Number(value);
    if (!Number.isFinite(next)) return;
    setIndexttsConfig((current) => {
      setActiveIndexTTSPresetLabel(null);
      const vector = [...(current.emo_vector ?? DEFAULT_INDEXTTS_CONFIG.emo_vector ?? [])];
      vector[index] = next;
      return { ...current, emo_vector: vector };
    });
  }, []);

  const applyIndexTTSEmotionPreset = useCallback((preset: IndexTTSEmotionPreset) => {
    setIndexttsConfig(indexTTSEmotionPresetConfig(preset));
    setActiveIndexTTSPresetLabel(preset.label);
  }, []);

  useEffect(() => {
    return () => {
      if (ttsPreviewUrlRef.current) {
        URL.revokeObjectURL(ttsPreviewUrlRef.current);
        ttsPreviewUrlRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    setVideoBackgroundId(
      videoCreationState.backgroundDisabled ? null : selectedScene?.background_id ?? null,
    );
    setVideoAvatarAdjust({ x: 0, y: 0, scale: 1 });
  }, [selectedAvatar?.id, selectedScene?.id, selectedScene?.background_id, videoCreationState.backgroundDisabled]);

  useEffect(() => {
    if (!videoCreationState.modelLocked) return;
    setCreationMode("spoken_video");
    setModel("mock");
    setVideoBackgroundId(null);
    setAudioSource((current) => current === "duo_dialog" ? "tts_text" : current);
  }, [videoCreationState.modelLocked]);

  useEffect(() => {
    if (
      !videoCreationState.modelLocked
      && selectedAvatar?.person_mode === "double"
      && models.includes("quicktalk")
    ) {
      setModel("quicktalk");
    }
    setDuoDialogSpeakers(duoDialogDefaultSpeakers(selectedAvatar, voiceCatalog));
  }, [models, selectedAvatar, videoCreationState.modelLocked, voiceCatalog]);

  useEffect(() => {
    if (duoDialogAvailable && audioSource !== "duo_dialog") {
      setAudioSource("duo_dialog");
      return;
    }
    if (!duoDialogAvailable && audioSource === "duo_dialog") {
      setAudioSource("tts_text");
    }
  }, [audioSource, duoDialogAvailable]);

  const handleSourceAsset = useCallback((file: File | null) => {
    if (!file || !selectedAvatar) return;
    const isVideo = file.type.startsWith("video/");
    const isImage = file.type.startsWith("image/");
    if (!isImage && !isVideo) {
      onNotify?.("请上传图片或视频作为数字人形象。", "error");
      return;
    }
    setPendingSourceAssetFile(file);
  }, [onNotify, selectedAvatar]);

  const handleUploadPersonModeSelect = useCallback(async (nextMode: PersonMode) => {
    const file = pendingSourceAssetFile;
    if (!file || !selectedAvatar) return;
    const isVideo = file.type.startsWith("video/");
    setSourceAssetBusy(true);
    try {
      const form = new FormData();
      form.set("base_avatar_id", selectedAvatar.id);
      form.set("name", avatarNameFromFile(file));
      form.set("model", effectiveModel);
      form.set("person_mode", nextMode);
      if (isVideo) {
        form.set("video", file);
      } else {
        form.set("image", file);
      }
      const created = await apiPostForm<AvatarSummary>("/avatars/custom", form);
      onAvatarUploaded(created);
      setPendingSourceAssetFile(null);
      onNotify?.(`已加入数字人资产：${created.name ?? created.id}`, "success");
    } catch (error) {
      console.warn("video creation source asset upload failed", error);
      const detail = error instanceof ApiError ? error.detail : null;
      onNotify?.(detail ? `上传形象失败：${detail}` : "上传形象失败。", "error");
    } finally {
      setSourceAssetBusy(false);
    }
  }, [effectiveModel, onAvatarUploaded, onNotify, pendingSourceAssetFile, selectedAvatar]);

  const handleVoiceCloned = useCallback(async (application: VoiceCloneApplication) => {
    await onVoiceCloned(application);
    onTtsProviderChange(application.provider);
    onQwenModelChange(application.model);
    onQwenVoiceChange(application.voice);
    if (duoCloneTargetRole) {
      setDuoDialogSpeakers((current) => ({
        ...current,
        [duoCloneTargetRole]: {
          tts_provider: application.provider,
          tts_model: application.model,
          voice: application.voice,
        },
      }));
    } else {
      setAudioSource("tts_text");
    }
    setDuoCloneTargetRole(null);
    setCloneOpen(false);
  }, [duoCloneTargetRole, onQwenModelChange, onQwenVoiceChange, onTtsProviderChange, onVoiceCloned]);

  const addDuoDialogLine = useCallback(() => {
    setDuoDialogLines((current) => {
      const lastLine = current[current.length - 1];
      const nextRole: DuoDialogRole = lastLine?.role === "left" ? "right" : "left";
      return [
        ...current,
        { id: `line-${Date.now()}`, role: nextRole, text: "" },
      ];
    });
  }, []);

  const updateDuoDialogLine = useCallback((lineId: string, patch: Partial<Pick<DuoDialogLine, "role" | "text">>) => {
    setDuoDialogLines((current) => current.map((line) => line.id === lineId ? { ...line, ...patch } : line));
  }, []);

  const removeDuoDialogLine = useCallback((lineId: string) => {
    setDuoDialogLines((current) => current.length <= 1 ? current : current.filter((line) => line.id !== lineId));
  }, []);

  const moveDuoDialogLine = useCallback((lineId: string, direction: -1 | 1) => {
    setDuoDialogLines((current) => {
      const index = current.findIndex((line) => line.id === lineId);
      const target = index + direction;
      if (index < 0 || target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }, []);

  const dropDuoDialogLine = useCallback((targetId: string) => {
    setDuoDialogLines((current) => {
      if (!draggingDuoLineId || draggingDuoLineId === targetId) return current;
      const from = current.findIndex((line) => line.id === draggingDuoLineId);
      const to = current.findIndex((line) => line.id === targetId);
      if (from < 0 || to < 0) return current;
      const next = [...current];
      const [item] = next.splice(from, 1);
      next.splice(to, 0, item);
      return next;
    });
    setDraggingDuoLineId(null);
  }, [draggingDuoLineId]);

  const updateDuoDialogSpeaker = useCallback((role: DuoDialogRole, patch: Partial<DuoDialogSpeakerTTS>) => {
    setDuoDialogSpeakers((current) => ({ ...current, [role]: { ...current[role], ...patch } }));
  }, []);

  const updateDuoDialogSpeakerProvider = useCallback((role: DuoDialogRole, provider: TtsProviderExtended) => {
    setDuoDialogSpeakers((current) => ({
      ...current,
      [role]: normalizedSpeakerForProvider(provider, voiceCatalog, current[role]?.voice),
    }));
  }, [voiceCatalog]);

  const handlePreviewTts = useCallback(async () => {
    if (duoDialogSelected) {
      if (duoDialogLines.some((line) => !line.text.trim())) {
        onNotify?.("请补全双人对话文本。", "info");
        return;
      }
      setTtsPreviewing(true);
      try {
        const blob = await requestDuoDialogPreview(duoDialogRequest(duoDialogLines, duoDialogSpeakers, duoDialogGapMs));
        if (ttsPreviewUrlRef.current) {
          URL.revokeObjectURL(ttsPreviewUrlRef.current);
        }
        const url = URL.createObjectURL(blob);
        ttsPreviewUrlRef.current = url;
        const audio = ttsPreviewAudioRef.current ?? new Audio();
        ttsPreviewAudioRef.current = audio;
        audio.src = url;
        await audio.play();
        onNotify?.("正在播放双人对话试听。", "success");
      } catch (error) {
        console.warn("video creation duo dialog preview failed", error);
        const detail = error instanceof ApiError ? error.detail : null;
        onNotify?.(detail ? `试听失败：${detail}` : "试听失败，请确认男女音色、模型和后端密钥配置。", "error");
      } finally {
        setTtsPreviewing(false);
      }
      return;
    }

    const previewText = text.trim();
    if (!previewText) {
      onNotify?.("请输入要试听的口播文本。", "info");
      return;
    }
    const voice = ttsProvider === "edge" ? edgeVoice : ttsProvider === "sambert" || ttsProvider === "openai_compatible" ? "" : qwenVoice;
    if (ttsProvider !== "edge" && ttsProvider !== "sambert" && ttsProvider !== "openai_compatible" && !voice.trim()) {
      onNotify?.("当前模型没有可用音色，请先复刻音色或切换模型。", "info");
      return;
    }
    if (showIndexTTSControls && indexttsConfig.emotion_mode === "audio" && !indexttsEmotionAudioFile) {
      onNotify?.("请先上传 IndexTTS 情绪音频。", "info");
      return;
    }
    setTtsPreviewing(true);
    try {
      const blob = await requestTTSPreview(
        buildTTSPreviewPayload({
          text: previewText,
          voice,
          provider: ttsProvider,
          model: qwenModel,
          indexttsConfig: effectiveIndexTTSConfig,
          indexttsEmotionAudioFile,
        }),
      );
      if (ttsPreviewUrlRef.current) {
        URL.revokeObjectURL(ttsPreviewUrlRef.current);
      }
      const url = URL.createObjectURL(blob);
      ttsPreviewUrlRef.current = url;
      const audio = ttsPreviewAudioRef.current ?? new Audio();
      ttsPreviewAudioRef.current = audio;
      audio.src = url;
      await audio.play();
      onNotify?.("正在播放试听音频。", "success");
    } catch (error) {
      console.warn("video creation tts preview failed", error);
      const detail = error instanceof ApiError ? error.detail : null;
      onNotify?.(detail ? `试听失败：${detail}` : "试听失败，请确认音色、模型和后端密钥配置。", "error");
    } finally {
      setTtsPreviewing(false);
    }
  }, [duoDialogGapMs, duoDialogLines, duoDialogSelected, duoDialogSpeakers, edgeVoice, effectiveIndexTTSConfig, indexttsConfig.emotion_mode, indexttsEmotionAudioFile, onNotify, qwenModel, qwenVoice, showIndexTTSControls, text, ttsProvider]);

  const handleGenerate = useCallback(async () => {
    if (!selectedAvatar) {
      onNotify?.("请先选择数字人资产。", "info");
      return;
    }
    if (isReferenceVideoMode && !models.includes("flashtalk")) {
      onNotify?.("当前环境没有可用 FlashTalk 模型，无法生成参考视频。", "info");
      return;
    }
    if (!isReferenceVideoMode && audioSource === "upload" && !audioFile) {
      onNotify?.("请先上传音频文件。", "info");
      return;
    }
    if (!isReferenceVideoMode && audioSource === "duo_dialog") {
      if (!duoDialogAvailable) {
        onNotify?.("当前形象不支持 QuickTalk 双人对话。", "info");
        return;
      }
      if (duoDialogLines.some((line) => !line.text.trim())) {
        onNotify?.("请补全双人对话文本。", "info");
        return;
      }
    }
    if (!isReferenceVideoMode && audioSource !== "upload" && audioSource !== "duo_dialog" && !text.trim()) {
      onNotify?.("请输入要合成的口播文本。", "info");
      return;
    }
    if (showIndexTTSControls && indexttsConfig.emotion_mode === "audio" && !indexttsEmotionAudioFile) {
      onNotify?.("请先上传 IndexTTS 情绪音频。", "info");
      return;
    }
    setGenerating(true);
    setResult(null);
    try {
      if (isReferenceVideoMode) {
        const response = await createVideoCreationJob({
          model: "flashtalk",
          avatarId: selectedAvatar.id,
          title,
          audioSource: "reference_video",
          durationSec: referenceDurationSec,
          compositionConfig,
        });
        setResult(response.export_video);
        onExportCreated?.(response.export_video);
        onNotify?.(`参考视频已保存到资产库：${response.export_video.title}`, "success");
        return;
      }
      if (audioSource === "duo_dialog") {
        const response = await createVideoCreationJob({
          model: effectiveModel,
          avatarId: selectedAvatar.id,
          title,
          audioSource: "duo_dialog",
          ttsProvider,
          ttsModel: ttsProvider === "edge" || ttsProvider === "openai_compatible" ? undefined : qwenModel,
          indexttsConfig: effectiveIndexTTSConfig,
          indexttsEmotionAudioFile,
          duoDialog: duoDialogRequest(duoDialogLines, duoDialogSpeakers, duoDialogGapMs),
          compositionConfig,
        });
        setResult(response.export_video);
        onExportCreated?.(response.export_video);
        onNotify?.(`视频创作已保存到资产库：${response.export_video.title}`, "success");
        return;
      }
      const response = await createVideoCreationJob({
        model: effectiveModel,
        avatarId: selectedAvatar.id,
        title,
        audioSource,
        audioFile,
        text,
        ttsProvider,
        ttsModel: ttsProvider === "edge" || ttsProvider === "openai_compatible" ? undefined : qwenModel,
        voice: ttsProvider === "edge" ? edgeVoice : ttsProvider === "openai_compatible" ? undefined : qwenVoice,
        fasterliveportraitConfig: effectiveModel === "fasterliveportrait" ? fasterliveportraitConfig : undefined,
        indexttsConfig: effectiveIndexTTSConfig,
        indexttsEmotionAudioFile,
        compositionConfig,
      });
      setResult(response.export_video);
      onExportCreated?.(response.export_video);
      onNotify?.(`视频创作已保存到资产库：${response.export_video.title}`, "success");
    } catch (error) {
      console.warn("video creation job failed", error);
      const detail = error instanceof ApiError ? error.detail : null;
      onNotify?.(detail ? `视频创作失败：${detail}` : "视频创作失败，请查看后端日志。", "error");
    } finally {
      setGenerating(false);
    }
  }, [audioFile, audioSource, compositionConfig, duoDialogAvailable, duoDialogGapMs, duoDialogLines, duoDialogSpeakers, edgeVoice, effectiveIndexTTSConfig, effectiveModel, fasterliveportraitConfig, indexttsConfig.emotion_mode, indexttsEmotionAudioFile, isReferenceVideoMode, models, onExportCreated, onNotify, qwenModel, qwenVoice, referenceDurationSec, selectedAvatar, showIndexTTSControls, text, title, ttsProvider]);

  return (
    <main className="flex min-h-0 flex-1 flex-col bg-slate-100 p-4">
      <div className="grid min-h-0 flex-1 gap-4 xl:grid-cols-[18rem_minmax(28rem,1fr)_minmax(32rem,42rem)]">
        <section className="min-h-0 overflow-y-auto rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-xs font-medium text-slate-500">Source</p>
              <h1 className="mt-1 text-base font-semibold text-slate-950">视频创作</h1>
            </div>
            <button
              type="button"
              onClick={() => sourceUploadRef.current?.click()}
              disabled={sourceAssetBusy || !selectedAvatar}
              className="rounded-lg border border-cyan-200 bg-cyan-50 px-3 py-1.5 text-xs font-semibold text-cyan-700 transition hover:bg-cyan-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {sourceAssetBusy ? "上传中..." : "上传图片/视频"}
            </button>
            <input
              ref={sourceUploadRef}
              type="file"
              accept="image/*,video/*"
              className="hidden"
              onChange={(event: ChangeEvent<HTMLInputElement>) => {
                const input = event.currentTarget;
                handleSourceAsset(input.files?.[0] ?? null);
                input.value = "";
              }}
            />
          </div>
          {pendingSourceAssetFile ? (
            <div className="mt-3 rounded-md border border-cyan-200 bg-cyan-50 p-3">
              <p className="truncate text-xs font-semibold text-slate-700">{pendingSourceAssetFile.name}</p>
              <div className="mt-2 grid grid-cols-2 gap-2">
                {PERSON_MODE_OPTIONS.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    onClick={() => void handleUploadPersonModeSelect(option.id)}
                    disabled={!selectedAvatar || sourceAssetBusy}
                    className="rounded-md border border-cyan-200 bg-white px-3 py-2 text-xs font-semibold text-cyan-700 transition hover:bg-cyan-100 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    上传{option.label}
                  </button>
                ))}
              </div>
              <button
                type="button"
                onClick={() => setPendingSourceAssetFile(null)}
                disabled={sourceAssetBusy}
                className="mt-2 w-full rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-500 transition hover:text-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                取消
              </button>
            </div>
          ) : null}
          <div className="mt-4 space-y-2">
            {avatars.map((avatar) => {
              const selected = selectedAvatar?.id === avatar.id;
              return (
                <button
                  key={avatar.id}
                  type="button"
                  onClick={() => onAvatarChange(avatar.id)}
                  className={`flex w-full items-center gap-3 rounded-lg border p-2 text-left transition ${selected ? "border-cyan-300 bg-cyan-50" : "border-slate-200 bg-white hover:border-slate-300"}`}
                >
                  {avatar.has_preview_video ? (
                    <video
                      src={buildApiUrl(`/avatars/${encodeURIComponent(avatar.id)}/preview-video`)}
                      className="h-12 w-12 rounded-md border border-slate-200 object-cover"
                      muted
                      playsInline
                      preload="metadata"
                    />
                  ) : (
                    <img src={buildApiUrl(`/avatars/${encodeURIComponent(avatar.id)}/preview`)} alt={avatar.name ?? avatar.id} className="h-12 w-12 rounded-md border border-slate-200 object-cover" />
                  )}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold text-slate-900">{avatar.name ?? avatar.id}</span>
                    <span className="block truncate text-xs text-slate-500">{avatar.width}x{avatar.height}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </section>

        <section className="flex min-h-[30rem] min-w-0 flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-200 px-4 py-3">
            <p className="text-xs font-medium text-slate-500">Offline Generation</p>
            <h2 className="text-base font-semibold text-slate-950">离线数字人口播</h2>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => setCreationMode("spoken_video")}
                className={`rounded-lg border px-3 py-1.5 text-xs font-semibold transition ${creationMode === "spoken_video" ? "border-cyan-300 bg-cyan-50 text-cyan-700" : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"}`}
              >
                离线数字人口播
              </button>
              <button
                type="button"
                onClick={() => {
                  if (videoCreationState.referenceDisabled) return;
                  setCreationMode("reference_video");
                  setModel("flashtalk");
                }}
                disabled={videoCreationState.referenceDisabled}
                className={`rounded-lg border px-3 py-1.5 text-xs font-semibold transition ${creationMode === "reference_video" ? "border-cyan-300 bg-cyan-50 text-cyan-700" : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"}`}
              >
                图片生成参考视频
              </button>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            <div className="grid gap-4 lg:grid-cols-2">
              <label className="block text-sm font-medium text-slate-700">
                生成模型
                <select value={isReferenceVideoMode ? "flashtalk" : effectiveModel} onChange={(event) => setModel(event.target.value)} disabled={isReferenceVideoMode || videoCreationState.modelLocked} className="mt-2 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm disabled:bg-slate-100">
                  {videoCreationModelOptions.map((item) => (
                    <option key={item} value={item} disabled={!videoCreationState.modelLocked && !models.includes(item)}>{modelLabel(item)}{videoCreationState.modelLocked || models.includes(item) ? "" : "（不可用）"}</option>
                  ))}
                </select>
              </label>
              <label className="block text-sm font-medium text-slate-700">
                标题
                <input value={title} onChange={(event) => setTitle(event.target.value)} className="mt-2 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm" />
              </label>
            </div>

            {!isReferenceVideoMode && effectiveModel === "fasterliveportrait" ? (
              <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-semibold text-slate-800">FasterLivePortrait 参数</p>
                  <button
                    type="button"
                    onClick={() => onFasterLivePortraitConfigChange({ ...DEFAULT_VIDEO_CREATION_FASTLIVEPORTRAIT_CONFIG })}
                    className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600 transition hover:border-cyan-200 hover:text-cyan-700"
                  >
                    恢复默认
                  </button>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
                  {FASTERLIVEPORTRAIT_ANIMATION_REGION_OPTIONS.map((option) => (
                    <button
                      key={option.id}
                      type="button"
                      onClick={() => onFasterLivePortraitConfigChange({ ...fasterliveportraitConfig, animation_region: option.id })}
                      className={`rounded-lg border px-2 py-2 text-xs font-semibold transition ${fasterliveportraitConfig.animation_region === option.id ? "border-cyan-300 bg-cyan-50 text-cyan-700" : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"}`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  {FASTERLIVEPORTRAIT_SLIDERS.map((control) => {
                    const value = Number(fasterliveportraitConfig[control.key]);
                    return (
                      <label key={control.key} className="block rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-600">
                        <span className="flex items-center justify-between gap-2">
                          <span>{control.label}</span>
                          <input
                            type="number"
                            min={control.min}
                            max={control.max}
                            step={control.step}
                            value={value}
                            onChange={(event) => updateFasterLivePortraitNumber(control.key, event.target.value)}
                            className="h-7 w-20 rounded-md border border-slate-200 bg-slate-50 px-2 text-right text-xs font-semibold text-slate-700 outline-none focus:border-cyan-300"
                          />
                        </span>
                        <input
                          type="range"
                          min={control.min}
                          max={control.max}
                          step={control.step}
                          value={value}
                          onChange={(event) => updateFasterLivePortraitNumber(control.key, event.target.value)}
                          className="mt-2 w-full accent-cyan-600"
                        />
                      </label>
                    );
                  })}
                </div>
                <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
                  {FASTERLIVEPORTRAIT_SWITCHES.map((control) => (
                    <label key={control.key} className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700">
                      <span className="truncate">{control.label}</span>
                      <input
                        type="checkbox"
                        checked={Boolean(fasterliveportraitConfig[control.key])}
                        onChange={(event) => updateFasterLivePortraitSwitch(control.key, event.target.checked)}
                        className="h-4 w-4 shrink-0 accent-cyan-600"
                      />
                    </label>
                  ))}
                </div>
              </div>
            ) : null}

            {!isReferenceVideoMode ? (
              <div className="mt-5">
                <p className="text-sm font-semibold text-slate-800">音频来源</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {availableAudioSourceOptions.map((option) => (
                    <button
                      key={option.id}
                      type="button"
                      onClick={() => setAudioSource(option.id)}
                      className={`rounded-lg border px-3 py-2 text-sm font-semibold transition ${audioSource === option.id ? "border-cyan-300 bg-cyan-50 text-cyan-700" : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"}`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="mt-5 rounded-lg border border-slate-200 bg-slate-50 p-4">
                <p className="text-sm font-semibold text-slate-800">参考视频时长</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {REFERENCE_DURATION_OPTIONS.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => setReferenceDurationSec(option.value)}
                      className={`rounded-lg border px-3 py-2 text-sm font-semibold transition ${referenceDurationSec === option.value ? "border-cyan-300 bg-cyan-50 text-cyan-700" : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"}`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
                <div className="mt-4 flex items-center gap-3 rounded-lg border border-slate-200 bg-white p-3">
                  {selectedAvatar ? (
                    <>
                      <img src={buildApiUrl(`/avatars/${encodeURIComponent(selectedAvatar.id)}/preview`)} alt={selectedAvatar.name ?? selectedAvatar.id} className="h-16 w-16 rounded-md border border-slate-200 object-cover" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-semibold text-slate-900">{selectedAvatar.name ?? selectedAvatar.id}</span>
                        <span className="block text-xs text-slate-500">FlashTalk 使用内部低能量驱动音频生成参考视频</span>
                      </span>
                    </>
                  ) : (
                    <span className="text-sm font-medium text-slate-500">请先在左侧选择或上传参考图片</span>
                  )}
                </div>
              </div>
            )}

            {!isReferenceVideoMode && audioSource === "upload" ? (
              <label className="mt-4 block rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-700">
                <span className="font-semibold">上传音频</span>
                <span className="mt-1 block text-xs text-slate-500">支持 wav/mp3/m4a/webm 等 ffmpeg 可解码格式，服务端限制文件大小。</span>
                <input type="file" accept="audio/*,.webm,.mp3,.wav,.m4a,.aac,.flac,.ogg" className="mt-3 block w-full text-xs" onChange={(event) => setAudioFile(event.currentTarget.files?.[0] ?? null)} />
                {audioFile ? <span className="mt-2 block text-xs font-medium text-cyan-700">已选择：{audioFile.name}</span> : null}
              </label>
            ) : !isReferenceVideoMode && duoDialogSelected ? (
              <div className="mt-4 space-y-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="text-sm font-semibold text-slate-800">双人对话设置</p>
                  <button type="button" onClick={addDuoDialogLine} className="rounded-lg border border-cyan-200 bg-cyan-50 px-3 py-1.5 text-xs font-semibold text-cyan-700 hover:bg-cyan-100">＋</button>
                </div>
                <div className="grid gap-3 lg:grid-cols-2">
                  {(["left", "right"] as DuoDialogRole[]).map((role) => {
                    const speaker = duoDialogSpeakers[role];
                    const provider = (speaker.tts_provider || "edge") as TtsProviderExtended;
                    const modelOptions = modelOptionsForProvider(provider);
                    const voiceOptions = voiceOptionsForProvider(provider, speaker.tts_model, voiceCatalog);
                    const voiceItems = speaker.voice && !voiceOptions.some((item) => item.id === speaker.voice)
                      ? [{ id: speaker.voice, label: speaker.voice }, ...voiceOptions]
                      : voiceOptions;
                    return (
                      <div key={role} className="rounded-lg border border-slate-200 bg-white p-3">
                        <div className="flex items-center justify-between gap-3">
                          <span className="text-sm font-semibold text-slate-800">{DUO_DIALOG_ROLE_LABELS[role]}</span>
                          <button
                            type="button"
                            onClick={() => {
                              setDuoCloneTargetRole(role);
                              setCloneOpen(true);
                            }}
                            className="rounded-lg border border-cyan-200 bg-cyan-50 px-2.5 py-1 text-xs font-semibold text-cyan-700 hover:bg-cyan-100"
                          >
                            复刻/添加
                          </button>
                        </div>
                        <div className="mt-3 grid gap-2 sm:grid-cols-3">
                          <label className="block text-xs font-medium text-slate-600">
                            TTS
                            <select value={provider} onChange={(event) => updateDuoDialogSpeakerProvider(role, event.target.value as TtsProviderExtended)} className="mt-1.5 w-full rounded-lg border border-slate-200 bg-white px-2 py-2 text-sm">
                              {TTS_PROVIDER_OPTIONS.map((item) => <option key={item} value={item}>{providerLabel(item)}</option>)}
                            </select>
                          </label>
                          <label className="block text-xs font-medium text-slate-600">
                            模型
                            <select disabled={!modelOptions.length} value={speaker.tts_model || ""} onChange={(event) => updateDuoDialogSpeaker(role, { tts_model: event.target.value || undefined })} className="mt-1.5 w-full rounded-lg border border-slate-200 bg-white px-2 py-2 text-sm disabled:bg-slate-100">
                              {!modelOptions.length ? <option value="">默认</option> : modelOptions.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                            </select>
                          </label>
                          <label className="block text-xs font-medium text-slate-600">
                            音色
                            {provider === "openai_compatible" ? (
                              <input disabled value="后端默认" className="mt-1.5 w-full rounded-lg border border-slate-200 bg-slate-100 px-2 py-2 text-sm text-slate-500" />
                            ) : provider === "sambert" ? (
                              <input disabled value="随模型" className="mt-1.5 w-full rounded-lg border border-slate-200 bg-slate-100 px-2 py-2 text-sm text-slate-500" />
                            ) : voiceItems.length ? (
                              <select value={speaker.voice || ""} onChange={(event) => updateDuoDialogSpeaker(role, { voice: event.target.value || undefined })} className="mt-1.5 w-full rounded-lg border border-slate-200 bg-white px-2 py-2 text-sm">
                                {voiceItems.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                              </select>
                            ) : (
                              <input value={speaker.voice || ""} onChange={(event) => updateDuoDialogSpeaker(role, { voice: event.target.value || undefined })} placeholder="输入 voice_id" className="mt-1.5 w-full rounded-lg border border-slate-200 bg-white px-2 py-2 text-sm" />
                            )}
                          </label>
                        </div>
                      </div>
                    );
                  })}
                </div>
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white p-3">
                  <label className="block text-sm font-medium text-slate-700">
                    间隔 ms
                    <input type="number" min={0} max={5000} step={20} value={duoDialogGapMs} onChange={(event) => setDuoDialogGapMs(Math.max(0, Math.min(5000, Number(event.target.value) || 0)))} className="ml-2 w-28 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" />
                  </label>
                  <button
                    type="button"
                    onClick={() => void handlePreviewTts()}
                    disabled={ttsPreviewing || duoDialogLines.some((line) => !line.text.trim())}
                    className="rounded-lg border border-cyan-200 bg-cyan-50 px-3 py-1.5 text-xs font-semibold text-cyan-700 transition hover:bg-cyan-100 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {ttsPreviewing ? "试听中..." : "试听对话"}
                  </button>
                </div>
                <div className="space-y-3">
                  {duoDialogLines.map((line, index) => (
                    <div
                      key={line.id}
                      draggable
                      onDragStart={() => setDraggingDuoLineId(line.id)}
                      onDragOver={(event) => event.preventDefault()}
                      onDrop={() => dropDuoDialogLine(line.id)}
                      onDragEnd={() => setDraggingDuoLineId(null)}
                      className={`grid gap-3 rounded-lg border bg-white p-3 transition md:grid-cols-[2.5rem_7rem_minmax(0,1fr)_6rem] md:items-center ${draggingDuoLineId === line.id ? "border-cyan-300 bg-cyan-50" : "border-slate-200"}`}
                    >
                      <button type="button" className="h-9 w-9 cursor-grab rounded-lg border border-slate-200 bg-slate-50 text-lg leading-none text-slate-400 active:cursor-grabbing" aria-label="拖拽排序">⋮⋮</button>
                      <select value={line.role} onChange={(event) => updateDuoDialogLine(line.id, { role: event.target.value as DuoDialogRole })} className="rounded-lg border border-slate-200 bg-white px-2 py-2 text-sm font-semibold text-slate-700">
                        <option value="left">左侧</option>
                        <option value="right">右侧</option>
                      </select>
                      <textarea value={line.text} onChange={(event) => updateDuoDialogLine(line.id, { text: event.target.value })} rows={2} maxLength={DUO_DIALOG_LINE_MAX_CHARS} className="min-h-16 w-full resize-y rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-800" />
                      <div className="flex justify-end gap-1">
                        <span className="mr-1 rounded-md bg-blue-100 px-2 py-1.5 text-xs font-semibold text-blue-700">{index + 1}</span>
                        <button type="button" onClick={() => moveDuoDialogLine(line.id, -1)} disabled={index === 0} className="h-8 w-8 rounded-lg border border-slate-200 bg-white text-xs font-semibold text-slate-600 disabled:opacity-40">↑</button>
                        <button type="button" onClick={() => moveDuoDialogLine(line.id, 1)} disabled={index === duoDialogLines.length - 1} className="h-8 w-8 rounded-lg border border-slate-200 bg-white text-xs font-semibold text-slate-600 disabled:opacity-40">↓</button>
                        <button type="button" onClick={() => removeDuoDialogLine(line.id)} disabled={duoDialogLines.length <= 1} className="h-8 w-8 rounded-lg border border-slate-200 bg-white text-xs font-semibold text-slate-600 disabled:opacity-40">×</button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : !isReferenceVideoMode ? (
              <div className="mt-4 space-y-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
                <label className="block text-sm font-medium text-slate-700">
                  <span className="flex items-center justify-between gap-3">
                    <span>口播文本</span>
                    <span className="text-xs font-medium text-slate-400">{text.trim().length}/{VIDEO_CREATION_SCRIPT_MAX_CHARS}</span>
                  </span>
                  <textarea value={text} onChange={(event) => setText(event.target.value)} rows={5} maxLength={VIDEO_CREATION_SCRIPT_MAX_CHARS} className="mt-2 w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" />
                </label>
                <div className="grid gap-3 md:grid-cols-3">
                  <label className="block text-sm font-medium text-slate-700">
                    TTS
                    <select value={ttsProvider} onChange={(event) => onTtsProviderChange(event.target.value as TtsProviderExtended)} className="mt-2 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm">
                      {(["edge", "dashscope", "cosyvoice", "sambert", "local_cosyvoice", "indextts", "local_f5_tts", "xiaomi_mimo", "openai_compatible"] as TtsProviderExtended[]).map((item) => <option key={item} value={item}>{providerLabel(item)}</option>)}
                    </select>
                  </label>
                  <label className="block text-sm font-medium text-slate-700">
                    模型
                    <select disabled={ttsProvider === "edge" || ttsProvider === "openai_compatible"} value={ttsProvider === "edge" || ttsProvider === "openai_compatible" ? "" : qwenModel} onChange={(event) => onQwenModelChange(event.target.value)} className="mt-2 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm disabled:bg-slate-100">
                      {qwenModelOptions.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                    </select>
                  </label>
                  <label className="block text-sm font-medium text-slate-700">
                    音色
                    {ttsProvider === "edge" ? (
                      <select value={edgeVoice} onChange={(event) => onEdgeVoiceChange(event.target.value)} className="mt-2 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm">
                        {EDGE_ZH_VOICES.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                      </select>
                    ) : ttsProvider === "openai_compatible" ? (
                      <input disabled value="后端 .env 默认音色" className="mt-2 w-full rounded-lg border border-slate-200 bg-slate-100 px-3 py-2 text-sm text-slate-500" />
                    ) : (
                      <select value={qwenVoice} onChange={(event) => onQwenVoiceChange(event.target.value)} className="mt-2 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm">
                        {qwenVoiceOptions.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                      </select>
                    )}
                  </label>
                </div>
                {showIndexTTSControls ? (
                  <div className="border-t border-slate-200 pt-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold text-slate-800">IndexTTS 语音情绪</p>
                        <p className="mt-1 text-xs text-slate-500">控制语气、韵律和能量；音色仍由参考音频决定，视频表情由口型模型驱动。</p>
                      </div>
                      <button
                        type="button"
                        onClick={() => {
                          setIndexttsConfig(freshIndexTTSConfig());
                          setIndexttsEmotionAudioFile(null);
                          setActiveIndexTTSPresetLabel(null);
                        }}
                        className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600 transition hover:border-cyan-200 hover:text-cyan-700"
                      >
                        恢复默认
                      </button>
                    </div>
                    <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                      {([
                        { id: "voice", label: "跟随音色" },
                        { id: "text", label: "文本情绪" },
                        { id: "vector", label: "手动向量" },
                        { id: "audio", label: "情绪音频" },
                      ] as const).map((option) => (
                        <button
                          key={option.id}
                          type="button"
                          onClick={() => {
                            setIndexttsConfig((current) => indexTTSEmotionModeConfig(current, option.id));
                            setActiveIndexTTSPresetLabel(null);
                          }}
                          className={`rounded-lg border px-2 py-2 text-xs font-semibold transition ${indexttsConfig.emotion_mode === option.id ? "border-cyan-300 bg-cyan-50 text-cyan-700" : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"}`}
                        >
                          {option.label}
                        </button>
                      ))}
                    </div>
                    <div className={`mt-3 grid gap-3 ${showIndexTTSEmotionStrength ? "md:grid-cols-2" : ""}`}>
                      {showIndexTTSEmotionStrength ? (
                        <label className="block rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-600">
                          <span className="flex items-center justify-between gap-2">
                            <span>情绪强度</span>
                            <input
                              type="number"
                              min={0}
                              max={1}
                              step={0.05}
                              value={numberOr(indexttsConfig.emo_alpha, 0.6)}
                              onChange={(event) => updateIndexTTSNumber("emo_alpha", event.target.value)}
                              className="h-7 w-20 rounded-md border border-slate-200 bg-slate-50 px-2 text-right text-xs font-semibold text-slate-700 outline-none focus:border-cyan-300"
                            />
                          </span>
                          <input
                            type="range"
                            min={0}
                            max={1}
                            step={0.05}
                            value={numberOr(indexttsConfig.emo_alpha, 0.6)}
                            onChange={(event) => updateIndexTTSNumber("emo_alpha", event.target.value)}
                            className="mt-2 w-full accent-cyan-600"
                          />
                        </label>
                      ) : null}
                      <label className="block rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-600">
                        <span className="flex items-center justify-between gap-2">
                          <span>段间静音 ms</span>
                          <input
                            type="number"
                            min={0}
                            max={2000}
                            step={20}
                            value={numberOr(indexttsConfig.interval_silence_ms, 0)}
                            onChange={(event) => updateIndexTTSNumber("interval_silence_ms", event.target.value)}
                            className="h-7 w-20 rounded-md border border-slate-200 bg-slate-50 px-2 text-right text-xs font-semibold text-slate-700 outline-none focus:border-cyan-300"
                          />
                        </span>
                        <input
                          type="range"
                          min={0}
                          max={500}
                          step={20}
                          value={Math.min(500, numberOr(indexttsConfig.interval_silence_ms, 0))}
                          onChange={(event) => updateIndexTTSNumber("interval_silence_ms", event.target.value)}
                          className="mt-2 w-full accent-cyan-600"
                        />
                      </label>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {INDEXTTS_EMOTION_PRESETS.map((preset) => (
                        <button
                          key={preset.label}
                          type="button"
                          onClick={() => applyIndexTTSEmotionPreset(preset)}
                          className={`rounded-lg border px-3 py-1.5 text-xs font-semibold transition ${preset.label === activeIndexTTSPresetLabel ? "border-cyan-300 bg-cyan-50 text-cyan-700" : "border-slate-200 bg-white text-slate-600 hover:border-cyan-200 hover:text-cyan-700"}`}
                        >
                          {preset.label}
                        </button>
                      ))}
                    </div>
                    {indexttsConfig.emotion_mode === "text" ? (
                      <label className="mt-3 block text-sm font-medium text-slate-700">
                        情绪文本
                        <textarea
                          value={indexttsConfig.emo_text ?? ""}
                          onChange={(event) => {
                            setIndexttsConfig((current) => ({ ...current, emo_text: event.target.value }));
                            setActiveIndexTTSPresetLabel(null);
                          }}
                          rows={2}
                          maxLength={240}
                          className="mt-2 w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
                        />
                      </label>
                    ) : null}
                    {indexttsConfig.emotion_mode === "audio" ? (
                      <label className="mt-3 block rounded-lg border border-slate-200 bg-white px-3 py-3 text-sm font-medium text-slate-700">
                        情绪音频
                        <input
                          type="file"
                          accept="audio/*,.webm,.mp3,.wav,.m4a,.aac,.flac,.ogg"
                          className="mt-2 block w-full text-xs"
                          onChange={(event) => {
                            setIndexttsEmotionAudioFile(event.currentTarget.files?.[0] ?? null);
                            setActiveIndexTTSPresetLabel(null);
                          }}
                        />
                        {indexttsEmotionAudioFile ? (
                          <span className="mt-2 block truncate text-xs font-medium text-cyan-700">已选择：{indexttsEmotionAudioFile.name}</span>
                        ) : null}
                      </label>
                    ) : null}
                    {indexttsConfig.emotion_mode === "vector" ? (
                      <div className="mt-3 grid gap-2 sm:grid-cols-2">
                        {INDEXTTS_EMOTION_VECTOR_CONTROLS.map((control) => {
                          const value = numberOr(indexttsConfig.emo_vector?.[control.index], 0);
                          return (
                            <label key={control.key} className="block rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-600">
                              <span className="flex items-center justify-between gap-2">
                                <span>{control.label}</span>
                                <input
                                  type="number"
                                  min={0}
                                  max={1}
                                  step={0.05}
                                  value={value}
                                  onChange={(event) => updateIndexTTSVector(control.index, event.target.value)}
                                  className="h-7 w-20 rounded-md border border-slate-200 bg-slate-50 px-2 text-right text-xs font-semibold text-slate-700 outline-none focus:border-cyan-300"
                                />
                              </span>
                              <input
                                type="range"
                                min={0}
                                max={1}
                                step={0.05}
                                value={value}
                                onChange={(event) => updateIndexTTSVector(control.index, event.target.value)}
                                className="mt-2 w-full accent-cyan-600"
                              />
                            </label>
                          );
                        })}
                        <label className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700">
                          <span>随机风格</span>
                          <input
                            type="checkbox"
                            checked={Boolean(indexttsConfig.use_random)}
                            onChange={(event) => {
                              setIndexttsConfig((current) => ({ ...current, use_random: event.target.checked }));
                              setActiveIndexTTSPresetLabel(null);
                            }}
                            className="h-4 w-4 shrink-0 accent-cyan-600"
                          />
                        </label>
                      </div>
                    ) : null}
                  </div>
                ) : null}
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-cyan-200 bg-cyan-50 p-3 text-sm text-cyan-800">
                  <span>复刻音色：已有 {cloneVoiceCount} 个复刻音色，当前使用 {selectedVoiceLabel || "未选择"}</span>
                  <button
                    type="button"
                    onClick={() => {
                      setDuoCloneTargetRole(null);
                      setCloneOpen(true);
                    }}
                    className="rounded-lg bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-cyan-500"
                  >
                    录制/上传复刻
                  </button>
                </div>
                {canPreviewTts ? (
                  <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white p-3">
                    <span className="text-xs font-medium text-slate-500">试听当前文本、模型和音色后再生成视频。</span>
                    <button
                      type="button"
                      onClick={() => void handlePreviewTts()}
                      disabled={ttsPreviewing || !text.trim()}
                      className="rounded-lg border border-cyan-200 bg-cyan-50 px-3 py-1.5 text-xs font-semibold text-cyan-700 transition hover:bg-cyan-100 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {ttsPreviewing ? "试听中..." : "试听口播"}
                    </button>
                  </div>
                ) : null}
              </div>
            ) : null}

            <div className="mt-5 flex flex-wrap items-center gap-3">
              <button type="button" disabled={generating || !selectedAvatar || !availableVideoModels.length} onClick={() => void handleGenerate()} className="rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50">
                {generating ? "生成中..." : "生成并保存"}
              </button>
              {result ? <span className="text-sm font-medium text-emerald-700">已保存到资产库</span> : null}
            </div>
            {result ? (
              <div data-testid="video-creation-result-panel" className="mt-6 rounded-lg border border-slate-200 bg-slate-50 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-xs font-medium text-slate-500">Result</p>
                    <h2 className="mt-1 text-base font-semibold text-slate-950">生成结果</h2>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <a href={buildApiDownloadUrl(result.download_url)} download className="rounded-lg bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-cyan-500">下载</a>
                    <button type="button" onClick={onGoAssetLibrary} className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:border-cyan-200 hover:text-cyan-700">去资产库查看</button>
                  </div>
                </div>
                <video src={buildApiDownloadUrl(result.download_url)} className={`mt-3 mx-auto rounded-lg bg-slate-950 object-contain ${selectedVideoOutputSize.previewClassName}`} controls preload="metadata" />
                <div className="mt-3 rounded-lg bg-white p-3 text-xs text-slate-600">
                  <p className="font-semibold text-slate-800">{result.title}</p>
                  <p className="mt-1 break-all font-mono text-[11px]">{result.path}</p>
                </div>
              </div>
            ) : null}
          </div>
        </section>

        <aside className="flex min-h-0 flex-col overflow-y-auto rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <p className="text-xs font-medium text-slate-500">Composition</p>
          <h2 className="mt-1 text-base font-semibold text-slate-950">构图设置</h2>
          <div className="mt-4 shrink-0 overflow-hidden rounded-lg border border-slate-200 bg-slate-950 p-3">
            <div className="mb-2 flex items-center justify-between gap-3">
              <div>
                <p className="text-xs font-semibold text-white/55">画面预览</p>
                <h3 className="text-sm font-semibold text-white">生成前预览</h3>
              </div>
              <span className="rounded-md border border-white/15 bg-white/10 px-2 py-0.5 text-[11px] font-semibold text-white/75">
                {selectedVideoOutputSize.width}x{selectedVideoOutputSize.height}
              </span>
            </div>
            <div
              className={`relative mx-auto overflow-hidden rounded-md border border-white/10 bg-white ${selectedVideoOutputSize.previewClassName}`}
              style={{ backgroundColor: selectedScene?.background_color ?? "#f8fafc" }}
            >
              {selectedVideoBackground?.kind === "image" ? (
                <img src={sceneBackgroundUrl(selectedVideoBackground)} alt={selectedVideoBackground.name} className="absolute inset-0 h-full w-full object-cover" />
              ) : null}
              {selectedVideoBackground?.kind === "video" ? (
                <div className="absolute inset-0 flex items-center justify-center bg-slate-900 px-4 text-center text-xs font-medium text-white/80">
                  视频创作暂不支持视频背景
                </div>
              ) : null}
              {!selectedVideoBackground ? (
                <div className="absolute inset-0 bg-white" />
              ) : null}
              {selectedAvatar ? (
                <div
                  className="absolute"
                  style={{
                    left: `${videoAvatarPreviewLayer.leftPct}%`,
                    top: `${videoAvatarPreviewLayer.topPct}%`,
                    width: `${videoAvatarPreviewLayer.widthPct}%`,
                    height: `${videoAvatarPreviewLayer.heightPct}%`,
                  }}
                >
                  <img
                    src={buildApiUrl(`/avatars/${encodeURIComponent(selectedAvatar.id)}/preview`)}
                    alt={selectedAvatar.name ?? selectedAvatar.id}
                    className="absolute inset-0 h-full w-full object-fill"
                  />
                </div>
              ) : null}
              <div className="pointer-events-none absolute inset-x-5 bottom-5 rounded border border-white/35 bg-slate-950/35 px-3 py-1 text-center text-xs font-semibold text-white/80">
                字幕安全区
              </div>
            </div>
          </div>
          <div data-testid="video-creation-composition-controls" className="mt-3 space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
            <div>
              <p className="mb-1.5 text-xs font-semibold text-slate-700">输出画幅</p>
              <div className="grid grid-cols-3 gap-2">
                {VIDEO_CREATION_OUTPUT_ASPECTS.map((aspect) => {
                  const option = VIDEO_CREATION_OUTPUT_SIZES[aspect];
                  const active = aspect === videoOutputAspect;
                  return (
                    <button
                      key={aspect}
                      type="button"
                      onClick={() => setVideoOutputAspect(aspect)}
                      className={`rounded-md border px-2 py-1.5 text-xs font-semibold transition-colors ${
                        active
                          ? "border-cyan-500 bg-cyan-50 text-cyan-700"
                          : "border-slate-200 bg-white text-slate-600 hover:border-cyan-200 hover:text-cyan-700"
                      }`}
                    >
                      {option.label}
                    </button>
                  );
                })}
              </div>
            </div>
            <div className="rounded-md border border-slate-200 bg-white px-3 py-2.5">
              <div className="mb-1.5 flex items-center justify-between gap-2">
                <p className="text-xs font-semibold text-slate-700">分辨率</p>
                <p className="text-[11px] font-medium text-slate-500">上限 {resolutionLabel(maxSelectableOutputResolution)}</p>
              </div>
              <select
                value={selectedOutputResolution}
                onChange={(event) => setVideoOutputResolution(Number(event.target.value))}
                className="w-full max-w-xs rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs font-medium text-slate-700"
              >
                {availableOutputResolutionOptions.map((value) => (
                  <option key={value} value={value}>{outputResolutionOptionLabel(value, maxSelectableOutputResolution)}</option>
                ))}
              </select>
            </div>
            <label className="block text-xs font-semibold text-slate-700">
              本次生成背景
              <select
                value={videoBackgroundId ?? ""}
                onChange={(event) => setVideoBackgroundId(event.target.value || null)}
                disabled={videoCreationState.backgroundDisabled}
                className="mt-1 w-full rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs font-medium text-slate-700 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
              >
                <option value="">不使用背景</option>
                {sceneBackgrounds.map((background) => (
                  <option key={background.id} value={background.id}>{background.name}</option>
                ))}
              </select>
            </label>
            <label className="block text-xs font-medium text-slate-600">
              <span className="mb-1 flex items-center justify-between gap-2">
                <span>水平位置</span>
                <span className="tabular-nums">{videoAvatarAdjust.x}px</span>
              </span>
              <input
                type="range"
                min="-800"
                max="800"
                step="4"
                value={videoAvatarAdjust.x}
                onChange={(event) => setVideoAvatarAdjust((current) => ({ ...current, x: Number(event.target.value) }))}
                className="w-full accent-cyan-600"
              />
            </label>
            <label className="block text-xs font-medium text-slate-600">
              <span className="mb-1 flex items-center justify-between gap-2">
                <span>垂直位置</span>
                <span className="tabular-nums">{videoAvatarAdjust.y}px</span>
              </span>
              <input
                type="range"
                min="-600"
                max="600"
                step="4"
                value={videoAvatarAdjust.y}
                onChange={(event) => setVideoAvatarAdjust((current) => ({ ...current, y: Number(event.target.value) }))}
                className="w-full accent-cyan-600"
              />
            </label>
            <label className="block text-xs font-medium text-slate-600">
              <span className="mb-1 flex items-center justify-between gap-2">
                <span>人物缩放</span>
                <span className="tabular-nums">{videoAvatarDisplayScale.toFixed(2)}x</span>
              </span>
              <input
                type="range"
                min="0.2"
                max="3"
                step="0.02"
                value={videoAvatarAdjust.scale}
                onChange={(event) => setVideoAvatarAdjust((current) => ({ ...current, scale: Number(event.target.value) }))}
                className="w-full accent-cyan-600"
              />
            </label>
            <button
              type="button"
              onClick={() => setVideoAvatarAdjust({ x: 0, y: 0, scale: 1 })}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-cyan-200 hover:text-cyan-700"
            >
              重置本次生成构图
            </button>
          </div>
        </aside>
      </div>

      {cloneOpen ? (
        <>
          <button type="button" className="fixed inset-0 z-[55] bg-slate-900/20 backdrop-blur-[2px]" aria-label="关闭音色复刻" onClick={() => setCloneOpen(false)} />
          <aside className="fixed inset-y-0 right-0 z-[56] flex w-[min(100vw,28rem)] shadow-2xl shadow-slate-300/70">
            <div className="h-full max-h-[100dvh] flex-1 overflow-y-auto border-l border-slate-200 bg-slate-50 p-4 sm:p-5">
              <BailianVoiceClone onSuccess={handleVoiceCloned} onClose={() => setCloneOpen(false)} />
            </div>
          </aside>
        </>
      ) : null}
    </main>
  );
}
