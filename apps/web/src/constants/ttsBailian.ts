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

export const LOCAL_TTS_VOICE_OPTIONS: { id: string; label: string }[] = [];

export type TtsProviderExtended =
  | "edge"
  | "dashscope"
  | "cosyvoice"
  | "sambert"
  | "local_cosyvoice";

export function isEdgeTts(p: string): boolean {
  return p === "edge";
}
