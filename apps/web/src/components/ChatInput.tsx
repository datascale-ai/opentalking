import {
  useRef,
  useState,
  useCallback,
  useEffect,
  type KeyboardEvent,
  type MutableRefObject,
} from "react";
import { getVoiceVadConfig } from "../config/voiceVad";
import { isEdgeTts, type TtsProviderExtended } from "../constants/ttsBailian";
import { buildWsUrl } from "../lib/api";

/** 浏览器 AudioContext 采样率 → 16kHz PCM（与 DashScope 流式 ASR 约定一致） */
const TARGET_SR = 16000;

function floatToInt16Buffer(input: Float32Array): ArrayBuffer {
  const buf = new ArrayBuffer(input.length * 2);
  const view = new DataView(buf);
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]));
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return buf;
}

/** 流式 STT：等待服务端 JSON；无超时会导致 uploadLock 永不释放，VAD 永久卡死 */
const STT_WS_REPLY_MS = 55_000;

async function awaitSttWsReply(ws: WebSocket): Promise<{ text?: string; error?: string }> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const settle = (fn: () => void) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      fn();
    };
    const timer = window.setTimeout(() => {
      settle(() =>
        reject(
          new Error(
            `语音识别等待超时（${STT_WS_REPLY_MS / 1000}s）。若后端无 STT 日志，多为连接未到达服务或 DashScope 阻塞。`,
          ),
        ),
      );
    }, STT_WS_REPLY_MS);

    ws.onmessage = (ev) => {
      settle(() => {
        ws.onclose = null;
        try {
          resolve(JSON.parse(ev.data as string) as { text?: string; error?: string });
        } catch {
          reject(new Error("服务器返回非 JSON"));
        }
      });
    };
    ws.onerror = () => settle(() => reject(new Error("WebSocket 出错")));
    ws.onclose = () => {
      settle(() => reject(new Error("连接在收到结果前已关闭")));
    };

    try {
      ws.send(JSON.stringify({ type: "end" }));
    } catch (e) {
      settle(() => reject(e instanceof Error ? e : new Error(String(e))));
    }
  });
}

function downsampleFloat32To16kPcm(input: Float32Array, inputRate: number): ArrayBuffer {
  if (inputRate === TARGET_SR) {
    return floatToInt16Buffer(input);
  }
  const ratio = inputRate / TARGET_SR;
  const outLen = Math.floor(input.length / ratio);
  const out = new Float32Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const srcPos = i * ratio;
    const i0 = Math.floor(srcPos);
    const frac = srcPos - i0;
    const a = input[i0] ?? 0;
    const b = input[i0 + 1] ?? a;
    out[i] = a * (1 - frac) + b * frac;
  }
  return floatToInt16Buffer(out);
}

interface ChatInputProps {
  onSend: (text: string) => void;
  onSpeakAudio?: (blob: Blob) => void | Promise<void>;
  /** 与 streamingAsrSessionId 同时传入时，语音走 WS 流式 PCM → 后端流式 ASR */
  onSpeakAudioStreamResult?: (payload: { text: string }) => void | Promise<void>;
  /** 当前会话 id（live 时）：启用真流式 STT */
  streamingAsrSessionId?: string | null;
  onInterrupt: () => void;
  isSpeaking: boolean;
  disabled: boolean;
  /** 底部「打开设置」快捷入口（TTS 已迁入设置侧栏） */
  onOpenSettings?: () => void;
  /** 当前 TTS 选项（用于识别上传 / WS meta；控件在设置侧栏） */
  ttsProvider?: TtsProviderExtended;
  edgeVoice?: string;
  qwenModel?: string;
  qwenVoice?: string;
}

function pickRecorderMime(): string | undefined {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"];
  for (const t of candidates) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(t)) {
      return t;
    }
  }
  return undefined;
}

/** 流式 STT：在 VAD 攻击帧确认前保留最近 PCM，连接建立后先补发，减轻句首丢失 */
const PCM_PREROLL_MAX_SAMPLES = 6400; // 400ms @ 16kHz

function appendPcmPrerollChunk(pcmAb: ArrayBuffer, store: MutableRefObject<Int16Array>) {
  const add = new Int16Array(pcmAb);
  if (add.length === 0) return;
  const cur = store.current;
  const merged = new Int16Array(cur.length + add.length);
  merged.set(cur, 0);
  merged.set(add, cur.length);
  store.current =
    merged.length > PCM_PREROLL_MAX_SAMPLES
      ? merged.subarray(merged.length - PCM_PREROLL_MAX_SAMPLES)
      : merged;
}

function computeRms(analyser: AnalyserNode): number {
  const buf = new Float32Array(analyser.fftSize);
  analyser.getFloatTimeDomainData(buf);
  let sum = 0;
  for (let i = 0; i < buf.length; i++) {
    const x = buf[i];
    sum += x * x;
  }
  return Math.sqrt(sum / buf.length);
}

export function ChatInput({
  onSend,
  onSpeakAudio,
  onSpeakAudioStreamResult,
  streamingAsrSessionId = null,
  onInterrupt,
  isSpeaking,
  disabled,
  onOpenSettings,
  ttsProvider = "edge",
  edgeVoice = "",
  qwenModel = "",
  qwenVoice = "",
}: ChatInputProps) {
  const voiceCaptureEnabled = !!(
    onSpeakAudio ||
    (streamingAsrSessionId && onSpeakAudioStreamResult)
  );
  const [text, setText] = useState("");
  const [voiceMode, setVoiceMode] = useState(false);
  const [segmentHot, setSegmentHot] = useState(false);
  const [voiceBusy, setVoiceBusy] = useState(false);

  const vadCfg = useRef(getVoiceVadConfig());
  useEffect(() => {
    vadCfg.current = getVoiceVadConfig();
  }, []);

  useEffect(() => {
    voiceModeRef.current = voiceMode;
  }, [voiceMode]);

  const streamRef = useRef<MediaStream | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const rafRef = useRef<number>(0);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);

  /** 流式 STT：WebSocket + ScriptProcessor */
  const streamWsRef = useRef<WebSocket | null>(null);
  const pcmSendGateRef = useRef(false);
  /** WebSocket 尚未接通时避免重复触发 startSegment（否则会并发多条连接，VAD 仍停留在「未起段」分支） */
  const segmentConnectingRef = useRef(false);
  /** ScriptProcessor 成功时才走 WS 流式；失败则回退 MediaRecorder + speak_audio */
  const pcmStreamAvailableRef = useRef(false);
  const scriptProcessorRef = useRef<ScriptProcessorNode | null>(null);
  const streamMuteRef = useRef<GainNode | null>(null);
  const voiceModeRef = useRef(false);
  const pcmPrerollRef = useRef<Int16Array>(new Int16Array(0));

  const segmentActiveRef = useRef(false);
  const loudFramesRef = useRef(0);
  const silenceStartRef = useRef<number | null>(null);
  const segmentStartTsRef = useRef<number>(0);
  const uploadLockRef = useRef(false);
  /** 用户点「打断」时递增，用于丢弃 VAD 已触发的断句上传 */
  const voiceBreakGenRef = useRef(0);

  const uiRef = useRef({ disabled, voiceBusy, isSpeaking });
  uiRef.current = { disabled, voiceBusy, isSpeaking };

  const onSpeakAudioRef = useRef(onSpeakAudio);
  onSpeakAudioRef.current = onSpeakAudio;

  const onSpeakAudioStreamResultRef = useRef(onSpeakAudioStreamResult);
  onSpeakAudioStreamResultRef.current = onSpeakAudioStreamResult;

  const onInterruptRef = useRef(onInterrupt);
  onInterruptRef.current = onInterrupt;

  const stopVadLoop = useCallback(() => {
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = 0;
    }
  }, []);

  const stopSegmentRecorder = useCallback(async (): Promise<Blob | null> => {
    /** 仅当真开过 WS 录音时才走流式收尾；否则会误伤 MediaRecorder 回退路径（此前无音频上传） */
    if (streamWsRef.current) {
      pcmSendGateRef.current = false;
      const ws = streamWsRef.current;
      streamWsRef.current = null;
      segmentActiveRef.current = false;
      setSegmentHot(false);
      if (ws.readyState !== WebSocket.OPEN) {
        try {
          ws.close();
        } catch {
          /* ignore */
        }
        return null;
      }
      const reply = await awaitSttWsReply(ws);
      try {
        ws.close();
      } catch {
        /* ignore */
      }
      if (reply.error) {
        throw new Error(reply.error);
      }
      const t = (reply.text ?? "").trim();
      if (t && onSpeakAudioStreamResultRef.current) {
        await onSpeakAudioStreamResultRef.current({ text: t });
      }
      return null;
    }

    const mr = mediaRecorderRef.current;
    if (!mr || mr.state === "inactive") {
      segmentActiveRef.current = false;
      setSegmentHot(false);
      return null;
    }
    const mime = mr.mimeType || "audio/webm";
    try {
      if (mr.state === "recording") mr.requestData();
    } catch {
      /* ignore */
    }
    await new Promise<void>((resolve) => {
      mr.onstop = () => resolve();
      mr.stop();
    });
    mediaRecorderRef.current = null;
    segmentActiveRef.current = false;
    setSegmentHot(false);

    const parts = chunksRef.current;
    chunksRef.current = [];
    const blob = new Blob(parts, { type: mime });
    if (blob.size < 256) return null;
    return blob;
  }, []);

  /** 不打断、不识别，直接丢掉当前正在录的片段 */
  const discardActiveSegment = useCallback(async () => {
    if (streamWsRef.current) {
      pcmSendGateRef.current = false;
      segmentConnectingRef.current = false;
      try {
        streamWsRef.current.close();
      } catch {
        /* ignore */
      }
      streamWsRef.current = null;
      segmentActiveRef.current = false;
      setSegmentHot(false);
      return;
    }

    const mr = mediaRecorderRef.current;
    if (!mr || mr.state === "inactive") {
      segmentActiveRef.current = false;
      setSegmentHot(false);
      return;
    }
    await new Promise<void>((resolve) => {
      mr.onstop = () => resolve();
      try {
        if (mr.state === "recording") mr.stop();
      } catch {
        /* ignore */
      }
    });
    mediaRecorderRef.current = null;
    chunksRef.current = [];
    segmentActiveRef.current = false;
    setSegmentHot(false);
  }, []);

  const teardownVoicePipeline = useCallback(async () => {
    voiceBreakGenRef.current += 1;
    stopVadLoop();
    uploadLockRef.current = false;
    pcmSendGateRef.current = false;
    segmentConnectingRef.current = false;
    try {
      await stopSegmentRecorder();
    } catch {
      /* stopSegmentRecorder may throw on WS error */
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (audioCtxRef.current) {
      try {
        await audioCtxRef.current.close();
      } catch {
        /* ignore */
      }
      audioCtxRef.current = null;
    }
    analyserRef.current = null;
    scriptProcessorRef.current = null;
    streamMuteRef.current = null;
    pcmStreamAvailableRef.current = false;
    pcmPrerollRef.current = new Int16Array(0);
    loudFramesRef.current = 0;
    silenceStartRef.current = null;
    setVoiceMode(false);
    setSegmentHot(false);
  }, [stopSegmentRecorder, stopVadLoop]);

  const startSegmentRecorder = useCallback(
    async (stream: MediaStream) => {
      if (
        streamingAsrSessionId &&
        onSpeakAudioStreamResultRef.current &&
        pcmStreamAvailableRef.current
      ) {
        if (streamWsRef.current || segmentConnectingRef.current) return;
        segmentConnectingRef.current = true;
        segmentActiveRef.current = true;
        segmentStartTsRef.current = performance.now();
        silenceStartRef.current = null;
        setSegmentHot(true);
        try {
          const url = buildWsUrl(`/sessions/${streamingAsrSessionId}/speak_audio_stream`);
          const ws = new WebSocket(url);
          await new Promise<void>((resolve, reject) => {
            ws.onopen = () => resolve();
            ws.onerror = () => reject(new Error("WebSocket 连接失败"));
          });
          ws.send(
            JSON.stringify({
              type: "meta",
              voice: isEdgeTts(ttsProvider)
                ? edgeVoice ?? ""
                : ttsProvider === "sambert"
                  ? ""
                  : qwenVoice ?? "",
              tts_provider: ttsProvider,
              tts_model: !isEdgeTts(ttsProvider) ? qwenModel ?? "" : "",
            }),
          );
          const pre = pcmPrerollRef.current;
          pcmPrerollRef.current = new Int16Array(0);
          const step = 3200;
          for (let i = 0; i < pre.length; i += step) {
            const chunk = pre.subarray(i, Math.min(i + step, pre.length));
            ws.send(chunk.buffer.slice(chunk.byteOffset, chunk.byteOffset + chunk.byteLength));
          }
          streamWsRef.current = ws;
          pcmSendGateRef.current = true;
        } catch (e) {
          console.warn("streaming ASR WebSocket failed", e);
          streamWsRef.current = null;
          pcmSendGateRef.current = false;
          segmentActiveRef.current = false;
          setSegmentHot(false);
        } finally {
          segmentConnectingRef.current = false;
        }
        return;
      }

      if (mediaRecorderRef.current) return;
      const mime = pickRecorderMime();
      const mr = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      chunksRef.current = [];
      mr.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      mr.start();
      mediaRecorderRef.current = mr;
      segmentActiveRef.current = true;
      segmentStartTsRef.current = performance.now();
      silenceStartRef.current = null;
      setSegmentHot(true);
    },
    [
      edgeVoice,
      qwenModel,
      qwenVoice,
      streamingAsrSessionId,
      ttsProvider,
    ],
  );

  const vadTick = useCallback(() => {
    const stream = streamRef.current;
    const analyser = analyserRef.current;
    /** 仅传流式回调、不传 onSpeakAudio 时也必须跑 VAD（原先误用 speakFn 导致 RMS 一整段不工作） */
    const voiceCaptureOk =
      !!onSpeakAudioRef.current || !!onSpeakAudioStreamResultRef.current;
    if (!stream || !analyser || !voiceCaptureOk) {
      return;
    }

    const cfg = vadCfg.current;
    const rms = computeRms(analyser);
    const now = performance.now();
    const { disabled: d, voiceBusy: vb, isSpeaking: spk } = uiRef.current;

    /** 上传中 / 禁用 时整段暂停；播报中不整段暂停，改用更高阈值的抢话检测 */
    const hardPaused = d || vb || uploadLockRef.current;
    if (!hardPaused) {
      /** 数字人正在出声时，用更高能量 + 更长连帧判定抢话，减轻扬声器回声误触 */
      const bargeMode = spk;

      if (!segmentActiveRef.current) {
        const speechTh = bargeMode ? cfg.bargeInSpeechRms : cfg.speechRms;
        const attackNeed = bargeMode ? cfg.bargeInAttackFrames : cfg.attackFrames;
        if (rms >= speechTh) {
          loudFramesRef.current += 1;
          if (loudFramesRef.current >= attackNeed) {
            if (bargeMode) {
              voiceBreakGenRef.current += 1;
              uploadLockRef.current = false;
              onInterruptRef.current();
            }
            void (async () => {
              await startSegmentRecorder(stream);
              loudFramesRef.current = 0;
            })();
          }
        } else {
          loudFramesRef.current = 0;
        }
      } else {
        if (rms <= cfg.silenceRms) {
          if (silenceStartRef.current === null) {
            silenceStartRef.current = now;
          }
          const silentFor = now - silenceStartRef.current;
          const segDur = now - segmentStartTsRef.current;
          if (silentFor >= cfg.silenceMs && segDur >= cfg.minSegmentMs) {
            const startedGen = voiceBreakGenRef.current;
            uploadLockRef.current = true;
            void (async () => {
              try {
                const blob = await stopSegmentRecorder();
                if (startedGen !== voiceBreakGenRef.current) return;
                if (blob && onSpeakAudioRef.current) {
                  setVoiceBusy(true);
                  try {
                    if (startedGen !== voiceBreakGenRef.current) return;
                    await onSpeakAudioRef.current(blob);
                  } finally {
                    setVoiceBusy(false);
                  }
                }
              } catch (err) {
                console.warn("voice segment failed", err);
              } finally {
                uploadLockRef.current = false;
              }
            })();
          }
        } else {
          silenceStartRef.current = null;
        }
      }
    }

    rafRef.current = requestAnimationFrame(vadTick);
  }, [startSegmentRecorder, stopSegmentRecorder]);

  const enterVoiceMode = useCallback(async () => {
    if (!voiceCaptureEnabled || disabled) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      streamRef.current = stream;

      const AC =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      const ctx = new AC();
      audioCtxRef.current = ctx;
      if (ctx.state === "suspended") {
        await ctx.resume();
      }

      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0.35;
      source.connect(analyser);
      analyserRef.current = analyser;

      if (streamingAsrSessionId && onSpeakAudioStreamResult) {
        try {
          const SP = ctx.createScriptProcessor(4096, 1, 1);
          scriptProcessorRef.current = SP;
          const mute = ctx.createGain();
          mute.gain.value = 0;
          streamMuteRef.current = mute;
          SP.onaudioprocess = (e) => {
            const input = e.inputBuffer.getChannelData(0);
            const pcm = downsampleFloat32To16kPcm(input, ctx.sampleRate);
            if (voiceModeRef.current && !pcmSendGateRef.current) {
              appendPcmPrerollChunk(pcm, pcmPrerollRef);
            }
            if (!pcmSendGateRef.current) return;
            const w = streamWsRef.current;
            if (!w || w.readyState !== WebSocket.OPEN) return;
            w.send(pcm);
          };
          SP.connect(mute);
          mute.connect(ctx.destination);
          source.connect(SP);
          pcmStreamAvailableRef.current = true;
        } catch (spErr) {
          pcmStreamAvailableRef.current = false;
          console.warn(
            "ScriptProcessor 不可用，连续语音将回退为录音上传（非实时流式）。",
            spErr,
          );
        }
      } else {
        pcmStreamAvailableRef.current = false;
      }

      loudFramesRef.current = 0;
      silenceStartRef.current = null;
      segmentActiveRef.current = false;

      setVoiceMode(true);
      rafRef.current = requestAnimationFrame(vadTick);
    } catch (e) {
      console.warn("Voice mode failed", e);
      window.alert(
        "无法使用麦克风。请用 localhost 或 HTTPS 打开页面，并允许麦克风权限（纯 IP 的 HTTP 多半会被浏览器拦截）。",
      );
    }
  }, [
    disabled,
    onSpeakAudioStreamResult,
    streamingAsrSessionId,
    vadTick,
    voiceCaptureEnabled,
  ]);

  const toggleVoiceMode = useCallback(async () => {
    if (!voiceCaptureEnabled || disabled) return;
    if (voiceBusy) return;
    if (voiceMode) {
      await teardownVoicePipeline();
      return;
    }
    await enterVoiceMode();
  }, [disabled, enterVoiceMode, teardownVoicePipeline, voiceBusy, voiceCaptureEnabled, voiceMode]);

  useEffect(() => {
    return () => {
      void teardownVoicePipeline();
    };
  }, [teardownVoicePipeline]);

  const handleSend = useCallback(() => {
    const trimmed = text.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setText("");
  }, [text, onSend]);

  /** 丢弃当前收音 / 取消识别中的请求；若数字人在播报则一并打断 */
  const handleVoiceBreak = useCallback(async () => {
    voiceBreakGenRef.current += 1;
    uploadLockRef.current = false;
    await discardActiveSegment();
    onInterrupt();
  }, [discardActiveSegment, onInterrupt]);

  const handleKey = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  return (
    <div className="glass fixed inset-x-0 bottom-0 z-30 px-4 pb-[env(safe-area-inset-bottom,8px)] pt-3">
      <div className="mx-auto flex max-w-2xl flex-col gap-2">
        {voiceMode ? (
          <p className="text-center text-[11px] leading-relaxed text-slate-400">
            连续对话：静音自动断句并识别。播报时可大声抢话或点红钮打断。朗读与音色在右侧「设置」侧栏。
          </p>
        ) : onOpenSettings ? (
          <p className="text-center text-[10px] text-slate-500">
            TTS · 数字人选项在右侧「设置」竖条，
            <button
              type="button"
              className="underline decoration-white/30 underline-offset-2 hover:text-slate-300"
              onClick={() => onOpenSettings()}
            >
              点击展开
            </button>
          </p>
        ) : null}
        <div className="flex items-end gap-2">
          <textarea
            className="flex-1 resize-none rounded-3xl bg-white/10 px-5 py-3 text-sm text-slate-100 placeholder-slate-500 outline-none transition-colors focus:bg-white/15"
            placeholder={
              voiceCaptureEnabled ? "输入文字，或点麦克风进入连续语音…" : "输入消息..."
            }
            rows={1}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKey}
            disabled={disabled || voiceBusy}
          />

          {voiceCaptureEnabled ? (
            <button
              type="button"
              className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full transition-colors ${
                voiceMode
                  ? segmentHot
                    ? "bg-rose-500 text-white ring-2 ring-rose-300"
                    : "bg-emerald-600 text-white ring-2 ring-emerald-300/80"
                  : `bg-violet-600 text-white hover:bg-violet-500 ${disabled ? "opacity-40" : ""}`
              }`}
              title={
                disabled
                  ? "请先连接：点击「开始 Demo」直到顶部显示「已连接」"
                  : voiceBusy
                    ? "正在识别/上传上一段语音…"
                    : voiceMode
                      ? "退出连续语音"
                      : "连续语音（静音自动断句）"
              }
              aria-label={voiceMode ? "退出连续语音" : "连续语音"}
              disabled={voiceBusy}
              onClick={(e) => {
                e.preventDefault();
                if (disabled) {
                  window.alert(
                    "请先点击画面上方的「开始 Demo」，等到顶部状态变为「已连接」后，再点麦克风进行连续语音。",
                  );
                  return;
                }
                void toggleVoiceMode();
              }}
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c0 3-2.54 5.1-5.3 5.1S6.7 14 6.7 11H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c3.28-.48 6-3.3 6-6.72h-1.7z" />
              </svg>
            </button>
          ) : null}

          {isSpeaking || (voiceMode && (segmentHot || voiceBusy)) ? (
            <button
              type="button"
              onClick={() => void handleVoiceBreak()}
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-red-500 text-white transition-colors hover:bg-red-600"
              title={
                voiceMode && (segmentHot || voiceBusy)
                  ? "打断：丢弃当前收音或取消识别"
                  : "停止播报"
              }
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 16 16" fill="currentColor">
                <rect x="3" y="3" width="10" height="10" rx="1" />
              </svg>
            </button>
          ) : (
            <button
              type="button"
              onClick={handleSend}
              disabled={disabled || voiceBusy || !text.trim()}
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-cyan-500 text-white transition-colors hover:bg-cyan-600 disabled:opacity-40"
              title="发送"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 10.5 12 3m0 0 7.5 7.5M12 3v18" />
              </svg>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
