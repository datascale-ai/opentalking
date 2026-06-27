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

const xiaomiMimoApplication = resolveVoiceCloneApplication({
  provider: "xiaomi_mimo",
  targetModel: "mimo-v2.5-tts-voiceclone",
  displayLabel: "小米复刻测试",
  voiceId: "data:audio/wav;base64,AAAA",
});

xiaomiMimoApplication satisfies {
  provider: "xiaomi_mimo";
  model: "mimo-v2.5-tts-voiceclone";
  voice: "data:audio/wav;base64,AAAA";
  message: "已使用复刻音色：小米复刻测试";
};

const localIndexTtsApplication = resolveVoiceCloneApplication({
  provider: "indextts",
  targetModel: "IndexTeam/IndexTTS-2",
  displayLabel: "IndexTTS 复刻",
  voiceId: "indextts-local-test",
});

localIndexTtsApplication satisfies {
  provider: "indextts";
  model: "IndexTeam/IndexTTS-2";
  voice: "indextts-local-test";
  message: "已使用复刻音色：IndexTTS 复刻";
};

const omniRtIndexTtsApplication = resolveVoiceCloneApplication({
  provider: "indextts",
  targetModel: "IndexTeam/IndexTTS-2",
  displayLabel: "IndexTTS 复刻",
  voiceId: "indextts-omnirt-test",
});

omniRtIndexTtsApplication satisfies {
  provider: "indextts";
  model: "IndexTeam/IndexTTS-2";
  voice: "indextts-omnirt-test";
  message: "已使用复刻音色：IndexTTS 复刻";
};
