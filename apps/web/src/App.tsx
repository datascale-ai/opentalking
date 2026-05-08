import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import { AvatarSelectionStage } from "./components/AvatarSelectionStage";
import { BailianVoiceClone } from "./components/BailianVoiceClone";
import { ChatInput } from "./components/ChatInput";
import { ChatMessages } from "./components/ChatMessages";
import { SETTINGS_DOCK_EXPANDED_KEY, SettingsPanel } from "./components/SettingsPanel";
import { TopBar } from "./components/TopBar";
import { ToastStack, type ToastMessage, type ToastTone } from "./components/ToastStack";
import { VideoBackground } from "./components/VideoBackground";
import {
  apiDelete,
  apiGet,
  apiPost,
  apiPostForm,
  buildApiUrl,
  type AvatarSummary,
  type CreateSessionResponse,
  type VoiceCatalogItem,
} from "./lib/api";
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
  SAMBERT_MODEL_OPTIONS,
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
import type { ConnectionStatus, Message, QueueInfo } from "./types";

function bailianModelOptions(provider: TtsProviderExtended): { id: string; label: string }[] {
  switch (provider) {
    case "dashscope":
      return QWEN_TTS_MODEL_OPTIONS;
    case "cosyvoice":
      return COSYVOICE_MODEL_OPTIONS;
    case "sambert":
      return SAMBERT_MODEL_OPTIONS;
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
    default:
      return [];
  }
}

function catalogProviderKey(p: TtsProviderExtended): string | null {
  if (p === "dashscope") return "dashscope";
  if (p === "cosyvoice") return "cosyvoice";
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
  const cloneModelIds = new Set(QWEN_VOICE_CLONE_TARGET_OPTIONS.map((o) => o.id));
  const cloneOnly = ttsProvider === "dashscope" && cloneModelIds.has(activeModel ?? "");
  const baseList = cloneOnly ? [] : staticList;
  const staticIds = new Set(baseList.map((s) => s.id));
  const extras: VoiceOpt[] = [];
  for (const r of catalog) {
    if (r.provider !== cp) continue;
    if (activeModel && r.target_model && r.target_model !== activeModel) continue;
    if (cloneOnly && r.source !== "clone") continue;
    if (staticIds.has(r.voice_id)) continue;
    extras.push({
      id: r.voice_id,
      label: r.source === "clone" ? `复刻 · ${r.display_label}` : r.display_label,
      targetModel: r.target_model,
    });
    staticIds.add(r.voice_id);
  }
  return [...baseList.map((s) => ({ id: s.id, label: s.label })), ...extras];
}

const MESSAGE_STORAGE_KEY = "opentalking-chat-history";
const LLM_SYSTEM_PROMPT_STORAGE_KEY = "opentalking-llm-system-prompt";
const SESSION_PANEL_COLLAPSED_KEY = "opentalking-session-panel-collapsed";
const CUSTOM_REFERENCE_NAME_KEY = "opentalking-custom-reference-name";

type SpeakAudioResponse = { session_id: string; status: string; text: string };
type SessionRecord = { session_id: string; state?: string };

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
): AvatarSummary | null {
  if (!avatars.length) return null;
  const available = new Set(registeredModels);
  // Prefer QuickTalk for the OpenTalking V3 demo, then fall back to the other demos.
  return (
    avatars.find((a) => a.id === "quicktalk-daytime" && available.has("quicktalk")) ??
    avatars.find((a) => a.model_type === "quicktalk" && available.has("quicktalk")) ??
    avatars.find((a) => a.model_type === "flashhead" && available.has("flashhead")) ??
    avatars.find((a) => a.model_type === "flashtalk" && available.has("flashtalk")) ??
    avatars.find((a) => a.model_type === "musetalk" && available.has("musetalk")) ??
    avatars.find((a) => available.has(a.model_type)) ??
    avatars[0]
  );
}

function isFlashRenderer(model: string): boolean {
  return model === "flashtalk" || model === "flashhead";
}

function usesCompactSquareStage(model: string): boolean {
  return model === "flashhead";
}

const MODEL_LABELS_FOR_STAGE: Record<string, string> = {
  flashhead: "FlashHead",
  flashtalk: "FlashTalk",
  musetalk: "MuseTalk",
  quicktalk: "QuickTalk",
  wav2lip: "Wav2Lip",
};

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export default function App() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const sessionIdRef = useRef<string | null>(null);
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
  const [avatarId, setAvatarId] = useState("demo-avatar");
  const [model, setModel] = useState("wav2lip");

  // Connection
  const [connection, setConnection] = useState<ConnectionStatus>("idle");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [queueInfo, setQueueInfo] = useState<QueueInfo | null>(null);
  const [expiringCountdown, setExpiringCountdown] = useState<number | null>(null);

  // Chat
  const [messages, setMessages] = useState<Message[]>([]);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [currentSubtitle, setCurrentSubtitle] = useState("");

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
  const [promptSaving, setPromptSaving] = useState(false);
  const [referenceSaving, setReferenceSaving] = useState(false);
  const [referenceImageFile, setReferenceImageFile] = useState<File | null>(null);
  const [panelTab, setPanelTab] = useState<PanelTab>("chat");
  const [sessionPanelCollapsed, setSessionPanelCollapsed] = useState(() => {
    try {
      return window.localStorage.getItem(SESSION_PANEL_COLLAPSED_KEY) === "1";
    } catch {
      return false;
    }
  });
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const [recordingSaving, setRecordingSaving] = useState(false);
  const [ftRecordPhase, setFtRecordPhase] = useState<"idle" | "recording" | "stopped">("idle");
  const [ftRecordBusy, setFtRecordBusy] = useState(false);
  const [offlineBundleBusy, setOfflineBundleBusy] = useState(false);
  const offlineBundleInputRef = useRef<HTMLInputElement>(null);
  const [voiceCatalog, setVoiceCatalog] = useState<VoiceCatalogItem[]>([]);
  const [voiceApplyNotice, setVoiceApplyNotice] = useState<string | null>(null);
  const [ttsPreviewText, setTtsPreviewText] = useState(DEFAULT_TTS_PREVIEW_TEXT);
  const [ttsPreviewing, setTtsPreviewing] = useState(false);
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
      if (s === "edge" || s === "dashscope" || s === "cosyvoice" || s === "sambert") return s;
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

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
  }, []);

  const notify = useCallback((message: string, tone: ToastTone = "info") => {
    const id = makeToastId();
    setToasts((prev) => [...prev.slice(-2), { id, tone, message }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((toast) => toast.id !== id));
    }, tone === "error" ? 5200 : 3600);
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem(SESSION_PANEL_COLLAPSED_KEY, sessionPanelCollapsed ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [sessionPanelCollapsed]);

  const [llmSystemPrompt, setLlmSystemPrompt] = useState<string>(() => {
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
      setIsSpeaking(false);
      setQueueInfo(null);
      setExpiringCountdown(null);
      slotAcquiredRef.current = null;
      subtitleAccRef.current = "";
      subtitleMediaReadyRef.current = false;
      clearSubtitleFallbackTimer();
      streamingAssistantMsgIdRef.current = null;
      pendingAssistantMsgIdRef.current = null;
      if (clearMessages) {
        setMessages([]);
      }
    },
    [clearSubtitleFallbackTimer, closePeerConnection],
  );

  // ---------- Init: fetch avatars & models ----------
  useEffect(() => {
    void (async () => {
      try {
        const [av, mo] = await Promise.all([
          apiGet<AvatarSummary[]>("/avatars"),
          apiGet<{ models: string[] }>("/models"),
          loadVoices(),
        ]);
        setAvatars(av);
        setModels(mo.models);
        const initialAvatar = pickInitialAvatar(av, mo.models);
        if (initialAvatar) {
          setAvatarId(initialAvatar.id);
          setModel((prev) => (mo.models.includes(prev) ? prev : initialAvatar.model_type));
        }
      } catch {
        setConnection("error");
      }
    })();
  }, [loadVoices]);

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
        setIsSpeaking(false);
        subtitleAccRef.current = "";
        const orphanId = streamingAssistantMsgIdRef.current;
        const pendingId = pendingAssistantMsgIdRef.current;
        streamingAssistantMsgIdRef.current = null;
        pendingAssistantMsgIdRef.current = null;
        if (orphanId || pendingId) {
          const removeIds = new Set([orphanId, pendingId].filter(Boolean));
          setMessages((prev) => prev.filter((m) => !removeIds.has(m.id)));
        }
      }
      if (ev === "error") {
        setIsSpeaking(false);
        clearSubtitleFallbackTimer();
        const d = data && typeof data === "object" ? (data as { message?: string; code?: string }) : {};
        const detail = d.message || d.code || "语音合成失败，请切换可用音色后重试。";
        const msgId = streamingAssistantMsgIdRef.current ?? pendingAssistantMsgIdRef.current;
        streamingAssistantMsgIdRef.current = null;
        pendingAssistantMsgIdRef.current = null;
        subtitleAccRef.current = "";
        if (msgId) {
          setMessages((prev) =>
            prev.map((m) => (m.id === msgId ? { ...m, text: `出错了：${detail}` } : m)),
          );
        } else {
          setMessages((prev) => [
            ...prev,
            { id: makeId(), role: "assistant", text: `出错了：${detail}`, timestamp: Date.now() },
          ]);
        }
      }
      if (ev === "speech.started") {
        setIsSpeaking(true);
        subtitleAccRef.current = "";
        subtitleMediaReadyRef.current = false;
        clearSubtitleFallbackTimer();
        setCurrentSubtitle("");
        const staleId = streamingAssistantMsgIdRef.current;
        if (staleId) {
          setMessages((prev) => prev.filter((m) => m.id !== staleId));
          streamingAssistantMsgIdRef.current = null;
        }
        const id = pendingAssistantMsgIdRef.current ?? makeId();
        pendingAssistantMsgIdRef.current = null;
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
      }
      if (ev === "subtitle.chunk" && data && typeof data === "object") {
        const t = (data as { text?: string }).text;
        if (!t) return;
        const msgId = streamingAssistantMsgIdRef.current;
        subtitleAccRef.current += t;
        if (msgId) {
          const next = subtitleAccRef.current;
          setMessages((prev) =>
            prev.map((m) => (m.id === msgId ? { ...m, text: next } : m)),
          );
        }
      }
      if (ev === "speech.ended") {
        setIsSpeaking(false);
        clearSubtitleFallbackTimer();
        const d = data && typeof data === "object" ? (data as { text?: string }) : {};
        const fromEvent = typeof d.text === "string" ? d.text.trim() : "";
        const streamed = subtitleAccRef.current.trim();
        const finalText = fromEvent || streamed;
        const msgId = streamingAssistantMsgIdRef.current;
        streamingAssistantMsgIdRef.current = null;
        subtitleAccRef.current = "";
        if (msgId) {
          if (finalText) {
            setMessages((prev) =>
              prev.map((m) => (m.id === msgId ? { ...m, text: finalText } : m)),
            );
          } else {
            setMessages((prev) => prev.filter((m) => m.id !== msgId));
          }
        } else if (finalText) {
          setMessages((prev) => [
            ...prev,
            { id: makeId(), role: "assistant", text: finalText, timestamp: Date.now() },
          ]);
        }
        subtitleMediaReadyRef.current = false;
      }
    });
    return stop;
  }, [clearSubtitleFallbackTimer, flushSubtitleDisplay, sessionId]);

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

    const previousSessionId = sessionIdRef.current;
    if (previousSessionId) {
      await releaseSession(previousSessionId);
      resetLiveState();
    }

    setConnection("connecting");
    setQueueInfo(null);
    let createdSessionId: string | null = null;
    try {
      const created = await apiPost<CreateSessionResponse>("/sessions", {
        avatar_id: avatarId,
        model,
        llm_system_prompt: llmSystemPrompt.trim() || undefined,
        tts_provider: ttsProvider,
        tts_voice: isEdgeTts(ttsProvider) ? edgeVoice : ttsProvider === "sambert" ? undefined : qwenVoice,
      });
      createdSessionId = created.session_id;
      setSessionId(created.session_id);

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
      const pc = await startPlayback(created.session_id, videoRef.current!);
      pcRef.current = pc;
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
      notify("启动会话失败，请稍后重试或查看后端日志。", "error");
    }
  }, [
    avatarId,
    closePeerConnection,
    edgeVoice,
    llmSystemPrompt,
    model,
    notify,
    qwenVoice,
    releaseSession,
    resetLiveState,
    ttsProvider,
    waitForSessionReady,
  ]);

  const handleSavePrompt = useCallback(async () => {
    setPromptSaving(true);
    try {
      await apiPost("/sessions/customize/prompt", {
        avatar_id: avatarId,
        llm_system_prompt: llmSystemPrompt,
      });
      const sid = sessionIdRef.current;
      if (sid) await releaseSession(sid);
      resetLiveState(true);
      setConnection("idle");
      notify("System Prompt 已保存，页面即将刷新并在新会话生效。", "success");
      window.setTimeout(() => window.location.reload(), 900);
    } catch (e) {
      console.warn("save prompt failed", e);
      notify("保存 Prompt 失败，请查看后端日志。", "error");
    } finally {
      setPromptSaving(false);
    }
  }, [avatarId, llmSystemPrompt, notify, releaseSession, resetLiveState]);

  const saveReferenceImageFile = useCallback(async (file: File | null, customName?: string) => {
    if (!file) {
      notify("请先选择一张参考图再上传。", "info");
      return;
    }
    const trimmedName = customName?.trim();
    if (trimmedName) {
      try {
        window.localStorage.setItem(CUSTOM_REFERENCE_NAME_KEY, trimmedName);
      } catch {
        /* ignore */
      }
    }
    setReferenceSaving(true);
    try {
      const fd = new FormData();
      fd.set("avatar_id", avatarId);
      fd.set("reference_image", file);
      await apiPostForm("/sessions/customize/reference", fd);
      setReferenceImageFile(null);
      const sid = sessionIdRef.current;
      if (sid) await releaseSession(sid);
      resetLiveState(true);
      setConnection("idle");
      notify(trimmedName ? `自定义形象「${trimmedName}」已保存，页面即将刷新并在新会话生效。` : "参考图已保存，页面即将刷新并在新会话生效。", "success");
      window.setTimeout(() => window.location.reload(), 900);
    } catch (e) {
      console.warn("save reference image failed", e);
      notify("上传参考图失败，请查看后端日志。", "error");
    } finally {
      setReferenceSaving(false);
    }
  }, [avatarId, notify, releaseSession, resetLiveState]);

  const handleSaveReferenceImage = useCallback(async () => {
    await saveReferenceImageFile(referenceImageFile);
  }, [referenceImageFile, saveReferenceImageFile]);

  const handleCreateCustomAvatar = useCallback(async (file: File, name: string) => {
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
      fd.set("image", file);
      const created = await apiPostForm<AvatarSummary>("/avatars/custom", fd);
      setAvatars((prev) => {
        const filtered = prev.filter((avatar) => avatar.id !== created.id);
        return [...filtered, created];
      });
      setAvatarId(created.id);
      const sid = sessionIdRef.current;
      if (sid) await releaseSession(sid);
      resetLiveState(true);
      setConnection("idle");
      notify(`自定义形象「${created.name ?? trimmedName}」已加入形象库。`, "success");
    } catch (e) {
      console.warn("create custom avatar failed", e);
      notify("创建自定义形象失败，请查看后端日志。", "error");
    } finally {
      setReferenceSaving(false);
    }
  }, [avatarId, notify, releaseSession, resetLiveState]);

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
  }, [releaseSession, resetLiveState]);

  const handlePreviewTts = useCallback(async () => {
    const text = ttsPreviewText.trim();
    if (!text) {
      notify("先输入一句试听文本。", "info");
      return;
    }
    setTtsPreviewing(true);
    try {
      const voice = isEdgeTts(ttsProvider) ? edgeVoice : ttsProvider === "sambert" ? "" : qwenVoice;
      if (!isEdgeTts(ttsProvider) && ttsProvider !== "sambert" && !voice.trim()) {
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
      notify("试听失败，请确认音色、模型和后端密钥配置。", "error");
    } finally {
      setTtsPreviewing(false);
    }
  }, [edgeVoice, notify, qwenModel, qwenVoice, ttsPreviewText, ttsProvider]);

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
      const useChat = model === "quicktalk";
      const endpoint = useChat ? "chat" : "speak";
      const payload = useChat
        ? {
            prompt: text,
            voice:
              isEdgeTts(ttsProvider)
                ? edgeVoice
                : ttsProvider === "sambert"
                  ? undefined
                  : qwenVoice,
            tts_provider: ttsProvider,
            tts_model: !isEdgeTts(ttsProvider) ? qwenModel : undefined,
          }
        : {
            text,
            voice:
              isEdgeTts(ttsProvider)
                ? edgeVoice
                : ttsProvider === "sambert"
                  ? undefined
                  : qwenVoice,
            tts_provider: ttsProvider,
            tts_model: !isEdgeTts(ttsProvider) ? qwenModel : undefined,
          };
      void apiPost(`/sessions/${sessionId}/${endpoint}`, payload).catch((err) => {
        console.warn(`${endpoint} failed`, err);
        if (pendingAssistantMsgIdRef.current === pendingId) {
          pendingAssistantMsgIdRef.current = null;
        }
        setMessages((prev) => prev.filter((m) => m.id !== pendingId));
        setIsSpeaking(false);
        notify("发送失败，请确认会话仍处于已连接状态。", "error");
      });
    },
    [edgeVoice, isSpeaking, model, notify, qwenModel, qwenVoice, sessionId, ttsProvider],
  );

  /** 流式 ASR（WebSocket PCM）成功后仅追加本地消息（speak 已由后端入队） */
  const handleSpeakAudioStreamResult = useCallback(({ text }: { text: string }) => {
    setMessages((prev) => [
      ...prev,
      { id: makeId(), role: "user", text, timestamp: Date.now() },
    ]);
  }, []);

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
        isEdgeTts(ttsProvider) ? edgeVoice : ttsProvider === "sambert" ? "" : qwenVoice,
      );
      fd.append("tts_provider", ttsProvider);
      if (!isEdgeTts(ttsProvider)) {
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
      } finally {
        if (speakAudioAbortRef.current === ac) {
          speakAudioAbortRef.current = null;
        }
      }
    },
    [edgeVoice, qwenModel, qwenVoice, sessionId, ttsProvider],
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
    setFtRecordPhase("idle");
  }, [sessionId, model]);

  useEffect(() => {
    if (connection !== "live" && connection !== "expiring") {
      setFtRecordPhase("idle");
    }
  }, [connection]);

  const handleFtRecordStart = useCallback(async () => {
    if (!sessionId || !isFlashRenderer(model)) return;
    setFtRecordBusy(true);
    try {
      await apiPost(`/sessions/${sessionId}/flashtalk-recording/start`, {});
      setFtRecordPhase("recording");
    } catch (error) {
      console.warn("flashtalk recording start failed", error);
      notify("开始录制失败：请确认当前会话为 FlashTalk / FlashHead 且已连接。", "error");
    } finally {
      setFtRecordBusy(false);
    }
  }, [model, notify, sessionId]);

  const handleFtRecordStop = useCallback(async () => {
    if (!sessionId || !isFlashRenderer(model)) return;
    setFtRecordBusy(true);
    try {
      await apiPost(`/sessions/${sessionId}/flashtalk-recording/stop`, {});
      setFtRecordPhase("stopped");
    } catch (error) {
      console.warn("flashtalk recording stop failed", error);
      notify("结束录制失败，请稍后重试或查看网络请求详情。", "error");
    } finally {
      setFtRecordBusy(false);
    }
  }, [model, notify, sessionId]);

  const handleFtRecordSave = useCallback(async () => {
    if (!sessionId || !isFlashRenderer(model)) return;
    setRecordingSaving(true);
    try {
      const url = buildApiUrl(`/sessions/${sessionId}/flashtalk-recording`);
      const response = await fetch(url);
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(`${response.status} ${detail}`);
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objectUrl;
      a.download = `${sessionId}_flashtalk_capture.mp4`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(objectUrl);
      setFtRecordPhase("idle");
    } catch (error) {
      console.warn("save FlashTalk recording failed", error);
      notify("暂无可保存的视频或导出失败。请先开始录制、结束录制，再保存视频。", "error");
    } finally {
      setRecordingSaving(false);
    }
  }, [model, notify, sessionId]);

  const handleOfflineBundleFile = useCallback(
    async (e: ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      e.target.value = "";
      if (!file || !sessionId || !isFlashRenderer(model)) return;
      setOfflineBundleBusy(true);
      try {
        const fd = new FormData();
        fd.append("file", file);
        const enq = await apiPostForm<{ session_id: string; job_id: string; status: string }>(
          `/sessions/${sessionId}/flashtalk-offline-bundle`,
          fd,
        );
        const jobId = enq.job_id;
        const deadline = Date.now() + 45 * 60 * 1000;
        type St = {
          session_id: string;
          job_id: string;
          status: string;
          message?: string;
        };
        let last: St = { session_id: sessionId, job_id: jobId, status: "queued" };
        while (Date.now() < deadline) {
          await new Promise((r) => setTimeout(r, 2000));
          last = await apiGet<St>(`/sessions/${sessionId}/flashtalk-offline-bundle/${jobId}`);
          if (last.status === "done" || last.status === "error") break;
        }
        if (last.status !== "done" && last.status !== "error") {
          throw new Error("离线导出超时（超过 45 分钟），请稍后重试。");
        }
        if (last.status === "error") {
          throw new Error(last.message || "Worker 处理失败");
        }
        const url = buildApiUrl(
          `/sessions/${sessionId}/flashtalk-offline-bundle/${jobId}/download?artifact=bundle`,
        );
        const response = await fetch(url);
        if (!response.ok) {
          const detail = await response.text();
          throw new Error(`${response.status} ${detail}`);
        }
        const blob = await response.blob();
        const objectUrl = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = objectUrl;
        a.download = `${sessionId}_offline_${jobId}_bundle.mp4`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(objectUrl);
        setMessages((prev) => [
          ...prev,
          {
            id: makeId(),
            role: "user",
            text: `[离线导出完成] ${file.name} → bundle.mp4`,
            timestamp: Date.now(),
          },
        ]);
      } catch (error) {
        console.warn("flashtalk offline bundle failed", error);
        const msg = error instanceof Error ? error.message : String(error);
        notify(`离线整段导出失败：${msg}`, "error");
      } finally {
        setOfflineBundleBusy(false);
      }
    },
    [model, notify, sessionId],
  );

  const handleAvatarChange = useCallback(
    (newId: string) => {
      setAvatarId(newId);
      void (async () => {
        const sid = sessionIdRef.current;
        if (sid) {
          await releaseSession(sid);
        }
        resetLiveState(true);
        setConnection("idle");
      })();
    },
    [releaseSession, resetLiveState],
  );

  const handleModelChange = useCallback((newModel: string) => {
    setModel(newModel);
    void (async () => {
      const sid = sessionIdRef.current;
      if (sid) {
        await releaseSession(sid);
      }
      resetLiveState();
      setConnection("idle");
    })();
  }, [releaseSession, resetLiveState]);

  useEffect(() => {
    const handlePageHide = () => {
      const sid = sessionIdRef.current;
      if (sid && isFlashRenderer(model)) {
        void apiPost(`/sessions/${sid}/flashtalk-recording/stop`, {}).catch(() => {});
      }
      if (sid) {
        void releaseSession(sid, true);
      }
      closePeerConnection();
    };

    window.addEventListener("pagehide", handlePageHide);
    return () => window.removeEventListener("pagehide", handlePageHide);
  }, [closePeerConnection, releaseSession, model]);

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
  const showStart = connection === "idle" || connection === "error" || connection === "connecting" || connection === "queued";
  const chatMaxVisible = readChatMaxVisible();
  const selectedModelLabel = MODEL_LABELS_FOR_STAGE[model] ?? model;
  const selectedVoiceLabel = isEdgeTts(ttsProvider)
    ? EDGE_ZH_VOICES.find((voice) => voice.id === edgeVoice)?.label ?? edgeVoice
    : bailianVoices.find((voice) => voice.id === qwenVoice)?.label ?? (qwenVoice || "暂无音色");

  return (
    <div className="min-h-screen bg-slate-100 text-slate-900 lg:h-screen lg:overflow-hidden">
      <TopBar
        connection={connection}
        flashtalkRecording={
          isFlashRenderer(model) &&
          !!sessionId &&
          (connection === "live" || connection === "expiring")
        }
        flashtalkRecordPhase={ftRecordPhase}
        flashtalkRecordBusy={ftRecordBusy}
        recordingSaving={recordingSaving}
        onInactiveModuleClick={(label) => notify(`${label}模块规划中。当前可用的是实时对话、数字人配置、语音驱动和导出能力。`, "info")}
        onFlashtalkRecordStart={() => void handleFtRecordStart()}
        onFlashtalkRecordStop={() => void handleFtRecordStop()}
        onFlashtalkRecordSave={() => void handleFtRecordSave()}
        flashtalkOfflineBundleBusy={offlineBundleBusy}
        onFlashtalkOfflineBundleClick={() => offlineBundleInputRef.current?.click()}
      />

      <input
        ref={offlineBundleInputRef}
        type="file"
        accept="audio/*,.webm,.mp3,.wav,.m4a,.aac,.flac,.ogg"
        className="hidden"
        tabIndex={-1}
        aria-hidden
        onChange={(ev) => void handleOfflineBundleFile(ev)}
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

      <div className="flex min-h-0 flex-col lg:h-[calc(100vh-3.5rem)] lg:flex-row">
        <div className="order-2 min-h-0 lg:order-none lg:h-full lg:shrink-0">
          <SettingsPanel
            expanded={settingsExpanded}
            onExpandedChange={setSettingsExpanded}
            avatars={avatars}
            models={models.length ? models : ["flashtalk", "musetalk", "wav2lip"]}
            avatarId={avatarId}
            model={model}
            onAvatarChange={handleAvatarChange}
            onModelChange={handleModelChange}
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
            llmSystemPrompt={llmSystemPrompt}
            onLlmSystemPromptChange={setLlmSystemPrompt}
            onReferenceImageChange={setReferenceImageFile}
            onSavePrompt={() => void handleSavePrompt()}
            onSaveReferenceImage={() => void handleSaveReferenceImage()}
            promptSaving={promptSaving}
            referenceSaving={referenceSaving}
            onOpenVoiceClone={() => setVoiceCloneOpen(true)}
          />
        </div>

        <main className="order-1 flex min-h-0 flex-1 flex-col bg-slate-100 lg:order-none">
          <div className="flex min-h-0 flex-1 flex-col p-4">
            <div className="relative min-h-[360px] flex-1 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm shadow-slate-200/70 lg:min-h-[420px]">
              <div className="absolute inset-0 bg-slate-50" />
              <div className="absolute inset-3 rounded-lg border border-slate-200 bg-white shadow-inner shadow-slate-200/60" />
              <div className="absolute inset-0 flex items-center justify-center p-4 sm:p-6 lg:p-8">
                <div
                  className={
                    compactSquareStage
                      ? "relative aspect-square w-full max-w-[42rem] max-h-full"
                      : "relative h-full w-full"
                  }
                >
                  <VideoBackground ref={videoRef} className="absolute inset-0 h-full w-full object-contain" />
                </div>
              </div>

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
                    {MODEL_LABELS_FOR_STAGE[model] ?? model}
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

              {currentSubtitle && !showStart ? (
                <div className="absolute inset-x-4 bottom-4 z-10 mx-auto max-w-xl rounded-lg border border-slate-200 bg-white/95 px-4 py-3 text-center text-sm font-medium leading-relaxed text-slate-900 shadow-lg shadow-slate-200/80 backdrop-blur">
                  {currentSubtitle}
                </div>
              ) : null}

              {showStart ? (
                <div className="absolute inset-0 z-40 bg-white">
                  <AvatarSelectionStage
                    avatars={avatars}
                    selectedAvatar={currentAvatar}
                    selectedModelLabel={selectedModelLabel}
                    selectedVoiceLabel={selectedVoiceLabel}
                    loading={connection === "connecting"}
                    queued={connection === "queued"}
                    queueInfo={queueInfo}
                    onAvatarChange={handleAvatarChange}
                    onStart={() => void handleStart()}
                    onCustomAvatarCreate={(file, name) => void handleCreateCustomAvatar(file, name)}
                    referenceSaving={referenceSaving}
                  />
                </div>
              ) : null}
            </div>

            {connection === "live" || connection === "expiring" ? (
            <div className="mt-4">
              <ChatInput
                onSend={handleSend}
                onSpeakAudio={handleSpeakAudio}
                onSpeakFlashtalkAudioFile={
                  isFlashRenderer(model) ? handleSpeakFlashtalkAudioFile : undefined
                }
                streamingAsrSessionId={sessionId}
                onSpeakAudioStreamResult={handleSpeakAudioStreamResult}
                onInterrupt={handleInterrupt}
                isSpeaking={isSpeaking}
                disabled={connection !== "live" && connection !== "expiring"}
                onNotify={notify}
                onOpenSettings={() => setSettingsExpanded(true)}
                ttsProvider={ttsProvider}
                edgeVoice={edgeVoice}
                qwenModel={qwenModel}
                qwenVoice={qwenVoice}
              />
            </div>
            ) : null}
          </div>
        </main>

        <aside
          className={`order-3 min-h-0 overflow-hidden border-l border-slate-200 bg-white transition-[width] duration-200 lg:shrink-0 ${
            sessionPanelCollapsed ? "lg:w-12" : "lg:w-[360px]"
          }`}
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
                      ["驱动模型", MODEL_LABELS_FOR_STAGE[model] ?? model],
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
                      FlashTalk / FlashHead 会话连接后，可在顶部使用录制和离线整段导出。
                    </div>
                    {isFlashRenderer(model) && sessionId ? (
                      <button
                        type="button"
                        disabled={offlineBundleBusy}
                        onClick={() => offlineBundleInputRef.current?.click()}
                        className="w-full rounded-lg bg-cyan-600 px-3 py-2.5 text-sm font-semibold text-white transition hover:bg-cyan-500 disabled:opacity-60"
                      >
                        {offlineBundleBusy ? "离线导出中..." : "上传音频并离线导出"}
                      </button>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        </aside>
      </div>
      <ToastStack toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}
