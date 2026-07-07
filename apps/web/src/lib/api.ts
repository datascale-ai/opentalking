import type { MemoryItem, MemoryLibrary, MemoryTurn, WeChatImportCommitResult, WeChatImportJob } from "../types";

export const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

export function buildApiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

export function buildApiDownloadUrl(path: string): string {
  return buildApiUrl(path);
}

/** WebSocket：相对 ``/api`` 走当前页 host；绝对 ``VITE_API_BASE`` 时与 HTTP 同机（与主仓一致） */
export function buildWsUrl(path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  if (typeof window === "undefined") {
    return `ws://127.0.0.1:5173${API_BASE}${p}`;
  }
  try {
    const baseUrl = new URL(API_BASE, window.location.origin);
    const wsProto = baseUrl.protocol === "https:" ? "wss:" : "ws:";
    return `${wsProto}//${baseUrl.host}${baseUrl.pathname}${p}`;
  } catch {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}${API_BASE}${p}`;
  }
}

/** Rich error type so callers can show the FastAPI {"detail": "..."} message. */
export class ApiError extends Error {
  status: number;
  detail: string | null;
  body: string;
  constructor(status: number, detail: string | null, body: string) {
    super(detail || `HTTP ${status}: ${body}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.body = body;
  }
}

async function throwIfNotOk(r: Response): Promise<void> {
  if (r.ok) return;
  const body = await r.text();
  let detail: string | null = null;
  try {
    const parsed = JSON.parse(body);
    if (typeof parsed?.detail === "string") {
      detail = parsed.detail;
    } else if (Array.isArray(parsed?.detail)) {
      // FastAPI validation errors arrive as a list of {loc, msg, ...}
      detail = parsed.detail
        .map((d: { msg?: string }) => d?.msg ?? JSON.stringify(d))
        .join("; ");
    } else if (parsed?.detail != null) {
      detail = JSON.stringify(parsed.detail);
    }
  } catch {
    // body wasn't JSON; leave detail null
  }
  throw new ApiError(r.status, detail, body);
}

export async function apiGet<T>(path: string): Promise<T> {
  const r = await fetch(buildApiUrl(path));
  await throwIfNotOk(r);
  return r.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(buildApiUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  await throwIfNotOk(r);
  return r.json() as Promise<T>;
}

export async function apiPut<T, B = unknown>(path: string, body?: B): Promise<T> {
  const r = await fetch(buildApiUrl(path), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  await throwIfNotOk(r);
  return r.json() as Promise<T>;
}

export async function apiPostBlob(path: string, body?: unknown): Promise<Blob> {
  const r = await fetch(buildApiUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  await throwIfNotOk(r);
  return r.blob();
}

export async function apiPostFormBlob(path: string, form: FormData, init?: RequestInit): Promise<Blob> {
  const r = await fetch(buildApiUrl(path), { method: "POST", body: form, ...init });
  await throwIfNotOk(r);
  return r.blob();
}

/** multipart/form-data（语音识别 speak_audio / transcribe） */
export async function apiPostForm<T>(path: string, form: FormData, init?: RequestInit): Promise<T> {
  const r = await fetch(buildApiUrl(path), { method: "POST", body: form, ...init });
  await throwIfNotOk(r);
  return r.json() as Promise<T>;
}

export async function apiUploadFile<T>(path: string, fieldName: string, file: File): Promise<T> {
  const form = new FormData();
  form.set(fieldName, file);
  return apiPostForm<T>(path, form);
}

export type RuntimeConfigLlm = {
  base_url: string;
  model: string;
  api_key_set: boolean;
};

export type RuntimeConfigStt = {
  provider: string;
  enabled_providers: string[];
  base_url: string;
  model: string;
  api_key_set: boolean;
  service_url_set: boolean;
};

export type RuntimeConfigTts = {
  provider: string;
  enabled_providers: string[];
  base_url: string;
  model: string;
  voice: string;
  api_key_set: boolean;
  service_url_set: boolean;
};

export type RuntimeConfigMem0Model = {
  provider: string;
  base_url: string;
  model: string;
  api_key_set: boolean;
};

export type RuntimeConfigMem0 = {
  llm: RuntimeConfigMem0Model;
  embedder: RuntimeConfigMem0Model;
};

export type RuntimeConfigResponse = {
  llm: RuntimeConfigLlm;
  stt: RuntimeConfigStt;
  tts: RuntimeConfigTts;
  mem0: RuntimeConfigMem0;
  applied?: boolean;
  requires_new_session?: boolean;
  live_runners_refreshed?: number;
};

export type RuntimeConfigApplyInput = {
  llm_base_url?: string;
  llm_model?: string;
  llm_api_key?: string;
  stt_provider?: string;
  stt_base_url?: string;
  stt_model?: string;
  stt_api_key?: string;
  tts_provider?: string;
  tts_base_url?: string;
  tts_model?: string;
  tts_voice?: string;
  tts_api_key?: string;
  mem0_llm_provider?: string;
  mem0_llm_base_url?: string;
  mem0_llm_api_key?: string;
  mem0_llm_model?: string;
  mem0_embedder_provider?: string;
  mem0_embedder_base_url?: string;
  mem0_embedder_api_key?: string;
  mem0_embedder_model?: string;
  sync_dashscope_api_key?: boolean;
};

export async function loadRuntimeConfig(): Promise<RuntimeConfigResponse> {
  return apiGet<RuntimeConfigResponse>("/runtime-config");
}

export async function applyRuntimeConfig(input: RuntimeConfigApplyInput): Promise<RuntimeConfigResponse> {
  return apiPost<RuntimeConfigResponse>("/runtime-config/apply", input);
}

export type ExportVideoKind = "realtime_dialogue" | "video_clone" | "video_creation";

export type ExportVideoItem = {
  id: string;
  kind: ExportVideoKind;
  title: string;
  duration_sec: number | null;
  size_bytes: number;
  mime_type: string;
  created_at: string;
  path: string;
  download_url: string;
  session_id: string | null;
  avatar_id: string | null;
  model: string | null;
};

export type UploadExportVideoInput = {
  blob: Blob;
  kind: ExportVideoKind;
  title: string;
  durationSec?: number | null;
  sessionId?: string | null;
  avatarId?: string | null;
  model?: string | null;
};

export function exportVideoExtensionForMimeType(mimeType: string): ".mp4" | ".webm" {
  const normalized = mimeType.split(";", 1)[0].trim().toLowerCase();
  if (normalized === "video/mp4") return ".mp4";
  if (normalized === "video/webm") return ".webm";
  return ".webm";
}

export async function uploadExportVideo(input: UploadExportVideoInput): Promise<ExportVideoItem> {
  const form = new FormData();
  form.set("file", input.blob, `${input.kind}${exportVideoExtensionForMimeType(input.blob.type)}`);
  form.set("kind", input.kind);
  form.set("title", input.title);
  if (input.durationSec != null) form.set("duration_sec", String(input.durationSec));
  if (input.sessionId) form.set("session_id", input.sessionId);
  if (input.avatarId) form.set("avatar_id", input.avatarId);
  if (input.model) form.set("model", input.model);
  return apiPostForm<ExportVideoItem>("/exports/videos", form);
}

export type SceneBackgroundAsset = {
  id: string;
  name: string;
  kind: "image" | "video";
  mime_type: string;
  filename: string;
  size_bytes: number;
  url: string;
  created_at: string;
};

export type SceneComposition = {
  id: string;
  name: string;
  avatar_id: string;
  background_id: string | null;
  background_color: string;
  avatar_fit: "contain" | "cover";
  avatar_scale: number;
  avatar_anchor: "center" | "bottom" | "left" | "right";
  matting_required: boolean;
  subtitle_style: "none" | "compact" | "lower-third";
  created_at: string;
  updated_at: string;
};

export type CreateSceneCompositionInput = {
  name: string;
  avatar_id: string;
  background_id?: string | null;
  background_color?: string;
  avatar_fit?: "contain" | "cover";
  avatar_scale?: number;
  avatar_anchor?: "center" | "bottom" | "left" | "right";
  matting_required?: boolean;
  subtitle_style?: "none" | "compact" | "lower-third";
};

export async function listSceneBackgrounds(): Promise<{ items: SceneBackgroundAsset[] }> {
  return apiGet<{ items: SceneBackgroundAsset[] }>("/scene-assets/backgrounds");
}

export async function uploadSceneBackground(input: { file: File; name: string }): Promise<SceneBackgroundAsset> {
  const form = new FormData();
  form.set("file", input.file);
  form.set("name", input.name);
  return apiPostForm<SceneBackgroundAsset>("/scene-assets/backgrounds", form);
}

export async function deleteSceneBackground(backgroundId: string): Promise<{ id: string; deleted: boolean }> {
  return apiDelete<{ id: string; deleted: boolean }>(`/scene-assets/backgrounds/${encodeURIComponent(backgroundId)}`);
}

export async function listSceneCompositions(): Promise<{ items: SceneComposition[] }> {
  return apiGet<{ items: SceneComposition[] }>("/scene-assets/compositions");
}

export async function createSceneComposition(input: CreateSceneCompositionInput): Promise<SceneComposition> {
  return apiPost<SceneComposition>("/scene-assets/compositions", input);
}

export async function deleteSceneComposition(compositionId: string): Promise<{ id: string; deleted: boolean }> {
  return apiDelete<{ id: string; deleted: boolean }>(`/scene-assets/compositions/${encodeURIComponent(compositionId)}`);
}


export type VideoCreationAudioSource = "upload" | "tts_text" | "voice_clone" | "duo_dialog" | "reference_video";

export type IndexTTSEmotionMode = "voice" | "text" | "vector" | "audio";

export type IndexTTSConfig = {
  emotion_mode: IndexTTSEmotionMode;
  emo_alpha?: number;
  emo_audio_prompt?: string;
  emo_text?: string;
  emo_vector?: number[];
  use_random?: boolean;
  interval_silence_ms?: number;
  streaming_mode?: "segment" | "token_window";
  max_text_tokens_per_segment?: number;
  quick_streaming_tokens?: number;
};

export type PersonMode = "single" | "double";

export type DuoDialogRole = "left" | "right";

export type DuoDialogLine = {
  id: string;
  role: DuoDialogRole;
  text: string;
};

export type DuoDialogSpeakerTTS = {
  tts_provider?: string;
  tts_model?: string;
  voice?: string;
  indextts_config?: IndexTTSConfig;
};

export type DuoDialogRequest = {
  lines: DuoDialogLine[];
  voices?: Record<DuoDialogRole, string>;
  speakers?: Record<DuoDialogRole, DuoDialogSpeakerTTS>;
  gap_ms?: number;
};

export type DuoDialogCapability = {
  speaker_faces: Record<string, string>;
  default_voices: Partial<Record<DuoDialogRole, string>>;
};

export type VideoCreationJobResponse = {
  job_id: string;
  status: "done" | "error" | string;
  source?: VideoCreationAudioSource | string;
  export_video: ExportVideoItem;
};

export type VideoCreationCompositionConfig = {
  scene_composition_id?: string | null;
  background_id?: string | null;
  background_color?: string;
  avatar_fit?: "contain" | "cover";
  avatar_anchor?: "center" | "bottom" | "left" | "right";
  avatar_scale?: number;
  avatar_offset_x?: number;
  avatar_offset_y?: number;
  output_width?: number;
  output_height?: number;
};

export type CreateVideoCreationJobInput = {
  model: string;
  avatarId: string;
  title?: string;
  audioSource: VideoCreationAudioSource;
  audioFile?: File | null;
  text?: string;
  ttsProvider?: string;
  ttsModel?: string;
  voice?: string;
  durationSec?: number;
  fasterliveportraitConfig?: Record<string, unknown>;
  indexttsConfig?: IndexTTSConfig;
  indexttsEmotionAudioFile?: File | null;
  duoDialog?: DuoDialogRequest;
  compositionConfig?: VideoCreationCompositionConfig | null;
};

export async function createVideoCreationJob(input: CreateVideoCreationJobInput): Promise<VideoCreationJobResponse> {
  const form = new FormData();
  form.set("model", input.model);
  form.set("avatar_id", input.avatarId);
  form.set("audio_source", input.audioSource);
  if (input.title) form.set("title", input.title);
  if (input.audioSource === "upload" && input.audioFile) {
    form.set("audio_file", input.audioFile);
  }
  if (input.text) form.set("text", input.text);
  if (input.ttsProvider) form.set("tts_provider", input.ttsProvider);
  if (input.ttsModel) form.set("tts_model", input.ttsModel);
  if (input.voice) form.set("voice", input.voice);
  if (input.durationSec != null) {
    form.set("duration_sec", String(input.durationSec));
  }
  if (input.fasterliveportraitConfig) {
    form.set("fasterliveportrait_config", JSON.stringify(input.fasterliveportraitConfig));
  }
  if (input.indexttsConfig) {
    form.set("indextts_config", JSON.stringify(input.indexttsConfig));
  }
  if (input.indexttsEmotionAudioFile) {
    form.set("indextts_emotion_audio_file", input.indexttsEmotionAudioFile);
  }
  if (input.duoDialog) {
    form.set("duo_dialog", JSON.stringify(input.duoDialog));
  }
  if (input.compositionConfig) {
    form.set("composition_config", JSON.stringify(input.compositionConfig));
  }
  return apiPostForm<VideoCreationJobResponse>("/video-creation/jobs", form);
}

export async function apiDelete<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(buildApiUrl(path), { ...init, method: "DELETE" });
  await throwIfNotOk(r);
  return r.json() as Promise<T>;
}

export type KnowledgeDocument = {
  id: string;
  kb_id: string;
  filename: string;
  mime_type: string;
  bytes: number;
  sha256: string;
  status: "ready" | "error" | string;
  error: string | null;
  chunk_count: number;
  created_at: string;
  updated_at: string;
};

export type KnowledgeDocumentsResponse = {
  documents: KnowledgeDocument[];
};

export type KnowledgeBaseSummary = {
  id: string;
  name: string;
  document_count: number;
  ready_document_count: number;
  error_document_count: number;
  created_at: string;
  updated_at: string;
};

export type KnowledgeBasesResponse = {
  knowledge_bases?: (string | KnowledgeBaseSummary)[];
  knowledge_base_summaries?: KnowledgeBaseSummary[];
};

export type AvatarKnowledgeBasesResponse = {
  avatar_id?: string;
  knowledge_base_ids?: string[];
  knowledge_base_summaries?: KnowledgeBaseSummary[];
};

export type AvatarKnowledgeBasesRequest = {
  knowledge_base_ids: string[];
};

export type SessionKnowledgeBasesRequest = {
  knowledge_base_ids: string[];
};

export type SessionKnowledgeBasesResponse = {
  session_id: string;
  knowledge_base_ids: string[];
};

export type CreateSessionRequest = {
  persona_id?: string;
  avatar_id?: string;
  model?: string;
  llm_system_prompt?: string;
  tts_provider: string;
  stt_provider: string;
  tts_voice?: string;
  tts_model?: string;
  wav2lip_postprocess_mode?: string;
  fasterliveportrait_config?: Record<string, unknown>;
  user_id: string;
  agent_enabled: boolean;
  memory_enabled: boolean;
  memory_profile_id?: string;
  character_id?: string;
  memory_library_id?: string;
  knowledge_enabled: boolean;
  knowledge_base_id: string;
  knowledge_base_ids: string[];
};

export type PersonaSummary = {
  schema_version: string;
  id: string;
  name: string;
  description: string;
  locale: string;
  avatar: {
    id: string;
    model: string;
    path?: string | null;
  };
  voice: {
    provider?: string | null;
    voice_id?: string | null;
    model?: string | null;
  };
  agent: {
    system_prompt?: string | null;
    style_prompt?: string | null;
    memory_enabled: boolean;
    knowledge_enabled: boolean;
    knowledge_base_ids: string[];
  };
  runtime: {
    stt_provider?: string | null;
    tts_provider?: string | null;
    preferred_backend?: string | null;
  };
  safety: {
    authorized_avatar: boolean;
    authorized_voice: boolean;
    content_label_required: boolean;
  };
  created_at: string;
  updated_at: string;
  source: string;
};

export type PersonasResponse = {
  personas: PersonaSummary[];
};

export type AvatarSummary = {
  id: string;
  name: string | null;
  model_type: string;
  width: number;
  height: number;
  person_mode: PersonMode;
  is_custom: boolean;
  has_preview_video: boolean;
  matting_status: "unknown" | "opaque" | "transparent_ready";
  duo_dialog: DuoDialogCapability | null;
};

export type CreateSessionResponse = { session_id: string; status: string };

function memoryQuery(profileId: string, characterId: string): string {
  const qs = new URLSearchParams({ profile_id: profileId, character_id: characterId });
  return qs.toString();
}

export function getMemoryLibraries(profileId: string, characterId: string): Promise<{ items: MemoryLibrary[] }> {
  return apiGet(`/memory/libraries?${memoryQuery(profileId, characterId)}`);
}

export function createMemoryLibrary(body: {
  id?: string;
  name?: string;
  profile_id?: string;
  character_id: string;
}): Promise<MemoryLibrary> {
  return apiPost("/memory/libraries", body);
}

export function getMemoryItems(
  libraryId: string,
  profileId: string,
  characterId: string,
): Promise<{ items: MemoryItem[] }> {
  return apiGet(`/memory/libraries/${encodeURIComponent(libraryId)}/items?${memoryQuery(profileId, characterId)}`);
}

export function deleteMemoryItem(
  libraryId: string,
  itemId: string,
  profileId: string,
  characterId: string,
): Promise<{ deleted: true }> {
  return apiDelete(
    `/memory/libraries/${encodeURIComponent(libraryId)}/items/${encodeURIComponent(itemId)}?${memoryQuery(
      profileId,
      characterId,
    )}`,
  );
}

export function importMemoryTurns(
  libraryId: string,
  body: {
    profile_id?: string;
    character_id: string;
    turns: MemoryTurn[];
    source?: string;
  },
): Promise<{ imported: number }> {
  return apiPost(`/memory/libraries/${encodeURIComponent(libraryId)}/import`, body);
}

export function uploadWeChatImport(
  file: File,
  body: {
    profileId?: string;
    memoryLibraryId?: string;
    avatarId: string;
    avatarModel?: string;
    characterId?: string;
    targetSpeakerId?: string;
    sourceFormat?: string;
    timezone?: string;
  },
): Promise<WeChatImportJob> {
  const form = new FormData();
  form.set("file", file);
  form.set("profile_id", body.profileId || "default");
  form.set("memory_library_id", body.memoryLibraryId || "default");
  form.set("avatar_id", body.avatarId);
  form.set("avatar_model", body.avatarModel || "mock");
  if (body.characterId) form.set("character_id", body.characterId);
  if (body.targetSpeakerId) form.set("target_speaker_id", body.targetSpeakerId);
  if (body.sourceFormat) form.set("source_format", body.sourceFormat);
  if (body.timezone) form.set("timezone", body.timezone);
  return apiPostForm<WeChatImportJob>("/memory/wechat-import", form);
}

export function selectWeChatImportSpeaker(jobId: string, targetSpeakerId: string): Promise<WeChatImportJob> {
  return apiPost(`/memory/wechat-import/${encodeURIComponent(jobId)}/speaker`, {
    target_speaker_id: targetSpeakerId,
  });
}

export function commitWeChatImportJob(
  jobId: string,
  body: { personaId: string; personaName?: string; description?: string },
): Promise<WeChatImportCommitResult> {
  return apiPost(`/memory/wechat-import/${encodeURIComponent(jobId)}/commit`, {
    persona_id: body.personaId,
    persona_name: body.personaName,
    description: body.description,
  });
}

/** GET /voices 返回的音色目录项（含 SQLite 中的系统预设与复刻） */
export type VoiceCatalogItem = {
  id: number;
  user_id: number;
  provider: string;
  voice_id: string;
  display_label: string;
  target_model: string | null;
  source: "system" | "clone" | string;
};
