import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import { BailianVoiceClone } from "./BailianVoiceClone";
import {
  ApiError,
  buildApiDownloadUrl,
  buildApiUrl,
  createVideoCreationJob,
  apiPostForm,
  type AvatarSummary,
  type ExportVideoItem,
  type VoiceCatalogItem,
} from "../lib/api";
import type { VoiceCloneApplication } from "../lib/voiceCloneApply";
import { EDGE_ZH_VOICES } from "../constants/edgeZhVoices";
import type { TtsProviderExtended } from "../constants/ttsBailian";
import { buildTTSPreviewPayload, requestTTSPreview } from "../lib/ttsPreview";

export type VideoCreationAudioSource = "upload" | "tts_text" | "voice_clone";

type VoiceOpt = { id: string; label: string; targetModel?: string | null };

type VideoCreationWorkspaceProps = {
  avatars: AvatarSummary[];
  avatarId: string;
  models: string[];
  onAvatarChange: (id: string) => void;
  onAvatarUploaded: (avatar: AvatarSummary) => void;
  onVoiceCloned: (application: VoiceCloneApplication) => void | Promise<void>;
  onExportCreated?: (item: ExportVideoItem) => void;
  onGoAssetLibrary?: () => void;
  onNotify?: (message: string, tone?: "info" | "success" | "error") => void;
  ttsProvider: TtsProviderExtended;
  onTtsProviderChange: (provider: TtsProviderExtended) => void;
  qwenModel: string;
  onQwenModelChange: (modelId: string) => void;
  qwenModelOptions: { id: string; label: string }[];
  qwenVoice: string;
  onQwenVoiceChange: (voiceId: string) => void;
  qwenVoiceOptions: VoiceOpt[];
  edgeVoice: string;
  onEdgeVoiceChange: (voiceId: string) => void;
  voiceCatalog: VoiceCatalogItem[];
};

const AUDIO_SOURCE_OPTIONS: { id: VideoCreationAudioSource; label: string }[] = [
  { id: "upload", label: "上传音频" },
  { id: "tts_text", label: "文本合成" },
  { id: "voice_clone", label: "复刻音色" },
];

const VIDEO_CREATION_MODELS = ["wav2lip", "quicktalk"];

function providerLabel(provider: TtsProviderExtended): string {
  if (provider === "edge") return "Edge TTS";
  if (provider === "dashscope") return "Qwen TTS";
  if (provider === "cosyvoice") return "CosyVoice";
  if (provider === "sambert") return "Sambert";
  return "Local CosyVoice";
}

function avatarNameFromFile(file: File): string {
  const stem = file.name.replace(/\.[^.]+$/, "").trim();
  return stem ? `视频创作 ${stem}` : "视频创作形象";
}

export function VideoCreationWorkspace({
  avatars,
  avatarId,
  models,
  onAvatarChange,
  onAvatarUploaded,
  onVoiceCloned,
  onExportCreated,
  onGoAssetLibrary,
  onNotify,
  ttsProvider,
  onTtsProviderChange,
  qwenModel,
  onQwenModelChange,
  qwenModelOptions,
  qwenVoice,
  onQwenVoiceChange,
  qwenVoiceOptions,
  edgeVoice,
  onEdgeVoiceChange,
  voiceCatalog,
}: VideoCreationWorkspaceProps) {
  const selectedAvatar = avatars.find((avatar) => avatar.id === avatarId) ?? avatars[0] ?? null;
  const [model, setModel] = useState(() => (models.includes("quicktalk") ? "quicktalk" : "wav2lip"));
  const [audioSource, setAudioSource] = useState<VideoCreationAudioSource>("upload");
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [sourceImageBusy, setSourceImageBusy] = useState(false);
  const [text, setText] = useState("欢迎使用 OpenTalking 视频创作。请选择数字人形象和音色，生成一段离线口播视频。");
  const [title, setTitle] = useState("数字人口播视频");
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState<ExportVideoItem | null>(null);
  const [cloneOpen, setCloneOpen] = useState(false);
  const [ttsPreviewing, setTtsPreviewing] = useState(false);
  const sourceUploadRef = useRef<HTMLInputElement>(null);
  const ttsPreviewAudioRef = useRef<HTMLAudioElement | null>(null);
  const ttsPreviewUrlRef = useRef<string | null>(null);

  const availableVideoModels = useMemo(() => VIDEO_CREATION_MODELS.filter((item) => models.includes(item)), [models]);
  const effectiveModel = availableVideoModels.includes(model) ? model : availableVideoModels[0] ?? model;
  const selectedVoiceLabel = ttsProvider === "edge"
    ? EDGE_ZH_VOICES.find((voice) => voice.id === edgeVoice)?.label ?? edgeVoice
    : qwenVoiceOptions.find((voice) => voice.id === qwenVoice)?.label ?? qwenVoice;
  const cloneVoiceCount = voiceCatalog.filter((item) => item.source === "clone").length;
  const canPreviewTts = audioSource !== "upload";

  useEffect(() => {
    return () => {
      if (ttsPreviewUrlRef.current) {
        URL.revokeObjectURL(ttsPreviewUrlRef.current);
        ttsPreviewUrlRef.current = null;
      }
    };
  }, []);

  const handleSourceImage = useCallback(async (file: File | null) => {
    if (!file || !selectedAvatar) return;
    if (!file.type.startsWith("image/")) {
      onNotify?.("请上传图片作为数字人形象。", "error");
      return;
    }
    setSourceImageBusy(true);
    try {
      const form = new FormData();
      form.set("base_avatar_id", selectedAvatar.id);
      form.set("name", avatarNameFromFile(file));
      form.set("model", effectiveModel);
      form.set("image", file);
      const created = await apiPostForm<AvatarSummary>("/avatars/custom", form);
      onAvatarUploaded(created);
      onNotify?.(`已加入数字人资产：${created.name ?? created.id}`, "success");
    } catch (error) {
      console.warn("video creation source image upload failed", error);
      const detail = error instanceof ApiError ? error.detail : null;
      onNotify?.(detail ? `上传形象失败：${detail}` : "上传形象失败。", "error");
    } finally {
      setSourceImageBusy(false);
    }
  }, [effectiveModel, onAvatarUploaded, onNotify, selectedAvatar]);

  const handleVoiceCloned = useCallback(async (application: VoiceCloneApplication) => {
    await onVoiceCloned(application);
    onTtsProviderChange(application.provider);
    onQwenModelChange(application.model);
    onQwenVoiceChange(application.voice);
    setCloneOpen(false);
    setAudioSource("voice_clone");
  }, [onQwenModelChange, onQwenVoiceChange, onTtsProviderChange, onVoiceCloned]);

  const handlePreviewTts = useCallback(async () => {
    const previewText = text.trim();
    if (!previewText) {
      onNotify?.("请输入要试听的口播文本。", "info");
      return;
    }
    const voice = ttsProvider === "edge" ? edgeVoice : ttsProvider === "sambert" ? "" : qwenVoice;
    if (ttsProvider !== "edge" && ttsProvider !== "sambert" && !voice.trim()) {
      onNotify?.("当前模型没有可用音色，请先复刻音色或切换模型。", "info");
      return;
    }
    setTtsPreviewing(true);
    try {
      const blob = await requestTTSPreview(
        buildTTSPreviewPayload({
          text: previewText,
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
      onNotify?.("正在播放试听音频。", "success");
    } catch (error) {
      console.warn("video creation tts preview failed", error);
      const detail = error instanceof ApiError ? error.detail : null;
      onNotify?.(detail ? `试听失败：${detail}` : "试听失败，请确认音色、模型和后端密钥配置。", "error");
    } finally {
      setTtsPreviewing(false);
    }
  }, [edgeVoice, onNotify, qwenModel, qwenVoice, text, ttsProvider]);

  const handleGenerate = useCallback(async () => {
    if (!selectedAvatar) {
      onNotify?.("请先选择数字人资产。", "info");
      return;
    }
    if (audioSource === "upload" && !audioFile) {
      onNotify?.("请先上传音频文件。", "info");
      return;
    }
    if (audioSource !== "upload" && !text.trim()) {
      onNotify?.("请输入要合成的口播文本。", "info");
      return;
    }
    setGenerating(true);
    setResult(null);
    try {
      const response = await createVideoCreationJob({
        model: effectiveModel,
        avatarId: selectedAvatar.id,
        title,
        audioSource: audioSource === "upload" ? "upload" : "tts_text",
        audioFile,
        text,
        ttsProvider,
        ttsModel: ttsProvider === "edge" ? undefined : qwenModel,
        voice: ttsProvider === "edge" ? edgeVoice : qwenVoice,
      });
      setResult(response.export_video);
      onExportCreated?.(response.export_video);
      onNotify?.(`视频创作已保存到资产库：${response.export_video.title}`, "success");
    } catch (error) {
      console.warn("video creation job failed", error);
      const detail = error instanceof ApiError ? error.detail : null;
      onNotify?.(detail ? `视频创作失败：${detail}` : "视频创作失败，请查看后端日志。", "error");
    } finally {
      setGenerating(false);
    }
  }, [audioFile, audioSource, edgeVoice, effectiveModel, onExportCreated, onNotify, qwenModel, qwenVoice, selectedAvatar, text, title, ttsProvider]);

  return (
    <main className="flex min-h-0 flex-1 flex-col bg-slate-100 p-4">
      <div className="grid min-h-0 flex-1 gap-4 xl:grid-cols-[20rem_minmax(0,1fr)_22rem]">
        <section className="min-h-0 overflow-y-auto rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-xs font-medium text-slate-500">Source</p>
              <h1 className="mt-1 text-base font-semibold text-slate-950">视频创作</h1>
            </div>
            <button
              type="button"
              onClick={() => sourceUploadRef.current?.click()}
              disabled={sourceImageBusy || !selectedAvatar}
              className="rounded-lg border border-cyan-200 bg-cyan-50 px-3 py-1.5 text-xs font-semibold text-cyan-700 transition hover:bg-cyan-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {sourceImageBusy ? "上传中..." : "上传图片"}
            </button>
            <input
              ref={sourceUploadRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(event: ChangeEvent<HTMLInputElement>) => {
                const input = event.currentTarget;
                void handleSourceImage(input.files?.[0] ?? null).finally(() => {
                  input.value = "";
                });
              }}
            />
          </div>
          <div className="mt-4 space-y-2">
            {avatars.map((avatar) => {
              const selected = selectedAvatar?.id === avatar.id;
              return (
                <button
                  key={avatar.id}
                  type="button"
                  onClick={() => onAvatarChange(avatar.id)}
                  className={`flex w-full items-center gap-3 rounded-lg border p-2 text-left transition ${selected ? "border-cyan-300 bg-cyan-50" : "border-slate-200 bg-white hover:border-slate-300"}`}
                >
                  <img src={buildApiUrl(`/avatars/${encodeURIComponent(avatar.id)}/preview`)} alt={avatar.name ?? avatar.id} className="h-12 w-12 rounded-md border border-slate-200 object-cover" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold text-slate-900">{avatar.name ?? avatar.id}</span>
                    <span className="block truncate text-xs text-slate-500">{avatar.width}x{avatar.height}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </section>

        <section className="flex min-h-[30rem] min-w-0 flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-200 px-4 py-3">
            <p className="text-xs font-medium text-slate-500">Offline Generation</p>
            <h2 className="text-base font-semibold text-slate-950">离线数字人口播</h2>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            <div className="grid gap-4 lg:grid-cols-2">
              <label className="block text-sm font-medium text-slate-700">
                生成模型
                <select value={effectiveModel} onChange={(event) => setModel(event.target.value)} className="mt-2 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm">
                  {VIDEO_CREATION_MODELS.map((item) => (
                    <option key={item} value={item} disabled={!models.includes(item)}>{item}{models.includes(item) ? "" : "（不可用）"}</option>
                  ))}
                </select>
              </label>
              <label className="block text-sm font-medium text-slate-700">
                标题
                <input value={title} onChange={(event) => setTitle(event.target.value)} className="mt-2 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm" />
              </label>
            </div>

            <div className="mt-5">
              <p className="text-sm font-semibold text-slate-800">音频来源</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {AUDIO_SOURCE_OPTIONS.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    onClick={() => setAudioSource(option.id)}
                    className={`rounded-lg border px-3 py-2 text-sm font-semibold transition ${audioSource === option.id ? "border-cyan-300 bg-cyan-50 text-cyan-700" : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"}`}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>

            {audioSource === "upload" ? (
              <label className="mt-4 block rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-700">
                <span className="font-semibold">上传音频</span>
                <span className="mt-1 block text-xs text-slate-500">支持 wav/mp3/m4a/webm 等 ffmpeg 可解码格式，服务端限制文件大小。</span>
                <input type="file" accept="audio/*,.webm,.mp3,.wav,.m4a,.aac,.flac,.ogg" className="mt-3 block w-full text-xs" onChange={(event) => setAudioFile(event.currentTarget.files?.[0] ?? null)} />
                {audioFile ? <span className="mt-2 block text-xs font-medium text-cyan-700">已选择：{audioFile.name}</span> : null}
              </label>
            ) : (
              <div className="mt-4 space-y-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
                <label className="block text-sm font-medium text-slate-700">
                  <span className="flex items-center justify-between gap-3">
                    <span>口播文本</span>
                    <span className="text-xs font-medium text-slate-400">{text.trim().length}/240</span>
                  </span>
                  <textarea value={text} onChange={(event) => setText(event.target.value)} rows={5} maxLength={240} className="mt-2 w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" />
                </label>
                <div className="grid gap-3 md:grid-cols-3">
                  <label className="block text-sm font-medium text-slate-700">
                    TTS
                    <select value={ttsProvider} onChange={(event) => onTtsProviderChange(event.target.value as TtsProviderExtended)} className="mt-2 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm">
                      {(["edge", "dashscope", "cosyvoice", "sambert", "local_cosyvoice"] as TtsProviderExtended[]).map((item) => <option key={item} value={item}>{providerLabel(item)}</option>)}
                    </select>
                  </label>
                  <label className="block text-sm font-medium text-slate-700">
                    模型
                    <select disabled={ttsProvider === "edge"} value={ttsProvider === "edge" ? "" : qwenModel} onChange={(event) => onQwenModelChange(event.target.value)} className="mt-2 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm disabled:bg-slate-100">
                      {qwenModelOptions.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                    </select>
                  </label>
                  <label className="block text-sm font-medium text-slate-700">
                    音色
                    {ttsProvider === "edge" ? (
                      <select value={edgeVoice} onChange={(event) => onEdgeVoiceChange(event.target.value)} className="mt-2 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm">
                        {EDGE_ZH_VOICES.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                      </select>
                    ) : (
                      <select value={qwenVoice} onChange={(event) => onQwenVoiceChange(event.target.value)} className="mt-2 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm">
                        {qwenVoiceOptions.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                      </select>
                    )}
                  </label>
                </div>
                {audioSource === "voice_clone" ? (
                  <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-cyan-200 bg-cyan-50 p-3 text-sm text-cyan-800">
                    <span>复刻音色：已有 {cloneVoiceCount} 个复刻音色，当前使用 {selectedVoiceLabel || "未选择"}</span>
                    <button type="button" onClick={() => setCloneOpen(true)} className="rounded-lg bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-cyan-500">录制/上传复刻</button>
                  </div>
                ) : null}
                {canPreviewTts ? (
                  <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white p-3">
                    <span className="text-xs font-medium text-slate-500">试听当前文本、模型和音色后再生成视频。</span>
                    <button
                      type="button"
                      onClick={() => void handlePreviewTts()}
                      disabled={ttsPreviewing || !text.trim()}
                      className="rounded-lg border border-cyan-200 bg-cyan-50 px-3 py-1.5 text-xs font-semibold text-cyan-700 transition hover:bg-cyan-100 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {ttsPreviewing ? "试听中..." : "试听口播"}
                    </button>
                  </div>
                ) : null}
              </div>
            )}

            <div className="mt-5 flex flex-wrap items-center gap-3">
              <button type="button" disabled={generating || !selectedAvatar || !availableVideoModels.length} onClick={() => void handleGenerate()} className="rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50">
                {generating ? "生成中..." : "生成并保存"}
              </button>
              {result ? <span className="text-sm font-medium text-emerald-700">已保存到资产库</span> : null}
            </div>
          </div>
        </section>

        <aside className="flex min-h-0 flex-col rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <p className="text-xs font-medium text-slate-500">Result</p>
          <h2 className="mt-1 text-base font-semibold text-slate-950">生成结果</h2>
          {result ? (
            <div className="mt-4 space-y-3">
              <video src={buildApiDownloadUrl(result.download_url)} className="aspect-video w-full rounded-lg bg-slate-950 object-contain" controls preload="metadata" />
              <div className="rounded-lg bg-slate-50 p-3 text-xs text-slate-600">
                <p className="font-semibold text-slate-800">{result.title}</p>
                <p className="mt-1 break-all font-mono text-[11px]">{result.path}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <a href={buildApiDownloadUrl(result.download_url)} download className="rounded-lg bg-cyan-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-cyan-500">下载</a>
                <button type="button" onClick={onGoAssetLibrary} className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:border-cyan-200 hover:text-cyan-700">去资产库查看</button>
              </div>
            </div>
          ) : (
            <div className="mt-4 flex min-h-[18rem] items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50 text-sm font-medium text-slate-500">生成后显示视频预览</div>
          )}
        </aside>
      </div>

      {cloneOpen ? (
        <>
          <button type="button" className="fixed inset-0 z-[55] bg-slate-900/20 backdrop-blur-[2px]" aria-label="关闭音色复刻" onClick={() => setCloneOpen(false)} />
          <aside className="fixed inset-y-0 right-0 z-[56] flex w-[min(100vw,28rem)] shadow-2xl shadow-slate-300/70">
            <div className="h-full max-h-[100dvh] flex-1 overflow-y-auto border-l border-slate-200 bg-slate-50 p-4 sm:p-5">
              <BailianVoiceClone onSuccess={handleVoiceCloned} onClose={() => setCloneOpen(false)} />
            </div>
          </aside>
        </>
      ) : null}
    </main>
  );
}
