export type VoiceCloneProvider =
  | "dashscope"
  | "cosyvoice"
  | "local_cosyvoice"
  | "indextts"
  | "local_f5_tts"
  | "xiaomi_mimo";

export type VoiceCloneApplicationInput<
  Provider extends VoiceCloneProvider = VoiceCloneProvider,
  TargetModel extends string = string,
  VoiceId extends string = string,
  DisplayLabel extends string = string,
> = {
  provider: Provider;
  targetModel: TargetModel;
  voiceId: VoiceId;
  displayLabel: DisplayLabel;
};

export type VoiceCloneApplication<
  Provider extends VoiceCloneProvider = VoiceCloneProvider,
  TargetModel extends string = string,
  VoiceId extends string = string,
  DisplayLabel extends string = string,
> = {
  provider: Provider;
  model: TargetModel;
  voice: VoiceId;
  displayLabel: DisplayLabel;
  message: `已使用复刻音色：${DisplayLabel}`;
};

export function resolveVoiceCloneApplication<
  Provider extends VoiceCloneProvider,
  TargetModel extends string,
  VoiceId extends string,
  DisplayLabel extends string,
>(
  input: VoiceCloneApplicationInput<Provider, TargetModel, VoiceId, DisplayLabel>,
): VoiceCloneApplication<Provider, TargetModel, VoiceId, DisplayLabel> {
  return {
    provider: input.provider,
    model: input.targetModel,
    voice: input.voiceId,
    displayLabel: input.displayLabel,
    message: `已使用复刻音色：${input.displayLabel}`,
  };
}
