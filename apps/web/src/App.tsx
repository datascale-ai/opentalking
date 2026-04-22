import { useCallback, useEffect, useRef, useState } from "react";
import { ChatInput } from "./components/ChatInput";
import { ChatMessages } from "./components/ChatMessages";
import { SettingsPanel } from "./components/SettingsPanel";
import { StartOverlay } from "./components/StartOverlay";
import { SubtitleOverlay } from "./components/SubtitleOverlay";
import { TopBar } from "./components/TopBar";
import { VideoBackground } from "./components/VideoBackground";
import {
  apiDelete,
  apiGet,
  apiPost,
  buildApiUrl,
  type AvatarSummary,
  type CreateSessionResponse,
  type TTSVoiceOption,
} from "./lib/api";
import { connectSse } from "./lib/sse";
import { startPlayback } from "./lib/webrtc";
import type { ConnectionStatus, Message } from "./types";

const MESSAGE_STORAGE_KEY = "opentalking-chat-history";
const TTS_VOICE_STORAGE_KEY = "opentalking-tts-voice";
const DEMO_AVATAR_ORDER = [
  "musetalk_new",
  "musetalk_new_static",
  "wav2lip_new",
  "wav2lip_new_static",
  "flashtalk-avator",
  "demo-musetalk-gesture-fullbody-v2",
  "demo-musetalk-xtts-myvoice",
  "demo-musetalk",
  "demo-wav2lip",
  "flashtalk-demo",
  "flashtalk-demo-idle-all",
] as const;

let msgCounter = 0;
function makeId() {
  return `msg-${++msgCounter}-${Date.now()}`;
}

function getDemoAvatars(avatars: AvatarSummary[]): AvatarSummary[] {
  const order = new Map<string, number>(DEMO_AVATAR_ORDER.map((id, index) => [id, index]));
  return avatars
    .filter((avatar) => order.has(avatar.id))
    .sort((left, right) => (order.get(left.id) ?? 0) - (order.get(right.id) ?? 0));
}

function mergeSubtitleChunk(current: string, incoming: string): string {
  if (!current) return incoming;
  if (!incoming) return current;
  if (incoming.startsWith(current) || current === incoming) return incoming;
  if (current.endsWith(incoming)) return current;
  return `${current}${incoming}`;
}

export default function App() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const subtitleAccRef = useRef("");

  // Data
  const [avatars, setAvatars] = useState<AvatarSummary[]>([]);
  const [avatarId, setAvatarId] = useState("musetalk_new");
  const [voiceOptions, setVoiceOptions] = useState<TTSVoiceOption[]>([]);
  const [voiceOptionId, setVoiceOptionId] = useState("edge:zh-CN-XiaoxiaoNeural");

  // Connection
  const [connection, setConnection] = useState<ConnectionStatus>("idle");
  const [sessionId, setSessionId] = useState<string | null>(null);

  // Chat
  const [messages, setMessages] = useState<Message[]>([]);
  const [currentSubtitle, setCurrentSubtitle] = useState("");
  const [isSpeaking, setIsSpeaking] = useState(false);

  // UI
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  useEffect(() => {
    try {
      const savedVoiceId = window.localStorage.getItem(TTS_VOICE_STORAGE_KEY);
      if (savedVoiceId) {
        setVoiceOptionId(savedVoiceId);
      }
    } catch (error) {
      console.warn("Failed to restore voice option", error);
    }
  }, []);

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

  useEffect(() => {
    try {
      window.localStorage.setItem(TTS_VOICE_STORAGE_KEY, voiceOptionId);
    } catch (error) {
      console.warn("Failed to persist voice option", error);
    }
  }, [voiceOptionId]);

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
      if (clearMessages) {
        setMessages([]);
      }
    },
    [closePeerConnection],
  );

  // ---------- Init: fetch demo avatars ----------
  useEffect(() => {
    void (async () => {
      try {
        const [av, voices] = await Promise.all([
          apiGet<AvatarSummary[]>("/avatars"),
          apiGet<TTSVoiceOption[]>("/tts/voices"),
        ]);
        const demoAvatars = getDemoAvatars(av);
        setAvatars(demoAvatars);
        setVoiceOptions(voices);
        const initialAvatar = demoAvatars[0] ?? null;
        if (initialAvatar) {
          setAvatarId(initialAvatar.id);
        }
        if (voices.length > 0 && !voices.some((voice) => voice.id === voiceOptionId)) {
          setVoiceOptionId(voices[0].id);
        }
      } catch {
        setConnection("error");
      }
    })();
  }, [voiceOptionId]);

  // ---------- SSE ----------
  useEffect(() => {
    if (!sessionId) return;
    const stop = connectSse(buildApiUrl(`/sessions/${sessionId}/events`), (ev, data) => {
      if (ev === "speech.started") {
        setIsSpeaking(true);
        subtitleAccRef.current = "";
        setCurrentSubtitle("");
      }
      if (ev === "subtitle.chunk" && data && typeof data === "object") {
        const t = (data as { text?: string }).text;
        if (t) {
          const merged = mergeSubtitleChunk(subtitleAccRef.current, t);
          subtitleAccRef.current = merged;
          setCurrentSubtitle(merged);
        }
      }
      if (ev === "speech.ended") {
        setIsSpeaking(false);
        const finalText = subtitleAccRef.current;
        if (finalText) {
          setMessages((prev) => [
            ...prev,
            { id: makeId(), role: "assistant", text: finalText, timestamp: Date.now() },
          ]);
        }
        setCurrentSubtitle("");
        subtitleAccRef.current = "";
      }
    });
    return stop;
  }, [sessionId]);

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
      const currentAvatar = avatars.find((item) => item.id === avatarId) ?? null;
      const currentVoice = voiceOptions.find((item) => item.id === voiceOptionId) ?? null;
      if (!currentAvatar) {
        throw new Error("No avatar selected");
      }
      const created = await apiPost<CreateSessionResponse>("/sessions", {
        avatar_id: avatarId,
        model: currentAvatar.model_type,
        tts_provider: currentVoice?.provider,
        tts_voice: currentVoice?.voice,
        tts_reference_audio: currentVoice?.reference_audio,
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
  }, [avatarId, avatars, closePeerConnection, releaseSession, resetLiveState, voiceOptionId, voiceOptions]);

  const handleSend = useCallback(
    (text: string) => {
      if (!sessionId || !text) return;
      setMessages((prev) => [
        ...prev,
        { id: makeId(), role: "user", text, timestamp: Date.now() },
      ]);
      void apiPost(`/sessions/${sessionId}/speak`, { text }).catch(() => {
        setConnection("error");
      });
    },
    [sessionId],
  );

  const handleInterrupt = useCallback(() => {
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

  const handleVoiceOptionChange = useCallback(
    (newId: string) => {
      setVoiceOptionId(newId);
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
      <TopBar
        connection={connection}
        onSettingsClick={() => setSettingsOpen(true)}
      />

      {/* Layer 3: Input bar */}
      <ChatInput
        onSend={handleSend}
        onInterrupt={handleInterrupt}
        isSpeaking={isSpeaking}
        disabled={connection !== "live"}
      />

      {/* Layer 4: Start overlay */}
      <StartOverlay
        avatars={avatars}
        avatar={currentAvatar}
        avatarId={avatarId}
        loading={connection === "connecting"}
        onAvatarChange={handleAvatarChange}
        onStart={() => void handleStart()}
        visible={showStart}
      />

      {/* Layer 5: Settings panel */}
      <SettingsPanel
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        avatars={avatars}
        avatarId={avatarId}
        onAvatarChange={handleAvatarChange}
        voiceOptions={voiceOptions}
        voiceOptionId={voiceOptionId}
        onVoiceOptionChange={handleVoiceOptionChange}
      />
    </>
  );
}
