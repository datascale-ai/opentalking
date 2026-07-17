const MODEL_LABELS: Record<string, string> = {
  flashhead: "FlashHead",
  fasterliveportrait: "FasterLivePortrait",
  flashtalk: "FlashTalk",
  mock: "轻量模式",
  musetalk: "MuseTalk",
  quicktalk: "QuickTalk",
  wav2lip: "Wav2Lip",
};

export function modelLabel(modelId: string): string {
  return MODEL_LABELS[modelId] ?? modelId;
}
