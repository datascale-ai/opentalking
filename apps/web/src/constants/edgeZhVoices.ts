/** Microsoft Edge TTS zh-CN Neural（与后端 edge_zh_voices.EDGE_ZH_VOICES 一致） */
export const EDGE_ZH_VOICES: { id: string; label: string }[] = [
  { id: "zh-CN-XiaoxiaoNeural", label: "晓晓（女·温和）" },
  { id: "zh-CN-XiaoyiNeural", label: "晓伊（女·活泼）" },
  { id: "zh-CN-YunxiNeural", label: "云希（男·阳光）" },
  { id: "zh-CN-YunjianNeural", label: "云健（男·运动）" },
  { id: "zh-CN-YunyangNeural", label: "云扬（男·新闻）" },
  { id: "zh-CN-YunxiaNeural", label: "云霞（男·可爱）" },
];

export const DEFAULT_EDGE_VOICE_ID = EDGE_ZH_VOICES[0]?.id ?? "zh-CN-XiaoxiaoNeural";

export const EDGE_VOICE_STORAGE_KEY = "opentalking-edge-voice";
