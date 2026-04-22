import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BailianVoiceClone } from "./components/BailianVoiceClone";
import { ChatInput } from "./components/ChatInput";
import { ChatMessages } from "./components/ChatMessages";
import { SETTINGS_DOCK_EXPANDED_KEY, SettingsPanel } from "./components/SettingsPanel";
import { StartOverlay } from "./components/StartOverlay";
import { SubtitleOverlay } from "./components/SubtitleOverlay";
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
  MINIMAX_MODEL_OPTIONS,
  MINIMAX_VOICE_OPTIONS,
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
import type { ConnectionStatus, Message } from "./types";

function bailianModelOptions(provider: TtsProviderExtended): { id: string; label: string }[] {
  switch (provider) {
    case "dashscope":
      return QWEN_TTS_MODEL_OPTIONS;
    case "cosyvoice":
      return COSYVOICE_MODEL_OPTIONS;
    case "sambert":
      return SAMBERT_MODEL_OPTIONS;
    case "minimax":
      return MINIMAX_MODEL_OPTIONS;
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
    case "minimax":
      return MINIMAX_VOICE_OPTIONS;
    case "sambert":
      return [];
    default:
      return [];
  }
}

function catalogProviderKey(p: TtsProviderExtended): string | null {
  if (p === "dashscope") return "dashscope";
  if (p === "cosyvoice") return "cosyvoice";
  if (p === "minimax") return "minimax";
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

type SpeakAudioResponse = { session_id: string; status: string; text: string };

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
  /** 本轮 assistant 字幕全文（多句 subtitle.chunk 累积） */
  const subtitleAccRef = useRef("");
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

  // Chat
  const [messages, setMessages] = useState<Message[]>([]);
  const [currentSubtitle, setCurrentSubtitle] = useState("");
  const [isSpeaking, setIsSpeaking] = useState(false);

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
      if (
        s === "edge" ||
        s === "dashscope" ||
        s === "cosyvoice" ||
        s === "sambert" ||
        s === "minimax"
      )
        return s;
    } catch {
      /* ignore */
    }
    return "dashscope";
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
      setCurrentSubtitle("");
      subtitleAccRef.current = "";
      subtitleMediaReadyRef.current = false;
      clearSubtitleFallbackTimer();
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
      if (ev === "speech.started") {
        setIsSpeaking(true);
        subtitleAccRef.current = "";
        subtitleMediaReadyRef.current = false;
        clearSubtitleFallbackTimer();
        setCurrentSubtitle("");
      }
      if (ev === "speech.media_started") {
        subtitleMediaReadyRef.current = true;
        clearSubtitleFallbackTimer();
        flushSubtitleDisplay();
      }
      if (ev === "subtitle.chunk" && data && typeof data === "object") {
        const t = (data as { text?: string }).text;
        if (t) {
          const prev = subtitleAccRef.current;
          subtitleAccRef.current = prev ? `${prev}\n${t}` : t;
          if (subtitleMediaReadyRef.current) {
            flushSubtitleDisplay();
          } else {
            clearSubtitleFallbackTimer();
            subtitleFallbackTimerRef.current = setTimeout(() => {
              subtitleFallbackTimerRef.current = null;
              if (!subtitleMediaReadyRef.current && subtitleAccRef.current) {
                subtitleMediaReadyRef.current = true;
                flushSubtitleDisplay();
              }
            }, 1200);
          }
        }
      }
      if (ev === "speech.ended") {
        setIsSpeaking(false);
        clearSubtitleFallbackTimer();
        const finalText = subtitleAccRef.current;
        if (finalText) {
          setMessages((prev) => [
            ...prev,
            { id: makeId(), role: "assistant", text: finalText, timestamp: Date.now() },
          ]);
        }
        setCurrentSubtitle("");
        subtitleAccRef.current = "";
        subtitleMediaReadyRef.current = false;
      }
    });
    return stop;
  }, [clearSubtitleFallbackTimer, flushSubtitleDisplay, sessionId]);

  // ---------- Actions ----------
  const handleStart = useCallback(async () => {
    if (!videoRef.current) return;

    const previousSessionId = sessionIdRef.current;
    if (previousSessionId) {
      await releaseSession(previousSessionId);
      resetLiveState();
    }

    setConnection("connecting");
    let createdSessionId: string | null = null;
    try {
      const created = await apiPost<CreateSessionResponse>("/sessions", {
        avatar_id: avatarId,
        model,
      });
      createdSessionId = created.session_id;
      setSessionId(created.session_id);

      closePeerConnection();
      const pc = await startPlayback(created.session_id, videoRef.current);
      pcRef.current = pc;
      // Unmute after user gesture so audio plays (autoplay policy requires muted initially)
      videoRef.current.muted = false;
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
  }, [avatarId, closePeerConnection, model, releaseSession, resetLiveState]);

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
      if (sid) {
        void releaseSession(sid, true);
      }
      closePeerConnection();
    };

    window.addEventListener("pagehide", handlePageHide);
    return () => window.removeEventListener("pagehide", handlePageHide);
  }, [closePeerConnection, releaseSession]);

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
  const showStart = connection === "idle" || connection === "error";

  return (
    <>
      {/* Layer 0: Full-screen video background */}
      <VideoBackground ref={videoRef} />

      {/* Layer 1: Bottom gradient overlay */}
      <div
        className="pointer-events-none fixed inset-x-0 bottom-0 z-10"
        style={{
          height: "45vh",
          background: "linear-gradient(to top, rgba(0,0,0,0.75) 0%, transparent 100%)",
        }}
      />

      {/* Layer 2: Subtitle */}
      <SubtitleOverlay text={currentSubtitle} />

      {/* Layer 2: Chat messages */}
      <ChatMessages messages={messages} />

      {/* Layer 3: Top bar */}
      <TopBar connection={connection} />

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
        streamingAsrSessionId={sessionId}
        onSpeakAudioStreamResult={handleSpeakAudioStreamResult}
        onInterrupt={handleInterrupt}
        isSpeaking={isSpeaking}
        disabled={connection !== "live"}
        onOpenSettings={() => setSettingsExpanded(true)}
        ttsProvider={ttsProvider}
        edgeVoice={edgeVoice}
        qwenModel={qwenModel}
        qwenVoice={qwenVoice}
      />

      {/* Layer 4: Start overlay */}
      <StartOverlay
        avatar={currentAvatar}
        loading={connection === "connecting"}
        onStart={() => void handleStart()}
        visible={showStart}
      />

      {/* Layer 5: Settings panel */}
      <SettingsPanel
        expanded={settingsExpanded}
        onExpandedChange={setSettingsExpanded}
        avatars={avatars}
        models={models.length ? models : ["wav2lip", "musetalk"]}
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
        onOpenVoiceClone={() => setVoiceCloneOpen(true)}
      />
    </>
  );
}
