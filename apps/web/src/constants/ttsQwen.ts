/**
 * 百炼 Qwen 语音合成可选模型（以控制台/API 文档为准，可自选尝试延迟差异）。
 * @see https://bailian.console.aliyun.com — 语音合成 / Qwen-TTS
 */
export const QWEN_TTS_MODEL_OPTIONS: { id: string; label: string }[] = [
  { id: "qwen3-tts-flash-realtime", label: "qwen3-tts-flash-realtime（Flash·实时）" },
  { id: "qwen-tts-realtime", label: "qwen-tts-realtime（若控制台提供）" },
];

/** 常用音色 short name；完整列表请在百炼控制台查看 */
export const QWEN_TTS_VOICE_OPTIONS: { id: string; label: string }[] = [
  { id: "Cherry", label: "Cherry" },
  { id: "Kiki", label: "Kiki（粤语女声）" },
  { id: "Rocky", label: "Rocky（粤语男声）" },
  { id: "Serena", label: "Serena" },
  { id: "Ethan", label: "Ethan" },
  { id: "Chelsie", label: "Chelsie" },
  { id: "Dylan", label: "Dylan" },
  { id: "Jada", label: "Jada" },
  { id: "Roy", label: "Roy" },
];

export const DEFAULT_QWEN_MODEL_ID = QWEN_TTS_MODEL_OPTIONS[0]?.id ?? "qwen3-tts-flash-realtime";
export const DEFAULT_QWEN_VOICE_ID = "Cherry";

/**
 * 千问「声音复刻」注册时选择的 target_model，须与后续合成所用模型一致（见百炼文档）。
 * 与实时 Flash 模型（如 qwen3-tts-flash-realtime）不是同一条链路。
 */
export const QWEN_VOICE_CLONE_TARGET_OPTIONS: { id: string; label: string }[] = [
  {
    id: "qwen3-tts-vc-realtime-2026-01-15",
    label: "qwen3-tts-vc-realtime-2026-01-15（音色复刻）",
  },
];

export const TTS_PROVIDER_STORAGE_KEY = "opentalking-tts-provider-v2"; // edge | dashscope | cosyvoice | sambert
export const QWEN_MODEL_STORAGE_KEY = "opentalking-qwen-tts-model";
export const QWEN_VOICE_STORAGE_KEY = "opentalking-qwen-tts-voice";
