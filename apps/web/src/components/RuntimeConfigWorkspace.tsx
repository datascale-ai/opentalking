import { useEffect, useRef, useState } from "react";
import type { RuntimeConfigApplyInput, RuntimeConfigResponse } from "../lib/api";
import type { TtsProviderExtended } from "../constants/ttsBailian";

const RUNTIME_LLM_DEFAULT = {
  baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
  model: "qwen-flash",
};

const RUNTIME_STT_PRESETS: Record<string, { label: string; baseUrl: string; model: string; needsKey: boolean }> = {
  dashscope: {
    label: "百炼",
    baseUrl: "https://dashscope.aliyuncs.com",
    model: "paraformer-realtime-v2",
    needsKey: true,
  },
  openai_compatible: {
    label: "OpenAI-compatible",
    baseUrl: "https://api.openai.com/v1",
    model: "whisper-1",
    needsKey: true,
  },
  xiaomi_mimo: {
    label: "小米 MiMo",
    baseUrl: "",
    model: "mimo-v2.5-asr",
    needsKey: true,
  },
  sensevoice: {
    label: "SenseVoice",
    baseUrl: "",
    model: "iic/SenseVoiceSmall",
    needsKey: false,
  },
};

const RUNTIME_TTS_PRESETS: Record<TtsProviderExtended, { label: string; baseUrl: string; model: string; voice: string; needsKey: boolean }> = {
  edge: {
    label: "Edge（无需配置）",
    baseUrl: "",
    model: "",
    voice: "zh-CN-XiaoxiaoNeural",
    needsKey: false,
  },
  dashscope: {
    label: "Qwen",
    baseUrl: "wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
    model: "qwen3-tts-flash-realtime",
    voice: "Cherry",
    needsKey: true,
  },
  cosyvoice: {
    label: "CosyVoice",
    baseUrl: "",
    model: "cosyvoice-v3-flash",
    voice: "longanyang",
    needsKey: true,
  },
  sambert: {
    label: "Sambert",
    baseUrl: "",
    model: "sambert-zhichu-v1",
    voice: "",
    needsKey: true,
  },
  local_cosyvoice: {
    label: "Local CosyVoice",
    baseUrl: "http://127.0.0.1:9880",
    model: "FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
    voice: "",
    needsKey: false,
  },
  indextts: {
    label: "Local IndexTTS",
    baseUrl: "http://127.0.0.1:9880",
    model: "IndexTeam/IndexTTS-2",
    voice: "",
    needsKey: false,
  },
  local_f5_tts: {
    label: "Local F5-TTS",
    baseUrl: "http://127.0.0.1:9880",
    model: "SWivid/F5-TTS/F5TTS_v1_Base",
    voice: "",
    needsKey: false,
  },
  xiaomi_mimo: {
    label: "小米 MiMo",
    baseUrl: "",
    model: "mimo-v2.5-tts",
    voice: "mimo_default",
    needsKey: true,
  },
  openai_compatible: {
    label: "OpenAI-compatible",
    baseUrl: "https://api.openai.com/v1",
    model: "gpt-4o-mini-tts",
    voice: "alloy",
    needsKey: true,
  },
};

const MEM0_MODEL_PRESETS = {
  llm: {
    provider: "openai",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    model: "qwen-flash",
  },
  embedder: {
    provider: "openai",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    model: "text-embedding-v4",
  },
};

type RuntimeConfigForm = {
  llmBaseUrl: string;
  llmModel: string;
  llmApiKey: string;
  sttProvider: string;
  sttBaseUrl: string;
  sttModel: string;
  sttApiKey: string;
  ttsProvider: TtsProviderExtended;
  ttsBaseUrl: string;
  ttsModel: string;
  ttsApiKey: string;
  mem0LlmProvider: string;
  mem0LlmBaseUrl: string;
  mem0LlmModel: string;
  mem0LlmApiKey: string;
  mem0EmbedderProvider: string;
  mem0EmbedderBaseUrl: string;
  mem0EmbedderModel: string;
  mem0EmbedderApiKey: string;
  syncDashscopeApiKey: boolean;
};

const RUNTIME_FORM_DEFAULTS: RuntimeConfigForm = {
  llmBaseUrl: RUNTIME_LLM_DEFAULT.baseUrl,
  llmModel: RUNTIME_LLM_DEFAULT.model,
  llmApiKey: "",
  sttProvider: "dashscope",
  sttBaseUrl: RUNTIME_STT_PRESETS.dashscope.baseUrl,
  sttModel: RUNTIME_STT_PRESETS.dashscope.model,
  sttApiKey: "",
  ttsProvider: "dashscope",
  ttsBaseUrl: RUNTIME_TTS_PRESETS.dashscope.baseUrl,
  ttsModel: RUNTIME_TTS_PRESETS.dashscope.model,
  ttsApiKey: "",
  mem0LlmProvider: MEM0_MODEL_PRESETS.llm.provider,
  mem0LlmBaseUrl: MEM0_MODEL_PRESETS.llm.baseUrl,
  mem0LlmModel: MEM0_MODEL_PRESETS.llm.model,
  mem0LlmApiKey: "",
  mem0EmbedderProvider: MEM0_MODEL_PRESETS.embedder.provider,
  mem0EmbedderBaseUrl: MEM0_MODEL_PRESETS.embedder.baseUrl,
  mem0EmbedderModel: MEM0_MODEL_PRESETS.embedder.model,
  mem0EmbedderApiKey: "",
  syncDashscopeApiKey: true,
};

function normalizeRuntimeTtsProvider(value: string | null | undefined): TtsProviderExtended {
  const normalized = (value ?? "").trim();
  if (normalized === "local_indextts" || normalized === "omnirt_indextts") return "indextts";
  return Object.prototype.hasOwnProperty.call(RUNTIME_TTS_PRESETS, normalized)
    ? normalized as TtsProviderExtended
    : "dashscope";
}

function runtimeFormFromConfig(
  runtimeConfig: RuntimeConfigResponse | null,
  preferDashscopeWhenEdge = false,
): RuntimeConfigForm {
  if (!runtimeConfig) return { ...RUNTIME_FORM_DEFAULTS };
  const sttProvider = Object.prototype.hasOwnProperty.call(RUNTIME_STT_PRESETS, runtimeConfig.stt.provider)
    ? runtimeConfig.stt.provider
    : "dashscope";
  const sttPreset = RUNTIME_STT_PRESETS[sttProvider] ?? RUNTIME_STT_PRESETS.dashscope;
  const resolvedTtsProvider = normalizeRuntimeTtsProvider(runtimeConfig.tts.provider);
  const ttsProvider = preferDashscopeWhenEdge && resolvedTtsProvider === "edge" ? "dashscope" : resolvedTtsProvider;
  const ttsPreset = RUNTIME_TTS_PRESETS[ttsProvider];
  return {
    llmBaseUrl: runtimeConfig.llm.base_url || RUNTIME_LLM_DEFAULT.baseUrl,
    llmModel: runtimeConfig.llm.model || RUNTIME_LLM_DEFAULT.model,
    llmApiKey: "",
    sttProvider,
    sttBaseUrl: runtimeConfig.stt.base_url || sttPreset.baseUrl,
    sttModel: runtimeConfig.stt.model || sttPreset.model,
    sttApiKey: "",
    ttsProvider,
    ttsBaseUrl: runtimeConfig.tts.base_url || ttsPreset.baseUrl,
    ttsModel: runtimeConfig.tts.model || ttsPreset.model,
    ttsApiKey: "",
    mem0LlmProvider: runtimeConfig.mem0?.llm.provider || MEM0_MODEL_PRESETS.llm.provider,
    mem0LlmBaseUrl: runtimeConfig.mem0?.llm.base_url || MEM0_MODEL_PRESETS.llm.baseUrl,
    mem0LlmModel: runtimeConfig.mem0?.llm.model || MEM0_MODEL_PRESETS.llm.model,
    mem0LlmApiKey: "",
    mem0EmbedderProvider: runtimeConfig.mem0?.embedder.provider || MEM0_MODEL_PRESETS.embedder.provider,
    mem0EmbedderBaseUrl: runtimeConfig.mem0?.embedder.base_url || MEM0_MODEL_PRESETS.embedder.baseUrl,
    mem0EmbedderModel: runtimeConfig.mem0?.embedder.model || MEM0_MODEL_PRESETS.embedder.model,
    mem0EmbedderApiKey: "",
    syncDashscopeApiKey: true,
  };
}

interface RuntimeConfigWorkspaceProps {
  runtimeConfig: RuntimeConfigResponse | null;
  runtimeConfigLoading?: boolean;
  runtimeConfigApplying?: boolean;
  onRuntimeConfigRefresh: () => void;
  onRuntimeConfigApply: (input: RuntimeConfigApplyInput) => Promise<void>;
}

export function RuntimeConfigWorkspace({
  runtimeConfig,
  runtimeConfigLoading = false,
  runtimeConfigApplying = false,
  onRuntimeConfigRefresh,
  onRuntimeConfigApply,
}: RuntimeConfigWorkspaceProps) {
  const runtimeConfigSyncedRef = useRef(false);
  const initialRuntimeFormRef = useRef<RuntimeConfigForm | null>(null);
  const [runtimeForm, setRuntimeForm] = useState<RuntimeConfigForm>(() => runtimeFormFromConfig(runtimeConfig, true));

  useEffect(() => {
    if (!runtimeConfig) return;
    // First paint shows Qwen when persisted TTS is Edge, but this display-only prompt
    // should not turn an unrelated save into a TTS provider change.
    const nextRuntimeForm = runtimeFormFromConfig(runtimeConfig, !runtimeConfigSyncedRef.current);
    setRuntimeForm(nextRuntimeForm);
    if (!runtimeConfigSyncedRef.current) {
      initialRuntimeFormRef.current = nextRuntimeForm;
    }
    runtimeConfigSyncedRef.current = true;
  }, [runtimeConfig]);

  const updateRuntimeForm = <K extends keyof RuntimeConfigForm>(key: K, value: RuntimeConfigForm[K]) => {
    setRuntimeForm((prev) => ({ ...prev, [key]: value }));
  };

  const selectRuntimeSttProvider = (provider: string) => {
    const preset = RUNTIME_STT_PRESETS[provider] ?? RUNTIME_STT_PRESETS.dashscope;
    setRuntimeForm((prev) => ({
      ...prev,
      sttProvider: provider,
      sttBaseUrl: preset.baseUrl,
      sttModel: preset.model,
    }));
  };

  const selectRuntimeTtsProvider = (provider: TtsProviderExtended) => {
    const preset = RUNTIME_TTS_PRESETS[provider];
    setRuntimeForm((prev) => ({
      ...prev,
      ttsProvider: provider,
      ttsBaseUrl: preset.baseUrl,
      ttsModel: preset.model,
    }));
  };

  const handleRuntimeApply = async () => {
    const initialRuntimeForm = initialRuntimeFormRef.current;
    const ttsChangedSinceInitial = !initialRuntimeForm
      || runtimeForm.ttsProvider !== initialRuntimeForm.ttsProvider
      || runtimeForm.ttsBaseUrl.trim() !== initialRuntimeForm.ttsBaseUrl.trim()
      || runtimeForm.ttsModel.trim() !== initialRuntimeForm.ttsModel.trim()
      || runtimeForm.ttsApiKey.trim() !== initialRuntimeForm.ttsApiKey.trim();
    const payload: RuntimeConfigApplyInput = {
      llm_base_url: runtimeForm.llmBaseUrl.trim(),
      llm_model: runtimeForm.llmModel.trim(),
      stt_provider: runtimeForm.sttProvider,
      stt_base_url: runtimeForm.sttBaseUrl.trim(),
      stt_model: runtimeForm.sttModel.trim(),
      mem0_llm_provider: runtimeForm.mem0LlmProvider.trim(),
      mem0_llm_base_url: runtimeForm.mem0LlmBaseUrl.trim(),
      mem0_llm_model: runtimeForm.mem0LlmModel.trim(),
      mem0_embedder_provider: runtimeForm.mem0EmbedderProvider.trim(),
      mem0_embedder_base_url: runtimeForm.mem0EmbedderBaseUrl.trim(),
      mem0_embedder_model: runtimeForm.mem0EmbedderModel.trim(),
      sync_dashscope_api_key: runtimeForm.syncDashscopeApiKey,
    };
    const llmApiKey = runtimeForm.llmApiKey.trim();
    const sttApiKey = runtimeForm.sttApiKey.trim();
    const ttsApiKey = runtimeForm.ttsApiKey.trim();
    const mem0LlmApiKey = runtimeForm.mem0LlmApiKey.trim();
    const mem0EmbedderApiKey = runtimeForm.mem0EmbedderApiKey.trim();
    payload.tts_provider = runtimeConfig?.tts.provider && !ttsChangedSinceInitial
      ? runtimeConfig.tts.provider
      : runtimeForm.ttsProvider;
    if (llmApiKey) payload.llm_api_key = llmApiKey;
    if (sttApiKey) payload.stt_api_key = sttApiKey;
    if (payload.tts_provider !== "edge") {
      payload.tts_base_url = runtimeForm.ttsBaseUrl.trim();
      payload.tts_model = runtimeForm.ttsModel.trim();
    }
    if (ttsApiKey) payload.tts_api_key = ttsApiKey;
    if (mem0LlmApiKey) payload.mem0_llm_api_key = mem0LlmApiKey;
    if (mem0EmbedderApiKey) payload.mem0_embedder_api_key = mem0EmbedderApiKey;
    await onRuntimeConfigApply(payload);
    setRuntimeForm((prev) => ({
      ...prev,
      llmApiKey: "",
      sttApiKey: "",
      ttsApiKey: "",
      mem0LlmApiKey: "",
      mem0EmbedderApiKey: "",
    }));
  };

  const runtimeSttPreset = RUNTIME_STT_PRESETS[runtimeForm.sttProvider] ?? RUNTIME_STT_PRESETS.dashscope;
  const runtimeTtsPreset = RUNTIME_TTS_PRESETS[runtimeForm.ttsProvider];
  const runtimeTtsNeedsSetup = runtimeForm.ttsProvider !== "edge";
  const runtimeLlmKeySet = Boolean(runtimeConfig?.llm.api_key_set || runtimeForm.llmApiKey.trim());
  const runtimeSttSavedKeySet = runtimeConfig?.stt.provider === runtimeForm.sttProvider && runtimeConfig.stt.api_key_set;
  const runtimeTtsSavedKeySet = normalizeRuntimeTtsProvider(runtimeConfig?.tts.provider) === runtimeForm.ttsProvider && runtimeConfig?.tts.api_key_set;
  const runtimeSttKeySet = Boolean(runtimeSttSavedKeySet || runtimeForm.sttApiKey.trim() || !runtimeSttPreset.needsKey);
  const runtimeTtsKeySet = Boolean(!runtimeTtsNeedsSetup || runtimeTtsSavedKeySet || runtimeForm.ttsApiKey.trim() || !runtimeTtsPreset.needsKey);
  const runtimeMem0LlmKeySet = Boolean(runtimeConfig?.mem0?.llm.api_key_set || runtimeForm.mem0LlmApiKey.trim());
  const runtimeMem0EmbedderKeySet = Boolean(runtimeConfig?.mem0?.embedder.api_key_set || runtimeForm.mem0EmbedderApiKey.trim());
  const runtimeSttProviderOptions = Object.entries(RUNTIME_STT_PRESETS);
  const runtimeTtsProviderOptions = Object.entries(RUNTIME_TTS_PRESETS) as [TtsProviderExtended, typeof RUNTIME_TTS_PRESETS[TtsProviderExtended]][];

  return (
    <main className="min-h-0 flex-1 overflow-y-auto bg-slate-100">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 p-4 lg:p-6">
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(20rem,0.9fr)]">
          <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm shadow-slate-200/60">
            <div className="mb-4 flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-slate-900">LLM</h2>
              <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${
                runtimeLlmKeySet ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-700"
              }`}>
                {runtimeLlmKeySet ? "Key 已设置" : "Key 未设置"}
              </span>
            </div>
            <div className="grid gap-3">
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-500">Base URL</span>
                <input
                  value={runtimeForm.llmBaseUrl}
                  onChange={(event) => updateRuntimeForm("llmBaseUrl", event.target.value)}
                  className="h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-800 outline-none transition focus:border-cyan-300"
                />
              </label>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-slate-500">Model</span>
                  <input
                    value={runtimeForm.llmModel}
                    onChange={(event) => updateRuntimeForm("llmModel", event.target.value)}
                    className="h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-800 outline-none transition focus:border-cyan-300"
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-slate-500">API Key</span>
                  <input
                    type="password"
                    value={runtimeForm.llmApiKey}
                    onChange={(event) => updateRuntimeForm("llmApiKey", event.target.value)}
                    autoComplete="new-password"
                    className="h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-800 outline-none transition focus:border-cyan-300"
                  />
                </label>
              </div>
            </div>
          </section>

          <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm shadow-slate-200/60">
            <div className="mb-4 flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-slate-900">STT</h2>
              <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${
                runtimeSttKeySet ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-700"
              }`}>
                {runtimeSttKeySet ? "Key 已设置" : "Key 未设置"}
              </span>
            </div>
            <div className="grid gap-3">
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-500">Provider</span>
                <select
                  value={runtimeForm.sttProvider}
                  onChange={(event) => selectRuntimeSttProvider(event.target.value)}
                  className="h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 outline-none transition focus:border-cyan-300"
                >
                  {runtimeSttProviderOptions.map(([provider, preset]) => (
                    <option key={provider} value={provider}>{preset.label}</option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-500">Base URL</span>
                <input
                  value={runtimeForm.sttBaseUrl}
                  onChange={(event) => updateRuntimeForm("sttBaseUrl", event.target.value)}
                  className="h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-800 outline-none transition focus:border-cyan-300"
                />
              </label>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-slate-500">Model</span>
                  <input
                    value={runtimeForm.sttModel}
                    onChange={(event) => updateRuntimeForm("sttModel", event.target.value)}
                    className="h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-800 outline-none transition focus:border-cyan-300"
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-slate-500">API Key</span>
                  <input
                    type="password"
                    value={runtimeForm.sttApiKey}
                    onChange={(event) => updateRuntimeForm("sttApiKey", event.target.value)}
                    autoComplete="new-password"
                    className="h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-800 outline-none transition focus:border-cyan-300"
                  />
                </label>
              </div>
            </div>
          </section>

          <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm shadow-slate-200/60 lg:col-span-2">
            <div className="mb-4 flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-slate-900">TTS</h2>
              <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${
                runtimeTtsKeySet ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-700"
              }`}>
                {runtimeTtsNeedsSetup ? (runtimeTtsKeySet ? "Key 已设置" : "Key 未设置") : "无需配置"}
              </span>
            </div>
            <div className="grid gap-3 lg:grid-cols-[minmax(11rem,0.45fr)_minmax(0,1fr)]">
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-500">Provider</span>
                <select
                  value={runtimeForm.ttsProvider}
                  onChange={(event) => selectRuntimeTtsProvider(event.target.value as TtsProviderExtended)}
                  className="h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 outline-none transition focus:border-cyan-300"
                >
                  {runtimeTtsProviderOptions.map(([provider, preset]) => (
                    <option key={provider} value={provider}>{preset.label}</option>
                  ))}
                </select>
              </label>
              {runtimeTtsNeedsSetup ? (
                <>
                  <label className="block">
                    <span className="mb-1 block text-xs font-medium text-slate-500">Base URL</span>
                    <input
                      value={runtimeForm.ttsBaseUrl}
                      onChange={(event) => updateRuntimeForm("ttsBaseUrl", event.target.value)}
                      className="h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-800 outline-none transition focus:border-cyan-300"
                    />
                  </label>
                  <div className="grid gap-3 sm:grid-cols-2 lg:col-span-2">
                    <label className="block">
                      <span className="mb-1 block text-xs font-medium text-slate-500">Model</span>
                      <input
                        value={runtimeForm.ttsModel}
                        onChange={(event) => updateRuntimeForm("ttsModel", event.target.value)}
                        className="h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-800 outline-none transition focus:border-cyan-300"
                      />
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-xs font-medium text-slate-500">API Key</span>
                      <input
                        type="password"
                        value={runtimeForm.ttsApiKey}
                        onChange={(event) => updateRuntimeForm("ttsApiKey", event.target.value)}
                        autoComplete="new-password"
                        className="h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-800 outline-none transition focus:border-cyan-300"
                      />
                    </label>
                  </div>
                  <p className="text-xs text-slate-500 lg:col-span-2">TTS 音色请在实时对话里选择，这里只配置服务连接。</p>
                </>
              ) : (
                null
              )}
            </div>
          </section>

          <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm shadow-slate-200/60">
            <div className="mb-4 flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-slate-900">Mem0 LLM</h2>
              <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${
                runtimeMem0LlmKeySet ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-700"
              }`}>
                {runtimeMem0LlmKeySet ? "Key 已设置" : "Key 未设置"}
              </span>
            </div>
            <div className="grid gap-3">
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-500">Provider</span>
                <input
                  value={runtimeForm.mem0LlmProvider}
                  onChange={(event) => updateRuntimeForm("mem0LlmProvider", event.target.value)}
                  className="h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-800 outline-none transition focus:border-cyan-300"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-500">Base URL</span>
                <input
                  value={runtimeForm.mem0LlmBaseUrl}
                  onChange={(event) => updateRuntimeForm("mem0LlmBaseUrl", event.target.value)}
                  className="h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-800 outline-none transition focus:border-cyan-300"
                />
              </label>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-slate-500">Model</span>
                  <input
                    value={runtimeForm.mem0LlmModel}
                    onChange={(event) => updateRuntimeForm("mem0LlmModel", event.target.value)}
                    className="h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-800 outline-none transition focus:border-cyan-300"
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-slate-500">API Key</span>
                  <input
                    type="password"
                    value={runtimeForm.mem0LlmApiKey}
                    onChange={(event) => updateRuntimeForm("mem0LlmApiKey", event.target.value)}
                    autoComplete="new-password"
                    className="h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-800 outline-none transition focus:border-cyan-300"
                  />
                </label>
              </div>
            </div>
          </section>

          <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm shadow-slate-200/60">
            <div className="mb-4 flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-slate-900">Mem0 Embedding</h2>
              <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${
                runtimeMem0EmbedderKeySet ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-700"
              }`}>
                {runtimeMem0EmbedderKeySet ? "Key 已设置" : "Key 未设置"}
              </span>
            </div>
            <div className="grid gap-3">
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-500">Provider</span>
                <input
                  value={runtimeForm.mem0EmbedderProvider}
                  onChange={(event) => updateRuntimeForm("mem0EmbedderProvider", event.target.value)}
                  className="h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-800 outline-none transition focus:border-cyan-300"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-500">Base URL</span>
                <input
                  value={runtimeForm.mem0EmbedderBaseUrl}
                  onChange={(event) => updateRuntimeForm("mem0EmbedderBaseUrl", event.target.value)}
                  className="h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-800 outline-none transition focus:border-cyan-300"
                />
              </label>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-slate-500">Model</span>
                  <input
                    value={runtimeForm.mem0EmbedderModel}
                    onChange={(event) => updateRuntimeForm("mem0EmbedderModel", event.target.value)}
                    className="h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-800 outline-none transition focus:border-cyan-300"
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-slate-500">API Key</span>
                  <input
                    type="password"
                    value={runtimeForm.mem0EmbedderApiKey}
                    onChange={(event) => updateRuntimeForm("mem0EmbedderApiKey", event.target.value)}
                    autoComplete="new-password"
                    className="h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-800 outline-none transition focus:border-cyan-300"
                  />
                </label>
              </div>
            </div>
          </section>

          <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm shadow-slate-200/60 lg:col-span-2">
            <div>
              <label className="flex min-w-0 items-start gap-3">
                <input
                  type="checkbox"
                  checked={runtimeForm.syncDashscopeApiKey}
                  onChange={(event) => updateRuntimeForm("syncDashscopeApiKey", event.target.checked)}
                  className="mt-0.5 h-4 w-4 shrink-0 accent-cyan-600"
                />
                <span className="min-w-0">
                  <span className="block text-sm font-semibold text-slate-700">同时保存为通用百炼 Key</span>
                  <span className="mt-1 block text-xs leading-5 text-slate-500">
                    勾选后会额外写入 DASHSCOPE_API_KEY，供百炼语音识别、语音合成及旧版配置读取。若不同服务使用不同 Key，请关闭。
                  </span>
                </span>
              </label>
              <div className="mt-3 flex flex-wrap items-center justify-end gap-2 border-t border-slate-100 pt-3">
                <button
                  type="button"
                  onClick={onRuntimeConfigRefresh}
                  disabled={runtimeConfigLoading || runtimeConfigApplying}
                  className="rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 transition hover:border-cyan-200 hover:text-cyan-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {runtimeConfigLoading ? "读取中" : "刷新"}
                </button>
                <button
                  type="button"
                  onClick={() => void handleRuntimeApply()}
                  disabled={runtimeConfigApplying || runtimeConfigLoading}
                  className="rounded-lg bg-slate-950 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {runtimeConfigApplying ? "应用中..." : "应用配置"}
                </button>
              </div>
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
