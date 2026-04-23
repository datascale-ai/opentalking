/**
 * 百炼控制台多种语音合成路由（DashScope）。
 * CosyVoice / MiniMax HTTP 参见 ``HttpSpeechSynthesizer``；MiniMax 若报错请对照控制台是否走独立 Multimodal 接口。
 *
 * @see https://help.aliyun.com/zh/model-studio/cosyvoice-python-sdk
 * @see https://help.aliyun.com/zh/model-studio/minimax-speech-synthesis/
 */

/** CosyVoice（HTTP/SSE）；音色需与所选模型版本匹配，表内为示例 */
export const COSYVOICE_MODEL_OPTIONS: { id: string; label: string }[] = [
  { id: "cosyvoice-v3-flash", label: "CosyVoice v3 flash" },
  { id: "cosyvoice-v3-plus", label: "CosyVoice v3 plus" },
  { id: "cosyvoice-v3.5-flash", label: "CosyVoice v3.5 flash（北京）" },
  { id: "cosyvoice-v3.5-plus", label: "CosyVoice v3.5 plus（北京）" },
];

export const COSYVOICE_VOICE_OPTIONS: { id: string; label: string }[] = [
  { id: "longanyang", label: "longanyang（示例·男）" },
  { id: "longhua", label: "longhua（示例）" },
  { id: "longxiaochun_v2", label: "longxiaochun_v2（v2 音色示例）" },
];

/** Sambert 经典链路；音色由模型名体现，不设独立 voice 字段 */
export const SAMBERT_MODEL_OPTIONS: { id: string; label: string }[] = [
  { id: "sambert-zhichu-v1", label: "sambert-zhichu-v1（知楚）" },
];

/** MiniMax：官方仅提供 ``multimodal-generation`` HTTP/SSE（无 DashScope WS 封装时用此路径） */
export const MINIMAX_MODEL_OPTIONS: { id: string; label: string }[] = [
  { id: "MiniMax/speech-02-turbo", label: "MiniMax speech-02-turbo" },
  { id: "MiniMax/speech-02-hd", label: "MiniMax speech-02-hd" },
  { id: "MiniMax/speech-2.8-turbo", label: "MiniMax speech-2.8-turbo" },
];

/**
 * MiniMax 使用 ``voice_setting.voice_id``（与 CosyVoice 音色名不同）。
 * 完整列表见控制台 / 阿里云文档；以下为文档常见示例。
 */
export const MINIMAX_VOICE_OPTIONS: { id: string; label: string }[] = [
  { id: "male-qn-qingse", label: "青涩青年 male-qn-qingse" },
  { id: "female-shaonv", label: "少女 female-shaonv" },
  { id: "male-qn-jingying", label: "精英青年 male-qn-jingying" },
];

export type TtsProviderExtended =
  | "edge"
  | "dashscope"
  | "cosyvoice"
  | "sambert"
  | "minimax";

export function isEdgeTts(p: string): boolean {
  return p === "edge";
}
