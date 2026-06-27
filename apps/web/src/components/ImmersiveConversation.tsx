import { useEffect, type RefObject } from "react";
import type { TtsProviderExtended } from "../constants/ttsBailian";
import type { SceneBackgroundAsset, SceneComposition } from "../lib/api";
import type { ConnectionStatus } from "../types";
import { ChatInput } from "./ChatInput";
import { SceneStage } from "./SceneStage";

type ImmersiveConversationProps = {
  videoRef: RefObject<HTMLVideoElement>;
  videoStream?: MediaStream | null;
  scene: SceneComposition | null;
  backgrounds: SceneBackgroundAsset[];
  connection: ConnectionStatus;
  sessionId: string | null;
  subtitle: string | null;
  isSpeaking: boolean;
  ttsProvider: TtsProviderExtended;
  sttProvider: string;
  edgeVoice: string;
  qwenModel: string;
  qwenVoice: string;
  onExit: () => void;
  onSend: (text: string) => void;
  onSpeakAudio: (blob: Blob) => void | Promise<void>;
  onSpeakFlashtalkAudioFile?: (file: File) => void | Promise<void>;
  onSpeakAudioStreamResult: (result: { text: string }) => void | Promise<void>;
  onSpeakAudioStreamError: (message: string) => void;
  onInterrupt: () => void;
  onNotify?: (message: string, tone?: "info" | "success" | "error") => void;
};

export function ImmersiveConversation({
  videoRef,
  videoStream = null,
  scene,
  backgrounds,
  connection,
  sessionId,
  subtitle,
  isSpeaking,
  ttsProvider,
  sttProvider,
  edgeVoice,
  qwenModel,
  qwenVoice,
  onExit,
  onSend,
  onSpeakAudio,
  onSpeakFlashtalkAudioFile,
  onSpeakAudioStreamResult,
  onSpeakAudioStreamError,
  onInterrupt,
  onNotify,
}: ImmersiveConversationProps) {
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const editing = target
        ? ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) || target.isContentEditable
        : false;
      if (editing) return;
      if (event.key === "Escape") onExit();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onExit]);

  const live = connection === "live" || connection === "expiring";

  return (
    <main className="relative h-dvh min-h-0 overflow-hidden bg-slate-950 text-white">
      <SceneStage
        videoRef={videoRef}
        videoStream={videoStream}
        scene={scene}
        backgrounds={backgrounds}
        subtitle={subtitle}
        className="h-full w-full"
      >
        <div className="absolute right-0 top-0 z-30 flex h-24 w-48 items-start justify-end p-4">
          <button
            type="button"
            onClick={onExit}
            className="rounded-lg border border-white/15 bg-slate-950/45 px-3 py-2 text-xs font-semibold text-white opacity-0 shadow-lg backdrop-blur transition hover:bg-slate-950/65 hover:opacity-100 focus:opacity-100"
          >
            返回工作台
          </button>
        </div>

        {live ? (
          <div className="absolute inset-x-3 bottom-3 z-30 mx-auto max-w-4xl sm:bottom-5">
            <ChatInput
              onSend={onSend}
              onSpeakAudio={onSpeakAudio}
              onSpeakFlashtalkAudioFile={onSpeakFlashtalkAudioFile}
              streamingAsrSessionId={sessionId}
              onSpeakAudioStreamResult={onSpeakAudioStreamResult}
              onSpeakAudioStreamError={onSpeakAudioStreamError}
              onInterrupt={onInterrupt}
              isSpeaking={isSpeaking}
              disabled={!live}
              onNotify={onNotify}
              ttsProvider={ttsProvider}
              sttProvider={sttProvider}
              edgeVoice={edgeVoice}
              qwenModel={qwenModel}
              qwenVoice={qwenVoice}
            />
          </div>
        ) : null}
      </SceneStage>
    </main>
  );
}
