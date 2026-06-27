/**
 * 百炼控制台多种语音合成路由（DashScope）。
 *
 * @see https://help.aliyun.com/zh/model-studio/cosyvoice-python-sdk
 */

/** CosyVoice（HTTP/SSE）；音色需与所选模型版本匹配，表内为示例 */
export const COSYVOICE_MODEL_OPTIONS: { id: string; label: string }[] = [
  { id: "cosyvoice-v3-flash", label: "CosyVoice v3 flash" },
  { id: "cosyvoice-v3-plus", label: "CosyVoice v3 plus" },
];

export const COSYVOICE_VOICE_OPTIONS: { id: string; label: string }[] = [
  { id: "longanyang", label: "longanyang（示例·男）" },
];

/** Sambert 经典链路；音色由模型名体现，不设独立 voice 字段 */
export const SAMBERT_MODEL_OPTIONS: { id: string; label: string }[] = [
  { id: "sambert-zhichu-v1", label: "sambert-zhichu-v1（知楚）" },
];

/** 本地模型：OpenTalking 同机/内网本地服务，不走百炼云端 TTS。 */
export const LOCAL_COSYVOICE_MODEL_OPTIONS: { id: string; label: string }[] = [
  { id: "FunAudioLLM/Fun-CosyVoice3-0.5B-2512", label: "CosyVoice3-0.5B-2512（本地模型）" },
];

export const LOCAL_INDEXTTS_MODEL_OPTIONS: { id: string; label: string }[] = [
  { id: "IndexTeam/IndexTTS-2", label: "IndexTTS-2（本地模型）" },
];

export const LOCAL_TTS_VOICE_OPTIONS: { id: string; label: string }[] = [];

export const XIAOMI_MIMO_MODEL_OPTIONS: { id: string; label: string }[] = [
  { id: "mimo-v2.5-tts", label: "MiMo v2.5 TTS" },
  { id: "mimo-v2.5-tts-voiceclone", label: "MiMo v2.5 TTS VoiceClone" },
];

export const XIAOMI_MIMO_VOICE_OPTIONS: { id: string; label: string }[] = [
  { id: "mimo_default", label: "MiMo 默认" },
  { id: "冰糖", label: "冰糖（中文女声）" },
  { id: "茉莉", label: "茉莉（中文女声）" },
  { id: "苏打", label: "苏打（中文男声）" },
  { id: "白桦", label: "白桦（中文男声）" },
  { id: "Mia", label: "Mia（English female）" },
  { id: "Chloe", label: "Chloe（English female）" },
  { id: "Milo", label: "Milo（English male）" },
  { id: "Dean", label: "Dean（English male）" },
];

export type TtsProviderExtended =
  | "edge"
  | "dashscope"
  | "cosyvoice"
  | "sambert"
  | "local_cosyvoice"
  | "indextts"
  | "xiaomi_mimo"
  | "openai_compatible";

export function isEdgeTts(p: string): boolean {
  return p === "edge";
}
