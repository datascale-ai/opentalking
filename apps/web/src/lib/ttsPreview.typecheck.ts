import { buildTTSPreviewPayload, requestDuoDialogPreview } from "./ttsPreview";
import type { TtsProviderExtended } from "../constants/ttsBailian";
import { indexTTSEmotionPresetConfig } from "../components/VideoCreationWorkspace";

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

const openaiCompatiblePayload = buildTTSPreviewPayload({
  text: "你好",
  provider: "openai_compatible",
});

openaiCompatiblePayload satisfies { tts_provider: TtsProviderExtended; tts_model?: string; voice?: string };

const xiaomiMimoPayload = buildTTSPreviewPayload({
  text: "你好",
  voice: "冰糖",
  provider: "xiaomi_mimo",
  model: "mimo-v2.5-tts",
});

xiaomiMimoPayload satisfies {
  tts_provider: TtsProviderExtended;
  tts_model?: string;
  voice?: string;
};

const indexttsPreviewPayload = buildTTSPreviewPayload({
  text: "你好",
  voice: "indextts-clear-cn",
  provider: "indextts",
  model: "IndexTeam/IndexTTS-2",
  indexttsConfig: {
    emotion_mode: "vector",
    emo_alpha: 0.8,
    emo_vector: [0, 0, 0, 0, 0, 0, 0, 0.8],
    use_random: false,
  },
});

indexttsPreviewPayload satisfies { indextts_config?: { emotion_mode: "voice" | "text" | "vector" | "audio" } };

const indexttsHappyPreset = indexTTSEmotionPresetConfig({ label: "快乐", config: { emotion_mode: "vector", emo_alpha: 1, emo_vector: [1, 0, 0, 0, 0, 0, 0, 0], use_random: false } });
indexttsHappyPreset satisfies {
  emotion_mode: "vector";
  emo_alpha: 1;
  emo_vector: number[];
  use_random: false;
};

const emotionReferenceAudio = new File(["RIFF"], "emotion.wav", { type: "audio/wav" });
const indexttsAudioPreviewPayload = buildTTSPreviewPayload({
  text: "你好",
  voice: "indextts-clear-cn",
  provider: "indextts",
  indexttsEmotionAudioFile: emotionReferenceAudio,
});
indexttsAudioPreviewPayload satisfies { indextts_emotion_audio_file?: File };

const localIndexTtsPreviewPayload = buildTTSPreviewPayload({
  text: "你好",
  voice: "indextts-local-voice",
  provider: "indextts",
  model: "IndexTeam/IndexTTS-2",
  indexttsConfig: {
    emotion_mode: "text",
    emo_alpha: 0.9,
    emo_text: "生气、坚定",
    use_random: false,
  },
});
localIndexTtsPreviewPayload satisfies {
  tts_provider: TtsProviderExtended;
  indextts_config?: { emotion_mode: "voice" | "text" | "vector" | "audio" };
};


const duoDialogPreviewPromise = requestDuoDialogPreview({
  lines: [
    { id: "line-1", role: "left", text: "左侧开场" },
    { id: "line-2", role: "right", text: "右侧回应" },
  ],
  speakers: {
    left: { tts_provider: "edge", voice: "zh-CN-XiaoxiaoNeural" },
    right: { tts_provider: "xiaomi_mimo", tts_model: "mimo-v2.5-tts", voice: "冰糖" },
  },
  gap_ms: 120,
});

duoDialogPreviewPromise satisfies Promise<Blob>;
