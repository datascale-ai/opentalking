import { apiPostBlob, apiPostFormBlob, type DuoDialogRequest, type IndexTTSConfig } from "./api";
import type { TtsProviderExtended } from "../constants/ttsBailian";

export const DEFAULT_TTS_PREVIEW_TEXT = "你好，我正在测试音色。";

export type TTSPreviewPayload = {
  text: string;
  voice?: string;
  tts_provider: TtsProviderExtended;
  tts_model?: string;
  indextts_config?: IndexTTSConfig;
  indextts_emotion_audio_file?: File;
};

export function buildTTSPreviewPayload({
  text,
  voice,
  provider,
  model,
  indexttsConfig,
  indexttsEmotionAudioFile,
}: {
  text: string;
  voice?: string;
  provider: TtsProviderExtended;
  model?: string;
  indexttsConfig?: IndexTTSConfig;
  indexttsEmotionAudioFile?: File | null;
}): TTSPreviewPayload {
  const payload: TTSPreviewPayload = {
    text: text.trim(),
    tts_provider: provider,
  };
  const trimmedVoice = (voice ?? "").trim();
  if (trimmedVoice && provider !== "sambert") {
    payload.voice = trimmedVoice;
  }
  const trimmedModel = (model ?? "").trim();
  if (provider !== "edge" && provider !== "openai_compatible" && trimmedModel) {
    payload.tts_model = trimmedModel;
  }
  if ((provider === "indextts") && indexttsConfig) {
    payload.indextts_config = indexttsConfig;
  }
  if ((provider === "indextts") && indexttsEmotionAudioFile) {
    payload.indextts_emotion_audio_file = indexttsEmotionAudioFile;
  }
  return payload;
}

export async function requestTTSPreview(payload: TTSPreviewPayload): Promise<Blob> {
  if (payload.indextts_emotion_audio_file) {
    const form = new FormData();
    form.set("text", payload.text);
    if (payload.voice) form.set("voice", payload.voice);
    form.set("tts_provider", payload.tts_provider);
    if (payload.tts_model) form.set("tts_model", payload.tts_model);
    if (payload.indextts_config) form.set("indextts_config", JSON.stringify(payload.indextts_config));
    form.set("indextts_emotion_audio_file", payload.indextts_emotion_audio_file);
    return apiPostFormBlob("/tts/preview", form);
  }
  return apiPostBlob("/tts/preview", payload);
}

export type DuoDialogPreviewPayload = DuoDialogRequest;

export async function requestDuoDialogPreview(payload: DuoDialogPreviewPayload): Promise<Blob> {
  return apiPostBlob("/tts/preview-duo-dialog", payload);
}
