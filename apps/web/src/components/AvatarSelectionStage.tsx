import { useEffect, useRef, useState, type ChangeEvent } from "react";
import type { AvatarSummary, PersonaSummary } from "../lib/api";
import { buildApiUrl } from "../lib/api";
import { modelLabel } from "../lib/modelLabels";
import type { ModelConnectionBadge } from "../lib/modelStatus";

const CUSTOM_REFERENCE_NAME_KEY = "opentalking-custom-reference-name";

export type AgentConfig = {
  memoryEnabled: boolean;
  knowledgeEnabled: boolean;
  knowledgeBaseIds: string[];
};

type AvatarSelectionStageProps = {
  avatars: AvatarSummary[];
  selectedAvatar: AvatarSummary | null;
  selectedModelLabel: string;
  selectedVoiceLabel: string;
  loading: boolean;
  queued: boolean;
  modelConnected: boolean;
  modelBadge: ModelConnectionBadge;
  queueInfo?: { position: number; message: string } | null;
  prewarmState?: "idle" | "preparing" | "ready" | "failed";
  onAvatarChange: (id: string) => void;
  onStart: () => void;
  onCustomAvatarCreate: (
    file: File,
    name: string,
    options?: { removeBackground?: boolean },
  ) => Promise<AvatarSummary | null | void>;
  onAvatarDelete?: (avatar: AvatarSummary) => void;
  referenceSaving?: boolean;
  personas: PersonaSummary[];
  selectedPersonaId: string;
  personaImporting?: boolean;
  onPersonaChange: (personaId: string) => void;
  onPersonaImport: (file: File) => void;
};

function AvatarPreviewImage({ avatar, className }: { avatar: AvatarSummary; className: string }) {
  return avatar.has_preview_video ? (
    <video
      src={buildApiUrl(`/avatars/${encodeURIComponent(avatar.id)}/preview-video`)}
      className={className}
      autoPlay
      muted
      loop
      playsInline
      preload="metadata"
      onError={(event) => {
        event.currentTarget.style.display = "none";
      }}
    />
  ) : (
    <img
      src={buildApiUrl(`/avatars/${encodeURIComponent(avatar.id)}/preview`)}
      alt={avatar.name ?? avatar.id}
      className={className}
      onError={(event) => {
        event.currentTarget.style.display = "none";
      }}
    />
  );
}

export function AvatarSelectionStage({
  avatars,
  selectedAvatar,
  selectedModelLabel,
  selectedVoiceLabel,
  loading,
  queued,
  modelConnected,
  modelBadge,
  queueInfo,
  prewarmState = "idle",
  onAvatarChange,
  onStart,
  onCustomAvatarCreate,
  onAvatarDelete,
  referenceSaving = false,
  personas,
  selectedPersonaId,
  personaImporting = false,
  onPersonaChange,
  onPersonaImport,
}: AvatarSelectionStageProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const personaInputRef = useRef<HTMLInputElement>(null);
  const [customUploadOpen, setCustomUploadOpen] = useState(false);
  const [customName, setCustomName] = useState(() => {
    try {
      return window.localStorage.getItem(CUSTOM_REFERENCE_NAME_KEY) ?? "";
    } catch {
      return "";
    }
  });
  const [customFile, setCustomFile] = useState<File | null>(null);
  const [customPreviewUrl, setCustomPreviewUrl] = useState<string | null>(null);
  const [customRemoveBackground, setCustomRemoveBackground] = useState(false);
  const [customUploadState, setCustomUploadState] = useState<"idle" | "processing" | "complete">("idle");
  const [createdCustomAvatar, setCreatedCustomAvatar] = useState<AvatarSummary | null>(null);
  const selectedPersona = personas.find((persona) => persona.id === selectedPersonaId) ?? null;
  const configDisabled = loading || queued || prewarmState === "preparing";
  const baseDisabled = loading || queued || prewarmState === "preparing" || !selectedAvatar || !modelConnected;
  const startLabel = queued
    ? "排队中"
    : loading
      ? "启动中..."
      : prewarmState === "preparing"
        ? "准备资产中..."
        : "开始对话";
  const startDisabled = baseDisabled;

  useEffect(() => {
    return () => {
      if (customPreviewUrl) URL.revokeObjectURL(customPreviewUrl);
    };
  }, [customPreviewUrl]);

  const handleCustomFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;
    event.target.value = "";
    setCustomFile(file);
    if (customPreviewUrl) URL.revokeObjectURL(customPreviewUrl);
    setCustomPreviewUrl(file ? URL.createObjectURL(file) : null);
  };

  const closeCustomUpload = () => {
    if (referenceSaving || customUploadState === "processing") return;
    setCustomUploadOpen(false);
    setCustomUploadState("idle");
    setCreatedCustomAvatar(null);
  };

  const handleCustomUpload = async () => {
    const name = customName.trim();
    if (!customFile || !name) return;
    try {
      window.localStorage.setItem(CUSTOM_REFERENCE_NAME_KEY, name);
    } catch {
      /* ignore */
    }
    setCreatedCustomAvatar(null);
    setCustomUploadState(customRemoveBackground ? "processing" : "idle");
    const created = await onCustomAvatarCreate(customFile, name, { removeBackground: customRemoveBackground });
    if (created) {
      setCreatedCustomAvatar(created);
      if (customRemoveBackground) {
        setCustomUploadState("complete");
      } else {
        setCustomUploadOpen(false);
      }
    } else {
      setCustomUploadState("idle");
    }
  };

  const handlePersonaFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;
    event.target.value = "";
    if (file) onPersonaImport(file);
  };

  return (
    <div className="relative h-full min-h-[520px] overflow-hidden bg-white">
      <div className="grid h-full min-h-0 gap-5 p-4 sm:p-5 xl:grid-cols-[minmax(28rem,1.15fr)_minmax(20rem,0.85fr)] xl:p-6">
        <section className="flex min-h-0 flex-col">
          <div className="mb-4 flex items-end justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-cyan-700">形象库</p>
              <h2 className="mt-1 text-2xl font-semibold text-slate-950">选择数字人形象</h2>
            </div>
            <span className="shrink-0 text-sm font-medium text-slate-500">{avatars.length} 个内置资产</span>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto pr-1">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 2xl:grid-cols-3">
              <button
                type="button"
                onClick={() => setCustomUploadOpen(true)}
                disabled={referenceSaving}
                className="group overflow-hidden rounded-lg border border-dashed border-cyan-300 bg-cyan-50 text-left transition hover:border-cyan-400 hover:bg-cyan-100 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <div className="flex h-12 items-center justify-end border-b border-cyan-100 px-3">
                  <span className="shrink-0 rounded-full bg-white px-2 py-0.5 text-xs font-medium text-cyan-700">
                    自定义
                  </span>
                </div>
                <div className="flex aspect-[4/3] items-center justify-center bg-cyan-100">
                  <span className="flex h-14 w-14 items-center justify-center rounded-full border border-cyan-300 bg-white text-3xl font-light leading-none text-cyan-700 shadow-sm">
                    +
                  </span>
                </div>
                <div className="px-3 py-2">
                  <span className="text-xs font-medium text-cyan-800">
                    {referenceSaving ? "创建中..." : "从本地上传新形象"}
                  </span>
                </div>
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                className="hidden"
                tabIndex={-1}
                aria-hidden
                onChange={handleCustomFileChange}
              />

              {avatars.map((avatar) => {
                const selected = avatar.id === selectedAvatar?.id;
                const canDelete = avatar.is_custom && Boolean(onAvatarDelete);
                return (
                  <div
                    key={avatar.id}
                    className={`group relative overflow-hidden rounded-lg border bg-white text-left transition ${
                      selected
                        ? "border-cyan-400 shadow-md shadow-cyan-100"
                        : "border-slate-200 shadow-sm shadow-slate-200/50 hover:border-slate-300"
                    }`}
                  >
                    {canDelete ? (
                      <button
                        type="button"
                        title="删除自定义形象"
                        aria-label={`删除 ${avatar.name ?? avatar.id}`}
                        onClick={(event) => {
                          event.stopPropagation();
                          if (
                            window.confirm(
                              `确认删除自定义形象「${avatar.name ?? avatar.id}」？此操作不可撤销。`,
                            )
                          ) {
                            onAvatarDelete?.(avatar);
                          }
                        }}
                        className="absolute right-2 top-2 z-10 hidden h-7 w-7 items-center justify-center rounded-full bg-white/90 text-slate-500 shadow-sm transition hover:bg-rose-50 hover:text-rose-600 group-hover:flex"
                      >
                        ×
                      </button>
                    ) : null}
                    <button
                      type="button"
                      onClick={() => onAvatarChange(avatar.id)}
                      className="block w-full text-left"
                    >
                      <div className="flex h-12 items-center justify-between gap-2 border-b border-slate-100 px-3">
                        <span className="min-w-0 truncate text-base font-semibold text-slate-950">
                          {avatar.name ?? avatar.id}
                        </span>
                        {selected ? (
                          <span className="shrink-0 rounded-full bg-cyan-600 px-2 py-0.5 text-xs font-medium text-white">
                            已选
                          </span>
                        ) : null}
                      </div>
                      <div className="aspect-[4/3] bg-slate-100">
                        <AvatarPreviewImage
                          avatar={avatar}
                          className="h-full w-full object-cover transition duration-200 group-hover:scale-[1.02]"
                        />
                      </div>
                      <div className="px-3 py-2">
                        <span className="block truncate text-xs font-medium text-slate-500">
                          {avatar.client_renderer?.type === "light2d"
                            ? "免 GPU / 浏览器动画"
                            : avatar.is_custom
                              ? "自定义形象"
                              : "数字人形象"}
                        </span>
                      </div>
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        </section>

        <section className="flex min-h-[24rem] flex-col overflow-hidden rounded-lg border border-slate-200 bg-slate-50 xl:min-h-0">
          {selectedAvatar ? (
            <>
              <div className="flex items-start justify-between gap-3 border-b border-slate-200 bg-white px-4 py-3">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-cyan-700">已选数字人</p>
                  <h2 className="mt-1 truncate text-2xl font-semibold text-slate-950">
                    {selectedAvatar.name ?? selectedAvatar.id}
                  </h2>
                </div>
                <span className="shrink-0 rounded-full border border-cyan-200 bg-cyan-50 px-2.5 py-1 text-xs font-medium text-cyan-700">
                  形象资产
                </span>
              </div>
              <div className="relative flex h-[min(42vh,380px)] shrink-0 items-center justify-center bg-slate-950 p-4 xl:h-auto xl:min-h-0 xl:flex-1">
                <AvatarPreviewImage
                  avatar={selectedAvatar}
                  className="max-h-full max-w-full rounded-md object-contain shadow-2xl shadow-slate-950/40"
                />
                <div className="pointer-events-none absolute inset-x-0 bottom-0 h-28 bg-gradient-to-t from-slate-950/65 to-transparent" />
              </div>
              <div className="border-t border-slate-200 bg-white p-4">
                <div className="mb-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <p className="text-xs font-semibold text-slate-600">Persona</p>
                    <button
                      type="button"
                      disabled={configDisabled || personaImporting}
                      onClick={() => personaInputRef.current?.click()}
                      className="rounded-md border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-semibold text-slate-600 transition hover:border-cyan-200 hover:text-cyan-700 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {personaImporting ? "导入中..." : "导入"}
                    </button>
                    <input
                      ref={personaInputRef}
                      type="file"
                      accept=".otpersona,.zip,application/zip"
                      className="hidden"
                      tabIndex={-1}
                      aria-hidden
                      onChange={handlePersonaFileChange}
                    />
                  </div>
                  <select
                    value={selectedPersonaId}
                    disabled={configDisabled || personaImporting}
                    onChange={(event) => onPersonaChange(event.target.value)}
                    className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-800 outline-none transition focus:border-cyan-400 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <option value="">未选择 Persona</option>
                    {personas.map((persona) => (
                      <option key={persona.id} value={persona.id}>
                        {persona.name}
                      </option>
                    ))}
                  </select>
                  {selectedPersona ? (
                    <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-slate-500">
                      <span className="truncate rounded-md bg-white px-2 py-1">
                        {selectedPersona.locale}
                      </span>
                      <span className="truncate rounded-md bg-white px-2 py-1">
                        {modelLabel(selectedPersona.avatar.model)}
                      </span>
                    </div>
                  ) : null}
                </div>
                <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-xs font-medium text-slate-500">已选驱动模型</p>
                      <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-semibold ${
                        modelBadge.tone === "connected"
                          ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                          : modelBadge.tone === "selfTest"
                            ? "border-cyan-200 bg-cyan-50 text-cyan-700"
                          : "border-slate-200 bg-white text-slate-500"
                      }`}>
                        {modelBadge.label}
                      </span>
                    </div>
                    <p className="mt-1 truncate text-sm font-semibold text-slate-950">{selectedModelLabel}</p>
                  </div>
                  <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                    <p className="text-xs font-medium text-slate-500">已选音色</p>
                    <p className="mt-1 truncate text-sm font-semibold text-slate-950">{selectedVoiceLabel}</p>
                  </div>
                </div>
                {queued ? (
                  <p className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm font-medium text-amber-800">
                    前面还有 {queueInfo?.position ?? 1} 人，请稍候...
                  </p>
                ) : null}
                {!modelConnected ? (
                  <p className="mb-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-600">
                    当前驱动模型未连接，请先启动对应模型服务。
                  </p>
                ) : null}
                {modelConnected && prewarmState === "preparing" ? (
                  <p className="mb-3 rounded-lg border border-cyan-200 bg-cyan-50 px-3 py-2 text-sm font-medium text-cyan-800">
                    正在准备当前形象资产，完成后会自动复用缓存。
                  </p>
                ) : null}
                {modelConnected && prewarmState === "failed" ? (
                  <p className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm font-medium text-amber-800">
                    资产准备失败，点击开始会重新尝试。
                  </p>
                ) : null}
                <button
                  type="button"
                  onClick={onStart}
                  disabled={startDisabled}
                  className="w-full rounded-lg bg-cyan-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {startLabel}
                </button>
              </div>
            </>
          ) : (
            <div className="flex flex-1 items-center justify-center p-6 text-sm font-medium text-slate-500">
              正在读取数字人资产...
            </div>
          )}
        </section>
      </div>

      {customUploadOpen ? (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-slate-950/30 p-4 backdrop-blur-[2px]">
          <div className="w-full max-w-md overflow-hidden rounded-lg border border-slate-200 bg-white shadow-2xl shadow-slate-900/20">
            <div className="border-b border-slate-100 px-4 py-3">
              <p className="text-sm font-semibold text-cyan-700">自定义形象</p>
              <h3 className="mt-1 text-xl font-semibold text-slate-950">上传参考图</h3>
            </div>
            <div className="space-y-4 p-4">
              <label className="block">
                <span className="mb-1.5 block text-xs font-medium text-slate-500">形象名称</span>
                <input
                  value={customName}
                  onChange={(event) => setCustomName(event.target.value)}
                  maxLength={32}
                  placeholder="例如：我的形象"
                  className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm font-medium text-slate-800 outline-none transition focus:border-cyan-300 focus:bg-white"
                />
              </label>
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={referenceSaving}
                className="flex w-full items-center gap-3 rounded-lg border border-dashed border-cyan-300 bg-cyan-50 p-3 text-left transition hover:bg-cyan-100"
              >
                <span className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-white text-2xl font-light text-cyan-700">
                  {customPreviewUrl ? (
                    <img src={customPreviewUrl} alt="" className="h-full w-full object-cover" />
                  ) : (
                    "+"
                  )}
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-semibold text-slate-950">
                    {customFile ? customFile.name : "选择本地图片"}
                  </span>
                  <span className="mt-0.5 block text-xs text-slate-500">会作为新资产加入形象库</span>
                </span>
              </button>
              <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5">
                <input
                  type="checkbox"
                  checked={customRemoveBackground}
                  onChange={(event) => setCustomRemoveBackground(event.target.checked)}
                  disabled={referenceSaving}
                  className="h-4 w-4 rounded border-slate-300 text-cyan-600 focus:ring-cyan-500"
                />
                <span className="text-sm font-medium text-slate-700">上传时抠除背景</span>
              </label>
              {customUploadState === "processing" ? (
                <div className="rounded-lg border border-cyan-200 bg-cyan-50 px-3 py-2.5">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm font-semibold text-cyan-800">正在抠除背景...</span>
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-cyan-200 border-t-cyan-600" />
                  </div>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-cyan-100">
                    <div className="h-full w-2/3 animate-pulse rounded-full bg-cyan-500" />
                  </div>
                  <p className="mt-2 text-xs text-cyan-700">正在识别人像边缘，首次处理可能较慢。</p>
                </div>
              ) : null}
              {customUploadState === "complete" && createdCustomAvatar ? (
                <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3">
                  <div className="flex items-center gap-3">
                    <span className="flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-[linear-gradient(45deg,#e2e8f0_25%,transparent_25%),linear-gradient(-45deg,#e2e8f0_25%,transparent_25%),linear-gradient(45deg,transparent_75%,#e2e8f0_75%),linear-gradient(-45deg,transparent_75%,#e2e8f0_75%)] bg-[length:16px_16px] bg-[position:0_0,0_8px,8px_-8px,-8px_0]">
                      <img
                        src={buildApiUrl(`/avatars/${encodeURIComponent(createdCustomAvatar.id)}/preview`)}
                        alt={createdCustomAvatar.name ?? createdCustomAvatar.id}
                        className="h-full w-full object-contain"
                      />
                    </span>
                    <span className="min-w-0">
                      <span className="block text-sm font-semibold text-emerald-900">抠图完成</span>
                      <span className="mt-0.5 block truncate text-xs text-emerald-700">
                        {createdCustomAvatar.name ?? createdCustomAvatar.id} 已加入形象库
                      </span>
                    </span>
                  </div>
                </div>
              ) : null}
            </div>
            <div className="flex items-center justify-end gap-2 border-t border-slate-100 bg-slate-50 px-4 py-3">
              <button
                type="button"
                onClick={closeCustomUpload}
                disabled={referenceSaving || customUploadState === "processing"}
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition hover:border-slate-300"
              >
                {customUploadState === "complete" ? "完成" : "取消"}
              </button>
              {customUploadState !== "complete" ? (
                <button
                  type="button"
                  onClick={() => void handleCustomUpload()}
                  disabled={referenceSaving || !customFile || !customName.trim()}
                  className="rounded-lg bg-cyan-600 px-3 py-2 text-sm font-semibold text-white transition hover:bg-cyan-500 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {referenceSaving && customRemoveBackground ? "正在抠除背景..." : referenceSaving ? "创建中..." : "保存形象"}
                </button>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
