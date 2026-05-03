import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import { BailianVoiceClone } from "./components/BailianVoiceClone";
import { ChatInput } from "./components/ChatInput";
import { ChatMessages } from "./components/ChatMessages";
import { SETTINGS_DOCK_EXPANDED_KEY, SettingsPanel } from "./components/SettingsPanel";
import { StartOverlay } from "./components/StartOverlay";
import { TopBar } from "./components/TopBar";
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

function mergeVoiceCatalogIntoOptions(
  staticList: { id: string; label: string }[],
  catalog: VoiceCatalogItem[],
  ttsProvider: TtsProviderExtended,
): VoiceOpt[] {
  const cp = catalogProviderKey(ttsProvider);
  if (!cp) {
    return staticList.map((s) => ({ id: s.id, label: s.label }));
  }
  const staticIds = new Set(staticList.map((s) => s.id));
  const extras: VoiceOpt[] = [];
  for (const r of catalog) {
    if (r.provider !== cp) continue;
    if (staticIds.has(r.voice_id)) continue;
    extras.push({
      id: r.voice_id,
      label: r.source === "clone" ? `✦ ${r.display_label}` : r.display_label,
      targetModel: r.target_model,
    });
    staticIds.add(r.voice_id);
  }
  return [...staticList.map((s) => ({ id: s.id, label: s.label })), ...extras];
}

const MESSAGE_STORAGE_KEY = "opentalking-chat-history";
const LLM_SYSTEM_PROMPT_STORAGE_KEY = "opentalking-llm-system-prompt";

type SpeakAudioResponse = { session_id: string; status: string; text: string };

/** From Vite env: max bubbles to show (most recent). 0 = show full history. */
function readChatMaxVisible(): number {
  const raw = import.meta.env.VITE_CHAT_MAX_VISIBLE;
  if (raw === undefined || raw === "") return 0;
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0) return 0;
  return Math.min(500, Math.floor(n));
}

let msgCounter = 0;
function makeId() {
  return `msg-${++msgCounter}-${Date.now()}`;
}

function pickInitialAvatar(
  avatars: AvatarSummary[],
  registeredModels: string[],
): AvatarSummary | null {
  if (!avatars.length) return null;
  const available = new Set(registeredModels);
  // Prefer flashtalk, then musetalk, then any available
  return (
    avatars.find((a) => a.model_type === "flashtalk" && available.has("flashtalk")) ??
    avatars.find((a) => a.model_type === "musetalk" && available.has("musetalk")) ??
    avatars.find((a) => available.has(a.model_type)) ??
    avatars[0]
  );
}

export default function App() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const speakAudioAbortRef = useRef<AbortController | null>(null);
  /** Cumulative assistant text for the current speech turn (subtitle.chunk segments). */
  const subtitleAccRef = useRef("");
  /** `messages` id of the in-progress assistant bubble for this turn; cleared on speech.ended. */
  const streamingAssistantMsgIdRef = useRef<string | null>(null);
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
  const [, setCurrentSubtitle] = useState("");

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
  const [recordingSaving, setRecordingSaving] = useState(false);
  const [ftRecordPhase, setFtRecordPhase] = useState<"idle" | "recording" | "stopped">("idle");
  const [ftRecordBusy, setFtRecordBusy] = useState(false);
  const [offlineBundleBusy, setOfflineBundleBusy] = useState(false);
  const offlineBundleInputRef = useRef<HTMLInputElement>(null);
  const [voiceCatalog, setVoiceCatalog] = useState<VoiceCatalogItem[]>([]);
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

  const [llmSystemPrompt, setLlmSystemPrompt] = useState<string>(() => {
    try {
      return window.localStorage.getItem(LLM_SYSTEM_PROMPT_STORAGE_KEY) ?? "";
    } catch {
      return "";
    }
  });

  const loadVoices = useCallback(async () => {
    try {
      const res = await apiGet<{ items: VoiceCatalogItem[] }>("/voices");
      setVoiceCatalog(res.items ?? []);
    } catch (e) {
      console.warn("Failed to load /voices", e);
    }
  }, []);

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
    () => mergeVoiceCatalogIntoOptions(bailianVoiceOptions(ttsProvider), voiceCatalog, ttsProvider),
    [ttsProvider, voiceCatalog],
  );

  useEffect(() => {
    const mids = bailianModels.map((o) => o.id);
    const vids = bailianVoices.map((o) => o.id);
    setQwenModel((prev) => (mids.includes(prev) ? prev : mids[0] ?? ""));
    if (vids.length === 0) return;
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
          setModel(initialAvatar.model_type);
        }
      } catch {
        setConnection("error");
      }
    })();
  }, [loadVoices]);

  // Keep model aligned with selected avatar
  useEffect(() => {
    const a = avatars.find((x) => x.id === avatarId);
    if (a) {
      setModel(a.model_type);
    }
  }, [avatarId, avatars]);

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
        streamingAssistantMsgIdRef.current = null;
        if (orphanId) {
          setMessages((prev) => prev.filter((m) => m.id !== orphanId));
        }
      }
      if (ev === "error") {
        setIsSpeaking(false);
        clearSubtitleFallbackTimer();
        const d = data && typeof data === "object" ? (data as { message?: string; code?: string }) : {};
        const detail = d.message || d.code || "语音合成失败，请切换可用音色后重试。";
        const msgId = streamingAssistantMsgIdRef.current;
        streamingAssistantMsgIdRef.current = null;
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
        const id = makeId();
        streamingAssistantMsgIdRef.current = id;
        setMessages((prev) => [
          ...prev,
          { id, role: "assistant", text: "", timestamp: Date.now() },
        ]);
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

      // FlashTalk: session is queued, wait for slot_acquired via SSE before WebRTC
      if (created.status === "queued") {
        // Fetch current queue position immediately (the queued event may have
        // fired before SSE was established and got lost in pub/sub)
        try {
          const qs = await apiGet<{ slot_occupied: boolean; queue_size: number }>("/queue/status");
          if (qs.slot_occupied) {
            setConnection("queued");
            setQueueInfo({ position: qs.queue_size, message: "waiting" });
          }
        } catch { /* ignore, SSE will update */ }

        await new Promise<void>((resolve, reject) => {
          slotAcquiredRef.current = resolve;
          // Timeout guard matching server-side slot timeout
          const timer = setTimeout(() => {
            slotAcquiredRef.current = null;
            reject(new Error("FlashTalk slot wait timeout"));
          }, 360_000);
          // Clean up timer when resolved
          const origResolve = resolve;
          slotAcquiredRef.current = () => { clearTimeout(timer); origResolve(); };
        });
      }

      closePeerConnection();
      const pc = await startPlayback(created.session_id, videoRef.current!);
      pcRef.current = pc;
      videoRef.current!.muted = false;
      setConnection("live");
      await apiPost(`/sessions/${created.session_id}/start`, {});
    } catch (error) {
      if (createdSessionId) {
        await releaseSession(createdSessionId);
      }
      resetLiveState();
      console.warn("Failed to start session", error);
      setConnection("error");
    }
  }, [
    avatarId,
    closePeerConnection,
    edgeVoice,
    llmSystemPrompt,
    model,
    qwenVoice,
    releaseSession,
    resetLiveState,
    ttsProvider,
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
      window.alert("System Prompt 已保存。页面将刷新并在新会话生效。");
      window.location.reload();
    } catch (e) {
      console.warn("save prompt failed", e);
      window.alert("保存 Prompt 失败，请查看后端日志。");
    } finally {
      setPromptSaving(false);
    }
  }, [avatarId, llmSystemPrompt, releaseSession, resetLiveState]);

  const handleSaveReferenceImage = useCallback(async () => {
    if (!referenceImageFile) {
      window.alert("请先选择一张参考图再上传。");
      return;
    }
    setReferenceSaving(true);
    try {
      const fd = new FormData();
      fd.set("avatar_id", avatarId);
      fd.set("reference_image", referenceImageFile);
      await apiPostForm("/sessions/customize/reference", fd);
      setReferenceImageFile(null);
      const sid = sessionIdRef.current;
      if (sid) await releaseSession(sid);
      resetLiveState(true);
      setConnection("idle");
      window.alert("参考图已保存。页面将刷新并在新会话生效。");
      window.location.reload();
    } catch (e) {
      console.warn("save reference image failed", e);
      window.alert("上传参考图失败，请查看后端日志。");
    } finally {
      setReferenceSaving(false);
    }
  }, [avatarId, referenceImageFile, releaseSession, resetLiveState]);

  const handleSend = useCallback(
    (text: string) => {
      if (!sessionId || !text) return;
      setMessages((prev) => [
        ...prev,
        { id: makeId(), role: "user", text, timestamp: Date.now() },
      ]);
      void apiPost(`/sessions/${sessionId}/speak`, {
        text,
        voice:
          isEdgeTts(ttsProvider) ? edgeVoice : ttsProvider === "sambert" ? undefined : qwenVoice,
        tts_provider: ttsProvider,
        tts_model: !isEdgeTts(ttsProvider) ? qwenModel : undefined,
      }).catch((err) => {
        console.warn("speak failed", err);
      });
    },
    [edgeVoice, qwenModel, qwenVoice, sessionId, ttsProvider],
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
      if (!sessionId || model !== "flashtalk") return;
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
        window.alert("上传音频驱动口型失败，请确认文件为常见音频格式且当前为 FlashTalk 会话。");
      }
    },
    [model, sessionId],
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
    if (!sessionId || model !== "flashtalk") return;
    setFtRecordBusy(true);
    try {
      await apiPost(`/sessions/${sessionId}/flashtalk-recording/start`, {});
      setFtRecordPhase("recording");
    } catch (error) {
      console.warn("flashtalk recording start failed", error);
      window.alert("开始录制失败：请确认当前会话为 FlashTalk 且已连接。");
    } finally {
      setFtRecordBusy(false);
    }
  }, [sessionId, model]);

  const handleFtRecordStop = useCallback(async () => {
    if (!sessionId || model !== "flashtalk") return;
    setFtRecordBusy(true);
    try {
      await apiPost(`/sessions/${sessionId}/flashtalk-recording/stop`, {});
      setFtRecordPhase("stopped");
    } catch (error) {
      console.warn("flashtalk recording stop failed", error);
      window.alert("结束录制失败，请稍后重试或查看网络请求详情。");
    } finally {
      setFtRecordBusy(false);
    }
  }, [sessionId, model]);

  const handleFtRecordSave = useCallback(async () => {
    if (!sessionId || model !== "flashtalk") return;
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
      window.alert(
        "暂无可保存的视频或导出失败。请确认流程：先点「开始录制」→ 对话中数字人有说话画面 →「结束录制」→ 再点「保存视频」。若仍失败，请在开发者工具 Network 中查看 /flashtalk-recording 的响应内容。",
      );
    } finally {
      setRecordingSaving(false);
    }
  }, [sessionId, model]);

  const handleOfflineBundleFile = useCallback(
    async (e: ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      e.target.value = "";
      if (!file || !sessionId || model !== "flashtalk") return;
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
        window.alert(`离线整段导出失败：${msg}`);
      } finally {
        setOfflineBundleBusy(false);
      }
    },
    [model, sessionId],
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
      if (sid && model === "flashtalk") {
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

  return (
    <>
      {/* Layer 0: Full-screen video background */}
      <VideoBackground ref={videoRef} />

      <input
        ref={offlineBundleInputRef}
        type="file"
        accept="audio/*,.webm,.mp3,.wav,.m4a,.aac,.flac,.ogg"
        className="sr-only"
        tabIndex={-1}
        aria-hidden
        onChange={(ev) => void handleOfflineBundleFile(ev)}
      />

      {/* Layer 1: Bottom gradient overlay */}
      <div
        className="pointer-events-none fixed inset-x-0 bottom-0 z-10"
        style={{
          height: "45vh",
          background: "linear-gradient(to top, rgba(0,0,0,0.75) 0%, transparent 100%)",
        }}
      />

      {/* Layer 2: Chat messages */}
      <ChatMessages messages={messages} maxVisible={chatMaxVisible} />

      {/* Layer 3: Top bar */}
      <TopBar
        connection={connection}
        flashtalkRecording={
          model === "flashtalk" &&
          !!sessionId &&
          (connection === "live" || connection === "expiring")
        }
        flashtalkRecordPhase={ftRecordPhase}
        flashtalkRecordBusy={ftRecordBusy}
        recordingSaving={recordingSaving}
        onFlashtalkRecordStart={() => void handleFtRecordStart()}
        onFlashtalkRecordStop={() => void handleFtRecordStop()}
        onFlashtalkRecordSave={() => void handleFtRecordSave()}
        flashtalkOfflineBundleBusy={offlineBundleBusy}
        onFlashtalkOfflineBundleClick={() => offlineBundleInputRef.current?.click()}
      />

      {voiceCloneOpen ? (
        <>
          <button
            type="button"
            className="fixed inset-0 z-[55] cursor-default bg-black/55 backdrop-blur-[2px]"
            aria-label="关闭音色复刻"
            onClick={() => setVoiceCloneOpen(false)}
          />
          <aside className="pointer-events-none fixed inset-y-0 right-0 z-[56] flex w-[min(100vw,26rem)] shadow-2xl">
            <div className="pointer-events-auto flex h-full max-h-[100dvh] flex-col overflow-hidden border-l border-white/15 bg-black/85 backdrop-blur-xl">
              <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">
                <BailianVoiceClone
                  onSuccess={() => void loadVoices()}
                  onClose={() => setVoiceCloneOpen(false)}
                />
              </div>
            </div>
          </aside>
        </>
      ) : null}

      {/* Layer 3: Input bar */}
      <ChatInput
        onSend={handleSend}
        onSpeakAudio={handleSpeakAudio}
        onSpeakFlashtalkAudioFile={
          model === "flashtalk" ? handleSpeakFlashtalkAudioFile : undefined
        }
        streamingAsrSessionId={sessionId}
        onSpeakAudioStreamResult={handleSpeakAudioStreamResult}
        onInterrupt={handleInterrupt}
        isSpeaking={isSpeaking}
        disabled={connection !== "live" && connection !== "expiring"}
        onOpenSettings={() => setSettingsExpanded(true)}
        ttsProvider={ttsProvider}
        edgeVoice={edgeVoice}
        qwenModel={qwenModel}
        qwenVoice={qwenVoice}
      />

      {/* Layer 3: Session expiring countdown toast */}
      {expiringCountdown !== null && (
        <div className="fixed right-4 top-14 z-30 flex items-center gap-2 rounded-xl bg-amber-500/90 px-4 py-2.5 text-sm font-medium text-white shadow-lg backdrop-blur-sm">
          <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6l4 2m6-2a10 10 0 1 1-20 0 10 10 0 0 1 20 0z" />
          </svg>
          体验即将到期，剩余 <span className="tabular-nums font-bold">{expiringCountdown}</span> 秒
        </div>
      )}

      {/* Layer 4: Start overlay */}
      <StartOverlay
        avatar={currentAvatar}
        loading={connection === "connecting"}
        queued={connection === "queued"}
        queueInfo={queueInfo}
        onStart={() => void handleStart()}
        visible={showStart}
      />

      {/* Layer 5: Settings panel */}
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
        llmSystemPrompt={llmSystemPrompt}
        onLlmSystemPromptChange={setLlmSystemPrompt}
        onReferenceImageChange={setReferenceImageFile}
        onSavePrompt={() => void handleSavePrompt()}
        onSaveReferenceImage={() => void handleSaveReferenceImage()}
        promptSaving={promptSaving}
        referenceSaving={referenceSaving}
        onOpenVoiceClone={() => setVoiceCloneOpen(true)}
      />
    </>
  );
}
