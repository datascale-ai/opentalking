import { useCallback, useRef, useState } from "react";
import { apiPostForm } from "../lib/api";
import { COSYVOICE_MODEL_OPTIONS } from "../constants/ttsBailian";
import { QWEN_VOICE_CLONE_TARGET_OPTIONS } from "../constants/ttsQwen";

/** 固定朗读文案：用于复刻时与百炼侧要求一致 */
export const BAILIAN_CLONE_SAMPLE_TEXT =
  "大家好，这是一段用于音色复刻的固定文本。我会用自然、清晰、平稳的语速读完它。";

function pickRecorderMime(): string | undefined {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"];
  for (const t of candidates) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(t)) {
      return t;
    }
  }
  return undefined;
}

type CloneProvider = "dashscope" | "cosyvoice";

interface BailianVoiceCloneProps {
  onSuccess: () => void;
  onClose: () => void;
}

export function BailianVoiceClone({ onSuccess, onClose }: BailianVoiceCloneProps) {
  const [provider, setProvider] = useState<CloneProvider>("dashscope");
  const [targetModel, setTargetModel] = useState(
    () =>
      (provider === "dashscope"
        ? QWEN_VOICE_CLONE_TARGET_OPTIONS[0]?.id
        : COSYVOICE_MODEL_OPTIONS[0]?.id) ?? "",
  );
  const [displayLabel, setDisplayLabel] = useState("我的复刻音色");
  const [prefix, setPrefix] = useState("");
  const [preferredName, setPreferredName] = useState("");
  const [recording, setRecording] = useState(false);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const mrRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const streamRef = useRef<MediaStream | null>(null);

  const onProviderChange = (p: CloneProvider) => {
    setProvider(p);
    if (p === "dashscope") {
      setTargetModel(QWEN_VOICE_CLONE_TARGET_OPTIONS[0]?.id ?? "");
    } else {
      setTargetModel(COSYVOICE_MODEL_OPTIONS[0]?.id ?? "");
    }
  };

  const stopRecording = useCallback(async () => {
    const mr = mrRef.current;
    if (!mr || mr.state === "inactive") {
      mrRef.current = null;
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      setRecording(false);
      return;
    }
    await new Promise<void>((resolve) => {
      mr.onstop = () => resolve();
      try {
        mr.stop();
      } catch {
        resolve();
      }
    });
    mrRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    const mime = mr.mimeType || "audio/webm";
    const b = new Blob(chunksRef.current, { type: mime });
    chunksRef.current = [];
    setBlob(b);
    setRecording(false);
  }, []);

  const startRecording = useCallback(async () => {
    setMessage(null);
    setBlob(null);
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
    setRecording(true);
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
      const ext = blob.type.includes("webm") ? "webm" : blob.type.includes("ogg") ? "ogg" : "webm";
      const fd = new FormData();
      fd.append("provider", provider);
      fd.append("target_model", targetModel.trim());
      fd.append("display_label", displayLabel.trim() || "我的复刻音色");
      fd.append("audio", blob, `sample.${ext}`);
      fd.append("prefix", prefix.trim());
      fd.append("preferred_name", preferredName.trim());
      const res = await apiPostForm<{
        ok?: boolean;
        message?: string;
        voice_id?: string;
      }>("/voices/clone", fd);
      setMessage(res.message ?? `已生成 voice_id：${res.voice_id ?? "?"}`);
      onSuccess();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [blob, displayLabel, onSuccess, preferredName, prefix, provider, targetModel]);

  return (
    <div className="glass mx-auto max-w-xl rounded-2xl border border-white/10 p-4 text-sm text-slate-200 shadow-xl">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-white">百炼音色复刻</h2>
        <button
          type="button"
          className="rounded-lg px-2 py-1 text-xs text-slate-400 hover:bg-white/10 hover:text-white"
          onClick={onClose}
        >
          关闭
        </button>
      </div>
      <p className="mb-2 text-xs leading-relaxed text-slate-400">
        请朗读下方固定文案并录音。千问复刻走 base64，内网可用；CosyVoice 需本服务对公网可访问或配置{" "}
        <code className="text-slate-300">OPENTALKING_PUBLIC_BASE_URL</code>。
      </p>
      <blockquote className="mb-3 rounded-lg bg-black/30 px-3 py-2 text-xs leading-relaxed text-slate-300">
        {BAILIAN_CLONE_SAMPLE_TEXT}
      </blockquote>

      <div className="mb-3 flex flex-wrap gap-3 text-xs">
        <label className="flex items-center gap-2">
          <span className="text-slate-400">线路</span>
          <select
            className="rounded-lg border border-white/10 bg-black/40 px-2 py-1 text-slate-100 outline-none"
            value={provider}
            onChange={(e) => onProviderChange(e.target.value as CloneProvider)}
            disabled={busy}
          >
            <option value="dashscope">千问（DashScope 复刻）</option>
            <option value="cosyvoice">CosyVoice</option>
          </select>
        </label>
        <label className="flex min-w-[12rem] flex-1 items-center gap-2">
          <span className="text-slate-400">目标模型</span>
          <select
            className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/40 px-2 py-1 text-slate-100 outline-none"
            value={targetModel}
            onChange={(e) => setTargetModel(e.target.value)}
            disabled={busy}
          >
            {(provider === "dashscope" ? QWEN_VOICE_CLONE_TARGET_OPTIONS : COSYVOICE_MODEL_OPTIONS).map(
              (o) => (
                <option key={o.id} value={o.id}>
                  {o.label}
                </option>
              ),
            )}
          </select>
        </label>
      </div>

      <div className="mb-3 flex flex-wrap gap-3 text-xs">
        <label className="flex flex-1 flex-col gap-1">
          <span className="text-slate-400">显示名称</span>
          <input
            className="rounded-lg border border-white/10 bg-black/40 px-2 py-1 text-slate-100 outline-none"
            value={displayLabel}
            onChange={(e) => setDisplayLabel(e.target.value)}
            disabled={busy}
          />
        </label>
        {provider === "cosyvoice" ? (
          <label className="flex flex-1 flex-col gap-1">
            <span className="text-slate-400">前缀 prefix（可选，小写字母数字）</span>
            <input
              className="rounded-lg border border-white/10 bg-black/40 px-2 py-1 text-slate-100 outline-none"
              value={prefix}
              onChange={(e) => setPrefix(e.target.value)}
              placeholder="留空则自动生成"
              disabled={busy}
            />
          </label>
        ) : (
          <label className="flex flex-1 flex-col gap-1">
            <span className="text-slate-400">preferred_name（可选，小写）</span>
            <input
              className="rounded-lg border border-white/10 bg-black/40 px-2 py-1 text-slate-100 outline-none"
              value={preferredName}
              onChange={(e) => setPreferredName(e.target.value)}
              placeholder="留空则自动生成"
              disabled={busy}
            />
          </label>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {!recording ? (
          <button
            type="button"
            className="rounded-xl bg-emerald-600/90 px-4 py-2 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
            disabled={busy}
            onClick={() => void startRecording()}
          >
            开始录音
          </button>
        ) : (
          <button
            type="button"
            className="rounded-xl bg-rose-600/90 px-4 py-2 text-xs font-medium text-white hover:bg-rose-500"
            onClick={() => void stopRecording()}
          >
            停止
          </button>
        )}
        <button
          type="button"
          className="rounded-xl bg-white/15 px-4 py-2 text-xs font-medium text-white hover:bg-white/25 disabled:opacity-50"
          disabled={busy || !blob}
          onClick={() => void submit()}
        >
          {busy ? "提交中…" : "上传并复刻"}
        </button>
        {blob ? (
          <span className="text-xs text-slate-500">已录 {Math.round(blob.size / 1024)} KB</span>
        ) : null}
      </div>
      {message ? <p className="mt-3 text-xs text-amber-200/90">{message}</p> : null}
    </div>
  );
}
