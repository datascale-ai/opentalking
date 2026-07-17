import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AvatarSelectionStage, type AgentConfig } from "./components/AvatarSelectionStage";
import { BailianVoiceClone } from "./components/BailianVoiceClone";
import { ChatInput } from "./components/ChatInput";
import { ChatMessages } from "./components/ChatMessages";
import {
  DEFAULT_FASTLIVEPORTRAIT_CONFIG,
  SETTINGS_DOCK_EXPANDED_KEY,
  SettingsPanel,
  type FasterLivePortraitConfig,
  type Wav2LipPostprocessMode,
} from "./components/SettingsPanel";
import { RuntimeConfigWorkspace } from "./components/RuntimeConfigWorkspace";
import { SceneStage } from "./components/SceneStage";
import { TopBar, type ConversationViewMode, type StudioWorkflow } from "./components/TopBar";
import { ToastStack, type ToastMessage, type ToastTone } from "./components/ToastStack";
import { AssetLibraryWorkspace, type AssetLibraryTab } from "./components/AssetLibraryWorkspace";
import { VideoCloneWorkspace } from "./components/VideoCloneWorkspace";
import { playWithMutedFallback } from "./components/VideoBackground";
import {
  DEFAULT_VIDEO_CREATION_FASTLIVEPORTRAIT_CONFIG,
  VideoCreationWorkspace,
} from "./components/VideoCreationWorkspace";
import {
  ApiError,
  applyRuntimeConfig,
  apiDelete,
  apiGet,
  apiPost,
  apiPostForm,
  apiPut,
  apiUploadFile,
  buildApiUrl,
  getMemoryLibraries,
  listSceneBackgrounds,
  listSceneCompositions,
  loadRuntimeConfig,
  uploadExportVideo,
  type AvatarKnowledgeBasesResponse,
  type AvatarSummary,
  type CreateSessionRequest,
  type CreateSessionResponse,
  type KnowledgeBaseSummary,
  type KnowledgeBasesResponse,
  type PersonaSummary,
  type PersonasResponse,
  type RuntimeConfigApplyInput,
  type RuntimeConfigResponse,
  type SceneBackgroundAsset,
  type SceneComposition,
  type SessionKnowledgeBasesRequest,
  type SessionKnowledgeBasesResponse,
  type VoiceCatalogItem,
} from "./lib/api";
import { modelConnectionBadge, type ModelStatus } from "./lib/modelStatus";
import { modelLabel } from "./lib/modelLabels";
import { connectSse } from "./lib/sse";
import {
  DEFAULT_TTS_PREVIEW_TEXT,
  buildTTSPreviewPayload,
  requestTTSPreview,
} from "./lib/ttsPreview";
import type { VoiceCloneApplication } from "./lib/voiceCloneApply";
import { startPlayback } from "./lib/webrtc";
import {
  DEFAULT_EDGE_VOICE_ID,
  EDGE_VOICE_STORAGE_KEY,
  EDGE_ZH_VOICES,
} from "./constants/edgeZhVoices";
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
  isEdgeTts,
} from "./constants/ttsBailian";
import {
  DEFAULT_QWEN_MODEL_ID,
  DEFAULT_QWEN_VOICE_ID,
  QWEN_MODEL_STORAGE_KEY,
  QWEN_TTS_MODEL_OPTIONS,
  QWEN_TTS_VOICE_OPTIONS,
  QWEN_VOICE_CLONE_TARGET_OPTIONS,
  QWEN_VOICE_STORAGE_KEY,
  TTS_PROVIDER_STORAGE_KEY,
} from "./constants/ttsQwen";
import type { ConnectionStatus, MemoryLibrary, Message, QueueInfo } from "./types";
import {
  canChangeModelForAvatar,
  normalizeAvatarModelSelection,
  pickInitialAvatarForModel,
  recommendAvatarForModel,
} from "./light2d/avatarSelection";

const MEMORY_PROFILE_ID = "default";

function bailianModelOptions(provider: TtsProviderExtended): { id: string; label: string }[] {
  switch (provider) {
    case "dashscope":
      return QWEN_TTS_MODEL_OPTIONS;
    case "cosyvoice":
      return COSYVOICE_MODEL_OPTIONS;
    case "sambert":
      return SAMBERT_MODEL_OPTIONS;
    case "local_cosyvoice":
      return LOCAL_COSYVOICE_MODEL_OPTIONS;
    case "indextts":
      return LOCAL_INDEXTTS_MODEL_OPTIONS;
    case "local_f5_tts":
      return LOCAL_F5_TTS_MODEL_OPTIONS;
    case "xiaomi_mimo":
      return XIAOMI_MIMO_MODEL_OPTIONS;
    default:
      return [];
  }
}

function bailianVoiceOptions(provider: TtsProviderExtended): { id: string; label: string }[] {
  switch (provider) {
    case "dashscope":
      return QWEN_TTS_VOICE_OPTIONS;
    case "cosyvoice":
      return COSYVOICE_VOICE_OPTIONS;
    case "sambert":
      return [];
    case "local_cosyvoice":
    case "indextts":
    case "local_f5_tts":
      return LOCAL_TTS_VOICE_OPTIONS;
    case "xiaomi_mimo":
      return XIAOMI_MIMO_VOICE_OPTIONS;
    default:
      return [];
  }
}

function catalogProviderKey(p: TtsProviderExtended): string | null {
  if (p === "dashscope") return "dashscope";
  if (p === "cosyvoice") return "cosyvoice";
  if (p === "local_cosyvoice") return "local_cosyvoice";
  if (p === "indextts") return "indextts";
  if (p === "local_f5_tts") return "local_f5_tts";
  if (p === "xiaomi_mimo") return "xiaomi_mimo";
  return null;
}

type VoiceOpt = { id: string; label: string; targetModel?: string | null };
type PanelTab = "chat" | "status" | "exports";

const PANEL_TABS: { id: PanelTab; label: string }[] = [
  { id: "chat", label: "对话" },
  { id: "status", label: "状态" },
  { id: "exports", label: "导出" },
];

function mergeVoiceCatalogIntoOptions(
  staticList: { id: string; label: string }[],
  catalog: VoiceCatalogItem[],
  ttsProvider: TtsProviderExtended,
  activeModel?: string,
): VoiceOpt[] {
  const cp = catalogProviderKey(ttsProvider);
  if (!cp) {
    return staticList.map((s) => ({ id: s.id, label: s.label }));
  }
  const dashscopeCloneModelIds = new Set(QWEN_VOICE_CLONE_TARGET_OPTIONS.map((o) => o.id));
  const cloneOnly =
    (ttsProvider === "dashscope" && dashscopeCloneModelIds.has(activeModel ?? "")) ||
    (ttsProvider === "xiaomi_mimo" && activeModel === "mimo-v2.5-tts-voiceclone");
  const baseList = cloneOnly ? [] : staticList;
  const staticIds = new Set(baseList.map((s) => s.id));
  const extras: VoiceOpt[] = [];
  for (const r of catalog) {
    if (r.provider !== cp) continue;
    const sharedSystemPrompt =
      r.source === "system" && (ttsProvider === "local_cosyvoice" || ttsProvider === "local_f5_tts");
    if (activeModel && r.target_model && r.target_model !== activeModel && !sharedSystemPrompt) continue;
    if (cloneOnly && r.source !== "clone") continue;
    if (staticIds.has(r.voice_id)) continue;
    extras.push({
      id: r.voice_id,
      label: r.source === "clone" ? `复刻 · ${r.display_label}` : r.display_label,
      targetModel: sharedSystemPrompt ? undefined : r.target_model,
    });
    staticIds.add(r.voice_id);
  }
  return [...baseList.map((s) => ({ id: s.id, label: s.label })), ...extras];
}

const MESSAGE_STORAGE_KEY = "opentalking-chat-history";
const LLM_SYSTEM_PROMPT_STORAGE_KEY = "opentalking-llm-system-prompt";
const SESSION_PANEL_COLLAPSED_KEY = "opentalking-session-panel-collapsed";
const CUSTOM_REFERENCE_NAME_KEY = "opentalking-custom-reference-name";
const SELECTED_AVATAR_STORAGE_KEY = "opentalking-selected-avatar-id";
const SELECTED_AVATAR_SOURCE_STORAGE_KEY = "opentalking-selected-avatar-source-v1";
const FASTLIVEPORTRAIT_CONFIG_STORAGE_KEY = "opentalking-fasterliveportrait-config-v2";
const VIDEO_CREATION_FASTLIVEPORTRAIT_CONFIG_STORAGE_KEY = "opentalking-video-creation-fasterliveportrait-config-v4";
const ASR_PROVIDER_STORAGE_KEY = "opentalking-asr-provider-v1";
const CLIENT_USER_ID_KEY = "opentalking-client-user-id";
const AGENT_CONFIG_STORAGE_KEY = "opentalking-agent-config-v1";
const SELECTED_PERSONA_STORAGE_KEY = "opentalking-selected-persona-id-v1";
const SELECTED_SCENE_STORAGE_KEY = "opentalking-selected-scene-id-v2";
const SELECTED_SCENE_BY_AVATAR_STORAGE_KEY = "opentalking-selected-scene-by-avatar-v1";
const CONVERSATION_VIEW_MODE_KEY = "opentalking-conversation-view-mode-v1";
const LEGACY_FASTLIVEPORTRAIT_DEFAULT_CONFIG: FasterLivePortraitConfig = {
  head_motion_multiplier: 1.0,
  pose_motion_multiplier: 0.35,
  yaw_multiplier: 0.85,
  pitch_multiplier: 1.0,
  roll_multiplier: 0.85,
  animation_region: "lip",
  expression_multiplier: 1.0,
  mouth_open_multiplier: 1.0,
  mouth_corner_multiplier: 1.0,
  cheek_jaw_multiplier: 1.0,
  driving_multiplier: 1.0,
  cfg_scale: 4.0,
  flag_stitching: true,
  flag_pasteback: true,
  flag_relative_motion: true,
  flag_normalize_lip: true,
  flag_lip_retargeting: false,
};
const CONSERVATIVE_FASTLIVEPORTRAIT_DEFAULT_CONFIG: FasterLivePortraitConfig = {
  head_motion_multiplier: 0.3,
  pose_motion_multiplier: 0.35,
  yaw_multiplier: 0.85,
  pitch_multiplier: 1.0,
  roll_multiplier: 0.85,
  animation_region: "lip",
  expression_multiplier: 0.9,
  mouth_open_multiplier: 1.0,
  mouth_corner_multiplier: 1.0,
  cheek_jaw_multiplier: 0.75,
  driving_multiplier: 1.0,
  cfg_scale: 3.0,
  flag_stitching: true,
  flag_pasteback: true,
  flag_relative_motion: true,
  flag_normalize_lip: true,
  flag_lip_retargeting: false,
};
const INTERMEDIATE_FASTLIVEPORTRAIT_DEFAULT_CONFIG: FasterLivePortraitConfig = {
  head_motion_multiplier: 0.3,
  pose_motion_multiplier: 0.35,
  yaw_multiplier: 0.85,
  pitch_multiplier: 1.0,
  roll_multiplier: 0.85,
  animation_region: "lip",
  expression_multiplier: 1.0,
  mouth_open_multiplier: 1.3,
  mouth_corner_multiplier: 1.0,
  cheek_jaw_multiplier: 1.0,
  driving_multiplier: 1.0,
  cfg_scale: 4.0,
  flag_stitching: true,
  flag_pasteback: true,
  flag_relative_motion: true,
  flag_normalize_lip: true,
  flag_lip_retargeting: false,
};
const OVERDRIVEN_FASTLIVEPORTRAIT_DEFAULT_CONFIG: FasterLivePortraitConfig = {
  head_motion_multiplier: 0.3,
  pose_motion_multiplier: 0.35,
  yaw_multiplier: 0.85,
  pitch_multiplier: 1.0,
  roll_multiplier: 0.85,
  animation_region: "lip",
  expression_multiplier: 1.05,
  mouth_open_multiplier: 1.5,
  mouth_corner_multiplier: 1.0,
  cheek_jaw_multiplier: 1.0,
  driving_multiplier: 1.0,
  cfg_scale: 5.0,
  flag_stitching: true,
  flag_pasteback: true,
  flag_relative_motion: true,
  flag_normalize_lip: true,
  flag_lip_retargeting: false,
};
const BROKEN_VIDEO_CREATION_FASTLIVEPORTRAIT_DEFAULT_CONFIG: FasterLivePortraitConfig = {
  head_motion_multiplier: 0.25,
  pose_motion_multiplier: 0.35,
  yaw_multiplier: 0.85,
  pitch_multiplier: 1.0,
  roll_multiplier: 0.85,
  animation_region: "all",
  expression_multiplier: 1.12,
  mouth_open_multiplier: 3.35,
  mouth_corner_multiplier: 0.78,
  cheek_jaw_multiplier: 0.9,
  driving_multiplier: 1.12,
  cfg_scale: 5.15,
  flag_stitching: true,
  flag_pasteback: true,
  flag_relative_motion: true,
  flag_normalize_lip: false,
  flag_lip_retargeting: false,
};

const STT_MODEL_BY_PROVIDER: Record<string, string> = {
  dashscope: "paraformer-realtime-v2",
  xiaomi_mimo: "mimo-v2.5-asr",
  openai_compatible: "OpenAI-compatible ASR",
  sensevoice: "iic/SenseVoiceSmall",
};

function normalizeAsrProvider(value: string | null | undefined, fallback = "dashscope"): string {
  const provider = (value ?? "").trim();
  return ["dashscope", "xiaomi_mimo", "openai_compatible", "sensevoice"].includes(provider) ? provider : fallback;
}

function sttModelForProvider(provider: string): string {
  return STT_MODEL_BY_PROVIDER[normalizeAsrProvider(provider)] ?? "OPENTALKING_STT_MODEL";
}

function sttProviderNeedsApiKey(provider: string): boolean {
  return ["dashscope", "xiaomi_mimo", "openai_compatible"].includes(normalizeAsrProvider(provider, "dashscope"));
}

function ttsProviderNeedsApiKey(provider: TtsProviderExtended): boolean {
  return provider === "dashscope" || provider === "cosyvoice" || provider === "sambert" || provider === "openai_compatible" || provider === "xiaomi_mimo";
}

function hasSelectableTtsVoice(provider: TtsProviderExtended): boolean {
  return !isEdgeTts(provider) && provider !== "sambert" && provider !== "openai_compatible";
}

function ttsModelSelectable(provider: TtsProviderExtended): boolean {
  return !isEdgeTts(provider) && provider !== "openai_compatible";
}

function resolveSelectableTtsVoice(
  provider: TtsProviderExtended,
  voice: string,
  options: VoiceOpt[],
): string {
  if (!hasSelectableTtsVoice(provider)) return "";
  const trimmed = voice.trim();
  if (trimmed && options.some((option) => option.id === trimmed)) return trimmed;
  return options[0]?.id ?? "";
}

type StoredAvatarSelection = { id: string; source: string | null };

function readStoredAvatarSelection(): StoredAvatarSelection | null {
  try {
    const id = window.localStorage.getItem(SELECTED_AVATAR_STORAGE_KEY);
    if (!id) return null;
    return {
      id,
      source: window.localStorage.getItem(SELECTED_AVATAR_SOURCE_STORAGE_KEY),
    };
  } catch {
    return null;
  }
}

function readStoredAvatarId(): string | null {
  return readStoredAvatarSelection()?.id ?? null;
}

function writeStoredAvatarId(avatarId: string, source: "auto" | "explicit" = "explicit"): void {
  try {
    if (avatarId) {
      window.localStorage.setItem(SELECTED_AVATAR_STORAGE_KEY, avatarId);
      window.localStorage.setItem(SELECTED_AVATAR_SOURCE_STORAGE_KEY, source);
    } else {
      window.localStorage.removeItem(SELECTED_AVATAR_STORAGE_KEY);
      window.localStorage.removeItem(SELECTED_AVATAR_SOURCE_STORAGE_KEY);
    }
  } catch {
    /* ignore */
  }
}

function readStoredSceneIdsByAvatar(): Record<string, string> {
  try {
    const raw = window.localStorage.getItem(SELECTED_SCENE_BY_AVATAR_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    return Object.fromEntries(
      Object.entries(parsed).filter((entry): entry is [string, string] => (
        typeof entry[0] === "string" && typeof entry[1] === "string" && entry[0].length > 0 && entry[1].length > 0
      )),
    );
  } catch {
    return {};
  }
}

function readOrCreateClientUserId(): string {
  try {
    const existing = window.localStorage.getItem(CLIENT_USER_ID_KEY)?.trim();
    if (existing) return existing;
    const randomPart =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID().replace(/-/g, "").slice(0, 16)
        : `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
    const next = `client_${randomPart}`;
    window.localStorage.setItem(CLIENT_USER_ID_KEY, next);
    return next;
  } catch {
    return `client_${Date.now().toString(36)}`;
  }
}

function normalizeKnowledgeBaseIds(ids: unknown, fallback: string[] = []): string[] {
  if (!Array.isArray(ids)) return fallback;
  const normalized = ids
    .filter((id): id is string => typeof id === "string")
    .map((id) => id.trim())
    .filter((id) => Boolean(id) && id !== "default");
  const deduped = Array.from(new Set(normalized));
  return deduped.length ? deduped : fallback;
}

function placeholderKnowledgeBaseSummary(id: string): KnowledgeBaseSummary {
  return {
    id,
    name: id,
    document_count: 0,
    ready_document_count: 0,
    error_document_count: 0,
    created_at: "",
    updated_at: "",
  };
}

function normalizeKnowledgeBaseSummaries(response: KnowledgeBasesResponse): KnowledgeBaseSummary[] {
  const summaries = Array.isArray(response.knowledge_base_summaries)
    ? response.knowledge_base_summaries
    : [];
  const knowledgeBases = Array.isArray(response.knowledge_bases)
    ? response.knowledge_bases
    : [];
  const byId = new Map<string, KnowledgeBaseSummary>();
  for (const summary of summaries) {
    if (summary.id) byId.set(summary.id, summary);
  }
  for (const item of knowledgeBases) {
    if (typeof item === "string") {
      const trimmed = item.trim();
      if (trimmed && !byId.has(trimmed)) {
        byId.set(trimmed, placeholderKnowledgeBaseSummary(trimmed));
      }
    } else if (item?.id && !byId.has(item.id)) {
      byId.set(item.id, item);
    }
  }
  return Array.from(byId.values());
}

function normalizeSelectedKnowledgeBaseIds(
  response: AvatarKnowledgeBasesResponse,
  fallback: string[] = [],
): string[] {
  const directIds = normalizeKnowledgeBaseIds(response.knowledge_base_ids, []);
  if (directIds.length) return directIds;
  const summaryIds = Array.isArray(response.knowledge_base_summaries)
    ? response.knowledge_base_summaries
        .map((summary) => summary.id?.trim())
        .filter((id): id is string => Boolean(id))
    : [];
  const deduped = Array.from(new Set(summaryIds));
  return deduped.length ? deduped : fallback;
}

function readStoredAgentConfig(): AgentConfig {
  try {
    const raw = window.localStorage.getItem(AGENT_CONFIG_STORAGE_KEY);
    if (!raw) {
      return { memoryEnabled: false, knowledgeEnabled: true, knowledgeBaseIds: [] };
    }
    const parsed = JSON.parse(raw) as Partial<AgentConfig> & { knowledgeBaseId?: unknown };
    const knowledgeBaseIds = Array.isArray(parsed.knowledgeBaseIds)
      ? normalizeKnowledgeBaseIds(parsed.knowledgeBaseIds)
      : typeof parsed.knowledgeBaseId === "string" && parsed.knowledgeBaseId.trim()
        ? normalizeKnowledgeBaseIds([parsed.knowledgeBaseId])
        : [];
    const migrated = {
      memoryEnabled: false,
      knowledgeEnabled: parsed.knowledgeEnabled !== false,
      knowledgeBaseIds,
    };
    writeStoredAgentConfig(migrated);
    return migrated;
  } catch {
    return { memoryEnabled: false, knowledgeEnabled: true, knowledgeBaseIds: [] };
  }
}

function writeStoredAgentConfig(config: AgentConfig): void {
  try {
    window.localStorage.setItem(AGENT_CONFIG_STORAGE_KEY, JSON.stringify(config));
  } catch {
    /* ignore */
  }
}

function normalizeTtsProvider(value: string | null | undefined, fallback: TtsProviderExtended = "edge"): TtsProviderExtended {
  const normalized = (value ?? "").trim();
  if (
    normalized === "edge" ||
    normalized === "dashscope" ||
    normalized === "cosyvoice" ||
    normalized === "sambert" ||
    normalized === "local_cosyvoice" ||
    normalized === "indextts" ||
    normalized === "local_f5_tts" ||
    normalized === "xiaomi_mimo" ||
    normalized === "openai_compatible"
  ) {
    return normalized;
  }
  if (normalized === "local_indextts" || normalized === "omnirt_indextts") {
    return "indextts";
  }
  return fallback;
}

function apiErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.detail) return error.detail;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

function validateAudioProviderConfigBeforeStart({
  sttProvider,
  ttsProvider,
  runtimeStatus,
}: {
  sttProvider: string;
  ttsProvider: TtsProviderExtended;
  runtimeStatus: HealthResponse | null;
}): string | null {
  const missing: string[] = [];
  const sttStatus = runtimeStatus?.stt_providers?.[normalizeAsrProvider(sttProvider, "dashscope")];
  const ttsStatus = runtimeStatus?.tts_providers?.[ttsProvider];
  const sttKeySet = sttStatus?.key_set ?? runtimeStatus?.stt_key_set;
  const ttsKeySet = ttsStatus?.key_set ?? runtimeStatus?.tts_key_set;
  const sttServiceUrlSet = sttStatus?.service_url_set;
  const ttsServiceUrlSet = ttsStatus?.service_url_set ?? runtimeStatus?.tts_service_url_set;
  if (sttProviderNeedsApiKey(sttProvider) && (sttKeySet !== true || ((sttProvider === "openai_compatible" || sttProvider === "xiaomi_mimo") && sttServiceUrlSet !== true))) {
    missing.push(sttProvider === "openai_compatible"
      ? "API 语音识别缺少 OPENTALKING_STT_OPENAI_API_KEY 或 OPENTALKING_STT_OPENAI_BASE_URL"
      : sttProvider === "xiaomi_mimo"
        ? "小米 MiMo 语音识别缺少 OPENTALKING_STT_XIAOMI_API_KEY 或 OPENTALKING_STT_XIAOMI_BASE_URL"
        : "API 语音识别缺少 OPENTALKING_STT_DASHSCOPE_API_KEY");
  }
  if (ttsProviderNeedsApiKey(ttsProvider) && (ttsKeySet !== true || ((ttsProvider === "openai_compatible" || ttsProvider === "xiaomi_mimo") && ttsServiceUrlSet !== true))) {
    missing.push(ttsProvider === "openai_compatible"
      ? "当前 TTS API 缺少 OPENTALKING_TTS_OPENAI_API_KEY 或 OPENTALKING_TTS_OPENAI_BASE_URL"
      : ttsProvider === "xiaomi_mimo"
        ? "小米 MiMo TTS 缺少 OPENTALKING_TTS_XIAOMI_API_KEY 或 OPENTALKING_TTS_XIAOMI_BASE_URL"
      : "当前 TTS API 缺少 OPENTALKING_TTS_DASHSCOPE_API_KEY");
  }
  if (missing.length === 0) return null;
  return `${missing.join("；")}。请在后端 .env 配置后重启服务。`;
}

type SpeakAudioResponse = { session_id: string; status: string; text: string };
type SessionRecord = { session_id: string; state?: string };
type PrewarmState = "idle" | "preparing" | "ready" | "failed";
type AvatarPrewarmResponse = {
  avatar_id: string;
  model: string;
  status: "ready" | "failed" | string;
  runtime_status?: "ready" | "failed" | "skipped" | string;
  cache?: { status?: string; frames?: number | null; detail?: string | null };
  runtime?: { type?: string; cache_hit?: boolean; elapsed_ms?: number; message?: string | null };
};
type HealthResponse = {
  status: string;
  tts_provider?: string;
  tts_key_set?: boolean;
  tts_service_url_set?: boolean;
  tts_default_provider?: string;
  tts_enabled_providers?: string[];
  tts_providers?: Record<string, { key_set?: boolean; model?: string; model_dir?: string; service_url_set?: boolean }>;
  stt_provider?: string;
  stt_key_set?: boolean;
  stt_model?: string;
  stt_device?: string;
  stt_default_provider?: string;
  stt_enabled_providers?: string[];
  stt_providers?: Record<string, { key_set?: boolean; model?: string; model_dir?: string; device?: string; service_url_set?: boolean }>;
};

function sanitizeFasterLivePortraitConfig(
  raw: unknown,
  defaults: FasterLivePortraitConfig = DEFAULT_FASTLIVEPORTRAIT_CONFIG,
): FasterLivePortraitConfig {
  const source = raw && typeof raw === "object" ? raw as Partial<Record<keyof FasterLivePortraitConfig, unknown>> : {};
  const clamp = (key: Exclude<keyof FasterLivePortraitConfig, "animation_region" | "flag_stitching" | "flag_pasteback" | "flag_relative_motion" | "flag_normalize_lip" | "flag_lip_retargeting">, min: number, max: number) => {
    const value = Number(source[key] ?? defaults[key]);
    if (!Number.isFinite(value)) return defaults[key];
    return Math.min(max, Math.max(min, value));
  };
  const boolValue = (
    key: Extract<keyof FasterLivePortraitConfig, "flag_stitching" | "flag_pasteback" | "flag_relative_motion" | "flag_normalize_lip" | "flag_lip_retargeting">,
  ) => {
    const value = source[key];
    if (typeof value === "boolean") return value;
    if (typeof value === "string") return ["1", "true", "yes", "on"].includes(value.trim().toLowerCase());
    if (typeof value === "number") return value !== 0;
    return defaults[key];
  };
  return {
    head_motion_multiplier: clamp("head_motion_multiplier", 0, 4),
    pose_motion_multiplier: clamp("pose_motion_multiplier", 0, 4),
    yaw_multiplier: clamp("yaw_multiplier", 0, 4),
    pitch_multiplier: clamp("pitch_multiplier", 0, 4),
    roll_multiplier: clamp("roll_multiplier", 0, 4),
    animation_region:
      source.animation_region === "lip" ||
      source.animation_region === "all" ||
      source.animation_region === "exp" ||
      source.animation_region === "pose" ||
      source.animation_region === "eyes"
        ? source.animation_region
        : defaults.animation_region,
    expression_multiplier: clamp("expression_multiplier", 0, 4),
    mouth_open_multiplier: clamp("mouth_open_multiplier", 0, 4),
    mouth_corner_multiplier: clamp("mouth_corner_multiplier", 0, 4),
    cheek_jaw_multiplier: clamp("cheek_jaw_multiplier", 0, 4),
    driving_multiplier: clamp("driving_multiplier", 0, 4),
    cfg_scale: clamp("cfg_scale", 0, 10),
    flag_stitching: boolValue("flag_stitching"),
    flag_pasteback: boolValue("flag_pasteback"),
    flag_relative_motion: boolValue("flag_relative_motion"),
    flag_normalize_lip: boolValue("flag_normalize_lip"),
    flag_lip_retargeting: boolValue("flag_lip_retargeting"),
  };
}

function sameFasterLivePortraitConfig(a: FasterLivePortraitConfig, b: FasterLivePortraitConfig): boolean {
  return (Object.keys(DEFAULT_FASTLIVEPORTRAIT_CONFIG) as (keyof FasterLivePortraitConfig)[]).every(
    (key) => a[key] === b[key],
  );
}

function readStoredFasterLivePortraitConfig(): FasterLivePortraitConfig {
  try {
    const raw = window.localStorage.getItem(FASTLIVEPORTRAIT_CONFIG_STORAGE_KEY);
    if (!raw) return { ...DEFAULT_FASTLIVEPORTRAIT_CONFIG };
    const parsed = JSON.parse(raw);
    const missingAnimationRegion = !parsed || typeof parsed !== "object" || !("animation_region" in parsed);
    const stored = sanitizeFasterLivePortraitConfig(parsed);
    if (
      missingAnimationRegion ||
      sameFasterLivePortraitConfig(stored, LEGACY_FASTLIVEPORTRAIT_DEFAULT_CONFIG) ||
      sameFasterLivePortraitConfig(stored, CONSERVATIVE_FASTLIVEPORTRAIT_DEFAULT_CONFIG) ||
      sameFasterLivePortraitConfig(stored, INTERMEDIATE_FASTLIVEPORTRAIT_DEFAULT_CONFIG) ||
      sameFasterLivePortraitConfig(stored, OVERDRIVEN_FASTLIVEPORTRAIT_DEFAULT_CONFIG)
    ) {
      window.localStorage.removeItem(FASTLIVEPORTRAIT_CONFIG_STORAGE_KEY);
      return { ...DEFAULT_FASTLIVEPORTRAIT_CONFIG };
    }
    return stored;
  } catch {
    return { ...DEFAULT_FASTLIVEPORTRAIT_CONFIG };
  }
}

function readStoredVideoCreationFasterLivePortraitConfig(): FasterLivePortraitConfig {
  try {
    const raw = window.localStorage.getItem(VIDEO_CREATION_FASTLIVEPORTRAIT_CONFIG_STORAGE_KEY);
    if (!raw) return { ...DEFAULT_VIDEO_CREATION_FASTLIVEPORTRAIT_CONFIG };
    const stored = sanitizeFasterLivePortraitConfig(JSON.parse(raw), {
      ...DEFAULT_VIDEO_CREATION_FASTLIVEPORTRAIT_CONFIG,
    });
    if (sameFasterLivePortraitConfig(stored, BROKEN_VIDEO_CREATION_FASTLIVEPORTRAIT_DEFAULT_CONFIG)) {
      window.localStorage.removeItem(VIDEO_CREATION_FASTLIVEPORTRAIT_CONFIG_STORAGE_KEY);
      return { ...DEFAULT_VIDEO_CREATION_FASTLIVEPORTRAIT_CONFIG };
    }
    return stored;
  } catch {
    return { ...DEFAULT_VIDEO_CREATION_FASTLIVEPORTRAIT_CONFIG };
  }
}

/** From Vite env: max bubbles to show (most recent). 0 = show full history. */
function readChatMaxVisible(): number {
  const raw = import.meta.env.VITE_CHAT_MAX_VISIBLE;
  if (raw === undefined || raw === "") return 0;
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0) return 0;
  return Math.min(500, Math.floor(n));
}

let msgCounter = 0;
let toastCounter = 0;
function makeId() {
  return `msg-${++msgCounter}-${Date.now()}`;
}

function makeToastId() {
  return `toast-${++toastCounter}-${Date.now()}`;
}

function pickInitialAvatar(
  avatars: AvatarSummary[],
  registeredModels: string[],
  storedSelection?: StoredAvatarSelection | null,
  defaultModel?: string | null,
): AvatarSummary | null {
  if (!avatars.length) return null;
  const available = new Set(registeredModels);
  if (defaultModel) {
    const recommended = pickInitialAvatarForModel(avatars, defaultModel, storedSelection ?? null);
    if (recommended?.client_renderer?.recommended_for.includes(defaultModel)) return recommended;
  }
  const customAvatar = pickInitialCustomAvatar(avatars, available);
  const storedAvatar = storedSelection?.id
    ? avatars.find((avatar) => avatar.id === storedSelection.id)
    : null;
  if (
    storedAvatar &&
    (storedSelection?.source === "explicit" || storedAvatar.is_custom || !customAvatar)
  ) {
    return storedAvatar;
  }
  if (customAvatar) return customAvatar;
  return (
    avatars.find((a) => a.id === "anime-handsome-guy" && available.has("fasterliveportrait")) ??
    avatars.find((a) => a.id === "quicktalk-daytime" && available.has("quicktalk")) ??
    avatars.find((a) => a.model_type === "quicktalk" && available.has("quicktalk")) ??
    avatars.find((a) => a.model_type === "flashhead" && available.has("flashhead")) ??
    avatars.find((a) => a.model_type === "flashtalk" && available.has("flashtalk")) ??
    avatars.find((a) => a.model_type === "musetalk" && available.has("musetalk")) ??
    avatars.find((a) => available.has(a.model_type)) ??
    avatars[0]
  );
}

function pickInitialCustomAvatar(
  avatars: AvatarSummary[],
  available: Set<string>,
): AvatarSummary | null {
  return (
    avatars.find((avatar) => avatar.is_custom && available.has(avatar.model_type)) ??
    avatars.find((avatar) => avatar.is_custom) ??
    null
  );
}

function pickInitialModel(
  currentModel: string,
  registeredModels: string[],
  statuses: ModelStatus[],
  initialAvatar: AvatarSummary | null,
  defaultModel?: string | null,
): string {
  const available = new Set(registeredModels);
  const connected = new Set(
    statuses.filter((status) => modelConnectionBadge(status).connected).map((status) => status.id),
  );
  if (defaultModel && available.has(defaultModel) && connected.has(defaultModel)) return defaultModel;
  if (available.has(currentModel) && connected.has(currentModel)) return currentModel;
  const avatarModel = initialAvatar?.model_type;
  if (avatarModel && available.has(avatarModel) && connected.has(avatarModel)) return avatarModel;
  for (const preferred of ["fasterliveportrait", "quicktalk", "mock"]) {
    if (available.has(preferred) && connected.has(preferred)) return preferred;
  }
  const firstConnected = registeredModels.find((id) => connected.has(id));
  return firstConnected ?? registeredModels[0] ?? avatarModel ?? currentModel;
}

const SERVER_AUDIO_RENDERERS = new Set(["flashtalk", "flashhead", "fasterliveportrait", "quicktalk", "musetalk", "wav2lip"]);

function isFlashRenderer(model: string): boolean {
  return SERVER_AUDIO_RENDERERS.has(model);
}

function usesCompactSquareStage(model: string): boolean {
  return model === "flashhead";
}

const PREWARMABLE_MODELS = new Set(["quicktalk", "wav2lip"]);

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

type CaptureStreamVideoElement = HTMLVideoElement & {
  captureStream?: (fps?: number) => MediaStream;
  mozCaptureStream?: (fps?: number) => MediaStream;
};

type PendingRealtimeExport = {
  blob: Blob;
  title: string;
  durationSec: number;
  sessionId: string | null;
  avatarId: string;
  model: string;
};

function selectMediaRecorderMimeType(candidates: string[]): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  return candidates.find((candidate) => MediaRecorder.isTypeSupported(candidate));
}

function realtimeExportTitle(model: string): string {
  return `实时对话录制 · ${modelLabel(model)}`;
}

async function requestUserAudioWithTimeout(microphonePermissionTimeoutMs = 8000): Promise<MediaStream> {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new DOMException("media devices unavailable", "NotSupportedError");
  }
  let settled = false;
  let timeoutId: number | null = null;
  const request = navigator.mediaDevices.getUserMedia({ audio: true }).then((stream) => {
    settled = true;
    if (timeoutId !== null) window.clearTimeout(timeoutId);
    return stream;
  });
  const timeout = new Promise<MediaStream>((_, reject) => {
    timeoutId = window.setTimeout(() => {
      if (settled) return;
      reject(new DOMException("microphone permission timeout", "TimeoutError"));
    }, microphonePermissionTimeoutMs);
  });
  return Promise.race([request, timeout]);
}

function realtimeRecordingLocalhostHelpUrl(): string {
  const port = window.location.port ? `:${window.location.port}` : "";
  return `http://127.0.0.1${port}/`;
}

function realtimeRecordingStartErrorMessage(error: unknown): string {
  const name = error instanceof DOMException ? error.name : "";
  const message = error instanceof Error ? error.message : "";
  const mediaDevicesUnavailable = !navigator.mediaDevices?.getUserMedia;
  const insecureOrigin = typeof window !== "undefined" && !window.isSecureContext;

  if (insecureOrigin && (name === "NotSupportedError" || name === "SecurityError" || mediaDevicesUnavailable)) {
    return `当前访问地址不是浏览器安全来源，无法请求麦克风。请通过本机 ${realtimeRecordingLocalhostHelpUrl()} 隧道或 HTTPS 打开后重试。`;
  }
  if (name === "TimeoutError") {
    return "麦克风权限请求超时，请在浏览器地址栏允许麦克风后重试。";
  }
  if (name === "NotAllowedError" || name === "SecurityError") {
    return "麦克风权限被拒绝，无法录制用户声音。请在浏览器地址栏允许麦克风后重试。";
  }
  if (name === "NotFoundError" || name === "DevicesNotFoundError") {
    return "未检测到可用麦克风。请连接麦克风，或确认系统输入设备可用后重试。";
  }
  if (name === "NotReadableError" || name === "TrackStartError") {
    return "麦克风正在被其他应用占用，关闭占用程序后重试。";
  }
  if (name === "NotSupportedError" || mediaDevicesUnavailable) {
    return "当前浏览器不支持麦克风录制。请换用新版 Chrome，并确认通过 localhost 或 HTTPS 访问。";
  }
  if (name === "InvalidStateError") {
    return "当前会话画面还没有准备好，请等数字人视频出现后再开始录制。";
  }
  return name || message
    ? `开始录制失败（${name || message}），请确认浏览器权限和当前会话状态。`
    : "开始录制失败：请确认浏览器权限和当前会话状态。";
}

export default function App() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const remoteStreamRef = useRef<MediaStream | null>(null);
  const realtimeRecorderRef = useRef<MediaRecorder | null>(null);
  const realtimeRecordChunksRef = useRef<Blob[]>([]);
  const realtimeRecordStartedAtRef = useRef(0);
  const realtimeRecordStreamRef = useRef<MediaStream | null>(null);
  const realtimeRecordMicStreamRef = useRef<MediaStream | null>(null);
  const pendingRealtimeExportRef = useRef<PendingRealtimeExport | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const knowledgeSyncChainRef = useRef<Promise<void>>(Promise.resolve());
  const speakAudioAbortRef = useRef<AbortController | null>(null);
  const ttsPreviewAudioRef = useRef<HTMLAudioElement | null>(null);
  const ttsPreviewUrlRef = useRef<string | null>(null);
  /** Cumulative assistant text for the current speech turn (subtitle.chunk segments). */
  const subtitleAccRef = useRef("");
  /** `messages` id of the in-progress assistant bubble for this turn; cleared on speech.ended. */
  const streamingAssistantMsgIdRef = useRef<string | null>(null);
  /** Local placeholder shown immediately after the user sends text, before worker SSE arrives. */
  const pendingAssistantMsgIdRef = useRef<string | null>(null);
  /** 首帧已进入 WebRTC 后再叠字幕（与口型对齐）；旧版 Worker 无 speech.media_started 时用定时回退 */
  const subtitleMediaReadyRef = useRef(false);
  const subtitleFallbackTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Data
  const [avatars, setAvatars] = useState<AvatarSummary[]>([]);
  const [models, setModels] = useState<string[]>([]);
  const [modelStatuses, setModelStatuses] = useState<ModelStatus[]>([]);
  const [avatarId, setAvatarId] = useState(() => readStoredAvatarId() ?? "singer");
  const [model, setModel] = useState("flashtalk");
  const [selectedPersonaId, setSelectedPersonaId] = useState<string>(() => {
    try {
      return window.localStorage.getItem(SELECTED_PERSONA_STORAGE_KEY) ?? "";
    } catch {
      return "";
    }
  });
  const [personas, setPersonas] = useState<PersonaSummary[]>([]);
  const [personaImporting, setPersonaImporting] = useState(false);
  const appliedPersonaIdRef = useRef("");
  const [prewarmByKey, setPrewarmByKey] = useState<Record<string, PrewarmState>>({});
  const prewarmInFlightRef = useRef<Map<string, Promise<boolean>>>(new Map());
  const prewarmSeqRef = useRef(0);
  const [wav2lipPostprocessMode, setWav2lipPostprocessMode] = useState<Wav2LipPostprocessMode>("auto");
  const [fasterliveportraitConfig, setFasterliveportraitConfig] = useState<FasterLivePortraitConfig>(
    readStoredFasterLivePortraitConfig,
  );
  const [fasterliveportraitAppliedConfig, setFasterliveportraitAppliedConfig] = useState<FasterLivePortraitConfig>(
    readStoredFasterLivePortraitConfig,
  );
  const [videoCreationFasterliveportraitConfig, setVideoCreationFasterliveportraitConfig] = useState<FasterLivePortraitConfig>(
    readStoredVideoCreationFasterLivePortraitConfig,
  );
  const [fasterliveportraitApplying, setFasterliveportraitApplying] = useState(false);
  const [workflow, setWorkflow] = useState<StudioWorkflow>("realtime");

  // Connection
  const [connection, setConnection] = useState<ConnectionStatus>("idle");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [remoteStream, setRemoteStream] = useState<MediaStream | null>(null);
  const [queueInfo, setQueueInfo] = useState<QueueInfo | null>(null);
  const [expiringCountdown, setExpiringCountdown] = useState<number | null>(null);

  // Chat
  const [messages, setMessages] = useState<Message[]>([]);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [currentSubtitle, setCurrentSubtitle] = useState("");
  const [, setRuntimeStatus] = useState<HealthResponse | null>(null);
  const [runtimeConfig, setRuntimeConfig] = useState<RuntimeConfigResponse | null>(null);
  const [runtimeConfigLoading, setRuntimeConfigLoading] = useState(false);
  const [runtimeConfigApplying, setRuntimeConfigApplying] = useState(false);

  const clearSubtitleFallbackTimer = useCallback(() => {
    if (subtitleFallbackTimerRef.current !== null) {
      clearTimeout(subtitleFallbackTimerRef.current);
      subtitleFallbackTimerRef.current = null;
    }
  }, []);

  const flushSubtitleDisplay = useCallback(() => {
    const t = subtitleAccRef.current;
    if (t) setCurrentSubtitle(t);
  }, []);

  const flushSubtitleMessage = useCallback(() => {
    const msgId = streamingAssistantMsgIdRef.current;
    const t = subtitleAccRef.current;
    if (!msgId || !t) return;
    setMessages((prev) =>
      prev.map((m) => (m.id === msgId ? { ...m, text: t } : m)),
    );
  }, []);

  const clearSubtitleState = useCallback(() => {
    setCurrentSubtitle("");
    subtitleAccRef.current = "";
    subtitleMediaReadyRef.current = false;
    clearSubtitleFallbackTimer();
    streamingAssistantMsgIdRef.current = null;
    pendingAssistantMsgIdRef.current = null;
    setIsSpeaking(false);
  }, [clearSubtitleFallbackTimer]);

  const appendAssistantError = useCallback((message: string) => {
    const normalized = message.startsWith("出错了：") ? message : `出错了：${message}`;
    const msgId = streamingAssistantMsgIdRef.current ?? pendingAssistantMsgIdRef.current;
    clearSubtitleState();
    if (msgId) {
      setMessages((prev) =>
        prev.map((m) => (m.id === msgId ? { ...m, text: normalized } : m)),
      );
      return;
    }
    setMessages((prev) => [
      ...prev,
      { id: makeId(), role: "assistant", text: normalized, timestamp: Date.now() },
    ]);
  }, [clearSubtitleState]);

  // UI
  const [settingsExpanded, setSettingsExpanded] = useState(() => {
    try {
      const s = window.localStorage.getItem(SETTINGS_DOCK_EXPANDED_KEY);
      if (s === "1") return true;
      if (s === "0") return false;
    } catch {
      /* ignore */
    }
    return false;
  });
  const [voiceCloneOpen, setVoiceCloneOpen] = useState(false);
  const [referenceSaving, setReferenceSaving] = useState(false);
  const [panelTab, setPanelTab] = useState<PanelTab>("chat");
  const [sessionPanelCollapsed, setSessionPanelCollapsed] = useState(() => {
    try {
      return window.localStorage.getItem(SESSION_PANEL_COLLAPSED_KEY) === "1";
    } catch {
      return false;
    }
  });
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const toastTimersRef = useRef<Map<string, ReturnType<typeof window.setTimeout>>>(new Map());
  const [recordingSaving, setRecordingSaving] = useState(false);
  const [ftRecordPhase, setFtRecordPhase] = useState<"idle" | "recording" | "stopped">("idle");
  const [ftRecordBusy, setFtRecordBusy] = useState(false);
  const [assetLibraryRefreshKey, setAssetLibraryRefreshKey] = useState(0);
  const [conversationViewMode, setConversationViewMode] = useState<ConversationViewMode>(() => {
    try {
      return window.localStorage.getItem(CONVERSATION_VIEW_MODE_KEY) === "immersive" ? "immersive" : "studio";
    } catch {
      return "studio";
    }
  });
  const [immersiveAvatarAdjust, setImmersiveAvatarAdjust] = useState({ x: 0, y: 0, scale: 1 });
  const [voiceCatalog, setVoiceCatalog] = useState<VoiceCatalogItem[]>([]);
  const [voiceApplyNotice, setVoiceApplyNotice] = useState<string | null>(null);
  const [ttsPreviewText, setTtsPreviewText] = useState(DEFAULT_TTS_PREVIEW_TEXT);
  const [ttsPreviewing, setTtsPreviewing] = useState(false);
  const [clientUserId] = useState(readOrCreateClientUserId);
  const [agentConfig, setAgentConfigState] = useState<AgentConfig>(readStoredAgentConfig);
  const [knowledgeBaseSummaries, setKnowledgeBaseSummaries] = useState<KnowledgeBaseSummary[]>([]);
  const [memoryEnabled, setMemoryEnabled] = useState(false);
  const [memoryLibraryId, setMemoryLibraryId] = useState<string | null>(null);
  const [memoryLibraries, setMemoryLibraries] = useState<MemoryLibrary[]>([]);
  const [sceneBackgrounds, setSceneBackgrounds] = useState<SceneBackgroundAsset[]>([]);
  const [sceneCompositions, setSceneCompositions] = useState<SceneComposition[]>([]);
  const [selectedSceneIdsByAvatar, setSelectedSceneIdsByAvatar] = useState<Record<string, string>>(readStoredSceneIdsByAvatar);
  const avatarKnowledgeBasesSyncReadyRef = useRef(false);
  const lastPersistedAvatarKnowledgeBasesRef = useRef<Map<string, string[]>>(new Map());
  const avatarKnowledgeBasesLoadSeqRef = useRef(0);
  const [assetLibraryTab, setAssetLibraryTab] = useState<AssetLibraryTab>("exports");
  const selectedModelStatus = modelStatuses.find((item) => item.id === model);
  const selectedModelBadge = modelConnectionBadge(selectedModelStatus, models.includes(model));
  const selectedModelConnected = selectedModelBadge.connected;
  const [asrProvider, setAsrProvider] = useState(() => {
    try {
      const saved = window.localStorage.getItem(ASR_PROVIDER_STORAGE_KEY);
      return saved ? normalizeAsrProvider(saved, "dashscope") : "";
    } catch {
      return "";
    }
  });
  const [asrModel, setAsrModel] = useState(STT_MODEL_BY_PROVIDER.dashscope);
  const [activeAsrProvider, setActiveAsrProvider] = useState("");
  const [edgeVoice, setEdgeVoice] = useState<string>(() => {
    try {
      const s = window.localStorage.getItem(EDGE_VOICE_STORAGE_KEY);
      if (s && EDGE_ZH_VOICES.some((v) => v.id === s)) return s;
    } catch {
      /* ignore */
    }
    return DEFAULT_EDGE_VOICE_ID;
  });

  const [ttsProvider, setTtsProvider] = useState<TtsProviderExtended>(() => {
    try {
      const s = window.localStorage.getItem(TTS_PROVIDER_STORAGE_KEY)?.trim();
      const normalized = normalizeTtsProvider(s, "edge");
      if (normalized !== "edge" || s === "edge") return normalized;
    } catch {
      /* ignore */
    }
    return "edge";
  });

  const [qwenModel, setQwenModel] = useState<string>(() => {
    try {
      const s = window.localStorage.getItem(QWEN_MODEL_STORAGE_KEY)?.trim();
      if (s && /^[\w.-]+$/.test(s)) return s;
    } catch {
      /* ignore */
    }
    return DEFAULT_QWEN_MODEL_ID;
  });

  const [qwenVoice, setQwenVoice] = useState<string>(() => {
    try {
      const s = window.localStorage.getItem(QWEN_VOICE_STORAGE_KEY)?.trim();
      if (s && s.length > 0 && s.length <= 256) return s;
    } catch {
      /* ignore */
    }
    return DEFAULT_QWEN_VOICE_ID;
  });

  const compactSquareStage = usesCompactSquareStage(model);
  const selectedScene = useMemo(
    () => {
      const selectedSceneId = selectedSceneIdsByAvatar[avatarId];
      const matchingScenes = sceneCompositions.filter((scene) => scene.avatar_id === avatarId);
      if (selectedSceneId) {
        return matchingScenes.find((scene) => scene.id === selectedSceneId) ?? null;
      }
      return matchingScenes.length === 1 ? matchingScenes[0] : null;
    },
    [avatarId, sceneCompositions, selectedSceneIdsByAvatar],
  );

  const dismissToast = useCallback((id: string) => {
    const timer = toastTimersRef.current.get(id);
    if (timer) window.clearTimeout(timer);
    toastTimersRef.current.delete(id);
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
  }, []);

  const notify = useCallback((message: string, tone: ToastTone = "info") => {
    const id = makeToastId();
    setToasts((prev) => [...prev.slice(-2), { id, tone, message }]);
    if (tone !== "error") {
      const timer = window.setTimeout(() => {
        toastTimersRef.current.delete(id);
        setToasts((prev) => prev.filter((toast) => toast.id !== id));
      }, 3600);
      toastTimersRef.current.set(id, timer);
    }
  }, []);

  const pauseToast = useCallback((id: string) => {
    const timer = toastTimersRef.current.get(id);
    if (!timer) return;
    window.clearTimeout(timer);
    toastTimersRef.current.delete(id);
  }, []);

  const resumeToast = useCallback((id: string) => {
    const toast = toasts.find((item) => item.id === id);
    if (!toast || toast.tone === "error" || toastTimersRef.current.has(id)) return;
    const timer = window.setTimeout(() => {
      toastTimersRef.current.delete(id);
      setToasts((prev) => prev.filter((item) => item.id !== id));
    }, 1800);
    toastTimersRef.current.set(id, timer);
  }, [toasts]);

  const syncRuntimeConfigSelection = useCallback((next: RuntimeConfigResponse) => {
    const nextAsrProvider = normalizeAsrProvider(next.stt.provider, "dashscope");
    setAsrProvider(nextAsrProvider);
    setAsrModel(next.stt.model || sttModelForProvider(nextAsrProvider));

    const nextTtsProvider = normalizeTtsProvider(next.tts.provider, "edge");
    setTtsProvider(nextTtsProvider);
    if (next.tts.model) {
      setQwenModel(next.tts.model);
    }
    if (next.tts.voice) {
      if (nextTtsProvider === "edge") {
        setEdgeVoice(next.tts.voice);
      } else {
        setQwenVoice(next.tts.voice);
      }
    }
  }, []);

  const refreshRuntimeConfig = useCallback(async () => {
    setRuntimeConfigLoading(true);
    try {
      const next = await loadRuntimeConfig();
      setRuntimeConfig(next);
      syncRuntimeConfigSelection(next);
      return next;
    } catch (error) {
      console.warn("load runtime config failed", error);
      const detail = error instanceof ApiError ? error.detail : null;
      notify(detail ? `运行配置读取失败：${detail}` : "运行配置读取失败，请查看后端日志。", "error");
      return null;
    } finally {
      setRuntimeConfigLoading(false);
    }
  }, [notify, syncRuntimeConfigSelection]);

  const handleApplyRuntimeConfig = useCallback(async (input: RuntimeConfigApplyInput) => {
    setRuntimeConfigApplying(true);
    try {
      const next = await applyRuntimeConfig(input);
      setRuntimeConfig(next);
      syncRuntimeConfigSelection(next);
      void apiGet<HealthResponse>("/health")
        .then(setRuntimeStatus)
        .catch((error) => console.warn("refresh health after runtime config failed", error));
      notify(next.requires_new_session ? "运行配置已保存，下次会话生效。" : "运行配置已应用。", "success");
    } catch (error) {
      console.warn("apply runtime config failed", error);
      const detail = error instanceof ApiError ? error.detail : null;
      notify(detail ? `运行配置应用失败：${detail}` : "运行配置应用失败，请查看后端日志。", "error");
      throw error;
    } finally {
      setRuntimeConfigApplying(false);
    }
  }, [notify, syncRuntimeConfigSelection]);

  const syncSessionKnowledgeBases = useCallback((knowledgeBaseIds: string[]) => {
    const sid = sessionIdRef.current;
    if (!sid) return;
    const selectedIds = normalizeKnowledgeBaseIds(knowledgeBaseIds);
    knowledgeSyncChainRef.current = knowledgeSyncChainRef.current
      .catch(() => undefined)
      .then(async () => {
        if (sessionIdRef.current !== sid) return;
        await apiPost<SessionKnowledgeBasesResponse>(
          `/sessions/${sid}/knowledge-bases`,
          {
            knowledge_base_ids: selectedIds,
          } satisfies SessionKnowledgeBasesRequest,
        );
      })
      .catch((error) => {
        console.warn("sync session knowledge bases failed", error);
        const detail = error instanceof ApiError ? error.detail : null;
        notify(detail ? `会话知识库切换失败：${detail}` : "会话知识库切换失败，请查看后端日志。", "error");
      });
  }, [notify]);

  const setAgentConfig = useCallback((next: AgentConfig) => {
    const normalized = {
      memoryEnabled: false,
      knowledgeEnabled: next.knowledgeEnabled !== false,
      knowledgeBaseIds: normalizeKnowledgeBaseIds(next.knowledgeBaseIds),
    };
    setAgentConfigState(normalized);
    writeStoredAgentConfig(normalized);
    void syncSessionKnowledgeBases(normalized.knowledgeBaseIds);
  }, [syncSessionKnowledgeBases]);

  const refreshKnowledgeBases = useCallback(async () => {
    try {
      const response = await apiGet<KnowledgeBasesResponse>("/agent/knowledge-bases");
      setKnowledgeBaseSummaries(normalizeKnowledgeBaseSummaries(response));
    } catch (error) {
      console.warn("load knowledge bases failed", error);
      const detail = error instanceof ApiError ? error.detail : null;
      notify(detail ? `知识库列表读取失败：${detail}` : "知识库列表读取失败，请查看后端日志。", "error");
    }
  }, [notify]);

  const refreshPersonas = useCallback(async () => {
    try {
      const response = await apiGet<PersonasResponse>("/personas");
      const next = Array.isArray(response.personas) ? response.personas : [];
      setPersonas(next);
      setSelectedPersonaId((current) => {
        if (!current || next.some((persona) => persona.id === current)) {
          return current;
        }
        try {
          window.localStorage.removeItem(SELECTED_PERSONA_STORAGE_KEY);
        } catch {
          /* ignore */
        }
        return "";
      });
    } catch (error) {
      console.warn("load personas failed", error);
      const detail = error instanceof ApiError ? error.detail : null;
      notify(detail ? `Persona 列表读取失败：${detail}` : "Persona 列表读取失败，请查看后端日志。", "error");
    }
  }, [notify]);

  const refreshScenes = useCallback(async () => {
    try {
      const [backgrounds, scenes] = await Promise.all([
        listSceneBackgrounds(),
        listSceneCompositions(),
      ]);
      setSceneBackgrounds(backgrounds.items);
      setSceneCompositions(scenes.items);
      setSelectedSceneIdsByAvatar((current) => {
        const next = Object.fromEntries(
          Object.entries(current).filter(([sceneAvatarId, sceneId]) => (
            scenes.items.some((scene) => scene.id === sceneId && scene.avatar_id === sceneAvatarId)
          )),
        );
        try {
          const legacySceneId = window.localStorage.getItem(SELECTED_SCENE_STORAGE_KEY);
          const legacyScene = legacySceneId ? scenes.items.find((scene) => scene.id === legacySceneId) : null;
          if (legacyScene && !next[legacyScene.avatar_id]) {
            next[legacyScene.avatar_id] = legacyScene.id;
          }
          window.localStorage.removeItem(SELECTED_SCENE_STORAGE_KEY);
        } catch {
          /* ignore */
        }
        return next;
      });
    } catch (error) {
      console.warn("load scene assets failed", error);
    }
  }, []);

  const handleSceneCompositionsChange = useCallback((scenes: SceneComposition[]) => {
    setSceneCompositions(scenes);
    setSelectedSceneIdsByAvatar((current) => {
      return Object.fromEntries(
        Object.entries(current).filter(([sceneAvatarId, sceneId]) => (
          scenes.some((scene) => scene.id === sceneId && scene.avatar_id === sceneAvatarId)
        )),
      );
    });
  }, []);

  const handleSceneSelect = useCallback((scene: SceneComposition) => {
    setSelectedSceneIdsByAvatar((current) => ({
      ...current,
      [scene.avatar_id]: scene.id,
    }));
  }, []);

  const handleSceneClear = useCallback((sceneAvatarId: string) => {
    setSelectedSceneIdsByAvatar((current) => {
      const next = { ...current };
      delete next[sceneAvatarId];
      return next;
    });
  }, []);

  const refreshAvatarKnowledgeBases = useCallback(async (targetAvatarId: string) => {
    if (!targetAvatarId) return;
    const seq = ++avatarKnowledgeBasesLoadSeqRef.current;
    avatarKnowledgeBasesSyncReadyRef.current = false;
    try {
      const response = await apiGet<AvatarKnowledgeBasesResponse>(
        `/agent/avatars/${encodeURIComponent(targetAvatarId)}/knowledge-bases`,
      );
      if (seq !== avatarKnowledgeBasesLoadSeqRef.current) return;
      const selectedIds = normalizeSelectedKnowledgeBaseIds(response);
      lastPersistedAvatarKnowledgeBasesRef.current.set(targetAvatarId, selectedIds);
      if (Array.isArray(response.knowledge_base_summaries) && response.knowledge_base_summaries.length) {
        setKnowledgeBaseSummaries((prev) => {
          const byId = new Map(prev.map((item) => [item.id, item]));
          for (const summary of response.knowledge_base_summaries ?? []) {
            if (summary.id) byId.set(summary.id, summary);
          }
          return Array.from(byId.values());
        });
      }
      setAgentConfigState((prev) => {
        const next = { ...prev, knowledgeBaseIds: selectedIds };
        writeStoredAgentConfig(next);
        return next;
      });
    } catch (error) {
      console.warn("load avatar knowledge bases failed", error);
      const detail = error instanceof ApiError ? error.detail : null;
      notify(detail ? `形象知识库读取失败：${detail}` : "形象知识库读取失败，请查看后端日志。", "error");
    } finally {
      if (seq === avatarKnowledgeBasesLoadSeqRef.current) {
        avatarKnowledgeBasesSyncReadyRef.current = true;
      }
    }
  }, [notify]);

  const handleManageKnowledgeBases = useCallback(() => {
    setAssetLibraryTab("knowledge");
    setWorkflow("assetLibrary");
  }, []);

  const handleManageMemoryLibraries = useCallback(() => {
    setAssetLibraryTab("memory");
    setWorkflow("assetLibrary");
  }, []);

  useEffect(() => {
    if (workflow === "realtime") void refreshKnowledgeBases();
  }, [refreshKnowledgeBases, workflow]);

  const refreshMemoryLibraries = useCallback(async () => {
    if (!avatarId) {
      setMemoryLibraries([]);
      setMemoryLibraryId(null);
      setMemoryEnabled(false);
      return;
    }
    try {
      const result = await getMemoryLibraries(MEMORY_PROFILE_ID, avatarId);
      const items = Array.isArray(result.items) ? result.items : [];
      setMemoryLibraries(items);
      setMemoryLibraryId((current) => {
        if (!current || items.some((library) => library.id === current)) return current;
        setMemoryEnabled(false);
        return null;
      });
    } catch (error) {
      console.warn("load memory libraries failed", error);
      const detail = error instanceof ApiError ? error.detail : null;
      notify(detail ? `记忆库列表读取失败：${detail}` : "记忆库列表读取失败，请查看后端日志。", "error");
      setMemoryLibraries([]);
    }
  }, [avatarId, notify]);

  useEffect(() => {
    if (workflow === "realtime") void refreshMemoryLibraries();
  }, [refreshMemoryLibraries, workflow]);

  useEffect(() => {
    if (workflow === "realtime") void refreshPersonas();
  }, [refreshPersonas, workflow]);

  useEffect(() => {
    void refreshScenes();
  }, [refreshScenes]);

  useEffect(() => {
    try {
      if (Object.keys(selectedSceneIdsByAvatar).length) {
        window.localStorage.setItem(SELECTED_SCENE_BY_AVATAR_STORAGE_KEY, JSON.stringify(selectedSceneIdsByAvatar));
      } else {
        window.localStorage.removeItem(SELECTED_SCENE_BY_AVATAR_STORAGE_KEY);
      }
    } catch {
      /* ignore */
    }
  }, [selectedSceneIdsByAvatar]);

  useEffect(() => {
    try {
      window.localStorage.setItem(CONVERSATION_VIEW_MODE_KEY, conversationViewMode);
    } catch {
      /* ignore */
    }
  }, [conversationViewMode]);

  useEffect(() => {
    const startupVisible = connection === "idle" || connection === "error" || connection === "connecting" || connection === "queued";
    if (startupVisible && conversationViewMode === "immersive") setConversationViewMode("studio");
  }, [connection, conversationViewMode]);

  useEffect(() => {
    if (workflow !== "realtime" || conversationViewMode !== "immersive") return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setConversationViewMode("studio");
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [conversationViewMode, workflow]);

  useEffect(() => {
    if (selectedPersonaId) return;
    void refreshAvatarKnowledgeBases(avatarId);
  }, [avatarId, refreshAvatarKnowledgeBases, selectedPersonaId]);

  useEffect(() => {
    if (selectedPersonaId) return;
    if (!avatarKnowledgeBasesSyncReadyRef.current || !avatarId) return;
    const selectedIds = normalizeKnowledgeBaseIds(agentConfig.knowledgeBaseIds);
    const lastPersisted = lastPersistedAvatarKnowledgeBasesRef.current.get(avatarId) ?? [];
    if (
      lastPersisted.length === selectedIds.length &&
      lastPersisted.every((id, index) => id === selectedIds[index])
    ) {
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        await apiPut<AvatarKnowledgeBasesResponse>(
          `/agent/avatars/${encodeURIComponent(avatarId)}/knowledge-bases`,
          { knowledge_base_ids: selectedIds },
        );
        if (!cancelled) {
          lastPersistedAvatarKnowledgeBasesRef.current.set(avatarId, selectedIds);
        }
      } catch (error) {
        console.warn("persist avatar knowledge bases failed", error);
        const detail = error instanceof ApiError ? error.detail : null;
        notify(detail ? `形象知识库保存失败：${detail}` : "形象知识库保存失败，请查看后端日志。", "error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [agentConfig.knowledgeBaseIds, avatarId, notify, selectedPersonaId]);

  const cleanupRealtimeRecordStreams = useCallback(() => {
    if (realtimeRecordMicStreamRef.current) {
      for (const track of realtimeRecordMicStreamRef.current.getTracks()) track.stop();
      realtimeRecordMicStreamRef.current = null;
    }
    if (realtimeRecordStreamRef.current) {
      for (const track of realtimeRecordStreamRef.current.getTracks()) track.stop();
      realtimeRecordStreamRef.current = null;
    }
  }, []);

  const uploadRealtimeExport = useCallback(async (pending: PendingRealtimeExport) => {
    setRecordingSaving(true);
    try {
      const saved = await uploadExportVideo({
        blob: pending.blob,
        kind: "realtime_dialogue",
        title: pending.title,
        durationSec: pending.durationSec,
        sessionId: pending.sessionId,
        avatarId: pending.avatarId,
        model: pending.model,
      });
      pendingRealtimeExportRef.current = null;
      setAssetLibraryRefreshKey((value) => value + 1);
      setFtRecordPhase("idle");
      notify(`录制已保存，可在资产库查看：${saved.title}`, "success");
    } catch (error) {
      console.warn("upload realtime export failed", error);
      pendingRealtimeExportRef.current = pending;
      setFtRecordPhase("stopped");
      const detail = error instanceof ApiError ? error.detail : null;
      notify(detail ? `录制上传失败：${detail}` : "录制上传失败，可点击重试保存。", "error");
    } finally {
      setRecordingSaving(false);
    }
  }, [notify]);

  const retryPendingRealtimeExport = useCallback(async () => {
    const pending = pendingRealtimeExportRef.current;
    if (!pending) {
      notify("没有待重试保存的录制。", "info");
      setFtRecordPhase("idle");
      return;
    }
    await uploadRealtimeExport(pending);
  }, [notify, uploadRealtimeExport]);

  const stopRealtimeRecording = useCallback(() => {
    const recorder = realtimeRecorderRef.current;
    if (!recorder) return;
    if (recorder.state !== "inactive") recorder.stop();
  }, []);

  const startRealtimeRecording = useCallback(async () => {
    if (!sessionId || connection !== "live" && connection !== "expiring") {
      notify("请先连接实时对话会话，再开始录制。", "info");
      return;
    }
    const videoEl = videoRef.current as CaptureStreamVideoElement | null;
    const captureStream = videoEl?.captureStream ?? videoEl?.mozCaptureStream;
    if (!videoEl || !captureStream) {
      notify("当前浏览器不支持录制舞台画面，请换用 Chrome。", "error");
      return;
    }
    if (typeof MediaRecorder === "undefined") {
      notify("当前浏览器不支持 MediaRecorder，无法录制。", "error");
      return;
    }
    if (realtimeRecorderRef.current?.state === "recording") return;

    setFtRecordBusy(true);
    let audioContext: AudioContext | null = null;
    try {
      cleanupRealtimeRecordStreams();
      const stageStream = captureStream.call(videoEl, 30);
      const recordVideoTracks = stageStream.getVideoTracks().map((track) => track.clone());
      const outputStream = new MediaStream(recordVideoTracks);
      realtimeRecordStreamRef.current = outputStream;
      audioContext = new AudioContext();
      const destination = audioContext.createMediaStreamDestination();
      let hasAudio = false;

      const micStream = await requestUserAudioWithTimeout();
      realtimeRecordMicStreamRef.current = micStream;
      if (micStream.getAudioTracks().length > 0) {
        audioContext.createMediaStreamSource(micStream).connect(destination);
        hasAudio = true;
      }

      const remoteAudioTracks = remoteStreamRef.current?.getAudioTracks() ?? [];
      if (remoteAudioTracks.length > 0) {
        const remoteAudioStream = new MediaStream(remoteAudioTracks);
        audioContext.createMediaStreamSource(remoteAudioStream).connect(destination);
        hasAudio = true;
      }
      if (hasAudio) {
        for (const track of destination.stream.getAudioTracks()) outputStream.addTrack(track);
      }
      const mimeType = selectMediaRecorderMimeType([
        "video/mp4;codecs=avc1.42E01E,mp4a.40.2",
        "video/mp4",
        "video/webm;codecs=vp9,opus",
        "video/webm;codecs=vp8,opus",
        "video/webm",
      ]);
      const recorder = new MediaRecorder(outputStream, mimeType ? { mimeType } : undefined);
      realtimeRecordChunksRef.current = [];
      realtimeRecordStartedAtRef.current = performance.now();
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) realtimeRecordChunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        const chunks = realtimeRecordChunksRef.current;
        realtimeRecordChunksRef.current = [];
        realtimeRecorderRef.current = null;
        void audioContext?.close().catch(() => {});
        cleanupRealtimeRecordStreams();
        const durationSec = Math.max(0.1, (performance.now() - realtimeRecordStartedAtRef.current) / 1000);
        if (!chunks.length) {
          setFtRecordPhase("idle");
          notify("录制内容为空，未生成导出视频。", "error");
          return;
        }
        const blob = new Blob(chunks, { type: recorder.mimeType || "video/webm" });
        const pending: PendingRealtimeExport = {
          blob,
          title: realtimeExportTitle(model),
          durationSec,
          sessionId,
          avatarId,
          model,
        };
        void uploadRealtimeExport(pending);
      };
      recorder.start(1000);
      realtimeRecorderRef.current = recorder;
      pendingRealtimeExportRef.current = null;
      setFtRecordPhase("recording");
      notify("已开始录制实时对话。", "success");
    } catch (error) {
      console.warn("start realtime recording failed", error);
      void audioContext?.close().catch(() => {});
      cleanupRealtimeRecordStreams();
      notify(realtimeRecordingStartErrorMessage(error), "error");
    } finally {
      setFtRecordBusy(false);
    }
  }, [avatarId, cleanupRealtimeRecordStreams, connection, model, notify, sessionId, uploadRealtimeExport]);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        FASTLIVEPORTRAIT_CONFIG_STORAGE_KEY,
        JSON.stringify(fasterliveportraitConfig),
      );
    } catch {
      /* ignore */
    }
  }, [fasterliveportraitConfig]);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        VIDEO_CREATION_FASTLIVEPORTRAIT_CONFIG_STORAGE_KEY,
        JSON.stringify(videoCreationFasterliveportraitConfig),
      );
    } catch {
      /* ignore */
    }
  }, [videoCreationFasterliveportraitConfig]);

  useEffect(() => {
    try {
      window.localStorage.setItem(SESSION_PANEL_COLLAPSED_KEY, sessionPanelCollapsed ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [sessionPanelCollapsed]);

  const [llmSystemPrompt] = useState<string>(() => {
    try {
      return window.localStorage.getItem(LLM_SYSTEM_PROMPT_STORAGE_KEY) ?? "";
    } catch {
      return "";
    }
  });

  const loadVoices = useCallback(async (): Promise<VoiceCatalogItem[]> => {
    try {
      const res = await apiGet<{ items: VoiceCatalogItem[] }>("/voices");
      const items = res.items ?? [];
      setVoiceCatalog(items);
      return items;
    } catch (e) {
      console.warn("Failed to load /voices", e);
      return [];
    }
  }, []);

  const applyClonedVoice = useCallback(async (application: VoiceCloneApplication) => {
    await loadVoices();
    setVoiceCatalog((prev) => {
      if (prev.some((item) => item.provider === application.provider && item.voice_id === application.voice)) {
        return prev;
      }
      return [
        ...prev,
        {
          id: Date.now(),
          user_id: 1,
          provider: application.provider,
          voice_id: application.voice,
          display_label: application.displayLabel,
          target_model: application.model,
          source: "clone",
        },
      ];
    });
    setTtsProvider(application.provider);
    setQwenModel(application.model);
    setQwenVoice(application.voice);
    setVoiceApplyNotice(application.message);
    setVoiceCloneOpen(false);
    notify(application.message, "success");
  }, [loadVoices, notify]);

  const bailianModels = useMemo(() => {
    const base = bailianModelOptions(ttsProvider);
    if (ttsProvider === "dashscope") {
      const ids = new Set(base.map((b) => b.id));
      const extra = QWEN_VOICE_CLONE_TARGET_OPTIONS.filter((o) => !ids.has(o.id));
      return [...base, ...extra];
    }
    return base;
  }, [ttsProvider]);

  const bailianVoices = useMemo(
    () => mergeVoiceCatalogIntoOptions(bailianVoiceOptions(ttsProvider), voiceCatalog, ttsProvider, qwenModel),
    [qwenModel, ttsProvider, voiceCatalog],
  );

  useEffect(() => {
    const mids = bailianModels.map((o) => o.id);
    const vids = bailianVoices.map((o) => o.id);
    setQwenModel((prev) => (mids.includes(prev) ? prev : mids[0] ?? ""));
    if (vids.length === 0) {
      setQwenVoice("");
      return;
    }
    setQwenVoice((prev) => (vids.includes(prev) ? prev : vids[0] ?? ""));
  }, [ttsProvider, bailianModels, bailianVoices]);

  useEffect(() => {
    const opt = bailianVoices.find((o) => o.id === qwenVoice);
    if (opt?.targetModel) {
      setQwenModel(opt.targetModel);
    }
  }, [qwenVoice, bailianVoices]);

  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    if (video.srcObject !== remoteStream) {
      video.srcObject = remoteStream;
    }
    if (remoteStream) {
      video.muted = false;
      video.volume = 1;
      playWithMutedFallback(video);
    } else {
      video.muted = true;
    }
  }, [conversationViewMode, remoteStream, workflow]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (!remoteStream) {
      audio.srcObject = null;
      return;
    }
    audio.srcObject = remoteStream;
    audio.muted = false;
    audio.volume = 1;
    void audio.play().catch(() => {});
    return () => {
      audio.srcObject = null;
    };
  }, [remoteStream]);

  useEffect(() => {
    return () => {
      if (ttsPreviewUrlRef.current) {
        URL.revokeObjectURL(ttsPreviewUrlRef.current);
        ttsPreviewUrlRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem(EDGE_VOICE_STORAGE_KEY, edgeVoice);
    } catch {
      /* ignore */
    }
  }, [edgeVoice]);

  useEffect(() => {
    try {
      window.localStorage.setItem(TTS_PROVIDER_STORAGE_KEY, ttsProvider);
    } catch {
      /* ignore */
    }
  }, [ttsProvider]);

  useEffect(() => {
    try {
      window.localStorage.setItem(QWEN_MODEL_STORAGE_KEY, qwenModel);
    } catch {
      /* ignore */
    }
  }, [qwenModel]);

  useEffect(() => {
    try {
      window.localStorage.setItem(QWEN_VOICE_STORAGE_KEY, qwenVoice);
    } catch {
      /* ignore */
    }
  }, [qwenVoice]);

  useEffect(() => {
    if (!asrProvider) return;
    try {
      window.localStorage.setItem(ASR_PROVIDER_STORAGE_KEY, asrProvider);
    } catch {
      /* ignore */
    }
  }, [asrProvider]);

  useEffect(() => {
    try {
      window.localStorage.setItem(LLM_SYSTEM_PROMPT_STORAGE_KEY, llmSystemPrompt);
    } catch {
      /* ignore */
    }
  }, [llmSystemPrompt]);

  useEffect(() => {
    try {
      window.localStorage.setItem(SETTINGS_DOCK_EXPANDED_KEY, settingsExpanded ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [settingsExpanded]);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(MESSAGE_STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as Message[];
      if (!Array.isArray(parsed)) return;
      setMessages(parsed);
      msgCounter = Math.max(msgCounter, parsed.length);
    } catch (error) {
      console.warn("Failed to restore chat history", error);
    }
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem(MESSAGE_STORAGE_KEY, JSON.stringify(messages));
    } catch (error) {
      console.warn("Failed to persist chat history", error);
    }
  }, [messages]);

  const closePeerConnection = useCallback(() => {
    if (pcRef.current) {
      pcRef.current.close();
      pcRef.current = null;
    }
    if (remoteStreamRef.current) {
      for (const track of remoteStreamRef.current.getTracks()) track.stop();
      remoteStreamRef.current = null;
    }
    setRemoteStream(null);
  }, []);

  const releaseSession = useCallback(async (sid: string, keepalive = false) => {
    try {
      await apiDelete(`/sessions/${sid}`, { keepalive });
    } catch (error) {
      console.warn("Failed to release session", sid, error);
    }
  }, []);

  const resetLiveState = useCallback(
    (clearMessages = false) => {
      closePeerConnection();
      setSessionId(null);
      setActiveAsrProvider("");
      setQueueInfo(null);
      setExpiringCountdown(null);
      slotAcquiredRef.current = null;
      clearSubtitleState();
      if (clearMessages) {
        setMessages([]);
      }
    },
    [clearSubtitleState, closePeerConnection],
  );

  const prewarmKey = useCallback((targetAvatarId: string, targetModel: string) => {
    return `${targetModel}:${targetAvatarId}`;
  }, []);

  const isPrewarmAssetReady = useCallback((response: AvatarPrewarmResponse) => {
    if (response.status === "ready") return true;
    const cacheStatus = String(response.cache?.status ?? "").trim().toLowerCase();
    return Boolean(cacheStatus && !["error", "failed", "missing", "skipped", "unknown"].includes(cacheStatus));
  }, []);

  const requestAvatarPrewarm = useCallback(async (
    targetAvatarId: string,
    targetModel: string,
    options?: { force?: boolean; modelConnected?: boolean },
  ): Promise<boolean> => {
    if (!targetAvatarId || !PREWARMABLE_MODELS.has(targetModel)) return true;
    if (!options?.modelConnected) return false;
    const key = prewarmKey(targetAvatarId, targetModel);
    const current = prewarmByKey[key];
    const inFlight = prewarmInFlightRef.current.get(key);
    if (inFlight) return inFlight;
    if (current === "ready") return true;
    if (current === "failed" && !options?.force) return false;
    const task = (async () => {
      const seq = ++prewarmSeqRef.current;
      setPrewarmByKey((prev) => ({ ...prev, [key]: "preparing" }));
      try {
        const response = await apiPost<AvatarPrewarmResponse>(
          `/avatars/${encodeURIComponent(targetAvatarId)}/prewarm`,
          { model: targetModel },
        );
        const ready = isPrewarmAssetReady(response);
        setPrewarmByKey((prev) => ({
          ...prev,
          [key]: ready ? "ready" : "failed",
        }));
        if (ready && seq === prewarmSeqRef.current) {
          const cacheStatus = response.cache?.status;
          const label = modelLabel(targetModel);
          if (response.runtime_status === "failed") {
            const detail = response.runtime?.message;
            notify(detail ? `${label} 资产已准备，运行时预热失败：${detail}` : `${label} 资产已准备，运行时预热失败。`, "info");
          } else {
            notify(cacheStatus ? `${label} 已准备：${cacheStatus}` : `${label} 已准备`, "success");
          }
        }
        return ready;
      } catch (error) {
        console.warn("Avatar prewarm failed", error);
        setPrewarmByKey((prev) => ({ ...prev, [key]: "failed" }));
        if (seq === prewarmSeqRef.current) {
          const detail = error instanceof ApiError ? error.detail : null;
          const label = modelLabel(targetModel);
          notify(detail ? `${label} 准备失败：${detail}` : `${label} 准备失败，首次生成会走冷启动。`, "error");
        }
        return false;
      } finally {
        prewarmInFlightRef.current.delete(key);
      }
    })();
    prewarmInFlightRef.current.set(key, task);
    return task;
  }, [isPrewarmAssetReady, notify, prewarmByKey, prewarmKey]);

  const selectedPrewarmState = prewarmByKey[prewarmKey(avatarId, model)] ?? "idle";

  useEffect(() => {
    if (!PREWARMABLE_MODELS.has(model) || !avatarId) return;
    void requestAvatarPrewarm(avatarId, model, { modelConnected: selectedModelConnected });
  }, [avatarId, model, requestAvatarPrewarm, selectedModelConnected]);

  // ---------- Init: fetch avatars & models ----------
  useEffect(() => {
    void (async () => {
      try {
        const [av, mo, health, , initialRuntimeConfig] = await Promise.all([
          apiGet<AvatarSummary[]>("/avatars"),
          apiGet<{ models: string[]; statuses?: ModelStatus[]; default_model?: string | null }>("/models"),
          apiGet<HealthResponse>("/health"),
          loadVoices(),
          loadRuntimeConfig().catch((error) => {
            console.warn("load runtime config during init failed", error);
            return null;
          }),
        ]);
        setRuntimeStatus(health);
        setAvatars(av);
        setModels(mo.models);
        if (initialRuntimeConfig) {
          setRuntimeConfig(initialRuntimeConfig);
          syncRuntimeConfigSelection(initialRuntimeConfig);
        } else {
          setAsrProvider((prev) => {
            const next = normalizeAsrProvider(prev || health.stt_provider, "dashscope");
            setAsrModel(sttModelForProvider(next));
            return next;
          });
        }
        const statuses = mo.statuses ?? mo.models.map((id) => ({ id, connected: true }));
        setModelStatuses(statuses);
        const storedAvatarSelection = readStoredAvatarSelection();
        const initialAvatar = pickInitialAvatar(av, mo.models, storedAvatarSelection, mo.default_model);
        if (initialAvatar) {
          setAvatarId(initialAvatar.id);
          if (initialAvatar.is_custom || storedAvatarSelection?.source === "explicit") {
            writeStoredAvatarId(
              initialAvatar.id,
              storedAvatarSelection?.source === "explicit" ? "explicit" : "auto",
            );
          }
          setModel((prev) => {
            const requestedModel = pickInitialModel(
              prev,
              mo.models,
              statuses,
              initialAvatar,
              mo.default_model,
            );
            return normalizeAvatarModelSelection(
              av,
              initialAvatar.id,
              requestedModel,
            ).model;
          });
        }
      } catch {
        setConnection("error");
      }
    })();
  }, [loadVoices, syncRuntimeConfigSelection]);

  // ---------- SSE ----------
  useEffect(() => {
    if (!sessionId) return;
    const stop = connectSse(buildApiUrl(`/sessions/${sessionId}/events`), (ev, data) => {
      if (ev === "session.queued" && data && typeof data === "object") {
        const d = data as { position?: number; message?: string };
        const position = d.position ?? 1;
        const message = d.message ?? "waiting";
        if (position > 0) {
          setConnection("queued");
          setQueueInfo({ position, message });
        } else if (position === 0) {
          // Slot acquired: unblock handleStart to proceed with WebRTC
          slotAcquiredRef.current?.();
          slotAcquiredRef.current = null;
          setConnection("connecting");
          setQueueInfo(null);
        } else {
          // -1: rejected (queue_full or timeout)
          slotAcquiredRef.current = null;
          setConnection("error");
          setQueueInfo({ position, message });
        }
      }
      if (ev === "session.expiring" && data && typeof data === "object") {
        const d = data as { remaining_sec?: number };
        const remaining = d.remaining_sec ?? 60;
        setConnection("expiring");
        setExpiringCountdown(remaining);
        // Start local countdown
        const interval = setInterval(() => {
          setExpiringCountdown((prev) => {
            if (prev === null || prev <= 1) {
              clearInterval(interval);
              return null;
            }
            return prev - 1;
          });
        }, 1000);
      }
      if (ev === "session.expired") {
        // Server force-closed the session, reset to idle
        setConnection("idle");
        setExpiringCountdown(null);
        setSessionId(null);
        setActiveAsrProvider("");
        const orphanId = streamingAssistantMsgIdRef.current;
        const pendingId = pendingAssistantMsgIdRef.current;
        clearSubtitleState();
        if (orphanId || pendingId) {
          const removeIds = new Set([orphanId, pendingId].filter(Boolean));
          setMessages((prev) => prev.filter((m) => !removeIds.has(m.id)));
        }
      }
      if (ev === "error") {
        const d = data && typeof data === "object" ? (data as { message?: string; code?: string }) : {};
        const detail = d.message || d.code || "语音合成失败，请切换可用音色后重试。";
        appendAssistantError(detail);
        notify(`对话失败：${detail}`, "error");
      }
      if (ev === "speech.started") {
        const staleId = streamingAssistantMsgIdRef.current;
        const pendingId = pendingAssistantMsgIdRef.current;
        clearSubtitleState();
        setIsSpeaking(true);
        if (staleId) {
          setMessages((prev) => prev.filter((m) => m.id !== staleId));
        }
        const id = pendingId ?? makeId();
        streamingAssistantMsgIdRef.current = id;
        setMessages((prev) => {
          if (prev.some((m) => m.id === id)) {
            return prev.map((m) => (m.id === id ? { ...m, text: "" } : m));
          }
          return [
            ...prev,
            { id, role: "assistant", text: "", timestamp: Date.now() },
          ];
        });
      }
      if (ev === "speech.media_started") {
        subtitleMediaReadyRef.current = true;
        clearSubtitleFallbackTimer();
        flushSubtitleDisplay();
        flushSubtitleMessage();
      }
      if (ev === "subtitle.chunk" && data && typeof data === "object") {
        const t = (data as { text?: string }).text;
        if (!t) return;
        subtitleAccRef.current += t;
        if (subtitleMediaReadyRef.current) {
          flushSubtitleDisplay();
          flushSubtitleMessage();
        }
      }
      if (ev === "speech.ended") {
        const d = data && typeof data === "object" ? (data as { text?: string }) : {};
        const fromEvent = typeof d.text === "string" ? d.text.trim() : "";
        const streamed = subtitleAccRef.current.trim();
        const finalText = fromEvent || streamed;
        const msgId = streamingAssistantMsgIdRef.current;
        clearSubtitleState();
        if (msgId) {
          if (finalText) {
            setMessages((prev) => {
              let updated = false;
              const next = prev.map((m) => {
                if (m.id !== msgId) return m;
                updated = true;
                return { ...m, text: finalText };
              });
              if (updated) return next;
              return [
                ...prev,
                { id: makeId(), role: "assistant", text: finalText, timestamp: Date.now() },
              ];
            });
          } else {
            setMessages((prev) => prev.filter((m) => m.id !== msgId));
          }
        } else if (finalText) {
          setMessages((prev) => [
            ...prev,
            { id: makeId(), role: "assistant", text: finalText, timestamp: Date.now() },
          ]);
        }
      }
    });
    return stop;
  }, [appendAssistantError, clearSubtitleFallbackTimer, clearSubtitleState, flushSubtitleDisplay, flushSubtitleMessage, notify, sessionId]);

  // Resolves when FlashTalk slot is acquired (session.queued position=0)
  const slotAcquiredRef = useRef<(() => void) | null>(null);

  const waitForSessionReady = useCallback(async (sid: string, timeoutMs = 180_000) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const rec = await apiGet<SessionRecord>(`/sessions/${sid}`);
      if (rec.state === "worker_ready" || rec.state === "ready" || rec.state === "speaking") {
        return;
      }
      if (rec.state === "error" || rec.state === "closed") {
        throw new Error(`Session ${rec.state}`);
      }
      await wait(750);
    }
    throw new Error("Session init wait timeout");
  }, []);

  // ---------- Actions ----------
  const handleStart = useCallback(async () => {
    if (!videoRef.current) return;
    clearSubtitleState();
    const lockedAsrProvider = normalizeAsrProvider(asrProvider, "dashscope");
    let latestRuntimeStatus: HealthResponse | null = null;
    try {
      latestRuntimeStatus = await apiGet<HealthResponse>("/health");
      setRuntimeStatus(latestRuntimeStatus);
    } catch (error) {
      console.warn("Failed to refresh runtime status before start", error);
    }

    const startBlockReason = validateAudioProviderConfigBeforeStart({
      sttProvider: lockedAsrProvider,
      ttsProvider,
      runtimeStatus: latestRuntimeStatus,
    });
    if (startBlockReason) {
      notify(startBlockReason, "error");
      setSettingsExpanded(true);
      return;
    }

    if (PREWARMABLE_MODELS.has(model) && selectedModelConnected && selectedPrewarmState !== "ready") {
      const ready = await requestAvatarPrewarm(avatarId, model, { force: true, modelConnected: selectedModelConnected });
      if (!ready) return;
    }

    const previousSessionId = sessionIdRef.current;
    if (previousSessionId) {
      await releaseSession(previousSessionId);
      resetLiveState();
    }

    setAsrProvider(lockedAsrProvider);
    setActiveAsrProvider(lockedAsrProvider);
    setAsrModel(sttModelForProvider(lockedAsrProvider));
    setConnection("connecting");
    setQueueInfo(null);
    let createdSessionId: string | null = null;
    try {
      const knowledgeBaseIds = normalizeKnowledgeBaseIds(agentConfig.knowledgeBaseIds);
      const selectedTtsVoice = resolveSelectableTtsVoice(ttsProvider, qwenVoice, bailianVoices);
      const created = await apiPost<CreateSessionResponse>("/sessions", {
        persona_id: selectedPersonaId || undefined,
        avatar_id: avatarId,
        model,
        llm_system_prompt: llmSystemPrompt.trim() || undefined,
        tts_provider: ttsProvider,
        stt_provider: lockedAsrProvider,
        tts_voice: isEdgeTts(ttsProvider)
          ? edgeVoice
          : !hasSelectableTtsVoice(ttsProvider)
            ? undefined
            : selectedTtsVoice || undefined,
        tts_model: ttsModelSelectable(ttsProvider) ? qwenModel : undefined,
        wav2lip_postprocess_mode:
          model === "wav2lip" && wav2lipPostprocessMode !== "auto" ? wav2lipPostprocessMode : undefined,
        fasterliveportrait_config:
          model === "fasterliveportrait" ? fasterliveportraitConfig : undefined,
        user_id: clientUserId,
        agent_enabled: agentConfig.memoryEnabled || agentConfig.knowledgeEnabled || (memoryEnabled && Boolean(memoryLibraryId)),
        memory_enabled: agentConfig.memoryEnabled || (memoryEnabled && Boolean(memoryLibraryId)),
        memory_profile_id: MEMORY_PROFILE_ID,
        character_id: avatarId,
        memory_library_id: memoryEnabled && memoryLibraryId ? memoryLibraryId : undefined,
        knowledge_enabled: agentConfig.knowledgeEnabled,
        knowledge_base_id: knowledgeBaseIds[0],
        knowledge_base_ids: knowledgeBaseIds,
      } satisfies CreateSessionRequest);
      createdSessionId = created.session_id;
      setSessionId(created.session_id);
      if (model === "fasterliveportrait") {
        setFasterliveportraitAppliedConfig(fasterliveportraitConfig);
      }

      // Some backends return before the heavy model/avatar prepare is complete.
      if (created.status === "queued" || created.status === "initializing") {
        setConnection(created.status === "queued" ? "queued" : "connecting");
        try {
          const qs = await apiGet<{ slot_occupied: boolean; queue_size: number }>("/queue/status");
          if (created.status === "queued" && qs.slot_occupied) {
            setConnection("queued");
            setQueueInfo({ position: qs.queue_size, message: "waiting" });
          }
        } catch { /* ignore, SSE/polling will update */ }

        await Promise.race([
          waitForSessionReady(created.session_id),
          new Promise<void>((resolve, reject) => {
            slotAcquiredRef.current = resolve;
            const timer = setTimeout(() => {
              slotAcquiredRef.current = null;
              reject(new Error("Session init wait timeout"));
            }, 360_000);
            const origResolve = resolve;
            slotAcquiredRef.current = () => { clearTimeout(timer); origResolve(); };
          }),
        ]);
        slotAcquiredRef.current = null;
        setConnection("connecting");
        setQueueInfo(null);
      }

      closePeerConnection();
      const playback = await startPlayback(created.session_id, videoRef.current!, {
        onRemoteStream: (remoteStream) => {
          remoteStreamRef.current = remoteStream;
          setRemoteStream(remoteStream);
        },
      });
      pcRef.current = playback.pc;
      remoteStreamRef.current = playback.remoteStream;
      setRemoteStream(playback.remoteStream);
      setActiveAsrProvider(lockedAsrProvider);
      videoRef.current!.muted = false;
      setConnection("live");
      await apiPost(`/sessions/${created.session_id}/start`, {});
      notify("会话已连接，可以开始文本、语音或音频驱动。", "success");
    } catch (error) {
      if (createdSessionId) {
        await releaseSession(createdSessionId);
      }
      resetLiveState();
      console.warn("Failed to start session", error);
      setConnection("error");
      const detail = error instanceof ApiError ? error.detail : null;
      const msg = detail
        ? `启动会话失败：${detail}`
        : "启动会话失败，请稍后重试或查看后端日志。";
      notify(msg, "error");
    }
  }, [
    agentConfig,
    asrProvider,
    avatarId,
    bailianVoices,
    clientUserId,
    clearSubtitleState,
    closePeerConnection,
    edgeVoice,
    llmSystemPrompt,
    memoryEnabled,
    memoryLibraryId,
    model,
    notify,
    qwenVoice,
    releaseSession,
    requestAvatarPrewarm,
    resetLiveState,
    selectedPersonaId,
    selectedModelConnected,
    selectedPrewarmState,
    ttsProvider,
    waitForSessionReady,
    fasterliveportraitConfig,
    wav2lipPostprocessMode,
  ]);

  const handleFasterLivePortraitConfigChange = useCallback((config: FasterLivePortraitConfig) => {
    setFasterliveportraitConfig(sanitizeFasterLivePortraitConfig(config));
  }, []);

  const handleResetFasterLivePortraitConfig = useCallback(() => {
    setFasterliveportraitConfig({ ...DEFAULT_FASTLIVEPORTRAIT_CONFIG });
  }, []);

  const handleVideoCreationFasterLivePortraitConfigChange = useCallback((config: FasterLivePortraitConfig) => {
    setVideoCreationFasterliveportraitConfig(
      sanitizeFasterLivePortraitConfig(config, { ...DEFAULT_VIDEO_CREATION_FASTLIVEPORTRAIT_CONFIG }),
    );
  }, []);

  const handleApplyFasterLivePortraitConfig = useCallback(async () => {
    const next = sanitizeFasterLivePortraitConfig(fasterliveportraitConfig);
    setFasterliveportraitConfig(next);
    const sid = sessionIdRef.current;
    if (model !== "fasterliveportrait" || !sid || connection === "idle" || connection === "error") {
      setFasterliveportraitAppliedConfig(next);
      notify("FasterLivePortrait 配置已保存，下次启动生效。", "success");
      return;
    }
    setFasterliveportraitApplying(true);
    try {
      await apiPost(`/sessions/${sid}/fasterliveportrait-config`, next);
      setFasterliveportraitAppliedConfig(next);
      notify("FasterLivePortrait 参数已应用，下一段音频块生效。", "success");
    } catch (error) {
      console.warn("Failed to update FasterLivePortrait config", error);
      const detail = error instanceof ApiError ? error.detail : null;
      notify(detail ? `应用参数失败：${detail}` : "应用参数失败，请查看后端日志。", "error");
    } finally {
      setFasterliveportraitApplying(false);
    }
  }, [connection, fasterliveportraitConfig, model, notify]);

  const handleCreateCustomAvatar = useCallback(async (
    file: File,
    name: string,
    options?: { removeBackground?: boolean },
  ) => {
    const trimmedName = name.trim();
    if (!trimmedName) {
      notify("请先给形象起个名字。", "info");
      return;
    }
    try {
      window.localStorage.setItem(CUSTOM_REFERENCE_NAME_KEY, trimmedName);
    } catch {
      /* ignore */
    }
    setReferenceSaving(true);
    try {
      const fd = new FormData();
      fd.set("base_avatar_id", avatarId);
      fd.set("name", trimmedName);
      fd.set("model", model);
      fd.set("image", file);
      fd.set("remove_background", options?.removeBackground ? "true" : "false");
      const created = await apiPostForm<AvatarSummary>("/avatars/custom", fd);
      setAvatars((prev) => {
        const filtered = prev.filter((avatar) => avatar.id !== created.id);
        return [...filtered, created];
      });
      setAvatarId(created.id);
      writeStoredAvatarId(created.id);
      const sid = sessionIdRef.current;
      if (sid) await releaseSession(sid);
      resetLiveState(true);
      setConnection("idle");
      notify(`自定义形象「${created.name ?? trimmedName}」已加入形象库。`, "success");
      return created;
    } catch (e) {
      console.warn("create custom avatar failed", e);
      const detail = e instanceof ApiError ? e.detail : null;
      notify(detail ? `创建失败：${detail}` : "创建自定义形象失败，请查看后端日志。", "error");
      return null;
    } finally {
      setReferenceSaving(false);
    }
  }, [avatarId, model, notify, releaseSession, resetLiveState]);

  const handleDeleteAvatar = useCallback(
    async (target: AvatarSummary) => {
      try {
        await apiDelete(`/avatars/${encodeURIComponent(target.id)}`);
        setAvatars((prev) => prev.filter((a) => a.id !== target.id));
        // If the deleted avatar was selected, fall back to the first remaining one.
        setAvatarId((current) => {
          if (current !== target.id) return current;
          const remaining = avatars.filter((a) => a.id !== target.id);
          const next = remaining[0]?.id ?? "";
          writeStoredAvatarId(next);
          return next;
        });
        notify(`已删除自定义形象「${target.name ?? target.id}」。`, "success");
      } catch (error) {
        console.warn("delete avatar failed", error);
        const detail = error instanceof ApiError ? error.detail : null;
        notify(detail ? `删除失败：${detail}` : "删除失败，请查看后端日志。", "error");
      }
    },
    [avatars, notify],
  );

  const handleReturnToAvatarSelection = useCallback(() => {
    if (!window.confirm("更换数字人会结束当前会话，是否继续？")) return;
    void (async () => {
      const sid = sessionIdRef.current;
      if (sid) {
        await releaseSession(sid);
      }
      resetLiveState(true);
      setConnection("idle");
    })();
  }, [avatars, releaseSession, resetLiveState]);

  const handlePreviewTts = useCallback(async () => {
    const text = ttsPreviewText.trim();
    if (!text) {
      notify("先输入一句试听文本。", "info");
      return;
    }
    setTtsPreviewing(true);
    try {
      const voice = isEdgeTts(ttsProvider)
        ? edgeVoice
        : resolveSelectableTtsVoice(ttsProvider, qwenVoice, bailianVoices);
      if (hasSelectableTtsVoice(ttsProvider) && !voice.trim()) {
        notify("当前模型没有可用音色，请先复刻音色或切换模型。", "info");
        return;
      }
      const blob = await requestTTSPreview(
        buildTTSPreviewPayload({
          text,
          voice,
          provider: ttsProvider,
          model: qwenModel,
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
      notify("正在播放试听音频。", "success");
    } catch (e) {
      console.warn("tts preview failed", e);
      const detail = apiErrorMessage(e, "请确认音色、模型和后端密钥配置。");
      notify(`试听失败：${detail}`, "error");
    } finally {
      setTtsPreviewing(false);
    }
  }, [bailianVoices, edgeVoice, notify, qwenModel, qwenVoice, ttsPreviewText, ttsProvider]);

  const handleSend = useCallback(
    (text: string) => {
      if (!sessionId || !text) return;
      const pendingId = makeId();
      const activeAssistantId = streamingAssistantMsgIdRef.current;
      const previousPendingId = pendingAssistantMsgIdRef.current;
      pendingAssistantMsgIdRef.current = pendingId;
      setIsSpeaking(true);
      setMessages((prev) => [
        ...prev.filter((m) => m.id !== previousPendingId && m.id !== activeAssistantId),
        { id: makeId(), role: "user", text, timestamp: Date.now() },
        { id: pendingId, role: "assistant", text: "正在合成语音和口型...", timestamp: Date.now() },
      ]);
      if (isSpeaking) {
        void apiPost(`/sessions/${sessionId}/interrupt`, {}).catch(() => {});
      }
      const endpoint = "speak";
      const selectedTtsVoice = resolveSelectableTtsVoice(ttsProvider, qwenVoice, bailianVoices);
      const payload = {
        text,
        voice:
          isEdgeTts(ttsProvider)
            ? edgeVoice
            : !hasSelectableTtsVoice(ttsProvider)
              ? undefined
              : selectedTtsVoice || undefined,
        tts_provider: ttsProvider,
        tts_model: ttsModelSelectable(ttsProvider) ? qwenModel : undefined,
      };
      void apiPost(`/sessions/${sessionId}/${endpoint}`, payload).catch((err) => {
        console.warn(`${endpoint} failed`, err);
        const detail = apiErrorMessage(err, "请确认会话仍处于已连接状态。");
        appendAssistantError(`发送失败：${detail}`);
        notify(`发送失败：${detail}`, "error");
      });
    },
    [appendAssistantError, bailianVoices, edgeVoice, isSpeaking, notify, qwenModel, qwenVoice, sessionId, ttsProvider],
  );

  /** 流式 STT（WebSocket PCM）成功后仅追加本地消息（speak 已由后端入队） */
  const handleSpeakAudioStreamResult = useCallback(({ text }: { text: string }) => {
    setMessages((prev) => [
      ...prev,
      { id: makeId(), role: "user", text, timestamp: Date.now() },
    ]);
  }, []);

  const handleSpeakAudioStreamError = useCallback((message: string) => {
    const detail = message || "语音识别失败，请检查 STT 配置。";
    appendAssistantError(`语音识别失败：${detail}`);
    notify(`语音识别失败：${detail}`, "error");
  }, [appendAssistantError, notify]);

  const handleSpeakAudio = useCallback(
    async (blob: Blob) => {
      if (!sessionId) return;
      speakAudioAbortRef.current?.abort();
      const ac = new AbortController();
      speakAudioAbortRef.current = ac;
      const fd = new FormData();
      fd.append("file", blob, "speech.webm");
      fd.append(
        "voice",
        isEdgeTts(ttsProvider)
          ? edgeVoice
          : resolveSelectableTtsVoice(ttsProvider, qwenVoice, bailianVoices),
      );
      fd.append("tts_provider", ttsProvider);
      fd.append("stt_provider", activeAsrProvider || normalizeAsrProvider(asrProvider, "dashscope"));
      if (ttsModelSelectable(ttsProvider)) {
        fd.append("tts_model", qwenModel);
      }
      try {
        const res = await apiPostForm<SpeakAudioResponse>(
          `/sessions/${sessionId}/speak_audio`,
          fd,
          { signal: ac.signal },
        );
        setMessages((prev) => [
          ...prev,
          { id: makeId(), role: "user", text: res.text, timestamp: Date.now() },
        ]);
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        // 勿将 connection 置为 error，否则会重新出现「开始 Demo」全屏遮罩
        console.warn("speak_audio failed", error);
        const detail = apiErrorMessage(error, "请检查 STT 配置和后端日志。");
        appendAssistantError(`语音识别失败：${detail}`);
        notify(`语音识别失败：${detail}`, "error");
      } finally {
        if (speakAudioAbortRef.current === ac) {
          speakAudioAbortRef.current = null;
        }
      }
    },
    [activeAsrProvider, appendAssistantError, asrProvider, bailianVoices, edgeVoice, notify, qwenModel, qwenVoice, sessionId, ttsProvider],
  );

  const handleInterrupt = useCallback(() => {
    speakAudioAbortRef.current?.abort();
    if (!sessionId) return;
    void apiPost(`/sessions/${sessionId}/interrupt`, {}).catch(() => {});
  }, [sessionId]);

  const handleSpeakFlashtalkAudioFile = useCallback(
    async (file: File) => {
      if (!sessionId || !isFlashRenderer(model)) return;
      const fd = new FormData();
      fd.append("file", file);
      try {
        await apiPostForm<{ session_id: string; status: string }>(
          `/sessions/${sessionId}/speak_flashtalk_audio`,
          fd,
        );
        setMessages((prev) => [
          ...prev,
          {
            id: makeId(),
            role: "user",
            text: `[上传音频] ${file.name}`,
            timestamp: Date.now(),
          },
        ]);
      } catch (error) {
        console.warn("speak_flashtalk_audio failed", error);
        notify("上传音频驱动口型失败，请确认文件格式和当前会话状态。", "error");
      }
    },
    [model, notify, sessionId],
  );

  useEffect(() => {
    if (realtimeRecorderRef.current?.state === "recording") {
      realtimeRecorderRef.current.stop();
    }
    cleanupRealtimeRecordStreams();
    setFtRecordPhase("idle");
  }, [cleanupRealtimeRecordStreams, sessionId, model]);

  useEffect(() => {
    if (connection !== "live" && connection !== "expiring") {
      if (realtimeRecorderRef.current?.state === "recording") {
        realtimeRecorderRef.current.stop();
      }
      cleanupRealtimeRecordStreams();
      setFtRecordPhase("idle");
    }
  }, [cleanupRealtimeRecordStreams, connection]);

  const handleFtRecordStart = useCallback(async () => {
    await startRealtimeRecording();
  }, [startRealtimeRecording]);

  const handleFtRecordStop = useCallback(() => {
    stopRealtimeRecording();
  }, [stopRealtimeRecording]);

  const handleFtRecordSave = useCallback(async () => {
    await retryPendingRealtimeExport();
  }, [retryPendingRealtimeExport]);

  const handleAvatarChange = useCallback(
    (newId: string) => {
      clearSubtitleState();
      setSelectedPersonaId("");
      try {
        window.localStorage.removeItem(SELECTED_PERSONA_STORAGE_KEY);
      } catch {
        /* ignore */
      }
      const normalized = normalizeAvatarModelSelection(avatars, newId, model);
      setAvatarId(normalized.avatarId);
      writeStoredAvatarId(normalized.avatarId);
      const requestedModel = normalized.model;
      if (requestedModel !== model) {
        setModel(requestedModel);
        notify("该形象使用免 GPU 浏览器动画，已切换到轻量模式。", "info");
      }
      void (async () => {
        const sid = sessionIdRef.current;
        if (sid) {
          await releaseSession(sid);
        }
        resetLiveState(true);
        setConnection("idle");
      })();
    },
    [avatars, clearSubtitleState, model, notify, releaseSession, resetLiveState],
  );

  const applyPersona = useCallback((persona: PersonaSummary | null) => {
    clearSubtitleState();
    if (!persona) {
      setSelectedPersonaId("");
      appliedPersonaIdRef.current = "";
      try {
        window.localStorage.removeItem(SELECTED_PERSONA_STORAGE_KEY);
      } catch {
        /* ignore */
      }
      return;
    }
    setSelectedPersonaId(persona.id);
    appliedPersonaIdRef.current = persona.id;
    try {
      window.localStorage.setItem(SELECTED_PERSONA_STORAGE_KEY, persona.id);
    } catch {
      /* ignore */
    }
    const normalized = normalizeAvatarModelSelection(
      avatars,
      persona.avatar.id,
      persona.avatar.model,
    );
    setAvatarId(normalized.avatarId);
    writeStoredAvatarId(normalized.avatarId);
    setModel(normalized.model);
    const nextTtsProvider = normalizeTtsProvider(persona.runtime.tts_provider ?? persona.voice.provider, ttsProvider);
    setTtsProvider(nextTtsProvider);
    if (persona.voice.model) {
      setQwenModel(persona.voice.model);
    }
    if (persona.voice.voice_id) {
      if (nextTtsProvider === "edge") {
        setEdgeVoice(persona.voice.voice_id);
      } else {
        setQwenVoice(persona.voice.voice_id);
      }
    }
    if (persona.runtime.stt_provider) {
      const normalizedAsr = normalizeAsrProvider(persona.runtime.stt_provider, "dashscope");
      setAsrProvider(normalizedAsr);
      setAsrModel(sttModelForProvider(normalizedAsr));
    }
    setAgentConfig({
      memoryEnabled: persona.agent.memory_enabled,
      knowledgeEnabled: persona.agent.knowledge_enabled,
      knowledgeBaseIds: normalizeKnowledgeBaseIds(persona.agent.knowledge_base_ids),
    });
    void (async () => {
      const sid = sessionIdRef.current;
      if (sid) {
        await releaseSession(sid);
      }
      resetLiveState(true);
      setConnection("idle");
    })();
  }, [
    clearSubtitleState,
    avatars,
    releaseSession,
    resetLiveState,
    setAgentConfig,
    ttsProvider,
  ]);

  const handlePersonaChange = useCallback((personaId: string) => {
    if (!personaId) {
      applyPersona(null);
      return;
    }
    const persona = personas.find((item) => item.id === personaId) ?? null;
    if (!persona) return;
    applyPersona(persona);
  }, [applyPersona, personas]);

  const handlePersonaImport = useCallback(async (file: File) => {
    setPersonaImporting(true);
    try {
      const imported = await apiUploadFile<PersonaSummary>("/personas/import", "file", file);
      setPersonas((prev) => {
        const filtered = prev.filter((item) => item.id !== imported.id);
        return [...filtered, imported].sort((a, b) => a.name.localeCompare(b.name));
      });
      applyPersona(imported);
      await refreshKnowledgeBases();
      notify(`Persona 已导入：${imported.name}`, "success");
    } catch (error) {
      console.warn("persona import failed", error);
      notify(apiErrorMessage(error, "Persona 导入失败，请检查包格式。"), "error");
    } finally {
      setPersonaImporting(false);
    }
  }, [applyPersona, notify, refreshKnowledgeBases]);

  useEffect(() => {
    if (!selectedPersonaId || appliedPersonaIdRef.current === selectedPersonaId) return;
    const persona = personas.find((item) => item.id === selectedPersonaId);
    if (persona) {
      applyPersona(persona);
    }
  }, [applyPersona, personas, selectedPersonaId]);

  const handleVideoCloneAvatarUploaded = useCallback(
    (created: AvatarSummary) => {
      setAvatars((prev) => {
        const filtered = prev.filter((avatar) => avatar.id !== created.id);
        return [...filtered, created];
      });
      handleAvatarChange(created.id);
    },
    [handleAvatarChange],
  );

  const handleModelChange = useCallback((newModel: string) => {
    const currentAvatar = avatars.find((avatar) => avatar.id === avatarId) ?? null;
    if (!canChangeModelForAvatar(currentAvatar, newModel)) {
      notify("博士小狗仅支持轻量模式，请先更换形象。", "info");
      return;
    }
    clearSubtitleState();
    setModel(newModel);
    const nextAvatarId = recommendAvatarForModel(avatars, newModel, avatarId);
    if (nextAvatarId !== avatarId) {
      setAvatarId(nextAvatarId);
      writeStoredAvatarId(nextAvatarId, "auto");
    }
    void (async () => {
      const sid = sessionIdRef.current;
      if (sid) {
        await releaseSession(sid);
      }
      resetLiveState();
      setConnection("idle");
    })();
  }, [avatarId, avatars, clearSubtitleState, notify, releaseSession, resetLiveState]);

  useEffect(() => {
    const handlePageHide = () => {
      const sid = sessionIdRef.current;
      if (realtimeRecorderRef.current?.state === "recording") {
        realtimeRecorderRef.current.stop();
      }
      cleanupRealtimeRecordStreams();
      if (sid) {
        void releaseSession(sid, true);
      }
      closePeerConnection();
    };

    window.addEventListener("pagehide", handlePageHide);
    return () => window.removeEventListener("pagehide", handlePageHide);
  }, [cleanupRealtimeRecordStreams, closePeerConnection, releaseSession]);

  useEffect(() => {
    return () => {
      const sid = sessionIdRef.current;
      if (sid) {
        void releaseSession(sid, true);
      }
      closePeerConnection();
    };
  }, [closePeerConnection, releaseSession]);

  const currentAvatar = avatars.find((a) => a.id === avatarId) ?? null;
  const selectedAvatarMaskUrl = selectedScene && currentAvatar?.matting_status === "transparent_ready"
    ? buildApiUrl(`/avatars/${encodeURIComponent(currentAvatar.id)}/preview`)
    : null;
  const sessionConfigLocked = connection === "connecting" || connection === "queued" || connection === "live" || connection === "expiring";
  const effectiveAsrProvider = activeAsrProvider || normalizeAsrProvider(asrProvider, "dashscope");
  const showStart = connection === "idle" || connection === "error" || connection === "connecting" || connection === "queued";
  const effectiveConversationViewMode = showStart ? "studio" : conversationViewMode;
  const immersiveActive = workflow === "realtime" && effectiveConversationViewMode === "immersive";
  const chatMaxVisible = readChatMaxVisible();
  const selectedModelLabel = modelLabel(model);
  const wav2lipPostprocessModeLocked = sessionId !== null && connection !== "idle" && connection !== "error";
  const fasterliveportraitDirty = JSON.stringify(fasterliveportraitConfig) !== JSON.stringify(fasterliveportraitAppliedConfig);
  const fasterliveportraitLive = model === "fasterliveportrait" && sessionId !== null && connection !== "idle" && connection !== "error";
  const selectedVoiceLabel = isEdgeTts(ttsProvider)
    ? EDGE_ZH_VOICES.find((voice) => voice.id === edgeVoice)?.label ?? edgeVoice
    : bailianVoices.find((voice) => voice.id === qwenVoice)?.label ?? (qwenVoice || "暂无音色");
  const runtimeConfigTtsProvider = runtimeConfig?.tts.provider ?? "";
  const runtimeConfigTtsReady = Boolean(
    runtimeConfig?.tts.api_key_set
      || runtimeConfigTtsProvider === "edge"
      || runtimeConfigTtsProvider === "local_cosyvoice"
      || runtimeConfigTtsProvider === "indextts"
      || runtimeConfigTtsProvider === "local_indextts"
      || runtimeConfigTtsProvider === "omnirt_indextts"
      || runtimeConfigTtsProvider === "local_f5_tts",
  );
  const runtimeConfigReady = Boolean(
    runtimeConfig?.llm.api_key_set
      && runtimeConfig.stt.api_key_set
      && runtimeConfigTtsReady
      && runtimeConfig.mem0?.llm.api_key_set
      && runtimeConfig.mem0?.embedder.api_key_set,
  );
  return (
    <div className="min-h-screen bg-slate-100 text-slate-900 lg:h-screen lg:overflow-hidden">
      <audio ref={audioRef} autoPlay playsInline className="hidden" />
      <TopBar
        connection={connection}
        workflow={workflow}
        conversationViewMode={effectiveConversationViewMode}
        immersiveChrome={immersiveActive}
        flashtalkRecording={!!sessionId && (connection === "live" || connection === "expiring")}
        flashtalkRecordPhase={ftRecordPhase}
        flashtalkRecordBusy={ftRecordBusy}
        recordingSaving={recordingSaving}
        runtimeConfigReady={runtimeConfigReady}
        runtimeConfigLoading={runtimeConfigLoading}
        onInactiveModuleClick={(label) => notify(`${label}模块规划中。当前可用的是实时对话、视频克隆、数字人配置、语音驱动和导出能力。`, "info")}
        onConversationViewModeChange={setConversationViewMode}
        onWorkflowChange={(next) => {
          setWorkflow(next);
          if (next === "videoClone" && sessionIdRef.current) {
            notify("视频克隆不会复用当前实时对话链路；如需释放实时会话，请先返回实时对话停止会话。", "info");
          }
        }}
        onFlashtalkRecordStart={() => void handleFtRecordStart()}
        onFlashtalkRecordStop={() => void handleFtRecordStop()}
        onFlashtalkRecordSave={() => void handleFtRecordSave()}
      />

      {voiceCloneOpen ? (
        <>
          <button
            type="button"
            className="fixed inset-0 z-[55] cursor-default bg-slate-900/20 backdrop-blur-[2px]"
            aria-label="关闭音色复刻"
            onClick={() => setVoiceCloneOpen(false)}
          />
          <aside className="pointer-events-none fixed inset-y-0 right-0 z-[56] flex w-[min(100vw,28rem)] shadow-2xl shadow-slate-300/70">
            <div className="pointer-events-auto flex h-full max-h-[100dvh] flex-col overflow-hidden border-l border-slate-200 bg-slate-50">
              <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">
                <BailianVoiceClone
                  onSuccess={applyClonedVoice}
                  onClose={() => setVoiceCloneOpen(false)}
                />
              </div>
            </div>
          </aside>
        </>
      ) : null}

      {expiringCountdown !== null && (
        <div className="fixed right-4 top-16 z-30 flex items-center gap-2 rounded-lg bg-amber-500/95 px-4 py-2.5 text-sm font-medium text-white shadow-lg backdrop-blur-sm">
          <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6l4 2m6-2a10 10 0 1 1-20 0 10 10 0 0 1 20 0z" />
          </svg>
          体验即将到期，剩余 <span className="tabular-nums font-bold">{expiringCountdown}</span> 秒
        </div>
      )}

      {workflow === "assetLibrary" ? (
        <div className="flex min-h-0 lg:h-[calc(100vh-3.5rem)]">
          <AssetLibraryWorkspace
            refreshToken={assetLibraryRefreshKey}
            onNotify={notify}
            initialTab={assetLibraryTab}
            activeTabOverride={assetLibraryTab}
            onActiveTabChange={setAssetLibraryTab}
            memoryCharacterId={currentAvatar?.id ?? null}
            memoryLibraryId={memoryLibraryId}
            memoryEnabled={memoryEnabled}
            memoryLibraries={memoryLibraries}
            profileId={MEMORY_PROFILE_ID}
            onMemoryLibrarySelect={setMemoryLibraryId}
            onMemoryEnabledChange={setMemoryEnabled}
            onMemoryLibrariesChange={setMemoryLibraries}
            onRefreshMemoryLibraries={() => void refreshMemoryLibraries()}
            avatars={avatars}
            selectedSceneIdsByAvatar={selectedSceneIdsByAvatar}
            onSceneSelect={handleSceneSelect}
            onSceneClear={handleSceneClear}
            onSceneBackgroundsChange={setSceneBackgrounds}
            onSceneCompositionsChange={handleSceneCompositionsChange}
          />
        </div>
      ) : workflow === "videoCreation" ? (
        <div className="flex min-h-0 lg:h-[calc(100vh-3.5rem)]">
          <VideoCreationWorkspace
            avatars={avatars}
            avatarId={avatarId}
            sceneBackgrounds={sceneBackgrounds}
            sceneCompositions={sceneCompositions}
            selectedSceneIdsByAvatar={selectedSceneIdsByAvatar}
            models={models}
            onAvatarChange={handleAvatarChange}
            onAvatarUploaded={handleVideoCloneAvatarUploaded}
            onVoiceCloned={applyClonedVoice}
            onExportCreated={() => setAssetLibraryRefreshKey((value) => value + 1)}
            onGoAssetLibrary={() => setWorkflow("assetLibrary")}
            onNotify={notify}
            ttsProvider={ttsProvider}
            onTtsProviderChange={setTtsProvider}
            qwenModel={qwenModel}
            onQwenModelChange={setQwenModel}
            qwenModelOptions={bailianModels}
            qwenVoice={qwenVoice}
            onQwenVoiceChange={setQwenVoice}
            qwenVoiceOptions={bailianVoices}
            edgeVoice={edgeVoice}
            onEdgeVoiceChange={setEdgeVoice}
            voiceCatalog={voiceCatalog}
            fasterliveportraitConfig={videoCreationFasterliveportraitConfig}
            onFasterLivePortraitConfigChange={handleVideoCreationFasterLivePortraitConfigChange}
          />
        </div>
      ) : workflow === "videoClone" ? (
        <div className="flex min-h-0 lg:h-[calc(100vh-3.5rem)]">
          <VideoCloneWorkspace
            avatars={avatars}
            avatarId={avatarId}
            config={fasterliveportraitConfig}
            onAvatarChange={handleAvatarChange}
            onAvatarUploaded={handleVideoCloneAvatarUploaded}
            onConfigChange={handleFasterLivePortraitConfigChange}
            onExportCreated={() => setAssetLibraryRefreshKey((value) => value + 1)}
            onNotify={notify}
          />
        </div>
      ) : workflow === "runtimeConfig" ? (
        <div className="flex min-h-0 lg:h-[calc(100vh-3.5rem)]">
          <RuntimeConfigWorkspace
            runtimeConfig={runtimeConfig}
            runtimeConfigLoading={runtimeConfigLoading}
            runtimeConfigApplying={runtimeConfigApplying}
            onRuntimeConfigRefresh={() => void refreshRuntimeConfig()}
            onRuntimeConfigApply={handleApplyRuntimeConfig}
          />
        </div>
      ) : (
      <div
        className={
          immersiveActive
            ? "relative flex h-dvh min-h-0 flex-col bg-slate-950"
            : "flex min-h-0 flex-col lg:h-[calc(100vh-3.5rem)] lg:flex-row"
        }
      >
        <div className={`${immersiveActive ? "hidden" : "order-2 min-h-0 lg:order-none lg:h-full lg:shrink-0"}`}>
          <SettingsPanel
            expanded={settingsExpanded}
            onExpandedChange={setSettingsExpanded}
            avatars={avatars}
            models={models}
            modelStatuses={modelStatuses}
            avatarId={avatarId}
            model={model}
            modelConnected={selectedModelConnected}
            wav2lipPostprocessMode={wav2lipPostprocessMode}
            wav2lipPostprocessModeLocked={wav2lipPostprocessModeLocked}
            fasterliveportraitConfig={fasterliveportraitConfig}
            fasterliveportraitApplying={fasterliveportraitApplying}
            fasterliveportraitDirty={fasterliveportraitDirty}
            fasterliveportraitLive={fasterliveportraitLive}
            onAvatarChange={handleAvatarChange}
            onModelChange={handleModelChange}
            onWav2LipPostprocessModeChange={setWav2lipPostprocessMode}
            onFasterLivePortraitConfigChange={handleFasterLivePortraitConfigChange}
            onApplyFasterLivePortraitConfig={() => void handleApplyFasterLivePortraitConfig()}
            onResetFasterLivePortraitConfig={handleResetFasterLivePortraitConfig}
            edgeVoice={edgeVoice}
            onEdgeVoiceChange={setEdgeVoice}
            edgeVoiceOptions={EDGE_ZH_VOICES}
            ttsProvider={ttsProvider}
            onTtsProviderChange={setTtsProvider}
            qwenModel={qwenModel}
            onQwenModelChange={setQwenModel}
            qwenModelOptions={bailianModels}
            qwenVoice={qwenVoice}
            onQwenVoiceChange={setQwenVoice}
            qwenVoiceOptions={bailianVoices}
            voiceApplyNotice={voiceApplyNotice}
            ttsPreviewText={ttsPreviewText}
            onTtsPreviewTextChange={setTtsPreviewText}
            onPreviewTts={() => void handlePreviewTts()}
            ttsPreviewing={ttsPreviewing}
            asrProvider={sessionConfigLocked ? effectiveAsrProvider : asrProvider}
            asrModel={asrModel}
            onAsrProviderChange={(provider) => {
              const normalized = normalizeAsrProvider(provider, "dashscope");
              setAsrProvider(normalized);
              setAsrModel(sttModelForProvider(normalized));
            }}
            configLocked={sessionConfigLocked}
            agentConfig={agentConfig}
            onAgentConfigChange={setAgentConfig}
            knowledgeBases={knowledgeBaseSummaries}
            onManageKnowledgeBases={() => void handleManageKnowledgeBases()}
            memoryLibraries={memoryLibraries}
            selectedMemoryLibraryId={memoryLibraryId}
            memoryEnabled={memoryEnabled}
            onMemoryLibrarySelect={setMemoryLibraryId}
            onMemoryEnabledChange={setMemoryEnabled}
            onManageMemoryLibraries={() => void handleManageMemoryLibraries()}
            onOpenVoiceClone={() => setVoiceCloneOpen(true)}
          />
        </div>

        <main
          className={
            immersiveActive
              ? "order-1 flex min-h-0 flex-1 flex-col overflow-hidden bg-slate-950 lg:order-none"
              : "order-1 flex min-h-0 flex-1 flex-col bg-slate-100 lg:order-none"
          }
        >
          <div
            className={
              immersiveActive
                ? "relative flex min-h-0 flex-1 flex-col overflow-hidden"
                : "flex min-h-0 flex-1 flex-col p-4"
            }
          >
            <div
              className={
                immersiveActive
                  ? "absolute inset-x-0 top-0 bottom-12 overflow-hidden bg-black sm:bottom-14"
                  : "relative min-h-[360px] flex-1 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm shadow-slate-200/70 lg:min-h-[420px]"
              }
            >
              <SceneStage
                videoRef={videoRef}
                videoStream={remoteStream}
                scene={showStart ? null : selectedScene}
                backgrounds={sceneBackgrounds}
                subtitle={!showStart ? currentSubtitle : null}
                avatarMaskUrl={showStart ? null : selectedAvatarMaskUrl}
                avatarAdjust={immersiveActive ? immersiveAvatarAdjust : undefined}
                compactSquareStage={compactSquareStage}
                clientRenderer={!showStart && model === "mock" ? currentAvatar?.client_renderer ?? null : null}
                className="h-full w-full"
              >
                {immersiveActive ? (
                  <>
                    <div className="absolute right-0 top-0 z-30 flex h-24 w-48 items-start justify-end p-4">
                      <button
                        type="button"
                        onClick={() => setConversationViewMode("studio")}
                        className="rounded-lg border border-white/15 bg-slate-950/45 px-3 py-2 text-xs font-semibold text-white opacity-0 shadow-lg backdrop-blur transition hover:bg-slate-950/65 hover:opacity-100 focus:opacity-100"
                      >
                        返回工作台
                      </button>
                    </div>
                    <div className="group absolute right-0 top-1/2 z-30 flex -translate-y-1/2 translate-x-[calc(100%-1.25rem)] items-center transition-transform duration-200 hover:translate-x-0 focus-within:translate-x-0">
                      <div className="flex h-20 w-5 items-center justify-center rounded-l-lg border border-r-0 border-slate-700 bg-slate-950 text-[10px] font-semibold text-white shadow-lg">
                        微调
                      </div>
                      <div className="w-64 rounded-l-xl border border-slate-700 bg-slate-950 p-4 text-white shadow-2xl shadow-slate-950/30">
                        <div className="mb-3 flex items-center justify-between gap-3">
                          <p className="text-sm font-semibold">画面微调</p>
                          <button
                            type="button"
                            onClick={() => setImmersiveAvatarAdjust({ x: 0, y: 0, scale: 1 })}
                            className="rounded-md border border-white/15 px-2 py-1 text-xs font-semibold text-white/80 transition hover:bg-white/10 hover:text-white"
                          >
                            重置
                          </button>
                        </div>
                        <label className="mb-3 block text-xs font-medium text-white/80">
                          <span className="mb-1 flex justify-between">
                            <span>水平</span>
                            <span className="tabular-nums">{immersiveAvatarAdjust.x}px</span>
                          </span>
                          <input
                            type="range"
                            min="-480"
                            max="480"
                            step="4"
                            value={immersiveAvatarAdjust.x}
                            onChange={(event) => setImmersiveAvatarAdjust((prev) => ({ ...prev, x: Number(event.target.value) }))}
                            className="w-full accent-cyan-300"
                          />
                        </label>
                        <label className="mb-3 block text-xs font-medium text-white/80">
                          <span className="mb-1 flex justify-between">
                            <span>垂直</span>
                            <span className="tabular-nums">{immersiveAvatarAdjust.y}px</span>
                          </span>
                          <input
                            type="range"
                            min="-320"
                            max="320"
                            step="4"
                            value={immersiveAvatarAdjust.y}
                            onChange={(event) => setImmersiveAvatarAdjust((prev) => ({ ...prev, y: Number(event.target.value) }))}
                            className="w-full accent-cyan-300"
                          />
                        </label>
                        <label className="block text-xs font-medium text-white/80">
                          <span className="mb-1 flex justify-between">
                            <span>缩放</span>
                            <span className="tabular-nums">{immersiveAvatarAdjust.scale.toFixed(2)}x</span>
                          </span>
                          <input
                            type="range"
                            min="0.4"
                            max="2.2"
                            step="0.02"
                            value={immersiveAvatarAdjust.scale}
                            onChange={(event) => setImmersiveAvatarAdjust((prev) => ({ ...prev, scale: Number(event.target.value) }))}
                            className="w-full accent-cyan-300"
                          />
                        </label>
                      </div>
                    </div>
                  </>
                ) : (
                  <div className="absolute left-4 right-4 top-4 z-30 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                    <div className="flex min-w-0 flex-wrap gap-2">
                      <span className="inline-flex items-center gap-1 rounded-full border border-white/15 bg-white/90 px-2.5 py-1 text-xs font-medium text-slate-700 shadow-sm">
                        <span className={`h-1.5 w-1.5 rounded-full ${
                          connection === "live" || connection === "expiring" ? "bg-emerald-500" : "bg-slate-400"
                        }`} />
                        {connection === "live" || connection === "expiring" ? "已连接" : "待启动"}
                      </span>
                      <span className="inline-flex items-center gap-1 rounded-full border border-cyan-200 bg-cyan-50 px-2.5 py-1 text-xs font-medium text-cyan-700 shadow-sm">
                        WebRTC 舞台
                      </span>
                      <span className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-600 shadow-sm">
                        {modelLabel(model)}
                      </span>
                      <span className="inline-flex max-w-[14rem] items-center gap-1 truncate rounded-full border border-slate-200 bg-white/90 px-2.5 py-1 text-xs font-medium text-slate-600 shadow-sm">
                        {currentAvatar?.name ?? currentAvatar?.id ?? "未选形象"}
                      </span>
                    </div>
                    <button
                      type="button"
                      onClick={handleReturnToAvatarSelection}
                      className="shrink-0 rounded-lg border border-slate-200 bg-white/95 px-3 py-2 text-xs font-semibold text-slate-700 shadow-sm transition hover:border-cyan-200 hover:text-cyan-700"
                    >
                      更换形象
                    </button>
                  </div>
                )}
              </SceneStage>

              {showStart ? (
                <div className="absolute inset-0 z-40 bg-white">
                  <AvatarSelectionStage
                    avatars={avatars}
                    selectedAvatar={currentAvatar}
                    selectedModelLabel={selectedModelLabel}
                    selectedVoiceLabel={selectedVoiceLabel}
                    loading={connection === "connecting"}
                    queued={connection === "queued"}
                    modelConnected={selectedModelConnected}
                    modelBadge={selectedModelBadge}
                    queueInfo={queueInfo}
                    prewarmState={selectedPrewarmState}
                    personas={personas}
                    selectedPersonaId={selectedPersonaId}
                    personaImporting={personaImporting}
                    onPersonaChange={handlePersonaChange}
                    onPersonaImport={handlePersonaImport}
                    onAvatarChange={handleAvatarChange}
                    onStart={() => void handleStart()}
                    onCustomAvatarCreate={(file, name, options) => handleCreateCustomAvatar(file, name, options)}
                    onAvatarDelete={(target) => void handleDeleteAvatar(target)}
                    referenceSaving={referenceSaving}
                  />
                </div>
              ) : null}
            </div>

            {connection === "live" || connection === "expiring" ? (
            <div
              className={
                immersiveActive
                  ? "group absolute inset-x-3 bottom-0 z-30 mx-auto max-w-4xl translate-y-[calc(100%-1.25rem)] pb-3 transition-transform duration-200 hover:translate-y-0 focus-within:translate-y-0 sm:pb-5"
                  : "mt-4"
              }
            >
              {immersiveActive ? (
                <div className="pointer-events-none mb-2 flex justify-center opacity-100 transition-opacity duration-150 group-hover:opacity-0 group-focus-within:opacity-0">
                  <div className="h-1.5 w-16 rounded-full bg-white/80 shadow-sm" />
                </div>
              ) : null}
              <ChatInput
                onSend={handleSend}
                onSpeakAudio={handleSpeakAudio}
                onSpeakFlashtalkAudioFile={
                  isFlashRenderer(model) ? handleSpeakFlashtalkAudioFile : undefined
                }
                streamingAsrSessionId={sessionId}
                onSpeakAudioStreamResult={handleSpeakAudioStreamResult}
                onSpeakAudioStreamError={handleSpeakAudioStreamError}
                onInterrupt={handleInterrupt}
                isSpeaking={isSpeaking}
                disabled={connection !== "live" && connection !== "expiring"}
                onNotify={notify}
                onOpenSettings={() => setSettingsExpanded(true)}
                ttsProvider={ttsProvider}
                sttProvider={activeAsrProvider}
                edgeVoice={edgeVoice}
                qwenModel={qwenModel}
                qwenVoice={qwenVoice}
              />
            </div>
            ) : null}
          </div>
        </main>

        <aside
          className={
            immersiveActive
              ? "hidden"
              : `order-3 min-h-0 overflow-hidden border-l border-slate-200 bg-white transition-[width] duration-200 lg:shrink-0 ${
                  sessionPanelCollapsed ? "lg:w-12" : "lg:w-[360px]"
                }`
          }
        >
          <div className="flex h-full min-h-0">
            <div className="flex w-12 shrink-0 flex-col items-center justify-center gap-4 border-r border-slate-100 bg-slate-50 py-3">
              <button
                type="button"
                onClick={() => setSessionPanelCollapsed((prev) => !prev)}
                aria-label={sessionPanelCollapsed ? "展开会话面板" : "折叠会话面板"}
                className="flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-600 shadow-sm transition hover:border-cyan-200 hover:text-cyan-700"
              >
                <svg
                  className={`h-4 w-4 transition-transform ${sessionPanelCollapsed ? "rotate-180" : ""}`}
                  viewBox="0 0 20 20"
                  fill="currentColor"
                  aria-hidden
                >
                  <path d="M12.7 4.3a1 1 0 0 1 0 1.4L8.41 10l4.3 4.3a1 1 0 0 1-1.42 1.4l-5-5a1 1 0 0 1 0-1.4l5-5a1 1 0 0 1 1.42 0z" />
                </svg>
              </button>
              <span className="[writing-mode:vertical-rl] text-xs font-semibold tracking-normal text-slate-500">
                会话面板
              </span>
            </div>
            <div className={`${sessionPanelCollapsed ? "hidden" : "flex"} min-w-0 flex-1 flex-col`}>
              <div className="border-b border-slate-200 px-4 pt-4">
                <p className="text-xs font-medium text-slate-500">会话面板</p>
                <div className="mt-3 grid grid-cols-3 gap-1 rounded-lg bg-slate-100 p-1">
                  {PANEL_TABS.map((tab) => (
                    <button
                      key={tab.id}
                      type="button"
                      onClick={() => setPanelTab(tab.id)}
                      className={`rounded-md px-2 py-1.5 text-xs font-medium ${
                        panelTab === tab.id ? "bg-white text-cyan-700 shadow-sm" : "text-slate-500 hover:text-slate-800"
                      }`}
                    >
                      {tab.label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="h-[22rem] overflow-y-auto p-4 lg:h-[calc(100%-5.75rem)]">
                {panelTab === "chat" ? (
                  <ChatMessages messages={messages} maxVisible={chatMaxVisible} />
                ) : null}
                {panelTab === "status" ? (
                  <div className="space-y-3">
                    {[
                      ["连接状态", connection === "live" ? "已连接" : connection === "expiring" ? "即将到期" : connection === "queued" ? "排队中" : connection === "connecting" ? "连接中" : connection === "error" ? "连接错误" : "未连接"],
                      ["当前会话", sessionId ?? "未创建"],
                      ["数字人", currentAvatar?.name ?? currentAvatar?.id ?? "等待加载"],
                      ["驱动模型", modelLabel(model)],
                      ["语音线路", ttsProvider],
                      ["排队信息", queueInfo ? `${queueInfo.position} · ${queueInfo.message}` : "无排队"],
                    ].map(([label, value]) => (
                      <div key={label} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                        <p className="text-xs font-medium text-slate-500">{label}</p>
                        <p className="mt-1 break-words text-sm font-semibold text-slate-900">{value}</p>
                      </div>
                    ))}
                  </div>
                ) : null}
                {panelTab === "exports" ? (
                  <div className="space-y-3">
                    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                      <p className="text-sm font-semibold text-slate-900">实时录制</p>
                      <p className="mt-1 text-xs leading-relaxed text-slate-500">
                        当前状态：{ftRecordPhase === "idle" ? "未录制" : ftRecordPhase === "recording" ? "录制中" : "待保存"}
                      </p>
                    </div>
                    <div className="rounded-lg border border-cyan-200 bg-cyan-50 p-3 text-xs leading-relaxed text-cyan-800">
                      音频驱动数字人会话连接后，可在顶部使用录制保存当前实时画面。
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        </aside>
      </div>
      )}
      <ToastStack toasts={toasts} onDismiss={dismissToast} onPause={pauseToast} onResume={resumeToast} />
    </div>
  );
}
