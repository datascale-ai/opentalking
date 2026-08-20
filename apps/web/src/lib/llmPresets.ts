export type LlmPreset = {
  label: string;
  baseUrl: string;
  model: string;
};

export const RUNTIME_LLM_PRESETS: Record<string, LlmPreset> = {
  dashscope: {
    label: "百炼 DashScope",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    model: "qwen-flash",
  },
  openai_compatible: {
    label: "OpenAI-compatible",
    baseUrl: "https://api.openai.com/v1",
    model: "gpt-4o-mini",
  },
  orcarouter: {
    label: "OrcaRouter",
    baseUrl: "https://api.orcarouter.ai/v1",
    model: "orcarouter/auto",
  },
};

export const RUNTIME_LLM_DEFAULT = RUNTIME_LLM_PRESETS.dashscope;

export function normalizeRuntimeLlmProvider(value: string | null | undefined): string {
  const normalized = (value ?? "").trim();
  return Object.prototype.hasOwnProperty.call(RUNTIME_LLM_PRESETS, normalized)
    ? normalized
    : "dashscope";
}
