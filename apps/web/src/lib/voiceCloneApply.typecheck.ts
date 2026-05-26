import { resolveVoiceCloneApplication } from "./voiceCloneApply";

const qwenApplication = resolveVoiceCloneApplication({
  provider: "dashscope",
  targetModel: "qwen3-tts-flash-realtime",
  displayLabel: "我的音色",
  voiceId: "voice-qwen",
});

qwenApplication satisfies {
  provider: "dashscope";
  model: "qwen3-tts-flash-realtime";
  voice: "voice-qwen";
  message: "已使用复刻音色：我的音色";
};

const cosyApplication = resolveVoiceCloneApplication({
  provider: "cosyvoice",
  targetModel: "cosyvoice-v3-flash",
  displayLabel: "Cosy 测试",
  voiceId: "voice-cosy",
});

cosyApplication satisfies {
  provider: "cosyvoice";
  model: "cosyvoice-v3-flash";
  voice: "voice-cosy";
  message: "已使用复刻音色：Cosy 测试";
};

const localCosyApplication = resolveVoiceCloneApplication({
  provider: "local_cosyvoice",
  targetModel: "FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
  displayLabel: "本地 Cosy 测试",
  voiceId: "local-cosy-test",
});

localCosyApplication satisfies {
  provider: "local_cosyvoice";
  model: "FunAudioLLM/Fun-CosyVoice3-0.5B-2512";
  voice: "local-cosy-test";
  message: "已使用复刻音色：本地 Cosy 测试";
};
