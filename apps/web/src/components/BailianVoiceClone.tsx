import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent } from "react";
import { apiPostForm } from "../lib/api";
import {
  COSYVOICE_MODEL_OPTIONS,
  LOCAL_COSYVOICE_MODEL_OPTIONS,
  LOCAL_INDEXTTS_MODEL_OPTIONS,
  LOCAL_F5_TTS_MODEL_OPTIONS,
  XIAOMI_MIMO_MODEL_OPTIONS,
} from "../constants/ttsBailian";
import { QWEN_VOICE_CLONE_TARGET_OPTIONS } from "../constants/ttsQwen";
import { resolveVoiceCloneApplication, type VoiceCloneApplication } from "../lib/voiceCloneApply";

/** 固定朗读文案：用于复刻时与百炼侧要求一致 */
export const BAILIAN_CLONE_SAMPLE_TEXT =
  "你好，今天阳光很好，我正在用自然清晰的声音，记录这一段音色。";

function pickRecorderMime(): string | undefined {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"];
  for (const t of candidates) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(t)) {
      return t;
    }
  }
  return undefined;
}

function recorderErrorMessage(error: unknown): string {
  const name = error instanceof DOMException ? error.name : "";
  if (name === "NotAllowedError" || name === "SecurityError") {
    return "麦克风权限被拒绝。请允许浏览器使用麦克风，或请改用上传音频。";
  }
  if (name === "NotFoundError" || name === "DevicesNotFoundError") {
    return "麦克风不可用：没有检测到可用的输入设备，请改用上传音频。";
  }
  if (name === "NotReadableError" || name === "TrackStartError") {
    return "麦克风不可用：设备正被其它程序占用，请关闭占用程序后重试，或请改用上传音频。";
  }
  return "麦克风不可用：浏览器只允许 HTTPS 或 localhost 页面录音，请通过本地隧道打开，或请改用上传音频。";
}

function fileExtFromBlob(blob: Blob): string {
  if (blob instanceof File) return blob.name.split(".").pop()?.toLowerCase() || "webm";
  if (blob.type.includes("wav")) return "wav";
  if (blob.type.includes("mpeg") || blob.type.includes("mp3")) return "mp3";
  if (blob.type.includes("ogg")) return "ogg";
  return "webm";
}

type CloneProvider =
  | "dashscope"
  | "cosyvoice"
  | "local_cosyvoice"
  | "indextts"
  | "local_f5_tts"
  | "xiaomi_mimo";
type RecorderPhase = "idle" | "recording" | "paused" | "recorded";

function defaultTargetModelForProvider(provider: CloneProvider): string {
  if (provider === "dashscope") return QWEN_VOICE_CLONE_TARGET_OPTIONS[0]?.id ?? "";
  if (provider === "xiaomi_mimo") return "mimo-v2.5-tts-voiceclone";
  if (provider === "local_cosyvoice") return LOCAL_COSYVOICE_MODEL_OPTIONS[0]?.id ?? "";
  if (provider === "indextts") {
    return LOCAL_INDEXTTS_MODEL_OPTIONS[0]?.id ?? "";
  }
  if (provider === "local_f5_tts") return LOCAL_F5_TTS_MODEL_OPTIONS[0]?.id ?? "";
  return COSYVOICE_MODEL_OPTIONS[0]?.id ?? "";
}

function formatDuration(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(totalSeconds / 60).toString().padStart(2, "0");
  const s = (totalSeconds % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

interface BailianVoiceCloneProps {
  onSuccess: (application: VoiceCloneApplication) => void | Promise<void>;
  onClose: () => void;
}

export function BailianVoiceClone({ onSuccess, onClose }: BailianVoiceCloneProps) {
  const [provider, setProvider] = useState<CloneProvider>("dashscope");
  const [targetModel, setTargetModel] = useState(() => defaultTargetModelForProvider("dashscope"));
  const [promptText, setPromptText] = useState(BAILIAN_CLONE_SAMPLE_TEXT);
  const [displayLabel, setDisplayLabel] = useState("我的复刻音色");
  const [prefix, setPrefix] = useState("");
  const [preferredName, setPreferredName] = useState("");
  const [recorderPhase, setRecorderPhase] = useState<RecorderPhase>("idle");
  const [elapsedMs, setElapsedMs] = useState(0);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [playbackTime, setPlaybackTime] = useState(0);
  const [playbackEnded, setPlaybackEnded] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const mrRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const timerRef = useRef<ReturnType<typeof window.setInterval> | null>(null);
  const recordStartedAtRef = useRef(0);
  const elapsedBeforePauseRef = useRef(0);

  const waveBars = useMemo(() => Array.from({ length: 32 }, (_, i) => 18 + ((i * 17) % 38)), []);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const stopTracks = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  const revokeAudioUrl = useCallback(() => {
    if (audioUrl) URL.revokeObjectURL(audioUrl);
  }, [audioUrl]);

  const onProviderChange = (p: CloneProvider) => {
    setProvider(p);
    setTargetModel(defaultTargetModelForProvider(p));
  };

  useEffect(() => {
    return () => {
      clearTimer();
      stopTracks();
      if (audioUrl) URL.revokeObjectURL(audioUrl);
    };
  }, [audioUrl, clearTimer, stopTracks]);

  const stopRecording = useCallback(async () => {
    const mr = mrRef.current;
    if (!mr || mr.state === "inactive") {
      mrRef.current = null;
      stopTracks();
      clearTimer();
      setRecorderPhase("idle");
      return;
    }
    const wasPaused = mr.state === "paused";
    await new Promise<void>((resolve) => {
      mr.onstop = () => resolve();
      try {
        mr.stop();
      } catch {
        resolve();
      }
    });
    mrRef.current = null;
    stopTracks();
    clearTimer();
    const duration =
      elapsedBeforePauseRef.current + (wasPaused ? 0 : Math.max(0, Date.now() - recordStartedAtRef.current));
    elapsedBeforePauseRef.current = duration;
    setElapsedMs(duration);
    const mime = mr.mimeType || "audio/webm";
    const b = new Blob(chunksRef.current, { type: mime });
    chunksRef.current = [];
    setBlob(b);
    revokeAudioUrl();
    setAudioUrl(URL.createObjectURL(b));
    setPlaybackTime(0);
    setPlaybackEnded(false);
    setPlaying(false);
    setRecorderPhase("recorded");
  }, [clearTimer, revokeAudioUrl, stopTracks]);

  const deleteRecording = useCallback(() => {
    const mr = mrRef.current;
    if (mr && mr.state !== "inactive") {
      try {
        mr.stop();
      } catch {
        /* ignore */
      }
    }
    mrRef.current = null;
    chunksRef.current = [];
    stopTracks();
    clearTimer();
    revokeAudioUrl();
    setBlob(null);
    setAudioUrl(null);
    setElapsedMs(0);
    elapsedBeforePauseRef.current = 0;
    recordStartedAtRef.current = 0;
    setPlaybackTime(0);
    setPlaybackEnded(false);
    setPlaying(false);
    setRecorderPhase("idle");
  }, [clearTimer, revokeAudioUrl, stopTracks]);

  const startRecording = useCallback(async () => {
    setMessage(null);
    deleteRecording();
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setMessage(recorderErrorMessage(new DOMException("media devices unavailable", "NotAllowedError")));
      return;
    }
    try {
      chunksRef.current = [];
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mime = pickRecorderMime();
      const mr = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      mrRef.current = mr;
      mr.ondataavailable = (ev) => {
        if (ev.data.size > 0) chunksRef.current.push(ev.data);
      };
      mr.start(200);
      elapsedBeforePauseRef.current = 0;
      recordStartedAtRef.current = Date.now();
      setElapsedMs(0);
      setRecorderPhase("recording");
      timerRef.current = window.setInterval(() => {
        setElapsedMs(elapsedBeforePauseRef.current + Math.max(0, Date.now() - recordStartedAtRef.current));
      }, 250);
    } catch (e) {
      stopTracks();
      clearTimer();
      chunksRef.current = [];
      mrRef.current = null;
      setRecorderPhase("idle");
      setMessage(recorderErrorMessage(e));
    }
  }, [clearTimer, deleteRecording, stopTracks]);

  const handleAudioFileChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.currentTarget.files?.[0];
      event.currentTarget.value = "";
      if (!file) return;
      deleteRecording();
      setBlob(file);
      revokeAudioUrl();
      setAudioUrl(URL.createObjectURL(file));
      setElapsedMs(0);
      setPlaybackTime(0);
      setPlaybackEnded(false);
      setPlaying(false);
      setRecorderPhase("recorded");
      setMessage("已选择上传音频，可试听后上传并复刻。");
    },
    [deleteRecording, revokeAudioUrl],
  );

  const pauseRecording = useCallback(() => {
    const mr = mrRef.current;
    if (!mr || mr.state !== "recording") return;
    mr.pause();
    elapsedBeforePauseRef.current += Math.max(0, Date.now() - recordStartedAtRef.current);
    recordStartedAtRef.current = 0;
    setElapsedMs(elapsedBeforePauseRef.current);
    clearTimer();
    setRecorderPhase("paused");
  }, [clearTimer]);

  const resumeRecording = useCallback(() => {
    const mr = mrRef.current;
    if (!mr || mr.state !== "paused") return;
    mr.resume();
    recordStartedAtRef.current = Date.now();
    setRecorderPhase("recording");
    timerRef.current = window.setInterval(() => {
      setElapsedMs(elapsedBeforePauseRef.current + Math.max(0, Date.now() - recordStartedAtRef.current));
    }, 250);
  }, []);

  const togglePlayback = useCallback(async () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) {
      if (audio.ended) {
        audio.currentTime = 0;
        setPlaybackTime(0);
        setPlaybackEnded(false);
      }
      await audio.play();
    } else {
      audio.pause();
    }
  }, []);

  const submit = useCallback(async () => {
    if (!blob || blob.size < 64) {
      setMessage("请先录制一段音频");
      return;
    }
    if (!targetModel.trim()) {
      setMessage("请选择目标模型");
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const ext = fileExtFromBlob(blob);
      const fd = new FormData();
      fd.append("provider", provider);
      fd.append("target_model", targetModel.trim());
      fd.append("display_label", displayLabel.trim() || "我的复刻音色");
      fd.append("audio", blob, `sample.${ext}`);
      fd.append("prefix", prefix.trim());
      fd.append("preferred_name", preferredName.trim());
      fd.append("prompt_text", promptText.trim() || BAILIAN_CLONE_SAMPLE_TEXT);
      const res = await apiPostForm<{
        ok?: boolean;
        message?: string;
        voice_id?: string;
        display_label?: string;
      }>("/voices/clone", fd);
      const voiceId = res.voice_id?.trim();
      if (!voiceId) {
        throw new Error(res.message ?? "音色复刻成功，但服务端未返回 voice_id");
      }
      const resolvedDisplayLabel = res.display_label?.trim() || displayLabel.trim() || "我的复刻音色";
      await onSuccess(
        resolveVoiceCloneApplication({
          provider,
          targetModel: targetModel.trim(),
          displayLabel: resolvedDisplayLabel,
          voiceId,
        }),
      );
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [blob, displayLabel, onSuccess, preferredName, prefix, promptText, provider, targetModel]);

  return (
    <div className="mx-auto max-w-xl rounded-lg border border-slate-200 bg-white text-sm text-slate-800 shadow-sm shadow-slate-200/70">
      <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-4 py-3">
        <div>
          <p className="text-xs font-medium text-slate-500">语音合成</p>
          <h2 className="mt-0.5 text-base font-semibold text-slate-950">音色复刻</h2>
        </div>
        <button
          type="button"
          className="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-slate-50"
          onClick={onClose}
        >
          关闭
        </button>
      </div>

      <div className="space-y-4 p-4">
        <div>
          <p className="text-xs leading-relaxed text-slate-500">
            请朗读下方固定文案并录音。本地 CosyVoice 和 IndexTTS 会保存到本机模型目录；千问和小米 MiMo 复刻走 base64，内网可用；云端 CosyVoice 需本服务对公网可访问或配置{" "}
            <code className="rounded bg-slate-100 px-1 py-0.5 text-slate-700">OPENTALKING_PUBLIC_BASE_URL</code>。
          </p>
          <div className="mt-3 rounded-lg border border-cyan-300 bg-cyan-50 shadow-sm shadow-cyan-100/70">
            <div className="flex items-center justify-between border-b border-cyan-200 px-3 py-2">
              <span className="text-xs font-bold text-cyan-900">朗读文本</span>
              <span className="text-[11px] font-medium text-cyan-700">请完整读出</span>
            </div>
            <blockquote className="px-3 py-2 text-sm font-semibold leading-relaxed text-cyan-950">
              {BAILIAN_CLONE_SAMPLE_TEXT}
            </blockquote>
          </div>
          {provider === "local_cosyvoice" ? (
            <label className="mt-3 block">
              <span className="mb-1.5 block text-xs font-medium text-slate-500">本地 CosyVoice 参考文本</span>
              <textarea
                className="min-h-20 w-full resize-y rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm leading-relaxed text-slate-800 outline-none transition focus:border-cyan-300 focus:bg-white"
                value={promptText}
                onChange={(e) => setPromptText(e.target.value)}
                disabled={busy}
              />
              <span className="mt-1 block text-[11px] leading-relaxed text-slate-500">
                本地 CosyVoice 会用这段文本对齐参考音频；请让录音内容和文本一致，并先试听确认声音清晰。
              </span>
            </label>
          ) : null}
        </div>

        <div className="grid gap-3 text-xs sm:grid-cols-2">
          <label className="block">
            <span className="mb-1.5 block text-slate-500">线路</span>
            <select
              className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-800 outline-none transition focus:border-cyan-300 focus:bg-white"
              value={provider}
              onChange={(e) => onProviderChange(e.target.value as CloneProvider)}
              disabled={busy}
            >
              <option value="dashscope">千问（百炼复刻）</option>
              <option value="xiaomi_mimo">小米 MiMo VoiceClone</option>
              <option value="local_cosyvoice">本地 CosyVoice</option>
              <option value="indextts">Local IndexTTS</option>
              <option value="local_f5_tts">Local F5-TTS</option>
              <option value="cosyvoice">云端 CosyVoice</option>
            </select>
          </label>
          <label className="block">
            <span className="mb-1.5 block text-slate-500">目标模型</span>
            <select
              className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-800 outline-none transition focus:border-cyan-300 focus:bg-white"
              value={targetModel}
              onChange={(e) => setTargetModel(e.target.value)}
              disabled={busy}
            >
              {(provider === "dashscope"
                ? QWEN_VOICE_CLONE_TARGET_OPTIONS
                : provider === "xiaomi_mimo"
                  ? XIAOMI_MIMO_MODEL_OPTIONS.filter((option) => option.id === "mimo-v2.5-tts-voiceclone")
                : provider === "local_cosyvoice"
                  ? LOCAL_COSYVOICE_MODEL_OPTIONS
                : provider === "indextts"
                  ? LOCAL_INDEXTTS_MODEL_OPTIONS
                : provider === "local_f5_tts"
                  ? LOCAL_F5_TTS_MODEL_OPTIONS
                  : COSYVOICE_MODEL_OPTIONS
              ).map((o) => (
                <option key={o.id} value={o.id}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="grid gap-3 text-xs sm:grid-cols-2">
          <label className="block">
            <span className="mb-1.5 block text-slate-500">显示名称</span>
            <input
              className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-800 outline-none transition focus:border-cyan-300 focus:bg-white"
              value={displayLabel}
              onChange={(e) => setDisplayLabel(e.target.value)}
              disabled={busy}
            />
          </label>
          {provider === "cosyvoice" ? (
            <label className="block">
              <span className="mb-1.5 block text-slate-500">前缀 prefix（可选，小写字母数字）</span>
              <input
                className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-800 outline-none transition focus:border-cyan-300 focus:bg-white"
                value={prefix}
                onChange={(e) => setPrefix(e.target.value)}
                placeholder="留空则自动生成"
                disabled={busy}
              />
            </label>
          ) : (
            <label className="block">
              <span className="mb-1.5 block text-slate-500">preferred_name（可选，小写）</span>
              <input
                className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-800 outline-none transition focus:border-cyan-300 focus:bg-white"
                value={preferredName}
                onChange={(e) => setPreferredName(e.target.value)}
                placeholder="留空则自动生成"
                disabled={busy}
              />
            </label>
          )}
        </div>

        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <span
                className={`h-2.5 w-2.5 rounded-full ${
                  recorderPhase === "recording"
                    ? "animate-pulse bg-rose-500"
                    : recorderPhase === "recorded"
                      ? "bg-emerald-500"
                      : "bg-slate-300"
                }`}
              />
              <span className="text-xs font-semibold text-slate-700">
                {recorderPhase === "recording"
                  ? "录制中"
                  : recorderPhase === "paused"
                    ? "已暂停"
                    : recorderPhase === "recorded"
                      ? "已录制"
                      : "未录制"}
              </span>
            </div>
            <span className="font-mono text-xs text-slate-500">
              {formatDuration(recorderPhase === "recorded" ? playbackTime * 1000 : elapsedMs)}
              {recorderPhase === "recorded" ? ` / ${formatDuration(elapsedMs)}` : ""}
            </span>
          </div>

          <div className="flex flex-wrap gap-2">
            {recorderPhase === "idle" ? (
              <button
                type="button"
                className="rounded-lg bg-emerald-600 px-4 py-2 text-xs font-semibold text-white transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
                disabled={busy}
                onClick={() => void startRecording()}
              >
                开始录音
              </button>
            ) : null}
            <label className="cursor-pointer rounded-lg border border-slate-200 bg-white px-4 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-50">
              上传音频文件
              <input
                type="file"
                className="sr-only"
                accept="audio/*,.webm,.mp3,.wav,.m4a,.aac,.flac,.ogg"
                disabled={busy}
                onChange={handleAudioFileChange}
              />
            </label>
          </div>
          {recorderPhase === "idle" ? (
            <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
              远程 HTTP 页面可能无法直接录音；如果点击无响应，请改用上传音频。上传前请试听，静音或声音太小会被拒绝。
            </p>
          ) : null}

          {recorderPhase === "recording" || recorderPhase === "paused" ? (
            <div className="space-y-3">
              <div className="flex h-12 items-center gap-1 rounded-lg border border-slate-200 bg-white px-3">
                {waveBars.map((h, i) => (
                  <span
                    key={i}
                    className={`w-1 rounded-full bg-cyan-500 ${recorderPhase === "recording" ? "animate-pulse" : "opacity-40"}`}
                    style={{
                      height: `${h}%`,
                      animationDelay: `${(i % 8) * 80}ms`,
                    }}
                  />
                ))}
              </div>
              <div className="flex flex-wrap gap-2">
                {recorderPhase === "recording" ? (
                  <button
                    type="button"
                    className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-50"
                    onClick={pauseRecording}
                  >
                    暂停
                  </button>
                ) : (
                  <button
                    type="button"
                    className="rounded-lg bg-emerald-600 px-4 py-2 text-xs font-semibold text-white transition hover:bg-emerald-500"
                    onClick={resumeRecording}
                  >
                    继续
                  </button>
                )}
                <button
                  type="button"
                  className="rounded-lg bg-rose-600 px-4 py-2 text-xs font-semibold text-white transition hover:bg-rose-500"
                  onClick={() => void stopRecording()}
                >
                  停止
                </button>
                <button
                  type="button"
                  className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-xs font-semibold text-slate-600 transition hover:bg-slate-50"
                  onClick={deleteRecording}
                >
                  删除
                </button>
              </div>
            </div>
          ) : null}

          {recorderPhase === "recorded" && audioUrl ? (
            <div className="space-y-3">
              <audio
                ref={audioRef}
                src={audioUrl}
                preload="metadata"
                onLoadedMetadata={(e) => {
                  const duration = e.currentTarget.duration;
                  if (Number.isFinite(duration) && duration > 0) {
                    setElapsedMs(duration * 1000);
                  }
                }}
                onTimeUpdate={(e) => {
                  setPlaybackTime(e.currentTarget.currentTime);
                  if (!e.currentTarget.ended) setPlaybackEnded(false);
                }}
                onPlay={() => {
                  setPlaying(true);
                  setPlaybackEnded(false);
                }}
                onPause={() => setPlaying(false)}
                onEnded={() => {
                  setPlaying(false);
                  setPlaybackEnded(true);
                  setPlaybackTime(elapsedMs / 1000);
                }}
              />
              <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2">
                <button
                  type="button"
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-slate-950 text-xs font-semibold text-white"
                  onClick={() => void togglePlayback()}
                >
                  {playing ? "Ⅱ" : "▶"}
                </button>
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
                  <div
                    className="h-full rounded-full bg-cyan-500"
                    style={{
                      width: `${playbackEnded ? 100 : Math.min(100, Math.max(0, (playbackTime / Math.max(0.1, elapsedMs / 1000)) * 100))}%`,
                    }}
                  />
                </div>
                <span className="text-xs text-slate-500">{Math.round((blob?.size ?? 0) / 1024)} KB</span>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-50"
                  onClick={() => void startRecording()}
                  disabled={busy}
                >
                  重录
                </button>
                <button
                  type="button"
                  className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-xs font-semibold text-slate-600 transition hover:bg-slate-50"
                  onClick={deleteRecording}
                  disabled={busy}
                >
                  删除
                </button>
                <button
                  type="button"
                  className="rounded-lg border border-cyan-200 bg-cyan-50 px-4 py-2 text-xs font-semibold text-cyan-700 transition hover:bg-cyan-100 disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={busy || !blob}
                  onClick={() => void submit()}
                >
                  {busy ? "提交中…" : "上传并复刻"}
                </button>
              </div>
            </div>
          ) : null}
        </div>
      {message ? (
        <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-800">
          {message}
        </p>
      ) : null}
      </div>
    </div>
  );
}
