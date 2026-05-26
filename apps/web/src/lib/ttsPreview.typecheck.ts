import { buildTTSPreviewPayload } from "./ttsPreview";
import type { TtsProviderExtended } from "../constants/ttsBailian";

const qwenPayload = buildTTSPreviewPayload({
  text: "  你好  ",
  voice: "voice-clone-1",
  provider: "dashscope",
  model: "qwen3-tts-flash-realtime",
});

qwenPayload satisfies {
  text: string;
  voice?: string;
  tts_provider: TtsProviderExtended;
  tts_model?: string;
};

const localPayload = buildTTSPreviewPayload({
  text: "你好",
  voice: "local-default",
  provider: "local_cosyvoice",
  model: "FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
});

localPayload satisfies { tts_provider: TtsProviderExtended; tts_model?: string };

const edgePayload = buildTTSPreviewPayload({
  text: "你好",
  voice: "zh-CN-XiaoxiaoNeural",
  provider: "edge",
  model: "",
});

edgePayload satisfies { tts_model?: string };
